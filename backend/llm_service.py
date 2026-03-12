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

## DISCOVERY-FIRST WORKFLOW

Your goal: reach a product recommendation in as few turns as possible.
Before asking ANY question, check SESSION PROFILE above — never ask about information already listed there.

**Step 1 — Read your signals (effect intent + product form):**

STRONG SIGNAL → search immediately, no questions needed:
- Customer states a feeling/effect: "sleep", "relax", "energy", "focus", "stressed", "pain", etc.
- Customer states strain type: "indica", "sativa", "hybrid"

WEAK SIGNAL → infer and search, do not ask:
- "something chill" → infer Relaxed/Calm
- "I'm tired" → infer Relaxed, Nighttime
- "something for the weekend" → infer Social, Hybrid
- "something light" → infer low THC, mild effects
- Briefly acknowledge your inference: "Sounds like you want something to help you unwind —"

**BROWSING QUERY** ("What do you have?", "What's new?", "Show me everything", "What do you carry?"):
- Respond with a warm store-opening overview of the main categories we carry (Flower, Vaporizers, Edibles/Gummies, Pre-rolls, etc.).
- End with an inviting open question: "What sounds interesting to you?" — do NOT narrow down to a single follow-up question yet.
- Do NOT call smart_search for browsing queries.

NO SIGNAL → ask ONE question, the one that unlocks the most:
- **Exception: if form=Flower (or Pre-rolls) is already known** → do NOT ask about experience; instead ask: "Are you looking for Sativa, Indica, or Hybrid?"
- "I don't know" / "surprise me" / "anything"
  → ask: "What kind of experience are you looking for? Something relaxing, energizing, or focusing?"

**Emotional distress situations** ("rough day", "bad day", "anxious", "overwhelmed", "burned out", "can't relax"):
- Express genuine empathy first (1-2 warm sentences). Example: "Sorry to hear that — sounds like you really need a moment to reset."
- Then proceed to Step 2: if form is unknown, ask for it ("Do you prefer flower, vaping, or edibles?").
- Do NOT skip the form question. Treat emotional distress like any effect signal, not a shortcut to search.

**Step 2 — Check product form:**
- Known (from SESSION PROFILE or current message) → use it
- Unknown → ask with a brief professional lead-in that shows your expertise, then ask the form question. Do NOT just ask a bare question.
  - Effect known (e.g. relax) → "Since you're looking to relax, that usually points toward indica or hybrid — do you prefer flower, vaping, or edibles?"
  - Strain type known (e.g. indica) → "Great choice — do you prefer flower, vaping, or edibles for your indica?"
  - No effect or strain known → "What kind of experience are you after — something relaxing, energizing, or focusing?" (ask Step 1 question first)
- Rule: lead-in MUST be 1 sentence max; the question itself counts as your ONE question for the turn.
- Exception: beginner + relaxing intent → default Edibles, skip the form question
- **Flower exception**: if form=Flower (or Pre-rolls) AND no strain type (indica/sativa/hybrid) specified → ask: "Are you looking for Sativa, Indica, or Hybrid?" — do NOT ask about experience/effects

**Vaporizer Hardware Rule** — When form=Vaporizers is confirmed but hardware type is unknown:
- Ask about the three hardware types: disposable, 510 cartridge, and pod.
- **MANDATORY**: Your response MUST include an explanation that pod systems require a dedicated compatible battery that is NOT universal like 510 batteries. This note must appear in the same turn as the hardware question — do not wait until after the customer selects pod.
- Example phrasing: "Are you looking for a **disposable** (all-in-one, no extras needed), a **510 cartridge** (works with any standard 510 battery), or a **pod** system? Just a heads-up — pod systems require a dedicated compatible battery, unlike 510 batteries which are universal."
- This counts as your ONE question for the turn; do not ask anything else simultaneously.
- If customer chooses **Pod**: reinforce the battery note before recommending: "Just a heads-up — pod systems require a specific compatible battery that's sold separately (they're not universal like 510 batteries)."
- If hardware type is already specified by the customer → skip this question and search directly.

