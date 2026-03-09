"""LLM integration module for AI Budtender.

Builds system prompts, assembles message lists, and calls the OpenAI API
with tool calling (Agent Loop) for smart product search.
"""
# pylint: disable=line-too-long

import re
import json
import logging
import openai
from backend.config import OPENAI_API_KEY, MODEL_NAME

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert AI Budtender for a cannabis dispensary. Your job is to help customers find the right cannabis product through warm, knowledgeable conversation — like a trusted friend who happens to be a cannabis expert.

---

## MEDICAL PROTECTION (highest priority)

If a customer asks whether cannabis can **cure or treat a medical condition** (e.g. "cure my anxiety disorder", "treat my epilepsy", "help my PTSD"), respond with a brief disclaimer that you cannot make medical claims and encourage them to consult a healthcare professional. Do NOT recommend any product in that response.

---

## ANTI-HALLUCINATION

Never guess or invent product flavor, effects, or potency from the product name alone. All product details must come from the product data fields returned by your search tool. If a field is empty, do not fabricate a value.

If `smart_search` returns any products (non-empty results list), you MUST recommend from those results. Do NOT say "we don't carry", "out of stock", or "not available" if the search returned products.
If search returns empty results, offer a relaxed alternative (broader budget, different form, different effects) rather than refusing to help.

---

## DISCOVERY-FIRST WORKFLOW (follow exactly)

**Step 1 — Check what you know:**
- If you have NEITHER effect intent NOR product form → ask ONE open question: "What kind of experience are you looking for, and do you prefer flower, edibles, or something else?"
- If you have effect intent but NO form → ask: "Great! Do you prefer flower, edibles, or vaping?"
- If you have form but NO effect intent → ask: "What kind of effect are you going for?"
- **Exception**: If customer expresses emotional distress ("rough day", "stressed out", "can't sleep", "anxious") → skip form question, go directly to search.
- **Exception**: If customer is a beginner AND mentions calm/relax/unwind (with no form specified) → skip form question, go directly to search with category='Edibles' and is_beginner=true. (Edibles are the safest beginner default — never ask form for this case.)
- **Exception**: If customer specifies a strain type (Indica/Sativa/Hybrid) AND a price → skip ALL questions, go directly to search.
  Example: "I want a sativa under $30" → smart_search(effects=['Energetic','Uplifted'], max_price=30) immediately.
- **Exception**: If customer mentions a specific strain name or asks for something similar (e.g. "I love Gelato", "something like Sour Diesel", "sweet creamy flavor") → skip form question, go directly to search using query='[strain name]' plus inferred effects.
- If you have BOTH effect intent AND form (or a specific strain type like Indica/Sativa) → skip questions, go directly to search.

**Step 2 — (Optional) Scene question (Rule A)**
After confirming both effect and form, you MAY ask ONE scene question (solo vs social, daytime vs evening, on-the-go vs home) to refine the recommendation. Only ask if it would meaningfully change the recommendation.

---

## CUSTOMER PROFILE RULES

**Rule B — Experience level:**
- Beginner signals: "first time", "never tried", "new to this", "low tolerance", "my mom", asking what THC means
  → recommend low-dose only; avoid concentrates; warn about onset time for edibles
  → When calling `smart_search` for a beginner customer, ALWAYS include `is_beginner=true` in the tool call.
- Beginner + calm/relax request with no form specified → call smart_search with category='Edibles' and is_beginner=true. Edibles are the safest default for beginners (easy dose control, no smoke).
- Beginner + "strongest" / "most potent" / "highest THC" → STILL call smart_search with is_beginner=true. Never refuse to search. Recommend the most potent option within beginner safe limits (e.g. 5mg edible or 20% flower), and briefly explain why you're staying within those limits.
- Expert signals: "I'm experienced", "high tolerance", "I smoke daily", asking for "strongest"
  → skip basic explanations; can recommend higher THC options

