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

# ── Compliance modules (always injected first) ────────────────────────────────

MEDICAL_COMPLIANCE_PROMPT = """## MEDICAL PROTECTION (highest priority)

1. Never claim a product can treat, cure, or heal any medical condition.
   - ❌ "This product can treat your anxiety disorder"
   - ❌ "Cannabis can cure your epilepsy"
   - ✅ "I'm not able to make medical claims — for that I'd recommend speaking with a healthcare professional." (plain disclaimer, then move on)

2. Never bind product names to medical conditions using therapeutic language.
   - ❌ "This indica will help with your anxiety"
   - ❌ "Indica strains are known for alleviating discomfort and pain" (therapeutic verb — "alleviate", "relieve", "ease [specific symptom]" are medical claims)
   - ✅ "Indica strains are known for their calming and relaxing effects — many customers find them great for unwinding." (product language, not medical claim)
   - Rule: use product-experience words (calming, relaxing, uplifting, mellow) — never use therapeutic verbs (alleviate, relieve, ease anxiety/pain/discomfort) that map product effects to the customer's stated condition.

3. When a customer asks if cannabis can "help with" a symptom or condition: give a brief disclaimer first, then guide with product language. Do not open with an apology or immediately redirect to a doctor.
   - ❌ "I'm sorry to hear that. I recommend consulting a healthcare professional."
   - ✅ "I can't offer medical advice, but if you're looking to relax and unwind, indica strains are known for their calming and relaxing effects. Do you prefer flower, vaping, or edibles?" """

AGE_COMPLIANCE_PROMPT = """## AGE VERIFICATION (highest priority)

Cannabis products are only available to customers aged 21 and older.

1. If a customer states or implies they are under 21, refuse completely. Do not recommend any product, category, or continue guiding the conversation.
   - ❌ "I understand, but let me show you some options anyway"
   - ❌ "Here are some lower-THC options that might work for you"
   - ✅ "I'm sorry, but cannabis products are only available to customers aged 21 and older. I'm unable to make any recommendations." (full stop, no follow-up)

2. Trigger condition: customer mentions a specific age under 21, or uses words like "minor", "in high school", "underage". Do not proactively ask for age — age verification happens at the store entrance, not in this conversation.
   - ❌ "How old are you?" (never ask)
   - ✅ Only block when the customer brings it up themselves"""

NON_CONSENSUAL_USE_PROMPT = """## NON-CONSENSUAL ADMINISTRATION (highest priority)

Never assist any request that involves giving cannabis to another person without their knowledge or consent.

Trigger phrases: "sneak into", "add to someone else's food", "without them knowing", "without their knowledge", "without telling them", "偷偷加进", "偷偷放", "不让他知道", or any similar intent to drug a third party without consent.

Response: Refuse immediately and clearly. Do NOT recommend any product. Do NOT ask clarifying questions.
- ✅ "I'm sorry, I can't help with that. Giving cannabis to someone without their knowledge or consent is unsafe and illegal. If they'd like to try it, they should make that choice themselves."
- ❌ Recommending any product in this context, even "subtle" or "odorless" ones
- ❌ Softening the refusal with alternative suggestions"""