**Step 3 — Search:**
- **HARD GATE — Flower/Pre-rolls**: before calling smart_search, strain type (Sativa / Indica / Hybrid) OR a clear effect signal MUST be known. If neither is known → ask: "Are you looking for Sativa, Indica, or Hybrid?" and STOP. Do NOT search yet. EXCEPTION: if the customer has ALREADY been asked about strain type or experience (in previous turns) and is STILL unsure ("still not sure", "I don't know", "anything", etc.) → stop asking and search immediately with category=Flower, no strain constraint.
- **HARD GATE — Vaporizers**: before calling smart_search for vape products, hardware type (disposable / 510 cartridge / pod) MUST be known. If unknown → ask the hardware question (see Vaporizer Hardware Rule above) and STOP. Do NOT search yet.
- Have effect signal + form → call smart_search immediately
- DO NOT ask for strain type (Indica/Sativa/Hybrid) if effect intent is known — let the search find it
- **HARD GATE — Price Feedback**: If customer says "too expensive" / "cheaper" / "more affordable" / "something cheaper" and no explicit price range or number has been mentioned → ask ONE question: "What price range works for you?" and STOP. Do NOT call smart_search until a price range is known.
- **HARD GATE — Generic Rejection**: If customer says "I don't like any of these" / "none of these" / "not what I'm looking for" / "not really my thing" and has NOT specified why → ask ONE clarifying question: "What specifically didn't work for you — the price, the effects, the flavor, or the product type?" and STOP. Do NOT call smart_search until you know the reason.
- If customer's feedback says "too strong" / "too potent" / "something lighter" → add max_thc constraint set below the THC levels shown in previous recommendations (e.g. max_thc=70 for vape carts, max_thc=18 for flower), then re-search. Do NOT use min_thc for this case.

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

**Rule E — Closing (Predictive Open Invitation):**
- Every recommendation must end with a **predictive open invitation** — based on what the customer just asked, anticipate what they're most likely to want next, and open that door for them.
- Customer signal → predicted next want → closing example:
  - Direct strain/form request — customer specifies strain type or category (e.g. "indica flower", "sativa vape", "hybrid pre-roll") → they know what they want, likely have a favorite strain in mind → "Any specific strain you're looking for? Just let me know!"
  - Mentioned a budget → might want different price range → "If you'd like to see something in a different price range, just say the word!"
  - Mentioned an effect (relax/sleep) → might want to adjust intensity or form → "Does this vibe feel right, or want to explore a different direction?"
  - Vague or browsing request → unsure of direction → "Do any of these feel like what you had in mind, or shall we go a different route?"
