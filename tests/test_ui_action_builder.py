"""Tests for backend/ui_action_builder.py.

Covers the trace → ui_action transformation:
- Empty / missing trace returns None.
- Both fast-path and agent-loop traces produce the same shape.
- Top Picks are chosen DETERMINISTICALLY from the retrieved products
  (via ProductManager.score_picks), independent of the reply text — so a
  card can never surface a product that was not retrieved.
- The visible-filters whitelist excludes is_beginner and hardware_type.
"""

from backend.product_manager import ProductManager
from backend.ui_action_builder import (
    REC_MAX,
    REC_MIN,
    TOP_PICK_LIMIT,
    VISIBLE_FILTER_FIELDS,
    build_top_picks,
    build_ui_action,
    build_ui_action_partial,
    select_recommendation_ids,
)


# ── Shared product_manager fixture ────────────────────────────────────────────
# Loaded once for the whole session via tests/conftest.py:load_products_once,
# but the conftest fixture binds against backend.main._product_manager. Build a
# local PM here too so tests can exercise the real score_picks code path.

_pm = ProductManager()
_pm.load()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_product(pid: int, name: str, **overrides) -> dict:
    """Build a minimal compact product dict with overridable fields."""
    base = {
        "id": pid,
        "s": name,
        "c": "BrandA",
        "cat": "Flower",
        "sub": "Premium Flower",
        "t": "Sativa",
        "thc": "22%",
        "p": 40.0,
        "pr": "Mid",
        "f": "Energetic,Uplifted",
        "sc": "Daytime",
        "tod": "Daytime",
        "xl": "All Levels",
        "cm": "Smoke",
        "on": "5-10 min",
        "dur": "2-3 hrs",
    }
    base.update(overrides)
    return base


# ── build_ui_action: empty / missing trace ────────────────────────────────────

def test_no_smart_search_returns_none():
    """When trace has no last_smart_search key, builder returns None."""
    trace = {"profile": {"experience_level": "intermediate"}}
    assert build_ui_action(trace, "Hello there!", _pm) is None


def test_completely_empty_trace_returns_none():
    """An empty dict trace also returns None."""
    assert build_ui_action({}, "hi", _pm) is None


# ── build_ui_action: fast-path & agent-loop traces produce ui_action ─────────

def test_agent_loop_trace_produces_ui_action():
    """Trace populated as if from the agent loop yields a non-None ui_action.

    The agent loop parses tool_call.function.arguments via json.loads; the
    result is a plain dict of snake_case kwargs identical to fast-path.
    """
    fake_products = [_make_fake_product(101, "Sample Sativa Flower")]
    trace = {
        "profile": {"experience_level": "intermediate"},
        "last_smart_search": {
            "args": {"category": "Flower", "strain_type": "Sativa"},
            "result": {"products": fake_products, "total": 1},
        },
    }
    ua = build_ui_action(trace, "Try the Sample Sativa Flower.", _pm)
    assert ua is not None
    assert ua["filters"] == {"category": "Flower", "strain_type": "Sativa"}
    assert ua["total_matched"] == 1
    # The single strict match leads; the list is padded from the same
    # category up to REC_MIN so the Best Matches row is never sparse.
    assert ua["picks"][0]["id"] == 101
    assert len(ua["picks"]) >= REC_MIN
    assert "pick_reason" in ua["picks"][0]
    # spoken_product_ids mirrors the picks' ids exactly.
    assert ua["spoken_product_ids"] == [p["id"] for p in ua["picks"]]


def test_fast_path_trace_produces_same_shape():
    """Fast-path trace yields a ui_action with identical structure to agent-loop."""
    fake_products = [_make_fake_product(202, "Daydream OG")]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower", "strain_type": "Sativa",
                     "effects": ["Energetic", "Uplifted"]},
            "result": {"products": fake_products, "total": 1},
        },
    }
    ua = build_ui_action(trace, "Daydream OG is a great choice.", _pm)
    assert ua is not None
    assert set(ua.keys()) == {"filters", "picks", "spoken_product_ids", "total_matched"}
    assert ua["filters"]["category"] == "Flower"
    assert ua["filters"]["strain_type"] == "Sativa"
    assert ua["filters"]["effects"] == ["Energetic", "Uplifted"]
    assert ua["total_matched"] == 1
    # The strict match leads; same-category backfill pads to REC_MIN.
    assert ua["spoken_product_ids"][0] == 202
    assert len(ua["spoken_product_ids"]) >= REC_MIN


# ── Deterministic picks: independent of reply text ────────────────────────────