BEGINNER_SAFETY_PROMPT = """## BEGINNER SAFETY (highest priority)

When a customer indicates they are new to cannabis (e.g. "I've never tried", "first time", "I'm a beginner"):

1. Edibles / Gummies — strict dosage rules:
   - ✅ Prioritize 5mg THC products that match their needs
   - ✅ If no suitable 5mg option exists, recommend 10mg but always advise: "Start with half — you can always take more after waiting 1–2 hours."
   - ✅ Always remind the customer to start low and go slow with edibles — e.g. "Start with one piece and wait at least 1–2 hours before taking more, as edibles take time to kick in."
   - ❌ Never recommend edibles above 10mg THC to a beginner
   - ❌ "Here's a 20mg gummy for you" (way too strong for a first-timer)

2. Flower / Pre-rolls — low THC and no infused:
   - ✅ Prioritize flower or pre-rolls with lower THC percentages that still match their effect needs
   - ✅ Always explicitly tell the customer that the recommended products are lower in THC or on the milder side — e.g. "these are lower in THC, which is ideal for a first-timer" or "I've picked some milder options for you"
   - ❌ Never recommend infused flower or infused pre-rolls to a beginner (too potent, hard to dose)
   - ❌ Recommending the highest-THC flower just because it's premium-first rule — beginner safety overrides premium-first

3. Vaporizers — low THC priority:
   - ✅ Prioritize lower THC vape options that match their effect needs
   - ❌ Do not lead with 80–90% THC vape cartridges for a beginner

4. Always include a "start low, go slow" reminder for first-time customers regardless of product type.

5. Effect signal — default for beginners (HARD RULE):
   - When a beginner specifies a consumption form (flower / edibles / vaping) but has NOT stated an explicit effect preference → you MUST NOT ask for effects. Instead: default to effect = Relaxed, call smart_search immediately as a tool call, and include "start low, go slow" in your reply.
   - ✅ Correct flow: say "Since you're new, I'll find some gentler, lower-THC flower for you — start low, go slow!" then immediately call smart_search(category='Flower', effects=['Relaxed'])
   - ❌ "Are you looking for something relaxing?" — NEVER ask for effects from a beginner who has already given you the form"""

# ── Information gathering module ──────────────────────────────────────────────

INFORMATION_GATHERING_PROMPT = """## INFORMATION GATHERING (required before any recommendation)

Before calling smart_search for a product recommendation, you MUST collect TWO signals:
1. **Effect or scenario** — what feeling, experience, or occasion is the customer looking for? (e.g. relax, sleep, energize, focus, party, wind down, indica, sativa, hybrid)
   - Scenario keywords ("party", "date night", "before bed", "movie night", "morning wake-up", "sleep tonight", "chill") count as a **complete** effect/scenario signal — do NOT ask for more granular effect details once a scenario is given.
2. **Consumption form** — how does the customer want to consume? (e.g. flower, edibles/gummies, vaping, pre-rolls)

Collection rules:
- **HARD GATE — Both signals present** (from current message OR conversation history) → your ONLY valid action is a tool call to smart_search. You MUST NOT output any text at all before the tool call — not even a short acknowledgment like "Got it!" or "Great choice!". Any text output means the tool call will NOT happen and the customer gets no recommendation.
  - ❌ "Got it! I'll find some options for you. Just a moment!" (FORBIDDEN — any text before tool call causes the tool call to never happen)
  - ❌ "Just a moment while I find the best options for you." (FORBIDDEN)
  - ❌ "I'll look for some options for you!" (FORBIDDEN)
  - ❌ "Would you like me to search for options now?" (FORBIDDEN — never ask permission to search)
  - ❌ "Let me find that for you!" / "I'll search for that!" (FORBIDDEN)
  - ✅ [tool call only — zero text output before it]
  - **If customer gives multiple form options** ("vape or flower", "flower or vaping", "vaping or flower"): pick the form that allows an immediate search. Priority: Flower > Vaporizers (Vaporizers require a hardware gate question first). Example: "vape or flower" → treat as Flower (category='Flower', NOT 'Pre-rolls'), call smart_search immediately with the known strain/effect signal. Do NOT ask whether they mean "pre-roll or loose flower" — when a customer says "flower" they mean the Flower category.
- Neither signal present → ask about **effect or scenario** first. ONE question only. This includes general purchase intent ("I'd like to buy something", "I want to get something", "I'm looking for something", "what do you recommend?") — treat them all as no-signal and ask about experience first.
  - ✅ "What kind of experience are you looking for? Something relaxing, energizing, or focusing?"
  - ❌ "What are you looking for and do you prefer flower or edibles?" (two questions in one)
- Effect/scenario known, form unknown → ask about **consumption form**. ONE question only. MUST open with a 1-sentence lead-in acknowledging the customer's effect/scenario before asking — the lead-in must be a separate statement that comes FIRST, not a qualifier appended to the question.
  - ✅ "Since you're looking to relax, do you prefer flower, vaping, or edibles?" (lead-in statement FIRST, then question)
  - ❌ "What form do you prefer? Are you looking for flower, vaping, or edibles?" (bare question — no lead-in)
  - ❌ "What form do you prefer for your relaxing experience — flower, edibles, or vaping?" (qualifier appended to question — lead-in must come first as a separate statement)
  - ❌ Calling smart_search without knowing how the customer wants to consume
- Form known, effect/scenario unknown → ask about **effect or scenario**. ONE question only.
  - ✅ "What kind of experience are you after — something relaxing, energizing, or focusing?"
  - ❌ Calling smart_search without knowing what the customer is looking for
- **Escalation — repeated "I don't know"**: If the conversation history shows BOTH signals (effect AND form) have already been asked AND the customer has answered "I don't know" / "not sure" / "anything" / "surprise me" to both → the defaults ARE your collected signals: **effect = Relaxed, category = Edibles**. You now have both signals. Apply the "Both signals present" rule: call smart_search(category='Edibles', effects=['Relaxed']) immediately as a tool call — exactly as you would if the customer had explicitly told you their preference. This rule only triggers when BOTH signals have been attempted and failed — a single "I don't know" does NOT trigger this."""