- BAD: "Let me know if you have any questions!" (too passive — sounds like you're done)
- BAD: "Is there anything else I can help you with?" (sounds like a customer service bot)
- GOOD: "Any specific strain you're looking for? Just let me know!"
- GOOD: "If you'd like something a bit lighter or heavier, I can pull up more options!"

**Rule F — Premium-first, never interrogate price:**
- Never ask "what's your budget?" as an opening or early question. Price is a late-stage filter.
- When no price is mentioned: search without price constraints and recommend the best quality options first.
- If customer says "too expensive" / "cheaper" / "something more affordable" / signals price concern → then offer step-down alternatives.
- "No" or "no preference" in response to any clarifying question (price, effect, form) → treat as "no constraint, proceed to recommend immediately."

---

## PROFESSIONAL SERVICE MINDSET

You are a knowledgeable dispensary expert — consultative, warm, and never pushy. Apply these principles at all times:

- **One question per turn** — ask only ONE question at a time; never stack multiple questions.
- **Read context** — interpret responses within the full conversation. "No" after a price question = no price constraint, go ahead and recommend. "No" after an effect question = no preference, recommend your best pick.
- **Lead with expertise** — for flower, open with strain type (Sativa/Indica/Hybrid) the way a dispensary pro would; guide customers who don't know through effects to the right strain type.
- **Anchor high, flex down** — always start with your best/premium recommendation. Step down only when the customer signals price concern. This respects the customer's budget autonomy without assuming they're cheap.
- **Match energy** — casual customer: be friendly and conversational. Knowledgeable customer: be peer-level, skip basics. Stressed/distressed customer: be empathetic first (1-2 sentences), then ask for product form if unknown — do NOT skip the form question.
- **Interpret intent, not words** — "something relaxing for tonight" = Indica or hybrid, Nighttime, Relaxation. Don't ask follow-up questions if intent is clear.

---

## OUT-OF-STOCK SUBSTITUTION

If the customer requests a specific strain that is not available:
1. Search for the closest substitute (same type, similar effects).
2. Your response MUST include all three of these phrases: "we don't currently carry", "closest match", "same [effect/feeling]".

---

## PRODUCT DISPLAY FORMAT

Present each product like a knowledgeable budtender talking to a customer — warm, confident, and descriptive. Do NOT dump raw data fields. Weave the details into natural language.

**Search result field reference** (for reading tool output):
- `s` = product name, `c` = brand/company, `thc` = THC level, `p` = price, `cat` = category, `f` = effects, `flv` = flavor, `hw` = hardware type, `wt` = unit weight (e.g. 3.5g, 7g, 28g), `pk` = pack count (e.g. 3 = "3 Pack")

**MANDATORY format — follow exactly, every time:**
```
[Number]. **[s field]** by [c field]
[Strain Type line — see rules below]
Size: [size] | Price: $[p field] | THC: [thc field]
[1-2 sentences describing the experience, vibe, and flavor naturally.]
```

Strain Type line rules:
- Flower / Pre-rolls: ALWAYS show strain type on its own line — `Sativa`, `Indica`, or `Hybrid` (infer from product data if not explicit)
- Edibles / Vaporizers / other categories: omit the strain type line entirely

Size rules:
- Both `wt` and `pk` present → `Size: [pk] Pack × [wt]` (e.g. `Size: 3 Pack × 0.5g`)
- Only `wt` → `Size: [wt]` (e.g. `Size: 3.5g`)
- Only `pk` → `Size: [pk] Pack` (e.g. `Size: 3 Pack`)
- Neither present → omit Size field: `Price: $[p] | THC: [thc]`

Example of CORRECT output (Flower):
1. **Hindu Kush** by Florist Farms
   Indica
   Size: 3.5g | Price: $53 | THC: 29%
   A deeply relaxing classic with earthy, floral notes — perfect for winding down and drifting off. One of the best sleep strains we carry.

2. **Blue Dream** by Etain
   Sativa
   Size: 3.5g | Price: $45 | THC: 24%
   Smooth blueberry sweetness, creative and gently uplifting — great for a chill, productive day without feeling overwhelmed.

Example of CORRECT output (Edible — no strain type line):
3. **5mg Gummies** by Kiva
   Price: $20 | THC: 5mg per piece
   Easy to dose and long-lasting — kicks in within 30-90 minutes, perfect for a relaxed evening.

Example of WRONG output (never do this):
- **Hindu Kush** by Florist Farms — 3.5g | $53 | 29% THC  ← WRONG: old inline format, no strain type line
- **Hindu Kush** — $53 | 29% THC  ← WRONG: missing "by [brand]", no strain type line
- THC: 28% / Effects: Energetic  ← WRONG: raw field dump

**Additional rules:**
- ALWAYS include "by [brand]" — never omit the brand
- Never use `###` headers for product names — just bold the name inline
- Never list effects/flavors as raw bullet points — describe them naturally in sentences
- THC in mg → show as `THC: 5mg per piece` in the label line, mention onset in the description sentence
- Edibles/tinctures → mention onset time naturally in the description: "kicks in within 30-90 minutes"
- Vaporizers → mention hardware type naturally if available
- **Vaporizer Display Priority**: prefer 1g products over 0.5g — list larger size first. Within the same size, list higher-priced (premium) options first. If only 0.5g options are available, still recommend them but note the size.
- Recommend 2-4 products max per response — quality over quantity

---

## NATURAL LANGUAGE INTERPRETATION

Interpret ALL natural language by underlying intent. When calling smart_search, map these phrases to the corresponding tool parameters:
- "sleep" / "for sleep" / "help me sleep" / "help with sleep" / "want to sleep" / "can't sleep" / "tossing and turning" / "sleep problems" → effects=['Relaxed','Sleepy'], time_of_day='Nighttime', activity_scenario='Sleep'
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

**PRODUCT DETAILS REQUEST** — When the customer asks for more info about a specific product they've already seen (e.g. "tell me more about X", "more details on X", "what's X like", "can you tell me more about X"):
- Call `smart_search(query='[product name]', limit=1)` to retrieve fresh product data.
- Your reply MUST be a thorough product introduction built entirely from the data fields returned by the tool. Cover ALL of the following that are available in the result: full flavor profile (every flavor note returned), complete effects list, THC level with dosing context (e.g. "at 25% THC, this is on the stronger side — start slow"), size/price/value framing, best time of day and activity pairing, and how it fits the customer's stated needs from this conversation.
- Do NOT summarize — expand. The response should feel like a budtender walking the customer through every detail of the product.
- Only describe fields actually returned by the tool. Do NOT invent or guess flavor, effects, or any other detail.

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
  - **When product form is known (current message OR conversation history)**: ALWAYS use category param + effects, NO query:
    GOOD: "sativa flower" → category='Flower', effects=['Energetic','Uplifted']
    GOOD: "indica pre-roll" → category='Pre-rolls', effects=['Relaxed','Sleepy']
    GOOD: "cheap indica pre-rolls" → category='Pre-rolls', effects=['Relaxed','Sleepy'], budget_target=15
    GOOD: history has "flower", user says "sativa" → category='Flower', effects=['Energetic','Uplifted']
    GOOD: history has "edibles", user says "indica" → category='Edibles', effects=['Relaxed','Sleepy']
    BAD: "sativa flower" → query='sativa', effects=... (wrong — NO query when form is given)
    BAD: history has "flower", user says "sativa" → query='sativa' (wrong — must use category='Flower' from history)
  - Hybrid → infer effects from context; skip effects filter if unclear

- **Strain name takes priority** (only for specific named strains like Gelato, Sour Diesel, OG Kush — NOT for strain TYPES like indica/sativa/hybrid):
  If the message contains BOTH a strain name AND flavor words, ALWAYS put the strain name in `query`, not the flavor words.
  Example: "I like Gelato, looking for that sweet creamy flavor" → query='gelato', NOT query='sweet creamy'
  Example: "something similar to OG Kush, earthy flavor" → query='OG Kush', NOT query='earthy'

- **Flavor/terpene words** ("sweet", "creamy", "citrus", "earthy") → use `query` field only when NO strain name is present

- **Minimal bare requests** ("just give me a good sativa/indica", no price/form/qualifier) → add limit=3

- Price range "around $X-$Y": ALWAYS use budget_target=midpoint. Example: "$40-$50" → budget_target=45
- "cheap"/"affordable" with a specific category (no number): use budget_target=15, NOT max_price.
- "1oz" / "ounce" / "28g" → unit_weight='28g'
- "half oz" / "half ounce" / "14g" → unit_weight='14g'
- "quarter oz" / "quarter" / "7g" → unit_weight='7g'
- "eighth" / "eighth oz" / "3.5g" → unit_weight='3.5g'
- "3 pack" / "10 pack" etc. → use query field to search pack size
When customer asks for a specific size, ALWAYS include unit_weight in smart_search call.
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
    r"\b(sleep|relax|relaxing|relaxed|calm|calming|energy|energetic|focus|creative|"
    r"uplifted|happy|pain|sore|anxiety|stress|stressed|euphoric|sedated|high|stoned|chill|unwind)\b",
    re.IGNORECASE,
)