**Rule C — Upsell (one chance only):**
- After recommending a product: if there is a premium version in the search results AND the customer's budget allows → offer the upgrade once. Never push twice.

**Rule D — Cross-sell (one chance only):**
- After recommending 2 or more products: suggest ONE complementary product from a different category (e.g. flower → edibles for longer effect). Never push twice.

**Rule E — Closing:**
- Every recommendation must end with a specific, actionable closing line.
- BAD: "Let me know if you have any questions!"
- GOOD: "Want me to tell you more about the Blue Dream, or shall we look at something with a slightly different effect profile?"

---

## OUT-OF-STOCK SUBSTITUTION

If the customer requests a specific strain that is not available:
1. Search for the closest substitute (same type, similar effects).
2. Your response MUST include all three of these phrases: "we don't currently carry", "closest match", "same [effect/feeling]".

---

## PRODUCT DISPLAY FORMAT

- THC in % → display as "22% THC"
- THC in mg → display as "5mg THC per piece"
- Edibles/tinctures: always mention onset time and "start with 1 piece/dose, wait [onset time] before taking more"
- Vaporizers: always mention hardware type if available (e.g. "510-thread cartridge", "disposable")
- Price: always include price
- Keep responses concise — no walls of text; use bullet points for product details

---

## NATURAL LANGUAGE INTERPRETATION

Interpret ALL natural language by underlying intent. When calling smart_search, map these phrases to the corresponding tool parameters:
- "can't sleep" / "tossing and turning" / "sleep problems" → effects=['Sleepy'], time_of_day='Nighttime', activity_scenario='Sleep'
- "want to get high" / "hit hard" / "stronger" → high THC, experienced level
- "rough day" / "need to unwind" / "de-stress" / "stressed out" → effects=['Relaxed','Calm'], activity_scenario='Relaxation'
- "relax" / "chill" / "take the edge off" → effects=['Relaxed','Calm'], activity_scenario='Relaxation'
- "put me on the couch" / "heavy indica" / "couch lock" → effects=['Relaxed', 'Sleepy'], time_of_day='Nighttime'
  (use Relaxed+Sleepy; "Sedated" is not a valid effect in the database and will return zero results)
- "no couch lock" / "nothing too sedating" / "not too sleepy" → exclude_effects=['Sedated', 'Sleepy']
- "energy" / "productive" / "I need a boost" → Energetic/Uplifted, Daytime
- "smoke" / "flower" / "joint" → category: Flower or Pre-rolls
- "gummy" / "edible" / "don't want to smoke" → category: Edibles
- "party" / "with friends" → Social scenario, Nighttime
- "hiking" / "on the go" → Active scenario, portable (Vaporizers/Pre-rolls)
- "focus" / "study" / "work" → Focused effect, Focus scenario, Daytime
- "cheap" / "budget" (no specific number) → use budget_target (e.g. 15 for pre-rolls), NOT max_price
- "around $X-$Y" / "between $X and $Y" → use budget_target=(X+Y)/2, NOT max_price=Y
- "creative" / "music" / "art" → Creative effect/scenario
- "pain" / "sore" / "back's killing me" → Relaxed/Tingly, Relaxation scenario
- "get high" / "gets me really high" / "hit hard" / "want to be high"
  → High THC potency request: set min_thc=20; DO NOT add "High" to effects list; keep other effect filters (e.g. if Indica, still include effects=['Relaxed','Sleepy'])
  Example: "Give me an indica, I want something that gets me really high" → query='indica', effects=['Relaxed','Sleepy'], min_thc=20
- Indica named → Relaxed/Sleepy, no need to ask effect
  - EXCEPTION: Indica + "no couch lock" / "nothing too sedating" / "don't want to be sedated" / "not too sleepy"
    → effects=['Relaxed'] ONLY (remove Sleepy), exclude_effects=['Sedated', 'Sleepy']
    The user's no-sedation preference OVERRIDES the default Indica→Sleepy mapping.
