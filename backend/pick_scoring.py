"""Pure scoring functions for AI Budtender Top Pick selection.

Implements the 7-tier scoring algorithm described in
`planning/two_pane_execution_plan.md` §2 Module 2.

Inputs:
  * `filtered`: list of compact-dict products (the search result already
    filtered to the user's current view).
  * `pick_meta`: pre-computed per-product metadata keyed by product id.
  * `profile`: optional dict of user-signal fields (effect_intent list,
    experience_level string, etc.) extracted by the LLM service.

Outputs:
  * list of compact-dict products with an attached `pick_reason` field.
"""

from __future__ import annotations

import re
from collections import Counter

# Mapping from lowercase user-facing intent verbs/adjectives
# to PascalCase DB effect labels stored in the products table.
EFFECT_INTENT_TO_DB: dict[str, str] = {
    "sleep": "Sleepy",
    "sleepy": "Sleepy",
    "relax": "Relaxed",
    "relaxed": "Relaxed",
    "unwind": "Relaxed",
    "chill": "Relaxed",
    "calm": "Calm",
    "energy": "Energetic",
    "energetic": "Energetic",
    "focus": "Focused",
    "creative": "Creative",
    "happy": "Happy",
    "uplifted": "Uplifted",
    "euphoric": "Happy",
    "sedated": "Sleepy",
    "stress": "Calm",
    "anxious": "Calm",
}

# Experience levels considered safe for a beginner gating tier.
_BEGINNER_SAFE_EXPERIENCE: set[str] = {"Beginner", "All Levels"}


def thc_numeric(thc_string: str) -> tuple[float, str] | None:
    """Parse a compact THC string into a numeric tuple.

    Examples:
        '22%'  -> (22.0, '%')
        '5mg'  -> (5.0, 'mg')
        ''     -> None
        '0%'   -> None
        'abc'  -> None
    """
    if not thc_string:
        return None
    m = re.match(r"^([\d.]+)(%|mg)?$", thc_string.strip())
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2) or ""
    return (val, unit) if val > 0 else None


def _dominant_thc_unit(
    filtered: list[dict],
    pick_meta: dict[int, dict],
) -> str | None:
    """Return the most common non-empty THC unit among filtered products.

    Returns None if no product in the filtered set has a numeric THC value.
    Ties resolve to the first encountered unit (Counter most_common is stable
    enough for our deterministic test data).
    """
    counts: Counter[str] = Counter()
    for prod in filtered:
        meta = pick_meta.get(prod.get("id"))
        if not meta:
            continue
        unit = meta.get("thc_unit") or ""
        if unit and meta.get("price_per_thc") is not None:
            counts[unit] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _mapped_intent_effects(profile: dict) -> list[tuple[str, str]]:
    """Map the profile's effect_intent list to (intent_verb, db_effect) pairs.

    Preserves order so the first matched intent can be reported as the
    `top_effect` in the Tier 4 reason template.
    """
    raw = profile.get("effect_intent") or []
    mapped: list[tuple[str, str]] = []
    for intent in raw:
        if not isinstance(intent, str):
            continue
        key = intent.strip().lower()
        db_effect = EFFECT_INTENT_TO_DB.get(key)
        if db_effect:
            mapped.append((key, db_effect))
    return mapped


def _tier_for_product(
    prod: dict,
    meta: dict,
    profile: dict,
    mapped_intents: list[tuple[str, str]],
    best_value_id: int | None,
    min_intent_matches: int = 2,
) -> tuple[int, str, str] | None:
    """Compute the highest-priority tier for one product.

    Returns a tuple of (tier_number, reason_key, reason_template_text) or None
    if the product qualifies for no tier 1-6 (in which case it's still eligible
    for Tier 7 fallback).

    ``min_intent_matches`` controls the Tier 4 (fit) threshold. The default
    of 2 preserves ``score_picks`` selection behavior — only products that
    clearly match the user's intent count as "fit" when the algorithm is
    choosing picks. ``assign_reasons_for_ids`` lowers this to 1 because
    the products were already chosen by the AI; the tier is just labeling.
    """
    is_on_sale = bool(meta.get("is_on_sale"))
    disc = int(meta.get("discount_pct") or 0)

    # Tier 1: sale_big
    if is_on_sale and disc >= 20:
        return (1, "sale_big", f"{disc}% off this week")

    # Tier 2: sale_small
    if is_on_sale and disc < 20 and disc > 0:
        return (2, "sale_small", f"{disc}% off")

    # Tier 3: best_value (single product, decided ahead of time)
    if best_value_id is not None and prod.get("id") == best_value_id:
        return (3, "best_value", "Best value in this filter")

    # Tier 4: fit (>= min_intent_matches intent effects match)
    if mapped_intents:
        effects_set = meta.get("effects_set") or set()
        matched = [
            (intent, db_effect)
            for intent, db_effect in mapped_intents
            if db_effect in effects_set
        ]
        if len(matched) >= min_intent_matches:
            top_effect = matched[0][0]
            return (4, "fit", f"Matches your {top_effect} vibe")

    # Tier 5: beginner safety
    if str(profile.get("experience_level", "")).lower() == "beginner":
        if meta.get("experience_level") in _BEGINNER_SAFE_EXPERIENCE:
            return (5, "beginner", "Gentle for first-timers")

    # Tier 6: premium
    if meta.get("is_premium"):
        return (6, "premium", "Top-shelf pick")

    return None