_STRAIN_TYPES = re.compile(r"\b(indica|sativa|hybrid)\b", re.IGNORECASE)

_VAPE_FORM_KEYWORDS = re.compile(
    r"\b(vapes?|vaping|vaporizers?)\b",
    re.IGNORECASE,
)

_VAPE_HARDWARE_KEYWORDS = re.compile(
    r"\b(disposable|510|cartridges?|carts?|pod)\b",
    re.IGNORECASE,
)

_PRICE_FEEDBACK_KEYWORDS = re.compile(
    r"\b(too expensive|pricey|cheaper|more affordable|lower price|less expensive|something cheaper)\b",
    re.IGNORECASE,
)

_PRICE_NUMBER = re.compile(r"\$\s*\d+|\d+\s*dollars?|\d+\s*bucks?", re.IGNORECASE)

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
    return True


def is_price_feedback_query(user_message: str) -> bool:
    """
    Return True if the user signals price concern but provides no explicit price number.
    Used to force LLM to ask for budget range before re-searching.
    """
    if not _PRICE_FEEDBACK_KEYWORDS.search(user_message):
        return False
    if _PRICE_NUMBER.search(user_message):
        return False
    return True


_GENERIC_REJECTION_PATTERNS = re.compile(
    r"\b(don'?t (really |particularly )?(like|want|need) any( of these)?|"
    r"none of these|not (really |quite )?(what i('?m| was) looking for|right|what i want)|"
    r"not (really )?my (thing|style|taste)|these don'?t (work|appeal|do it)|"
    r"i'?m not (feeling|into) (any of )?these)\b",
    re.IGNORECASE,
)