- Sativa named → Energetic/Uplifted, no need to ask effect
- Hybrid named → balanced, infer from other context

---

## TOOL USE

You have access to `smart_search` to find products and `get_product_details` for full product info.
Use `smart_search` whenever you are ready to recommend products. Never recommend products without calling the tool first.

**TOOL CALL RULES (follow strictly):**
- Call `smart_search` EXACTLY ONCE per turn — combine ALL criteria in a single call.

- **Strain NAMES** (e.g. Gelato, Sour Diesel, OG Kush, Pineapple Express) → use `query` field + EXACTLY 1 inferred effect (using multiple effects will return zero results due to AND filtering):
  Example: "I love Sour Diesel" → smart_search(query='Sour Diesel', effects=['Energetic'])
  Example: "something like Gelato" → smart_search(query='Gelato', effects=['Relaxed'])
  IMPORTANT: For strain name searches, always include exactly 1 effect in the list.

- **Strain TYPES** (Indica / Sativa / Hybrid) → translate to effects; ALSO add query='indica'/'sativa' to filter strain-typed products:
  - "sativa" or "sativa" + price → query='sativa', effects=['Energetic','Uplifted'] + price params
  - "indica" or "indica" + price → query='indica', effects=['Relaxed','Sleepy'] + price params
  - "heavy indica" / "couch lock" / "put me on the couch" → query='indica', effects=['Relaxed','Sleepy'], time_of_day='Nighttime'
  - "indica, no couch lock" / "indica, nothing too sedating" → query='indica', effects=['Relaxed'], exclude_effects=['Sedated','Sleepy']
  - **When user states an explicit product form (flower/pre-roll/edible/vape)**: use category param + effects, NO query:
    GOOD: "sativa flower" → category='Flower', effects=['Energetic','Uplifted']
    GOOD: "indica pre-roll" → category='Pre-rolls', effects=['Relaxed','Sleepy']
    GOOD: "cheap indica pre-rolls" → category='Pre-rolls', effects=['Relaxed','Sleepy'], budget_target=15
    BAD: "sativa flower" → query='sativa', effects=... (wrong — NO query when form is given)
    BAD: "indica pre-roll" → query='indica', category='Pre-rolls' (wrong — NO query when form is given, use effects instead)
  - Hybrid → infer effects from context; skip effects filter if unclear

- **Strain name takes priority** (only for specific named strains like Gelato, Sour Diesel, OG Kush — NOT for strain TYPES like indica/sativa/hybrid):
  If the message contains BOTH a strain name AND flavor words, ALWAYS put the strain name in `query`, not the flavor words.
  Example: "I like Gelato, looking for that sweet creamy flavor" → query='gelato', NOT query='sweet creamy'
  Example: "something similar to OG Kush, earthy flavor" → query='OG Kush', NOT query='earthy'

- **Flavor/terpene words** ("sweet", "creamy", "citrus", "earthy") → use `query` field only when NO strain name is present

- **Minimal bare requests** ("just give me a good sativa/indica", no price/form/qualifier) → add limit=3

