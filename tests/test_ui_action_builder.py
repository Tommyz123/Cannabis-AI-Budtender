"""Tests for backend/ui_action_builder.py.

Covers the trace → ui_action transformation:
- Empty / missing trace returns None.
- Both fast-path and agent-loop traces produce the same shape.
- The reply scanner is robust to pipe-separated names and markdown bold.
- The visible-filters whitelist excludes is_beginner and hardware_type.
"""

from backend.product_manager import ProductManager
from backend.ui_action_builder import (
    VISIBLE_FILTER_FIELDS,
    build_picks_for_spoken,
    build_ui_action,
    build_ui_action_partial,
    scan_spoken_product_ids,
    _scan_key,
    _scan_reply_for_product_ids,
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
    # picks should contain at least one entry (Tier 7 fallback guarantees this)
    assert len(ua["picks"]) >= 1
    assert ua["picks"][0]["id"] == 101
    assert "pick_reason" in ua["picks"][0]
    # The reply mentions the product name → it should appear in spoken ids
    assert ua["spoken_product_ids"] == [101]


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
    assert ua["spoken_product_ids"] == [202]


# ── Reply scanning: pipe-separated names ──────────────────────────────────────

def test_scan_picks_up_name_with_pipe_separator():
    """Reply mentions 'Half & Half'; DB name is 'Half & Half | UP | 10mg'."""
    fake_products = [
        _make_fake_product(301, "Half & Half | UP | 2:1 | Single | 10mg"),
    ]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Edibles"},
            "result": {"products": fake_products, "total": 1},
        },
    }
    reply = "I recommend Half & Half — a balanced ratio gummy."
    ua = build_ui_action(trace, reply, _pm)
    assert ua is not None
    assert ua["spoken_product_ids"] == [301]


def test_scan_key_strips_pipe_segments():
    """_scan_key returns just the leading pipe segment, trimmed."""
    assert _scan_key("Half & Half | UP | 10mg") == "Half & Half"
    assert _scan_key("Plain Name") == "Plain Name"
    assert _scan_key("  Leading Space | Whatever") == "Leading Space"


# ── Reply scanning: markdown bold and other flanking punctuation ──────────────

def test_scan_handles_markdown_bold():
    """**Half & Half** in markdown should still match — `*` is a non-word char."""
    fake_products = [
        _make_fake_product(401, "Half & Half | UP | 10mg"),
    ]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Edibles"},
            "result": {"products": fake_products, "total": 1},
        },
    }
    reply = "Try **Half & Half** for a balanced experience."
    ua = build_ui_action(trace, reply, _pm)
    assert ua is not None
    assert ua["spoken_product_ids"] == [401]


def test_scan_returns_ids_in_reply_order_and_dedupes():
    """Two products both mentioned → ordered by first appearance, no dupes."""
    products = [
        _make_fake_product(501, "Alpha One"),
        _make_fake_product(502, "Beta Two"),
    ]
    reply = "Start with Beta Two, but Alpha One also works. Beta Two again!"
    ids = _scan_reply_for_product_ids(reply, products)
    assert ids == [502, 501]


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


# ── build_ui_action_partial: streaming-friendly half (filters + picks) ────

def test_partial_returns_none_when_no_smart_search():
    """No trace → no partial — same contract as build_ui_action."""
    assert build_ui_action_partial({}, _pm) is None
    assert build_ui_action_partial({"profile": {}}, _pm) is None


def test_partial_includes_filters_total_but_empty_picks_and_spoken():
    """Partial omits the reply scan AND picks selection.

    The streaming /chat/stream endpoint emits ui_action BEFORE the reply
    has streamed in. Under the spoken-driven Top Pick scheme (see
    `build_picks_for_spoken`), picks cannot be known until the reply
    text exists, so the partial payload's `picks` is always [] — the
    streaming endpoint follows up with a dedicated `picks` SSE event
    once the reply finishes.
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
    # Critical: picks and spoken are both deferred to post-stream events.
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


# ── scan_spoken_product_ids: streaming reply scan ────────────────────────

def test_scan_spoken_returns_empty_when_no_smart_search():
    """Reply scan returns [] when no smart_search happened (no candidates)."""
    assert scan_spoken_product_ids("any reply here", {}) == []
    assert scan_spoken_product_ids("any reply here", {"profile": {}}) == []


def test_scan_spoken_returns_ids_in_order_of_first_mention():
    """Spoken ids come back ordered by appearance in the reply, deduped."""
    products = [
        _make_fake_product(1, "Alpha Strain"),
        _make_fake_product(2, "Beta Strain"),
        _make_fake_product(3, "Gamma Strain"),
    ]
    trace = {
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 3},
        },
    }
    reply = "Try Gamma Strain first, then Alpha Strain, then Alpha Strain again."
    ids = scan_spoken_product_ids(reply, trace)
    # Gamma first (mentioned first), Alpha second, no Beta (never mentioned),
    # Alpha not duplicated.
    assert ids == [3, 1]


def test_scan_spoken_empty_reply_returns_empty():
    """Empty / whitespace reply text → empty list."""
    products = [_make_fake_product(1, "Alpha Strain")]
    trace = {
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 1},
        },
    }
    assert scan_spoken_product_ids("", trace) == []


# ── build_ui_action: picks are spoken-driven (Phase A contract) ──────────


def test_build_ui_action_picks_strictly_subset_of_spoken_ids():
    """Top Pick row content ⊆ products mentioned in the AI reply.

    Contract guard: filtered set has 4 products, AI reply mentions only
    2 of them — picks must be exactly those 2, not the algorithm's
    independent 3-product selection. Products in filtered but not
    spoken stay in the regular grid only.
    """
    products = [
        _make_fake_product(1001, "Lemon Haze"),
        _make_fake_product(1002, "Blue Dream"),
        _make_fake_product(1003, "OG Kush"),
        _make_fake_product(1004, "Sour Diesel"),
    ]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 4},
        },
    }
    reply = "Two solid choices: try **Lemon Haze** for daytime, or **OG Kush** to wind down."
    ua = build_ui_action(trace, reply, _pm)
    assert ua is not None
    pick_ids = [p["id"] for p in ua["picks"]]
    spoken_ids = ua["spoken_product_ids"]
    # Order of picks follows mention order (which matches spoken).
    assert pick_ids == spoken_ids
    # Strict subset of spoken — never algorithm-selected products.
    assert set(pick_ids).issubset(set(spoken_ids))
    # Every pick carries a reason.
    for p in ua["picks"]:
        assert "pick_reason" in p and isinstance(p["pick_reason"], str)


def test_build_ui_action_picks_empty_when_reply_mentions_no_products():
    """No product names in reply → picks list is empty (Top Pick row hidden)."""
    products = [_make_fake_product(2001, "Lemon Haze")]
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {"products": products, "total": 1},
        },
    }
    reply = "Let me know if you want something calming or energizing."
    ua = build_ui_action(trace, reply, _pm)
    assert ua is not None
    assert ua["picks"] == []
    assert ua["spoken_product_ids"] == []


def test_build_picks_for_spoken_returns_empty_when_spoken_empty():
    """Helper used by the streaming endpoint returns [] for empty ids."""
    trace = {
        "profile": {},
        "last_smart_search": {
            "args": {"category": "Flower"},
            "result": {
                "products": [_make_fake_product(3001, "Lemon Haze")],
                "total": 1,
            },
        },
    }
    assert build_picks_for_spoken(trace, _pm, []) == []
    assert build_picks_for_spoken({}, _pm, [3001]) == []