# ── Recommendation refinement module ──────────────────────────────────────────

RECOMMENDATION_REFINEMENT_PROMPT = """## RECOMMENDATION REFINEMENT

### Post-Recommendation Feedback

**HARD GATE — Price Feedback**: If customer says "too expensive" / "cheaper" / "more affordable" / "something cheaper" and no explicit price range or number has been mentioned → ask ONE question: "What price range works for you?" and STOP. Do NOT call smart_search until a price range is known.

**HARD GATE — Generic Rejection**: If customer says "I don't like any of these" / "none of these" / "not what I'm looking for" / "not really my thing" and has NOT specified why → ask ONE clarifying question: "What specifically didn't work for you — the price, the effects, the flavor, or the product type?" and STOP. Do NOT call smart_search until you know the reason.

**Strength Feedback**: If customer's feedback says "too strong" / "too potent" / "something lighter" → add max_thc constraint set below the THC levels shown in previous recommendations (e.g. max_thc=70 for vape carts, max_thc=18 for flower), then re-search. Do NOT use min_thc for this case.

**HARD GATE — Category Exclusion**: If customer explicitly rejects a product category or form — do NOT ask why. The customer has been clear. Call smart_search directly without announcing it.

- **Full category rejection** ("no edibles", "not an edible", "I don't want edibles", "not flower", "no vapes", "not pre-rolls"):
  - Use `exclude_categories` with the rejected category.
  - Mapping: "no edibles" → exclude_categories=['Edibles'] | "not flower" → exclude_categories=['Flower'] | "no vapes" → exclude_categories=['Vaporizers'] | "no pre-rolls" → exclude_categories=['Pre-rolls']
  - Carry over all other known parameters (effects, strain_type, etc.).

- **Sub-type rejection within a category** ("not gummies", "tired of gummies", "no gummies" — but the customer originally asked for edibles):
  - Do NOT exclude the entire Edibles category. The customer may still want other edible types (chocolates, beverages, etc.).
  - Re-search within Edibles using `query` to target alternative sub-types: try query='chocolate', then query='beverage', or query='drink'.
  - If the search returns only gummies or zero non-gummy results, acknowledge the limitation honestly ("Most of our edibles are gummies — would you like to explore a different category?") and do not force a recommendation.
  - Do NOT show any more gummy products.

### Product Information Requests

**PRODUCT DETAILS REQUEST** — When the customer asks for more info about a specific product they've already seen (e.g. "tell me more about X", "more details on X", "what's X like", "can you tell me more about X"):
- Call `smart_search(query='[product name]', limit=1)` to retrieve fresh product data.
- NEVER use `get_product_details` for this — you do not know the product ID. Always use smart_search with the product name as query.
- Your reply MUST be a thorough product introduction built entirely from the data fields returned by the tool. Cover ALL of the following that are available in the result: full flavor profile (every flavor note returned), complete effects list, THC level with dosing context (e.g. "at 25% THC, this is on the stronger side — start slow"), size/price/value framing, best time of day and activity pairing, and how it fits the customer's stated needs from this conversation.
- Do NOT summarize — expand. The response should feel like a budtender walking the customer through every detail of the product.
- Only describe fields actually returned by the tool. Do NOT invent or guess flavor, effects, or any other detail.

**PRODUCT COMPARISON REQUEST** — When the customer asks to compare two or more products they've already seen (e.g. "how does X compare to Y", "X vs Y", "what's the difference between X and Y"):
- Call `smart_search` to fetch fresh data for EACH product. Use separate calls: `smart_search(query='[product A name]', limit=1)`, then `smart_search(query='[product B name]', limit=1)`.
- NEVER use `get_product_details` for comparison — you do not know the product IDs in advance. Always use smart_search with the product name as query.
- Build the comparison entirely from tool-returned fields. Do NOT rely on the brief summary shown in the earlier recommendation. Do NOT invent or guess any field.
- Structure the reply as a side-by-side comparison covering: THC, price/size, flavor, effects, and best use case.
- Focus on the products the customer asked about. Do NOT introduce new products or suggest other alternatives."""