def test_picks_are_independent_of_reply_text():
    """Same trace + different reply text → identical picks.

    The core guarantee of the deterministic design: picks come from the
    retrieved set, never from scanning the prose. Two wildly different
    replies (one naming products, one naming none) must yield the same
    Top Pick row.
    """
    products = [
        _make_fake_product(1001, "Lemon Haze"),
        _make_fake_product(1002, "Blue Dream"),
        _make_fake_product(1003, "OG Kush"),
    ]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 3},
        },
    }
    ua_named = build_ui_action(trace, "Try **Lemon Haze** or **OG Kush**.", _pm)
    ua_silent = build_ui_action(trace, "Let me know what vibe you're after.", _pm)
    assert ua_named is not None and ua_silent is not None
    assert ua_named["picks"] == ua_silent["picks"]
    assert ua_named["spoken_product_ids"] == ua_silent["spoken_product_ids"]


def test_picks_are_subset_of_retrieved_products():
    """Every pick id must come from the retrieved set — never invented.

    This is the property that makes 'displayed == retrieved' true by
    construction and kills the old name-collision mis-attribution bug.
    """
    products = [
        _make_fake_product(1, "TTM | Pluto Punch | 100mg"),
        _make_fake_product(2, "TTM | Cherry Nova | 100mg"),
        _make_fake_product(3, "Blue Dream"),
        _make_fake_product(4, "Blue Dream | Hash | 0.5g"),
    ]
    retrieved_ids = {p["id"] for p in products}
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Edibles"},
            "result": {"products": products, "total": 4},
        },
    }
    # A reply that names one sibling would have tripped the old scanner into
    # also highlighting the collision partner; the deterministic path can't.
    ua = build_ui_action(trace, "I recommend TTM | Pluto Punch.", _pm)
    assert ua is not None
    pick_ids = [p["id"] for p in ua["picks"]]
    assert set(pick_ids).issubset(retrieved_ids)
    assert pick_ids == ua["spoken_product_ids"]


def test_picks_capped_at_top_pick_limit():
    """No more than TOP_PICK_LIMIT cards, even with a large retrieved set."""
    products = [_make_fake_product(3000 + i, f"Strain {i}") for i in range(20)]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 20},
        },
    }
    ua = build_ui_action(trace, "Here are some options.", _pm)
    assert ua is not None
    assert len(ua["picks"]) <= TOP_PICK_LIMIT


def test_picks_nonempty_whenever_retrieval_nonempty():
    """A non-empty retrieved set always yields at least one pick (Tier 7)."""
    products = [_make_fake_product(5001, "Anything At All")]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 1},
        },
    }
    ua = build_ui_action(trace, "", _pm)  # empty reply must not matter
    assert ua is not None
    assert len(ua["picks"]) >= 1
    for p in ua["picks"]:
        assert "pick_reason" in p and isinstance(p["pick_reason"], str)


# ── Visible-filter whitelist: is_beginner / hardware_type excluded ────────────

def test_is_beginner_and_hardware_type_excluded_from_filters():
    """Even if present in args, is_beginner and hardware_type never appear as chips."""
    fake_products = [_make_fake_product(601, "Anything")]
    trace = {
        "profile": {"experience_level": "beginner"},
        "last_smart_search": {
            "args": {
                "category": "Vaporizers",
                "strain_type": "Indica",
                "is_beginner": True,
                "hardware_type": "510",
                "effects": ["Relaxed"],
                "max_price": 50,
            },
            "result": {"products": fake_products, "total": 1},
        },
    }
    ua = build_ui_action(trace, "Here are some picks.", _pm)
    assert ua is not None
    assert "is_beginner" not in ua["filters"]
    assert "hardware_type" not in ua["filters"]
    # The four whitelisted fields should be present
    assert ua["filters"] == {
        "category": "Vaporizers",
        "strain_type": "Indica",
        "effects": ["Relaxed"],
        "max_price": 50,
    }
    # And the whitelist itself reflects the contract
    assert VISIBLE_FILTER_FIELDS == {"category", "strain_type", "effects", "max_price"}


# ── build_ui_action_partial: streaming-friendly half (filters, no picks) ──────

def test_partial_returns_none_when_no_smart_search():
    """No trace → no partial — same contract as build_ui_action."""
    assert build_ui_action_partial({}, _pm) is None
    assert build_ui_action_partial({"profile": {}}, _pm) is None


def test_partial_includes_filters_total_but_empty_picks_and_spoken():
    """Partial carries filters/total immediately but defers picks.

    The streaming /chat/stream endpoint emits ui_action the moment
    smart_search resolves (so the storefront can animate chips/grid), then
    follows up with a dedicated `picks` SSE event once the reply finishes.
    The partial's `picks`/`spoken_product_ids` are therefore always empty.
    """
    fake_products = [_make_fake_product(701, "Pre-stream Pick")]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower", "strain_type": "Sativa"},
            "result": {"products": fake_products, "total": 1},
        },
    }
    partial = build_ui_action_partial(trace, _pm)
    assert partial is not None
    assert partial["filters"] == {"category": "Flower", "strain_type": "Sativa"}
    assert partial["total_matched"] == 1
    assert partial["picks"] == []
    assert partial["spoken_product_ids"] == []


