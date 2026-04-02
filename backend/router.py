"""Request routing and classification for AI Budtender.

Contains:
- Fast-path simple response patterns (greetings, thanks, etc.)
- Query classifiers (is_*_query functions)
- Tool-choice decision logic (_determine_tool_choice)
- Session profile extraction and serialization
- Fast-path search parameter extraction (try_extract_search_params)
"""
# pylint: disable=line-too-long

import re

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
    r"\b(sleep|relax|relaxation|relaxing|relaxed|calm|calming|energy|energetic|focus|creative|"
    r"uplifted|happy|pain|sore|anxiety|stress|stressed|euphoric|sedated|high|stoned|chill|unwind)\b",
    re.IGNORECASE,
)

_SOCIAL_VIBE_KEYWORDS = re.compile(
    r"\b(smiley|connected|connection|giggly|laugh|laughing|social|sociable|romantic|intimate)\b",
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

_VAPE_FLOWER_ALTERNATIVE = re.compile(
    r"\b(vapes?|vaping|vaporizers?)\s+(or|and)\s+(flower|pre.?rolls?)\b"
    r"|\b(flower|pre.?rolls?)\s+(or|and)\s+(vapes?|vaping|vaporizers?)\b",
    re.IGNORECASE,
)

_PRODUCT_COMPARISON_PATTERNS = re.compile(
    r"\b(difference|compare|comparison|versus|vs\.?)\b.{0,60}\b(and|or|vs\.?)\b|"
    r"\bwhich (one|is better|would you recommend)\b|"
    r"\bhow does .{1,40} compare\b",
    re.IGNORECASE,
)

_NEGATIVE_STRENGTH_CONSTRAINT = re.compile(
    r"\b(do\s*n'?t|do\s+not)\s+want\s+to\s+(feel|be|get)\s+(wrecked|out of it|knocked out|destroyed|overwhelmed|too high|too stoned)|"
    r"\bnot\s+(too\s+(intense|strong|heavy|much)|feel\s+wrecked)\b|"
    r"\bnot\s+knocked\s+out\b|"
    r"\bnot\s+paranoid\b|"
    r"\bmentally\s+(pretty\s+)?clear\b|"
    r"\bclear(?:-|\s)?headed\b|"
    r"\bnothing\s+too\s+(heavy|intense|strong)\b|"
    r"\b(without|no)\s+(a\s+)?hangover\b|"
    r"\b(do\s*n'?t|do\s+not)\s+want\s+(a\s+)?hangover\b|"
    r"\bnot\s+(wrecked|hammered|destroyed)\s+tomorrow\b",
    re.IGNORECASE,
)

_PRICE_FEEDBACK_KEYWORDS = re.compile(
    r"\b(too expensive|pricey|cheaper|more affordable|lower price|less expensive|something cheaper)\b",
    re.IGNORECASE,
)

_PRICE_NUMBER = re.compile(r"\$\s*\d+|\d+\s*dollars?|\d+\s*bucks?", re.IGNORECASE)

_GENERIC_REJECTION_PATTERNS = re.compile(
    r"\b(don'?t (really |particularly )?(like|want|need) any( of these)?|"
    r"none of these|not (really |quite )?(what i('?m| was) looking for|right|what i want)|"
    r"not (really )?my (thing|style|taste)|these don'?t (work|appeal|do it)|"
    r"i'?m not (feeling|into) (any of )?these)\b",
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

    Exception: when a clear occasion/scenario signal is present (e.g. date night,
    party, workout), information is sufficient to search — do not ask for form.
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
    # 明确场景信号（date night / party / workout 等）→ 信息已足够，无需追问形式
    if _OCCASION_SIGNALS.search(user_message):
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
    Only checks USER messages for vape intent — ignores assistant messages that may offer vaping as an option.
    """
    # "vape or flower" / "flower or vape" → treat as Flower, skip hardware gate
    if _VAPE_FLOWER_ALTERNATIVE.search(user_message):
        return False
    # Only look at user-side messages for vape intent
    user_text = user_message + " " + " ".join(
        msg.get("content", "") for msg in history if msg.get("role") == "user"
    )
    if not _VAPE_FORM_KEYWORDS.search(user_text):
        return False
    # Hardware keyword can appear anywhere (user or assistant)
    all_text = user_message + " " + " ".join(msg.get("content", "") for msg in history)
    if _VAPE_HARDWARE_KEYWORDS.search(all_text):
        return False
    return True


# ── Pattern-check public API (keeps private regex internals encapsulated) ────────

def is_vape_flower_alternative(message: str) -> bool:
    """Return True if message contains 'vape or flower' (or similar) alternative."""
    return bool(_VAPE_FLOWER_ALTERNATIVE.search(message))


def is_product_comparison(message: str) -> bool:
    """Return True if message is a product comparison request."""
    return bool(_PRODUCT_COMPARISON_PATTERNS.search(message))


def is_negative_strength_constraint(message: str) -> bool:
    """Return True if message contains a negative strength/intensity constraint."""
    return bool(_NEGATIVE_STRENGTH_CONSTRAINT.search(message))


def is_occasion_ready_query(user_message: str, history: list[dict]) -> bool:
    """
    Return True when occasion + vibe/effect signals are complete enough to search
    even if the customer has not specified a product form yet.
    """
    if has_form_keyword(user_message):
        return False

    user_history = " ".join(
        msg.get("content", "") for msg in history if msg.get("role") == "user"
    )
    all_user_text = f"{user_history} {user_message}".strip()
    if not _OCCASION_SIGNALS.search(all_user_text):
        return False

    has_effect = bool(_EFFECT_KEYWORDS.search(all_user_text)) or bool(
        _STRAIN_TYPES.search(all_user_text)
    )
    has_social_vibe = bool(_SOCIAL_VIBE_KEYWORDS.search(all_user_text))
    has_guardrail = bool(_NEGATIVE_STRENGTH_CONSTRAINT.search(all_user_text))
    return (has_effect or has_social_vibe) and has_guardrail


def has_form_keyword(text: str) -> bool:
    """Return True if text contains a product form keyword (flower, edibles, vape, etc.)."""
    return bool(_FORM_KEYWORDS.search(text))


# ── Tool-choice decision ───────────────────────────────────────────────────────

def determine_tool_choice(user_message: str, history: list[dict]) -> str:
    """Return 'none', 'auto', or 'required' based on query classification."""
    if is_medical_query(user_message):
        return "none"
    if is_vague_query(user_message):
        return "none"
    if is_occasion_ready_query(user_message, history):
        return "required"
    if is_form_unknown_query(user_message, history):
        return "none"
    if is_vape_hardware_unknown_query(user_message, history):
        return "none"
    if is_price_feedback_query(user_message):
        return "none"
    if is_generic_rejection_query(user_message):
        return "none"
    # Negative strength constraint + form known → force tool call
    all_history_text = " ".join(msg.get("content", "") for msg in history)
    form_known = bool(_FORM_KEYWORDS.search(user_message)) or bool(_FORM_KEYWORDS.search(all_history_text))
    if _NEGATIVE_STRENGTH_CONSTRAINT.search(user_message) and form_known:
        return "required"
    return "auto"


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
    r"studying|work|gaming|movie|concert|yoga|gym|outdoor|workout|workouts|"
    r"recovery|recovering|training|post-workout)\b",
    re.IGNORECASE,
)
_BUDGET_SIGNALS = re.compile(
    r"\b(budget|cheap|affordable|under \$[\d]+|around \$[\d]+|less than \$[\d]+|"
    r"premium|top shelf|high.?end|luxury)\b",
    re.IGNORECASE,
)
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

    effect_matches = _EFFECT_INTENT_SIGNALS.findall(user_text)
    if effect_matches:
        profile["effect_intent"] = list({e.lower() for e in effect_matches})

    strain_matches = _STRAIN_PREF.findall(user_text)
    if strain_matches:
        profile["strain_preference"] = list({s.lower() for s in strain_matches})

    recommended_matches = _RECOMMENDED_PATTERN.findall(assistant_text)
    if recommended_matches:
        profile["already_recommended"] = list(dict.fromkeys(recommended_matches))

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
        "strain_preference": "Strain type (use strain_type parameter)",
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


# ── Fast-path search parameter extraction ────────────────────────────────────

def try_extract_search_params(
    user_message: str,
    history: list[dict],
    is_beginner: bool,
) -> dict | None:
    """
    Fast path: extract smart_search parameters at Python level without an LLM call.

    Returns a params dict if confident enough to skip Call 1, or None to fall
    back to the standard 2-call agent loop.

    Requires: category + (effects OR strain_type) to be present.
    """
    msg_lower = user_message.lower()

    # Guard: product detail / comparison requests must go through LLM
    _DETAIL_PATTERNS = re.compile(
        r"tell me more about|more (details?|info) (about|on)|what(\'s| is) .+ like"
        r"|more about|details? (on|about)|describe .+|explain .+",
        re.I,
    )
    if _DETAIL_PATTERNS.search(user_message):
        return None

    # Guard: flavor/taste-specific searches must go through LLM (fast path can't handle query param)
    _FLAVOR_PATTERNS = re.compile(
        r"\bflavor\b|\btaste\b|\bnotes?\b|\bdiesel\b|\bsour\b|\bcitrus\b|\bearthy\b"
        r"|\bfruity\b|\bsweet\b|\bspicy\b|\bherbal\b|\bpine\b|\bberr",
        re.I,
    )
    if _FLAVOR_PATTERNS.search(user_message):
        return None

    user_history = " ".join(
        m.get("content", "") for m in history if m.get("role") == "user"
    )
    all_user = (user_history + " " + msg_lower).lower()

    # ── Category ─────────────────────────────────────────────────────────────
    _CAT_PATTERNS = [
        ("Edibles",    re.compile(r"edibles?|gummies?|gummy|chocolate|candy|软糖|巧克力|可食用", re.I)),
        ("Pre-rolls",  re.compile(r"pre.?rolls?|pre-roll|joint(?!s?\s+venture)|prerolls?|预卷|预制卷", re.I)),
        ("Vaporizers", re.compile(r"vapes?|vaping|vaporizers?|\bcart\b|\bcarts\b|cartridges?|蒸发|电子烟", re.I)),
        ("Flower",     re.compile(r"flower|bud(?!get)|buds|smoke|大麻花", re.I)),
    ]
    category = None
    for text in [msg_lower, user_history.lower()]:
        for cat_name, pat in _CAT_PATTERNS:
            if pat.search(text):
                category = cat_name
                break
        if category:
            break

    if not category:
        return None

    # ── Strain type ───────────────────────────────────────────────────────────
    effects: list[str] = []
    strain_type: str | None = None

    if re.search(r"indica", all_user, re.I):
        strain_type = "Indica"
        effects = ["Relaxed", "Sleepy"]
    elif re.search(r"sativa", all_user, re.I):
        strain_type = "Sativa"
        effects = ["Energetic", "Uplifted"]
    elif re.search(r"hybrid", all_user, re.I):
        strain_type = "Hybrid"

    # ── Effect keywords ───────────────────────────────────────────────────────
    if re.search(r"\b(sleep|sleepy)\b|助眠|睡眠|入睡|睡觉|夜间", all_user, re.I):
        if "Relaxed" not in effects:
            effects.append("Relaxed")
        if "Sleepy" not in effects:
            effects.append("Sleepy")

    if re.search(r"\b(relax|relaxing|unwind|chill|calm)\b|放松|轻松|减压|平静", all_user, re.I):
        if "Relaxed" not in effects:
            effects.append("Relaxed")
        if "Calm" not in effects:
            effects.append("Calm")

    if re.search(r"\b(energy|energetic|focus|creative)\b|提神|精力|专注|创意", all_user, re.I):
        if "Energetic" not in effects:
            effects.append("Energetic")

    if not effects and not strain_type:
        return None

    # ── Build params ──────────────────────────────────────────────────────────
    params: dict = {"category": category}
    if strain_type:
        params["strain_type"] = strain_type
    if effects:
        params["effects"] = effects[:2]
    if is_beginner:
        params["is_beginner"] = True

    price_match = re.search(
        r"(?:最多|最高|不超过|under|below|less\s+than|budget|预算)[^\d]*(\d+)",
        user_message, re.I,
    )
    if price_match:
        params["max_price"] = float(price_match.group(1))
    else:
        dollar_match = re.search(
            r"\$\s*(\d+)|\b(\d+)\s*(?:美元|dollars?|bucks?)\b", user_message, re.I
        )
        if dollar_match:
            amount = float(dollar_match.group(1) or dollar_match.group(2))
            params["budget_target"] = amount

    return params