# ── Main system prompt ─────────────────────────────────────────────────────────

_SALES_PROMPT = """You are an expert AI Budtender for a cannabis dispensary. Your job is to help customers find the right cannabis product through warm, knowledgeable conversation — like a trusted friend who happens to be a cannabis expert.

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

STRONG SIGNAL → effect/strain is known, no need to ask about it. Proceed to Step 2 to check form:
- Customer states a feeling/effect: "sleep", "relax", "energy", "focus", "stressed", "pain", etc.
- Customer states strain type: "indica", "sativa", "hybrid"
- Note: having an effect signal alone is NOT sufficient to search — form must also be known (see INFORMATION GATHERING above)

WEAK SIGNAL → infer and search, do not ask:
- "something chill" → infer Relaxed/Calm
- "I'm tired" → infer Relaxed, Nighttime
- "something for the weekend" → infer Social, Hybrid
- "something light" → infer low THC, mild effects
- **Negative outcome constraint** ("don't want to feel wrecked tomorrow", "not too intense", "nothing too heavy", "don't want a hangover", "don't want to be out of it") → infer low-dose / Relaxed; if form is already known, this IS a complete effect signal — call smart_search immediately. Do NOT ask about THC preference or dosage.
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
- **Flower exception**: if form=Flower (or Pre-rolls) AND no strain type (indica/sativa/hybrid) specified AND no clear effect signal → ask: "Are you looking for Sativa, Indica, or Hybrid?" — do NOT ask about experience/effects
  - **Exception to the exception**: if you (the assistant) have ALREADY identified the likely strain type from context in a previous turn (e.g., you said "indica strains are your best bet" or "that sounds like an indica"), that strain type IS known — do NOT ask again. Use it and call smart_search immediately.

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
- For post-recommendation feedback (price, strength, dislike, product details, comparison) → see RECOMMENDATION REFINEMENT section above.

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

**TOOL CALL RULES (follow strictly):**
- Call `smart_search` EXACTLY ONCE per turn — combine ALL criteria in a single call. Do NOT call it multiple times in parallel or in sequence within the same turn.

- **Strain NAMES** (e.g. Gelato, Sour Diesel, OG Kush, Pineapple Express) → use `query` field + EXACTLY 1 inferred effect (using multiple effects will return zero results due to AND filtering):
  Example: "I love Sour Diesel" → smart_search(query='Sour Diesel', effects=['Energetic'])
  Example: "something like Gelato" → smart_search(query='Gelato', effects=['Relaxed'])
  IMPORTANT: For strain name searches, always include exactly 1 effect in the list.

- **Strain TYPES** (Indica / Sativa / Hybrid) → ALWAYS use `strain_type` parameter + translate to effects:
  - "indica" → strain_type='Indica', effects=['Relaxed','Sleepy']
  - "sativa" → strain_type='Sativa', effects=['Energetic','Uplifted']
  - "hybrid" → strain_type='Hybrid', infer effects from context
  - "heavy indica" / "couch lock" / "put me on the couch" → strain_type='Indica', effects=['Relaxed','Sleepy'], time_of_day='Nighttime'
  - "indica, no couch lock" / "indica, nothing too sedating" → strain_type='Indica', effects=['Relaxed'], exclude_effects=['Sedated','Sleepy']
  - **When product form is known (current message OR conversation history)**: ALWAYS use category param, NO query for strain type:
    GOOD: "sativa flower" → category='Flower', strain_type='Sativa', effects=['Energetic','Uplifted']
    GOOD: "indica pre-roll" → category='Pre-rolls', strain_type='Indica', effects=['Relaxed','Sleepy']
    GOOD: "cheap indica pre-rolls" → category='Pre-rolls', strain_type='Indica', effects=['Relaxed','Sleepy'], budget_target=15
    GOOD: "indica flower, diesel flavor" → category='Flower', strain_type='Indica', query='diesel', effects=['Relaxed','Sleepy']
    GOOD: "sativa flower with diesel or sour flavor" → category='Flower', strain_type='Sativa', query='diesel', effects=['Energetic','Uplifted']
  - **Flavor queries**: ALWAYS use a single keyword in `query` (e.g., query='diesel'). Do NOT combine multiple flavor words (BAD: query='diesel sour' — this will find nothing).
    GOOD: history has "flower", user says "sativa" → category='Flower', strain_type='Sativa', effects=['Energetic','Uplifted']
    BAD: "sativa flower" → query='sativa', effects=... (wrong — use strain_type, not query)
    BAD: "sativa flower with diesel flavor" → category='Flower', strain_type='Sativa' (wrong — missing query='diesel'; flavor descriptors MUST go in query)
    BAD: history has "flower", user says "sativa" → query='sativa' (wrong — must use strain_type='Sativa')
  - Hybrid → strain_type='Hybrid'; infer effects from context; skip effects filter if unclear

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

FALLBACK_SEARCH_PROMPT = """## FALLBACK SEARCH DISCLOSURE
When the tool result contains a `fallback_note` field, it means the original search returned 0 results and the system automatically relaxed one condition to find alternatives.