def test_partial_keys_match_full_ui_action():
    """build_ui_action and build_ui_action_partial share the same dict shape.

    Frontend code consumes both via the same code path; key skew here would
    silently break the streaming flow.
    """
    fake = [_make_fake_product(800, "Shape Check")]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": fake, "total": 1},
        },
    }
    full = build_ui_action(trace, "irrelevant reply", _pm)
    partial = build_ui_action_partial(trace, _pm)
    assert set(full.keys()) == set(partial.keys())


# ── build_top_picks: the deterministic picker used by the streaming endpoint ──

def test_build_top_picks_empty_when_no_smart_search():
    """No smart_search in trace → no picks."""
    assert build_top_picks({}, _pm) == []
    assert build_top_picks({"profile": {}}, _pm) == []


def test_build_top_picks_empty_when_retrieval_empty():
    """smart_search ran but returned nothing → no picks."""
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": [], "total": 0},
        },
    }
    assert build_top_picks(trace, _pm) == []


def test_build_top_picks_returns_ranked_reasoned_cards():
    """Non-empty retrieval → capped, reasoned Top-Pick cards from that set."""
    products = [_make_fake_product(6000 + i, f"Strain {i}") for i in range(10)]
    retrieved_ids = {p["id"] for p in products}
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 10},
        },
    }
    picks = build_top_picks(trace, _pm)
    assert 1 <= len(picks) <= TOP_PICK_LIMIT
    for p in picks:
        assert p["id"] in retrieved_ids
        assert "pick_reason" in p and isinstance(p["pick_reason"], str)


# ── Recommendation count guarantee (3-6) & shared selection ───────────────────

def test_select_recommendation_ids_takes_top_n_in_order():
    """The shared menu = first REC_MAX retrieved ids, in retrieval order."""
    products = [_make_fake_product(7000 + i, f"Strain {i}") for i in range(10)]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 10},
        },
    }
    ids = select_recommendation_ids(trace)
    assert ids == [7000 + i for i in range(REC_MAX)]  # top REC_MAX, in order


def test_recommendation_count_capped_at_rec_max():
    """A large retrieved set yields exactly REC_MAX picks — no more."""
    products = [_make_fake_product(8000 + i, f"Strain {i}") for i in range(20)]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 20},
        },
    }
    ua = build_ui_action(trace, "irrelevant", _pm)
    assert ua is not None
    assert len(ua["picks"]) == REC_MAX


def test_recommendation_hits_rec_min_when_enough_retrieved():
    """With >= REC_MIN products retrieved, at least REC_MIN cards show."""
    products = [_make_fake_product(9000 + i, f"Strain {i}") for i in range(REC_MIN)]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": REC_MIN},
        },
    }
    ua = build_ui_action(trace, "irrelevant", _pm)
    assert ua is not None
    assert len(ua["picks"]) >= REC_MIN


def test_cards_and_selection_are_the_same_list():
    """The cards' ids equal select_recommendation_ids — one source of truth.

    This is the guarantee that the storefront cards and the products the
    assistant is instructed to recommend can never diverge: both are built
    from this single list.
    """
    products = [_make_fake_product(9100 + i, f"Strain {i}") for i in range(8)]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 8},
        },
    }
    selected = select_recommendation_ids(trace)
    cards = build_top_picks(trace, _pm)
    assert [c["id"] for c in cards] == selected


# ── Backfill: thin real result padded to REC_MIN, marked "Similar option" ─────

def test_thin_result_backfilled_to_rec_min_with_similar_option():
    """A single real match is padded from the same category up to REC_MIN.

    The real match keeps a normal reason; the padded products are labeled
    SIMILAR_OPTION_REASON so the UI can be honest about what's an exact match
    vs a same-category suggestion.
    """
    from backend.ui_action_builder import SIMILAR_OPTION_REASON
    # id 101 is a fake product; category Flower exists in the real catalog so
    # backfill can top it up.
    products = [_make_fake_product(101, "Only Real Match")]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 1},
        },
    }
    picks = build_top_picks(trace, _pm)
    assert len(picks) >= REC_MIN
    assert picks[0]["id"] == 101  # the real match leads
    # At least one padded product carries the "Similar option" label.
    assert any(p["pick_reason"] == SIMILAR_OPTION_REASON for p in picks[1:])
    # The real match is NOT labeled as a similar option.
    assert picks[0]["pick_reason"] != SIMILAR_OPTION_REASON


def test_zero_matches_not_backfilled():
    """0 strict matches → stay empty; never fabricate from a true no-result."""
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": [], "total": 0},
        },
    }
    assert build_top_picks(trace, _pm) == []
    assert select_recommendation_ids(trace, _pm) == []