def _resolve_best_value_id(
    filtered: list[dict],
    pick_meta: dict[int, dict],
) -> int | None:
    """Identify the single best-value product id within the dominant THC cohort.

    Returns None when no product in the filtered set has a parseable
    `price_per_thc` (Tier 3 is then skipped).
    """
    unit = _dominant_thc_unit(filtered, pick_meta)
    if unit is None:
        return None
    best_id: int | None = None
    best_ratio: float | None = None
    for prod in filtered:
        pid = prod.get("id")
        meta = pick_meta.get(pid)
        if not meta:
            continue
        if meta.get("thc_unit") != unit:
            continue
        ratio = meta.get("price_per_thc")
        if ratio is None:
            continue
        if best_ratio is None or ratio < best_ratio:
            best_ratio = ratio
            best_id = pid
    return best_id


# Per-tier caps for the selection walk.  Tier 7 is the fallback bucket and
# is filled separately, not via this mapping.
_TIER_CAPS: dict[int, int | None] = {
    1: None,
    2: None,
    3: 1,
    4: None,
    5: None,
    6: 1,
}


def score_picks(
    filtered: list[dict],
    pick_meta: dict[int, dict],
    profile: dict,
    limit: int = 3,
) -> list[dict]:
    """Rank filtered products by the 7-tier rule system and return up to `limit`.

    Each returned dict is a shallow copy of an input product with a
    `pick_reason` string added.  When the filtered set is non-empty, the
    return list is also non-empty thanks to the Tier 7 fallback.
    """
    if not filtered:
        return []

    profile = profile or {}
    mapped_intents = _mapped_intent_effects(profile)
    best_value_id = _resolve_best_value_id(filtered, pick_meta)

    # Bucket products by their best-qualifying tier (1-6).  Products with no
    # tier 1-6 qualification are eligible only for Tier 7.
    buckets: dict[int, list[tuple[dict, str, str]]] = {t: [] for t in _TIER_CAPS}
    for prod in filtered:
        meta = pick_meta.get(prod.get("id"))
        if not meta:
            continue
        result = _tier_for_product(
            prod, meta, profile, mapped_intents, best_value_id,
        )
        if result is None:
            continue
        tier_num, reason_key, reason_text = result
        buckets[tier_num].append((prod, reason_key, reason_text))

    picks: list[dict] = []
    seen_ids: set[int] = set()

    for tier_num in (1, 2, 3, 4, 5, 6):
        cap = _TIER_CAPS[tier_num]
        taken_this_tier = 0
        for prod, _reason_key, reason_text in buckets[tier_num]:
            if len(picks) >= limit:
                break
            pid = prod.get("id")
            if pid in seen_ids:
                continue
            if cap is not None and taken_this_tier >= cap:
                break
            picks.append({**prod, "pick_reason": reason_text})
            seen_ids.add(pid)
            taken_this_tier += 1
        if len(picks) >= limit:
            break

    # Tier 7: fallback only if no tier 1-6 produced any picks.
    if not picks:
        for prod in filtered[:limit]:
            picks.append({**prod, "pick_reason": "Recommended for you"})

    return picks


def assign_reasons_for_ids(
    filtered: list[dict],
    pick_meta: dict[int, dict],
    profile: dict,
    ids: list[int],
) -> list[dict]:
    """Attach `pick_reason` to each product in `ids`, preserving order.

    Unlike ``score_picks``, this performs NO selection or tier capping —
    every requested id that exists in ``filtered`` is returned with a
    reason. Used by the Top Pick row when the AI's reply has already
    chosen the products (via ``spoken_product_ids``), so the algorithm's
    job is reduced to labeling rather than picking.

    Products absent from ``filtered`` are silently skipped. Products
    without ``pick_meta`` or with no qualifying tier fall back to a
    generic reason.
    """
    if not ids or not filtered:
        return []

    profile = profile or {}
    mapped_intents = _mapped_intent_effects(profile)

    by_id = {prod.get("id"): prod for prod in filtered if prod.get("id") is not None}
    # Best-value is computed over the spoken subset, not the full filtered
    # set. The AI already chose these products; "best value in this filter"
    # should mean "cheapest per THC among what was recommended."
    spoken_subset = [by_id[pid] for pid in ids if pid in by_id]
    best_value_id = _resolve_best_value_id(spoken_subset, pick_meta)

    out: list[dict] = []
    seen: set[int] = set()
    for pid in ids:
        if pid in seen:
            continue
        prod = by_id.get(pid)
        if prod is None:
            continue
        seen.add(pid)
        meta = pick_meta.get(pid)
        if not meta:
            out.append({**prod, "pick_reason": "Recommended for you"})
            continue
        # min_intent_matches=1: products were chosen by the AI; even a
        # single matching intent effect is enough to label the fit.
        tier_result = _tier_for_product(
            prod, meta, profile, mapped_intents, best_value_id,
            min_intent_matches=1,
        )
        if tier_result is None:
            out.append({**prod, "pick_reason": "Recommended for you"})
        else:
            _, _, reason_text = tier_result
            out.append({**prod, "pick_reason": reason_text})
    return out