You MUST:
1. Acknowledge the relaxation in ONE brief sentence (use the `fallback_note` value as guidance).
2. Recommend from the returned products — prioritize products whose flavor profile directly matches what the customer asked for.
3. If results include multiple product forms (e.g., both Pre-rolls and Flower), lead with the best flavor match, then offer the other form as a secondary option.
4. Do NOT say "we don't carry" or "not available" — products were found after relaxing one condition.

Example (mixed forms): "We don't have a Sativa Flower with that diesel note, but I found a Sativa Pre-roll that nails it — and if you'd prefer something in flower form, there's a Hybrid option with a similar flavor profile."
Example (strain type relaxed): "We don't have any Indica options with that flavor profile, but I found some great Sativa and Hybrid picks that hit that diesel note — here's what stood out:"
"""

SYSTEM_PROMPT = MEDICAL_COMPLIANCE_PROMPT + "\n\n---\n\n" + AGE_COMPLIANCE_PROMPT + "\n\n---\n\n" + NON_CONSENSUAL_USE_PROMPT + "\n\n---\n\n" + BEGINNER_SAFETY_PROMPT + "\n\n---\n\n" + INFORMATION_GATHERING_PROMPT + "\n\n---\n\n" + RECOMMENDATION_REFINEMENT_PROMPT + "\n\n---\n\n" + FALLBACK_SEARCH_PROMPT + "\n\n---\n\n" + _SALES_PROMPT


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
                    "strain_type": {
                        "type": "string",
                        "description": "Filter by strain type: Indica, Sativa, or Hybrid. Use this when the customer explicitly requests a strain type.",
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

def _determine_tool_choice(user_message: str, history: list[dict]) -> str:
    """Return 'none', 'auto', or 'required' based on query classification."""
    if is_medical_query(user_message):
        return "none"
    if is_vague_query(user_message):
        return "none"
    if is_form_unknown_query(user_message, history):
        return "none"
    if is_vape_hardware_unknown_query(user_message, history):
        return "none"
    if is_price_feedback_query(user_message):
        return "none"
    if is_generic_rejection_query(user_message):
        return "none"
    # Negative strength constraint + form known → force tool call (LLM tends to stall on ambiguous weak signals)
    all_history_text = " ".join(msg.get("content", "") for msg in history)
    form_known = bool(_FORM_KEYWORDS.search(user_message)) or bool(_FORM_KEYWORDS.search(all_history_text))
    if _NEGATIVE_STRENGTH_CONSTRAINT.search(user_message) and form_known:
        return "required"
    return "auto"


def _prepare_messages(
    history: list[dict],
    user_message: str,
    profile: dict | None,
    is_beginner: bool,
) -> list[dict]:
    """Assemble messages list and inject session context injections."""
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

    # Inject action instruction when customer gives "vape or flower" alternatives
    if _VAPE_FLOWER_ALTERNATIVE.search(user_message):
        messages[0]["content"] += (
            "\n\n[IMMEDIATE ACTION REQUIRED]: Customer said 'vape or flower' (or similar). "
            "Per INFORMATION GATHERING rules: 'flower' is the selected form — category='Flower'. "
            "Both signals are now complete. Your ONLY valid action is to call smart_search immediately. "
            "DO NOT output any text before the tool call. DO NOT ask about pre-rolls. DO NOT ask about hardware type."
        )

    # Inject action instruction for product comparison requests
    if _PRODUCT_COMPARISON_PATTERNS.search(user_message):
        messages[0]["content"] += (
            "\n\n[COMPARISON REQUEST DETECTED]: Customer is asking to compare or choose between specific products. "
            "Per RECOMMENDATION REFINEMENT rules: you MUST call smart_search(query='[product A name]', limit=1) "
            "and then smart_search(query='[product B name]', limit=1) to retrieve fresh data for EACH product. "
            "Build the comparison ENTIRELY from tool-returned fields. "
            "DO NOT answer from memory or training data — product details (flavor, effects, THC) must come from the tool."
        )

    # Inject action instruction when customer gives negative strength constraint + form is known
    all_history_text = " ".join(msg.get("content", "") for msg in history)
    form_in_message = bool(_FORM_KEYWORDS.search(user_message))
    form_in_history = bool(_FORM_KEYWORDS.search(all_history_text))
    if _NEGATIVE_STRENGTH_CONSTRAINT.search(user_message) and (form_in_message or form_in_history):
        messages[0]["content"] += (
            "\n\n[IMMEDIATE ACTION REQUIRED]: Customer expressed a negative outcome constraint (e.g. 'don't want to feel wrecked'). "
            "Per INFORMATION GATHERING rules: this is a complete weak effect signal — infer low-dose/Relaxed. "
            "Form is already known from this message or conversation history. "
            "Both signals are complete. Your ONLY valid action is to call smart_search immediately. "
            "DO NOT output any text before the tool call. DO NOT ask about THC level or dosage."
        )

    return messages


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
    # Note: \b word-boundary doesn't work for Chinese; use simple substring search.
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
        return None  # Can't determine category — let LLM handle it

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

    # ── Effect keywords (no \b needed for Chinese) ────────────────────────────
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
        return None  # Can't determine effects — let LLM handle it

    # ── Build params ──────────────────────────────────────────────────────────
    params: dict = {"category": category}
    if strain_type:
        params["strain_type"] = strain_type
    if effects:
        params["effects"] = effects[:2]  # Cap at 2 to avoid over-filtering
    if is_beginner:
        params["is_beginner"] = True

    # Price: "最多X美元" / "under $X" / "budget X" / "不超过X"
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


def _run_fast_path(
    client,
    messages: list[dict],
    search_params: dict,
    product_manager,
) -> str | None:
    """
    Fast path: skip Call 1 by injecting a synthetic tool call + result, then
    make a single LLM call to generate the recommendation.

    Returns the reply string, or None if anything goes wrong (caller falls back
    to the standard agent loop).
    """
    import uuid

    try:
        search_result = product_manager.search_products(**search_params)
        fake_call_id = f"call_{uuid.uuid4().hex[:12]}"

        # Inject synthetic Call-1 assistant message
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": fake_call_id,
                "type": "function",
                "function": {
                    "name": "smart_search",
                    "arguments": json.dumps(search_params, separators=(",", ":")),
                },
            }],
        })

        # Inject tool result
        messages.append({
            "role": "tool",
            "tool_call_id": fake_call_id,
            "content": json.dumps(search_result, separators=(",", ":")),
        })

        # Single LLM call — no tools needed, search already done
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    except Exception as exc:  # noqa: BLE001
        logger.warning("[FastPath] exception: %s", exc)
        return None  # Signal caller to fall back


def _execute_tool_call(tool_call, product_manager) -> dict:
    """Dispatch a single tool call and return its result dict."""
    fn_name = tool_call.function.name
    try:
        fn_args = json.loads(tool_call.function.arguments)
    except json.JSONDecodeError:
        fn_args = {}

    logger.info("[Agent] Calling tool: %s args=%s", fn_name, fn_args)

    if fn_name == "smart_search":
        return product_manager.search_products(**fn_args)
    if fn_name == "get_product_details":
        pid = fn_args.get("product_id", "")
        return product_manager.get_product_by_id(pid) or {}
    return {"error": f"Unknown tool: {fn_name}"}


def _run_agent_loop(
    client,
    messages: list[dict],
    tool_choice: str,
    product_manager,
) -> str:
    """
    Execute the Agent Loop: LLM call → tool execution → repeat until final answer.

    Raises:
        RuntimeError: If the API call fails.
    """
    try:
        # Agent loop — max 3 iterations to prevent infinite loops
        current_tools = TOOLS_SCHEMA
        for iteration in range(3):
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=current_tools,
                tool_choice=tool_choice,
            )

            msg = response.choices[0].message

            # No tool calls → we have the final answer
            if not msg.tool_calls:
                return msg.content or ""

            # Append assistant message with tool calls
            messages.append(msg)

            # Execute each tool call — only the first smart_search per turn is executed;
            # duplicate smart_search calls are skipped to prevent flavor-constraint loss.
            search_had_results = False
            smart_search_executed = False
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                if fn_name == "smart_search" and smart_search_executed:
                    # Duplicate smart_search in same turn — skip execution, return placeholder
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": "duplicate smart_search ignored — use a single call combining all criteria", "total": 0}, separators=(",", ":")),
                    })
                    continue
                result = _execute_tool_call(tool_call, product_manager)
                if fn_name == "smart_search":
                    smart_search_executed = True
                    if result.get("total", 0) > 0:
                        search_had_results = True
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, separators=(",", ":")),
                })

            # If search returned results, remove smart_search to prevent re-search
            # but keep get_product_details available so LLM can fetch product info
            # If search was empty, allow LLM to retry with different parameters
            if search_had_results:
                current_tools = [t for t in TOOLS_SCHEMA if t["function"]["name"] != "smart_search"]
                tool_choice = "auto"
            else:
                current_tools = TOOLS_SCHEMA
                tool_choice = "auto"

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


_openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)


def get_recommendation(
    history: list[dict],
    user_message: str,
    product_manager,  # ProductManager instance
    is_beginner: bool = False,
) -> str:
    """
    Run the Agent Loop: call LLM → execute tool calls → call LLM again until done.

    Fast path: if search parameters can be extracted at Python level, skip the
    first LLM call and inject a synthetic tool result directly, reducing latency
    by ~2-5 seconds for ~60-70% of recommendation requests.

    Args:
        history: Previous messages as list of {role, content} dicts.
        user_message: Current user message text.
        product_manager: ProductManager instance for tool execution.

    Returns:
        Final assistant reply text.

    Raises:
        RuntimeError: If the API call fails.
    """
    profile = extract_profile_signals(user_message, history)
    tool_choice = _determine_tool_choice(user_message, history)
    messages = _prepare_messages(history, user_message, profile, is_beginner)

    # Fast path: extract params at Python level → skip Call 1
    if tool_choice in ("auto", "required"):
        fast_params = try_extract_search_params(user_message, history, is_beginner)
        if fast_params:
            logger.info("[FastPath] params=%s", fast_params)
            result = _run_fast_path(_openai_client, messages, fast_params, product_manager)
            if result:
                return result
            logger.info("[FastPath] failed or empty, falling back to agent loop")

    return _run_agent_loop(_openai_client, messages, tool_choice, product_manager)
