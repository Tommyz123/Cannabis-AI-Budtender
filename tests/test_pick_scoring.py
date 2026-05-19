"""Tests for backend/pick_scoring.py.

Covers the 7-tier scoring algorithm, per-tier caps, the Tier 7 fallback,
the THC numeric extractor, intent-to-DB effect mapping, beginner gating,
and cohort-aware best-value selection.
"""

from backend.pick_scoring import (
    EFFECT_INTENT_TO_DB,
    score_picks,
    thc_numeric,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_product(pid: int, **overrides) -> dict:
    """Build a minimal compact-dict product. Override any field via kwargs."""
    base = {
        "id": pid,
        "s": f"Product {pid}",
        "c": "BrandA",
        "cat": "Flower",
        "sub": "Premium Flower",
        "t": "Hybrid",
        "thc": "22%",
        "p": 40.0,
        "pr": "Mid",
        "f": "Relaxed,Happy",
        "sc": "Relaxation",
        "tod": "Anytime",
        "xl": "All Levels",
        "cm": "Smoke",
        "on": "5-10 min",
        "dur": "2-3 hrs",
    }
    base.update(overrides)
    return base


def _make_meta(
    is_on_sale: bool = False,
    discount_pct: int = 0,
    is_premium: bool = False,
    price_per_thc: float | None = 1.0,
    thc_unit: str = "%",
    effects_set: set | None = None,
    experience_level: str = "All Levels",
) -> dict:
    """Build a pick_meta entry. Defaults represent a plain unremarkable product."""
    return {
        "is_on_sale": is_on_sale,
        "discount_pct": discount_pct,
        "is_premium": is_premium,
        "price_per_thc": price_per_thc,
        "thc_unit": thc_unit,
        "effects_set": effects_set if effects_set is not None else {"Relaxed", "Happy"},
        "experience_level": experience_level,
    }


# ── thc_numeric extractor ─────────────────────────────────────────────────────

def test_thc_numeric_percent():
    """'22%' parses to (22.0, '%')."""
    assert thc_numeric("22%") == (22.0, "%")


def test_thc_numeric_milligrams():
    """'5mg' parses to (5.0, 'mg')."""
    assert thc_numeric("5mg") == (5.0, "mg")


def test_thc_numeric_empty():
    """Empty string returns None."""
    assert thc_numeric("") is None


def test_thc_numeric_zero():
    """'0%' returns None (zero is treated as missing)."""
    assert thc_numeric("0%") is None


def test_thc_numeric_malformed():
    """'abc' returns None (no leading number)."""
    assert thc_numeric("abc") is None


# ── Per-tier triggers (each tier in isolation) ─────────────────────────────────

def test_tier1_sale_big():
    """Tier 1 fires when product is on sale with discount >= 20 percent."""
    products = [_make_product(1)]
    meta = {1: _make_meta(is_on_sale=True, discount_pct=25)}
    picks = score_picks(products, meta, profile={}, limit=3)
    assert len(picks) == 1
    assert picks[0]["id"] == 1
    assert picks[0]["pick_reason"] == "25% off this week"


def test_tier2_sale_small():
    """Tier 2 fires when product is on sale with discount < 20 percent."""
    products = [_make_product(2)]
    meta = {2: _make_meta(is_on_sale=True, discount_pct=10)}
    picks = score_picks(products, meta, profile={}, limit=3)
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "10% off"


def test_tier3_best_value_in_dominant_unit():
    """Tier 3 picks the lowest price_per_thc within the dominant unit cohort."""
    products = [_make_product(1), _make_product(2), _make_product(3)]
    meta = {
        1: _make_meta(price_per_thc=2.0, thc_unit="%"),
        2: _make_meta(price_per_thc=1.0, thc_unit="%"),  # best value
        3: _make_meta(price_per_thc=3.0, thc_unit="%"),
    }
    picks = score_picks(products, meta, profile={}, limit=3)
    # All three products have no sale, no fit, no premium, no beginner -> tier 3 + nothing else.
    # Best value should win and be the only tier-3 pick, the rest fall through to Tier 7 only
    # if no tier 1-6 produced any picks. Since tier 3 produced one, no fallback fires;
    # other products contribute zero tier-1-6 qualifications, so picks length is 1.
    assert len(picks) == 1
    assert picks[0]["id"] == 2
    assert picks[0]["pick_reason"] == "Best value in this filter"


def test_tier4_fit_requires_two_intent_matches():
    """Tier 4 fires when >= 2 mapped intent effects intersect the product's effects_set."""
    products = [_make_product(1)]
    # Disable Tier 3 (no THC cohort) so the Tier 4 trigger isn't preempted.
    meta = {
        1: _make_meta(
            effects_set={"Sleepy", "Relaxed", "Calm"},
            price_per_thc=None,
            thc_unit="",
        ),
    }
    profile = {"effect_intent": ["sleep", "relax"]}  # both map -> 2 matches
    picks = score_picks(products, meta, profile=profile, limit=3)
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "Matches your sleep vibe"


def test_tier5_beginner_safety():
    """Tier 5 fires for beginner profile + safe experience_level."""
    products = [_make_product(1)]
    # Disable Tier 3 so it doesn't preempt the beginner trigger.
    meta = {
        1: _make_meta(
            experience_level="Beginner",
            price_per_thc=None,
            thc_unit="",
        ),
    }
    profile = {"experience_level": "beginner"}
    picks = score_picks(products, meta, profile=profile, limit=3)
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "Gentle for first-timers"


def test_tier6_premium():
    """Tier 6 fires for is_premium products lacking higher-tier qualifications."""
    products = [_make_product(1)]
    # Disable Tier 3 so it doesn't preempt the premium trigger.
    meta = {
        1: _make_meta(
            is_premium=True,
            price_per_thc=None,
            thc_unit="",
        ),
    }
    picks = score_picks(products, meta, profile={}, limit=3)
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "Top-shelf pick"


def test_tier7_fallback_when_nothing_else_matches():
    """Tier 7 fires when no tier 1-6 qualifies any product, taking the first N from filtered."""
    # Product with no sale, no fit intents, not premium, not beginner-safe-context,
    # AND no other product to be best-value against (so dominant unit is empty).
    products = [_make_product(1)]
    meta = {
        1: _make_meta(
            price_per_thc=None,  # no THC -> no best-value cohort
            thc_unit="",
        ),
    }
    picks = score_picks(products, meta, profile={}, limit=3)
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "Recommended for you"


# ── Caps ──────────────────────────────────────────────────────────────────────

def test_best_value_cap_only_one():
    """Tier 3 must not contribute more than one pick even if multiple products tie."""
    # Two products with identical price_per_thc in the same cohort.
    # Only one (the first-found best) should be Tier 3; the other lacks any tier 1-6
    # qualification, so without a fallback firing (since picks exist), it's omitted.
    products = [_make_product(1), _make_product(2)]
    meta = {
        1: _make_meta(price_per_thc=1.0, thc_unit="%"),
        2: _make_meta(price_per_thc=2.0, thc_unit="%"),
    }
    picks = score_picks(products, meta, profile={}, limit=3)
    tier3_picks = [p for p in picks if p["pick_reason"] == "Best value in this filter"]
    assert len(tier3_picks) == 1


def test_premium_cap_only_one():
    """Tier 6 must not contribute more than one pick even when many products are premium."""
    products = [_make_product(1), _make_product(2), _make_product(3)]
    meta = {
        # Disable Tier 3 entirely by giving none a numeric THC.
        1: _make_meta(is_premium=True, price_per_thc=None, thc_unit=""),
        2: _make_meta(is_premium=True, price_per_thc=None, thc_unit=""),
        3: _make_meta(is_premium=True, price_per_thc=None, thc_unit=""),
    }
    picks = score_picks(products, meta, profile={}, limit=3)
    premium_picks = [p for p in picks if p["pick_reason"] == "Top-shelf pick"]
    assert len(premium_picks) == 1


# ── Mixed THC unit cohort ─────────────────────────────────────────────────────

def test_best_value_scoped_to_majority_unit():
    """When the filter mixes % and mg products, best-value uses the majority unit."""
    # 3 percent products, 2 milligram products -> % is majority.
    # The cheapest-per-thc product in mg has a lower ratio than any %, but
    # tier 3 should still pick from the % cohort.
    products = [
        _make_product(1, cat="Flower"),
        _make_product(2, cat="Flower"),
        _make_product(3, cat="Flower"),
        _make_product(4, cat="Edibles", thc="10mg"),
        _make_product(5, cat="Edibles", thc="10mg"),
    ]
    meta = {
        1: _make_meta(price_per_thc=3.0, thc_unit="%"),
        2: _make_meta(price_per_thc=2.0, thc_unit="%"),  # best within % cohort
        3: _make_meta(price_per_thc=4.0, thc_unit="%"),
        4: _make_meta(price_per_thc=0.1, thc_unit="mg"),  # cheapest overall, wrong cohort
        5: _make_meta(price_per_thc=0.2, thc_unit="mg"),
    }
    picks = score_picks(products, meta, profile={}, limit=3)
    tier3 = [p for p in picks if p["pick_reason"] == "Best value in this filter"]
    assert len(tier3) == 1
    assert tier3[0]["id"] == 2, "Best-value must come from the dominant (%) cohort"


# ── Empty input ───────────────────────────────────────────────────────────────

def test_empty_input_returns_empty():
    """Empty filtered list returns empty pick list (no fallback)."""
    assert score_picks([], {}, profile={}, limit=3) == []


# ── Effect intent mapping ─────────────────────────────────────────────────────

def test_effect_intent_mapping_sleep_to_sleepy():
    """profile.effect_intent='sleep' is matched against DB effect 'Sleepy'."""
    # Use TWO matched intents so Tier 4 fires (size >= 2 requirement),
    # and disable Tier 3 so it doesn't preempt this trigger.
    products = [_make_product(1)]
    meta = {
        1: _make_meta(
            effects_set={"Sleepy", "Calm", "Relaxed"},
            price_per_thc=None,
            thc_unit="",
        ),
    }
    profile = {"effect_intent": ["sleep", "calm"]}  # both map: sleep->Sleepy, calm->Calm
    picks = score_picks(products, meta, profile=profile, limit=3)
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "Matches your sleep vibe"
    # Mapping table sanity: the spec values used above must exist.
    assert EFFECT_INTENT_TO_DB["sleep"] == "Sleepy"
    assert EFFECT_INTENT_TO_DB["calm"] == "Calm"


# ── Beginner gating ───────────────────────────────────────────────────────────

def test_beginner_gating_blocks_experienced_product():
    """Tier 5 must NOT pick a product whose experience_level is not beginner-safe."""
    products = [_make_product(1)]
    # Product has effects to ensure no Tier 4 hit, no sale, not premium, no THC -> no Tier 3.
    meta = {
        1: _make_meta(
            experience_level="Experienced",
            price_per_thc=None,
            thc_unit="",
            effects_set={"Relaxed"},
        ),
    }
    profile = {"experience_level": "beginner"}
    picks = score_picks(products, meta, profile=profile, limit=3)
    # Beginner gating fails -> no tier 1-6 -> Tier 7 fallback fires.
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "Recommended for you"


def test_beginner_gating_allows_all_levels_product():
    """Tier 5 accepts 'All Levels' experience as beginner-safe."""
    products = [_make_product(1)]
    meta = {
        1: _make_meta(
            experience_level="All Levels",
            price_per_thc=None,
            thc_unit="",
            effects_set={"Relaxed"},
        ),
    }
    profile = {"experience_level": "beginner"}
    picks = score_picks(products, meta, profile=profile, limit=3)
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "Gentle for first-timers"


# ── Tier priority ────────────────────────────────────────────────────────────

def test_tier_priority_sale_beats_premium():
    """A product qualifying for both sale_big and premium gets the Tier 1 reason."""
    products = [_make_product(1)]
    meta = {1: _make_meta(is_on_sale=True, discount_pct=25, is_premium=True)}
    picks = score_picks(products, meta, profile={}, limit=3)
    assert len(picks) == 1
    assert picks[0]["pick_reason"] == "25% off this week"