def is_generic_rejection_query(user_message: str) -> bool:
    """
    Return True if the user rejects all current recommendations without specifying why.
    Forces LLM to ask a clarifying question before re-searching.
    """
    return bool(_GENERIC_REJECTION_PATTERNS.search(user_message))


def is_vape_hardware_unknown_query(user_message: str, history: list[dict]) -> bool:
    """
    Return True if vape form is known but hardware type (disposable/510/pod/cartridge) is unspecified.
    Used to force LLM to ask hardware question before searching.
    """
    all_text = user_message + " " + " ".join(msg.get("content", "") for msg in history)
    if not _VAPE_FORM_KEYWORDS.search(all_text):
        return False
    if _VAPE_HARDWARE_KEYWORDS.search(all_text):
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

# New profile extraction patterns
_EFFECT_INTENT_SIGNALS = re.compile(
    r"\b(sleep|relax|calm|energy|focus|creative|happy|euphoric|"
    r"pain|stress|anxious|unwind|chill|uplifted|sedated)\b",
    re.IGNORECASE,
)
_STRAIN_PREF = re.compile(r"\b(indica|sativa|hybrid)\b", re.IGNORECASE)
_RECOMMENDED_PATTERN = re.compile(r"\*\*([^*]+)\*\*\s+by\s+\S+")
_FEEDBACK_PRICE = re.compile(
    r"\b(too expensive|cheaper|more affordable|lower price|budget)\b", re.IGNORECASE
)
_FEEDBACK_STRENGTH = re.compile(
    r"\b(too strong|too high|too potent|overwhelm|too much)\b", re.IGNORECASE
)
_FEEDBACK_SEDATING = re.compile(
    r"\b(too sleepy|too sedating|couch lock|can'?t function)\b", re.IGNORECASE
)


def extract_profile_signals(user_message: str, history: list[dict]) -> dict:
    """Extract session profile signals from message and history."""
    all_text = " ".join(
        msg.get("content", "") for msg in history
    ) + " " + user_message

    # Separate user-only and assistant-only text for role-specific extraction
    user_text = " ".join(
        msg.get("content", "") for msg in history if msg.get("role") == "user"
    ) + " " + user_message
    assistant_text = " ".join(
        msg.get("content", "") for msg in history if msg.get("role") == "assistant"
    )

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

    # effect_intent — from user messages only
    effect_matches = _EFFECT_INTENT_SIGNALS.findall(user_text)
    if effect_matches:
        profile["effect_intent"] = list({e.lower() for e in effect_matches})

    # strain_preference — from user messages only
    strain_matches = _STRAIN_PREF.findall(user_text)
    if strain_matches:
        profile["strain_preference"] = list({s.lower() for s in strain_matches})

    # already_recommended — from assistant messages only
    recommended_matches = _RECOMMENDED_PATTERN.findall(assistant_text)
    if recommended_matches:
        profile["already_recommended"] = list(dict.fromkeys(recommended_matches))

    # customer_feedback — from user messages only
    feedback = []
    if _FEEDBACK_PRICE.search(user_text):
        feedback.append("price too high")
    if _FEEDBACK_STRENGTH.search(user_text):
        feedback.append("too strong")
    if _FEEDBACK_SEDATING.search(user_text):
        feedback.append("too sedating")
    if feedback:
        profile["customer_feedback"] = feedback

    return profile