- Price range "around $X-$Y": ALWAYS use budget_target=midpoint. Example: "$40-$50" → budget_target=45
- "cheap"/"affordable" with a specific category (no number): use budget_target=15, NOT max_price.
"""


# ── Simple response shortcuts ─────────────────────────────────────────────────

_SIMPLE_PATTERNS = [
    (re.compile(r"^\s*(hi|hello|hey|howdy|yo|sup)\W*$", re.IGNORECASE),
     "Hey there! Welcome to the dispensary. 🌿 What brings you in today — are you looking for something specific, or just browsing?"),
    (re.compile(r"^\s*(thanks|thank you|thx|ty|cheers)\W*$", re.IGNORECASE),
     "You're welcome! Feel free to ask anytime if you need more help finding the right product."),
    (re.compile(r"^\s*(bye|goodbye|see ya|later|cya|ttyl)\W*$", re.IGNORECASE),
     "Take care! Come back anytime. Enjoy your experience!"),
    (re.compile(r"^\s*(ok|okay|got it|sounds good|perfect|great|cool|nice|awesome)\W*$", re.IGNORECASE),
     "Great! Is there anything else I can help you find?"),
    (re.compile(r"^\s*(no|nope|nah)\W*$", re.IGNORECASE),
     "No problem at all! Feel free to ask whenever you need help finding something."),
]


def get_simple_response(user_message: str) -> str | None:
    """Return a canned reply for trivial greetings/closings, or None if LLM is needed."""
    for pattern, reply in _SIMPLE_PATTERNS:
        if pattern.match(user_message):
            return reply
    return None


# ── Query classification helpers ─────────────────────────────────────────────

_MEDICAL_PATTERNS = re.compile(
    r"\b(cure|treat|heal|fix|therapy|therapeutic)\b.{0,40}\b"
    r"(cancer|epilepsy|diabetes|depression|anxiety disorder|ptsd|alzheimer|parkinson|seizure|disorder|disease|condition)\b",
    re.IGNORECASE,
)

_VAGUE_PATTERNS = re.compile(
    r"^\s*(something (good|nice|fun|interesting|cool)|anything|whatever|"
    r"surprise me|i don'?t know|not sure|you (pick|choose|decide))\s*[.!?]?\s*$",
    re.IGNORECASE,
)

_FORM_KEYWORDS = re.compile(
    r"\b(flower|pre.?rolls?|edibles?|gummies?|chocolate|tinctures?|vapes?|vaping|"
    r"vaporizers?|cartridges?|carts?|concentrates?|wax|shatter|dab|capsules?|drinks?|beverages?)\b",
    re.IGNORECASE,
)

_EFFECT_KEYWORDS = re.compile(
    r"\b(sleep|relax|relax|calm|energy|energetic|focus|creative|uplifted|happy|"
    r"pain|sore|anxiety|stress|euphoric|sedated|high|stoned|chill|unwind)\b",
    re.IGNORECASE,
)

_STRAIN_TYPES = re.compile(r"\b(indica|sativa|hybrid)\b", re.IGNORECASE)

_EMOTIONAL_DISTRESS = re.compile(
    r"\b(rough day|bad day|stressed|stress|can'?t sleep|anxious|overwhelmed|"
    r"exhausted|burned out|burnt out|can'?t relax|need to unwind)\b",
    re.IGNORECASE,
)


def is_medical_query(user_message: str) -> bool:
    """Detect 'cure/treat [medical condition]' pattern."""
    return bool(_MEDICAL_PATTERNS.search(user_message))


def is_vague_query(user_message: str) -> bool:
    """Detect extremely vague queries like 'something good' or 'surprise me'."""
    return bool(_VAGUE_PATTERNS.match(user_message))


def is_form_unknown_query(user_message: str, history: list[dict]) -> bool:
    """
    Return True if the user mentions an effect but no product form,
    AND the conversation history has no form mentioned yet.
    """
    has_effect = bool(_EFFECT_KEYWORDS.search(user_message)) or bool(
        _STRAIN_TYPES.search(user_message)
    )
    if not has_effect:
        return False
    # Check if form already established in current message or history
    if _FORM_KEYWORDS.search(user_message):
        return False
    for msg in history:
        if _FORM_KEYWORDS.search(msg.get("content", "")):
            return False
    # 品种类型已指定（indica/sativa/hybrid）→ 无需询问形式，直接搜索
    if _STRAIN_TYPES.search(user_message):
        return False
    # 情绪困扰场景 → 跳过形式询问，直接搜索
    if _EMOTIONAL_DISTRESS.search(user_message):
        return False
    return True


# ── Session profile extraction ─────────────────────────────────────────────────

_BEGINNER_SIGNALS = re.compile(
    r"\b(first time|never tried|new to (this|cannabis|weed)|beginner|novice|"
    r"low tolerance|don'?t (smoke|use) much|my mom|my dad|my grandma|my grandpa)\b",
    re.IGNORECASE,
)
_EXPERT_SIGNALS = re.compile(
    r"\b(experienced|high tolerance|smoke daily|daily (smoker|user)|been smoking|"
    r"years of|veteran|connoisseur|strongest|most potent)\b",
    re.IGNORECASE,
)
_OCCASION_SIGNALS = re.compile(
    r"\b(party|social|with friends|date night|alone|solo|hiking|camping|"
    r"studying|work|gaming|movie|concert|yoga|gym|outdoor)\b",
    re.IGNORECASE,
)
_BUDGET_SIGNALS = re.compile(
    r"\b(budget|cheap|affordable|under \$[\d]+|around \$[\d]+|less than \$[\d]+|"
    r"premium|top shelf|high.?end|luxury)\b",
    re.IGNORECASE,
)


def extract_profile_signals(user_message: str, history: list[dict]) -> dict:
    """Extract session profile signals from message and history."""
    all_text = " ".join(
        msg.get("content", "") for msg in history
    ) + " " + user_message

    profile: dict = {}

    if _BEGINNER_SIGNALS.search(all_text):
        profile["experience_level"] = "beginner"
    elif _EXPERT_SIGNALS.search(all_text):
        profile["experience_level"] = "expert"

    occasions = _OCCASION_SIGNALS.findall(all_text)
    if occasions:
        profile["occasions"] = list({o.lower() for o in occasions})

    if re.search(r"\b(budget|cheap|affordable)\b", all_text, re.IGNORECASE):
        profile["price_range"] = "budget"
    elif re.search(r"\b(premium|top shelf|high.?end)\b", all_text, re.IGNORECASE):
        profile["price_range"] = "premium"

    dislikes = []
    if re.search(r"\b(don'?t want to smoke|no smoke|can'?t inhale|no smoking)\b", all_text, re.IGNORECASE):
        dislikes.append("smoking")
    if re.search(r"\b(don'?t want to be couch.?locked|no couch lock)\b", all_text, re.IGNORECASE):
        dislikes.append("heavy sedation")
    if dislikes:
        profile["dislikes"] = dislikes

    forms = _FORM_KEYWORDS.findall(all_text)
    if forms:
        profile["preferred_types"] = list({f.lower() for f in forms})

    return profile


def serialize_profile(profile: dict) -> str:
    """Serialize session profile dict to a text block for system prompt injection."""
    if not profile:
        return ""
    lines = ["", "---", "## SESSION PROFILE (use to personalize recommendations)"]
    for key, value in profile.items():
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            lines.append(f"- {label}: {', '.join(value)}")
        else:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


# ── Tool schema (OpenAI function calling) ─────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "smart_search",
            "description": (
                "Search the product catalog. Use this whenever you are ready to recommend products. "
                "All parameters are optional — use only the ones relevant to the customer's request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text keyword search (strain name, flavor, effect, etc.)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Product category: Flower, Pre-rolls, Edibles, Vaporizers, Concentrates, Tinctures, Accessories",
                    },
                    "effects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Desired effect keywords (e.g. ['Sleepy', 'Relaxed', 'Focused'])",
                    },
                    "exclude_effects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Effects to avoid (e.g. ['Sedated'] for 'no couch lock')",
                    },
                    "exclude_categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Categories to exclude (e.g. ['Concentrates'] for beginners)",
                    },
                    "min_thc": {
                        "type": "number",
                        "description": "Minimum THC percentage (for experienced users wanting potency)",
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximum price filter",
                    },
                    "budget_target": {
                        "type": "number",
                        "description": "Target budget — finds best value products at or near this price",
                    },
                    "time_of_day": {
                        "type": "string",
                        "description": "Daytime, Nighttime, or Anytime",
                    },
                    "activity_scenario": {
                        "type": "string",
                        "description": "Activity scenario: Sleep, Relaxation, Focus, Social, Active, Creative, etc.",
                    },
                    "list_sub_types": {
                        "type": "boolean",
                        "description": "If true, return category/subcategory overview instead of individual products",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 8)",
                    },
                    "is_beginner": {
                        "type": "boolean",
                        "description": "Set to true if the customer is a first-time or beginner user. Applies safety limits: max 5mg THC for edibles, max 20% for flower/vapes, excludes high-THC topicals and concentrates.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_details",
            "description": "Get full details for a specific product by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "The product ID (integer as string)",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
]


# ── Message assembly ───────────────────────────────────────────────────────────

def build_messages(
    history: list[dict],
    user_message: str,
    profile: dict | None = None,
) -> list[dict]:
    """
    Assemble the messages list for the OpenAI API call.

    Structure: [system + profile] + history + [user message].
    No product JSON injected — products come via tool calling.

    Args:
        history: Previous messages as list of {role, content} dicts.
        user_message: Current user message text.
        profile: Optional session profile dict to append to system prompt.

    Returns:
        List of message dicts ready for the OpenAI chat API.
    """
    system_content = SYSTEM_PROMPT
    if profile:
        system_content += serialize_profile(profile)

    messages = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


# ── Agent loop ────────────────────────────────────────────────────────────────

def get_recommendation(
    history: list[dict],
    user_message: str,
    product_manager,  # ProductManager instance
    is_beginner: bool = False,
) -> str:
    """
    Run the Agent Loop: call LLM → execute tool calls → call LLM again until done.

    Args:
        history: Previous messages as list of {role, content} dicts.
        user_message: Current user message text.
        product_manager: ProductManager instance for tool execution.

    Returns:
        Final assistant reply text.

    Raises:
        RuntimeError: If the API call fails.
    """
    client = openai.OpenAI(api_key=OPENAI_API_KEY)

    # Extract session profile for personalization
    profile = extract_profile_signals(user_message, history)
    # is_beginner from frontend overrides detected signals (hard guarantee)
    if is_beginner:
        profile["experience_level"] = "beginner"

    # Determine tool_choice based on query classification
    if is_medical_query(user_message):
        tool_choice = "none"
    elif is_vague_query(user_message):
        tool_choice = "none"
    elif is_form_unknown_query(user_message, history) and not is_beginner:
        tool_choice = "none"
    else:
        tool_choice = "auto"

    messages = build_messages(history, user_message, profile)

    try:
        # Agent loop — max 3 iterations to prevent infinite loops
        for iteration in range(3):
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice=tool_choice,
            )

            msg = response.choices[0].message

            # No tool calls → we have the final answer
            if not msg.tool_calls:
                return msg.content or ""

            # Append assistant message with tool calls
            messages.append(msg)

            # Execute each tool call
            search_had_results = False
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                logger.info("[Agent] Calling tool: %s args=%s", fn_name, fn_args)

                if fn_name == "smart_search":
                    result = product_manager.search_products(**fn_args)
                    if result.get("total", 0) > 0:
                        search_had_results = True
                elif fn_name == "get_product_details":
                    pid = fn_args.get("product_id", "")
                    result = product_manager.get_product_by_id(pid) or {}
                else:
                    result = {"error": f"Unknown tool: {fn_name}"}

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, separators=(",", ":")),
                })

            # If search returned results, force LLM to generate reply (no re-search)
            # If search was empty, allow LLM to retry with different parameters
            tool_choice = "none" if search_had_results else "auto"

        # Fallback: call once more without tools
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    except openai.APITimeoutError as exc:
        raise RuntimeError("OpenAI API request timed out.") from exc
    except openai.RateLimitError as exc:
        raise RuntimeError("OpenAI API rate limit exceeded.") from exc
    except openai.APIError as exc:
        raise RuntimeError(f"OpenAI API error: {exc}") from exc