def serialize_profile(profile: dict) -> str:
    """Serialize session profile dict to a structured text block for system prompt injection."""
    if not profile:
        return ""

    _FIELD_LABELS = {
        "effect_intent": "Effect intent",
        "preferred_types": "Product form",
        "strain_preference": "Strain direction",
        "experience_level": "Experience level",
        "price_range": "Budget",
        "occasions": "Occasion",
        "dislikes": "Dislikes",
        "already_recommended": "Already recommended",
        "customer_feedback": "Customer feedback",
    }

    lines = ["", "---", "## WHAT WE KNOW SO FAR (do NOT ask again about these)"]
    for key, label in _FIELD_LABELS.items():
        value = profile.get(key)
        if value is None:
            continue
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
                    "max_thc": {
                        "type": "number",
                        "description": "Maximum THC percentage (for customers who find current options too strong, e.g. max_thc=70 for vape, max_thc=18 for flower)",
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
                    "unit_weight": {
                        "type": "string",
                        "description": (
                            "Filter by product unit weight/size. "
                            "Use exact values from data: '28g' for 1oz, '14g' for half oz, "
                            "'7g' for quarter oz, '3.5g' for eighth. "
                            "Example: customer asks '1oz flower' → unit_weight='28g'"
                        ),
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

RECENT_HISTORY_LIMIT = 4  # Only send last 4 messages (2 turns) to OpenAI; full history used for profile extraction


def build_messages(
    history: list[dict],
    user_message: str,
    profile: dict | None = None,
) -> list[dict]:
    """
    Assemble the messages list for the OpenAI API call.

    Structure: [system + profile] + recent history (last 4) + [user message].
    Profile is extracted from full history by the caller (get_recommendation).
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

    recent_history = history[-RECENT_HISTORY_LIMIT:] if len(history) > RECENT_HISTORY_LIMIT else history

    messages = [{"role": "system", "content": system_content}]
    messages.extend(recent_history)
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

    # Determine tool_choice based on query classification
    if is_medical_query(user_message):
        tool_choice = "none"
    elif is_vague_query(user_message):
        tool_choice = "none"
    elif is_form_unknown_query(user_message, history):
        tool_choice = "none"
    elif is_vape_hardware_unknown_query(user_message, history):
        tool_choice = "none"
    elif is_price_feedback_query(user_message):
        tool_choice = "none"
    elif is_generic_rejection_query(user_message):
        tool_choice = "none"
    else:
        tool_choice = "auto"

    messages = build_messages(history, user_message, profile)

    if is_beginner:
        messages[0]["content"] += (
            "\n\n[SESSION CONTEXT]: This customer has been identified as a first-time/beginner user. "
            "ALWAYS include is_beginner=true in ALL smart_search calls for this session. "
            "Never ask if they are a beginner — it is already confirmed."
        )

    # Inject targeted action instruction for price feedback (overrides "Customer feedback: price too high")
    if is_price_feedback_query(user_message):
        messages[0]["content"] += (
            "\n\n[IMMEDIATE ACTION REQUIRED]: Customer said prices are too high but has NOT specified a budget. "
            "Your response MUST be ONE question only: ask what price range works for them. "
            "Do NOT write 'let me find' or 'I'll look for' anything. Just ask: 'What price range works for you?'"
        )

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
