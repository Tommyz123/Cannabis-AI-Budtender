"""Tests for backend/router.py — focus on try_extract_search_params.

The strain/effect extraction rules went through a substantive rework that
fixed two long-standing bugs:

  1. Strain detection used to OR the current message with all of
     conversation history, so "indica" from an earlier turn would override
     "sativa" in the current message.

  2. Detecting a strain auto-added a default effect set (indica →
     [Relaxed, Sleepy]); the user wanted strain alone to mean "any flavor
     of that strain" and effects to be reserved for explicit keywords.

The current 3-step rule, in priority order:

  step 1. Strain from CURRENT message wins.
          Fall back to history strain only when current message has none.

  step 2. Effect keywords detected in the CURRENT message are always
          honored — strain and effects can coexist when both are explicit
          ("energetic sativa flower" → strain=Sativa, effects=[Energetic]).

  step 3. If current message has neither explicit effect words nor a
          strain, fall back to effect keywords found in history. This
          preserves "make it cheaper, keep the same vibe" follow-ups
          while NOT dragging stale effects onto a fresh strain choice.

These tests lock the rule down so future refactors don't regress to the
old auto-effect-from-strain or history-wins-strain behaviors.
"""

from backend.router import try_extract_search_params


def _hist(*messages: str) -> list[dict]:
    """Build a user-only history list."""
    return [{"role": "user", "content": m} for m in messages]


# ── Strain detection: current message wins ─────────────────────────────────

def test_strain_current_message_overrides_history():
    """`sativa vape` after an `indica flower` turn → strain=Sativa, not Indica."""
    params = try_extract_search_params(
        "sativa vape", _hist("indica flower"), is_beginner=False,
    )
    assert params["category"] == "Vaporizers"
    assert params["strain_type"] == "Sativa"


def test_strain_carries_from_history_when_current_silent():
    """`vape` alone after `sativa flower` → strain=Sativa carried from history."""
    params = try_extract_search_params(
        "vape", _hist("sativa flower"), is_beginner=False,
    )
    assert params["strain_type"] == "Sativa"
    assert params["category"] == "Vaporizers"


def test_strain_hybrid_recognized():
    """`hybrid` keyword extracted as strain."""
    params = try_extract_search_params(
        "hybrid flower", [], is_beginner=False,
    )
    assert params["strain_type"] == "Hybrid"


# ── No auto-effects from strain ────────────────────────────────────────────

def test_indica_alone_does_not_inject_effects():
    """`indica flower` must NOT auto-add Relaxed/Sleepy effects."""
    params = try_extract_search_params(
        "indica flower", [], is_beginner=False,
    )
    assert params["strain_type"] == "Indica"
    assert "effects" not in params


def test_sativa_alone_does_not_inject_effects():
    """`sativa vape` must NOT auto-add Energetic/Uplifted effects."""
    params = try_extract_search_params(
        "sativa vape", [], is_beginner=False,
    )
    assert params["strain_type"] == "Sativa"
    assert "effects" not in params


# ── Explicit effect words coexist with strain ──────────────────────────────

def test_explicit_effect_with_strain_keeps_both():
    """`energetic sativa flower` → strain=Sativa AND effects=[Energetic]."""
    params = try_extract_search_params(
        "energetic sativa flower", [], is_beginner=False,
    )
    assert params["strain_type"] == "Sativa"
    assert "Energetic" in params["effects"]


def test_sleepy_indica_keeps_both():
    """`sleepy indica edibles` → strain=Indica AND effects=[Relaxed, Sleepy]."""
    params = try_extract_search_params(
        "sleepy indica edibles", [], is_beginner=False,
    )
    assert params["strain_type"] == "Indica"
    assert "Sleepy" in params["effects"]
    assert "Relaxed" in params["effects"]


# ── Strain switch drops history effects ────────────────────────────────────

def test_strain_switch_drops_history_effects():
    """After `indica flower for sleep`, `actually sativa` keeps Sativa with no Sleepy.

    User scenario: the customer originally asked for sleepy indica, then
    changes their mind to sativa. Sleepy should NOT carry — they switched
    intent. (`category=Flower` does carry from history because there is no
    new category in the current message.)
    """
    hist = _hist("indica flower for sleep")
    params = try_extract_search_params(
        "actually sativa", hist, is_beginner=False,
    )
    assert params["strain_type"] == "Sativa"
    assert "effects" not in params
    # Category carries from history since current msg has no category keyword.
    assert params["category"] == "Flower"


def test_sativa_flower_after_sleepy_history_drops_sleepy():
    """`sativa flower` after a Sleepy turn → no Sleepy carry-over."""
    hist = _hist("vape for sleep")
    params = try_extract_search_params(
        "sativa flower", hist, is_beginner=False,
    )
    assert params["strain_type"] == "Sativa"
    assert "effects" not in params


# ── History fallback for effects when current has nothing ──────────────────

def test_keep_the_vibe_carries_effects_from_history():
    """`Actually make it a little cheaper and keep the same vibe.` with prior
    `uplifting drawing` turn → effects=[Energetic, Uplifted] carry through.

    This preserves the price-refinement UX where the customer asks for
    cheaper but wants the same emotional profile. With no strain in the
    current message AND no explicit effect words, history effects win.
    """
    hist = _hist(
        "I want a flower for weekend drawing sessions, uplifting but not racey."
    )
    params = try_extract_search_params(
        "Actually make it a little cheaper and keep the same vibe.",
        hist,
        is_beginner=False,
    )
    assert params["category"] == "Flower"
    # The `keep the same vibe` phrase has no effect word itself, but history
    # has "uplifting" and "drawing" which trigger Energetic + Uplifted.
    assert "Energetic" in params.get("effects", [])
    assert "Uplifted" in params.get("effects", [])


def test_history_effects_do_not_carry_when_current_has_strain():
    """`indica flower` after `make me sleepy` history → no Sleepy carry.

    Strain in current message is specific enough that we don't muddy it
    with history effects.
    """
    hist = _hist("I want something sleepy")
    params = try_extract_search_params(
        "indica flower", hist, is_beginner=False,
    )
    assert params["strain_type"] == "Indica"
    assert "effects" not in params


# ── Sanity: cold start with effect only ────────────────────────────────────

def test_effect_only_no_strain():
    """`relaxing edibles` with no history → effects only, no strain."""
    params = try_extract_search_params(
        "relaxing edibles", [], is_beginner=False,
    )
    assert "strain_type" not in params
    assert params["category"] == "Edibles"
    assert "Relaxed" in params["effects"]


def test_sleep_keyword_maps_to_relaxed_and_sleepy():
    """`something for sleep` → effects=[Relaxed, Sleepy]."""
    params = try_extract_search_params(
        "something for sleep, edibles", [], is_beginner=False,
    )
    assert "Sleepy" in params["effects"]
    assert "Relaxed" in params["effects"]


# ── Guards: fast path should bail to LLM in certain cases ─────────────────

def test_flavor_query_bails_out_of_fast_path():
    """Flavor mentions force the LLM path (fast path can't pass `query` arg)."""
    assert try_extract_search_params(
        "I want something citrus", [], is_beginner=False,
    ) is None


def test_detail_query_bails_out_of_fast_path():
    """Detail/explanation requests bypass fast path."""
    assert try_extract_search_params(
        "tell me more about Blue Dream", [], is_beginner=False,
    ) is None


def test_returns_none_when_nothing_extractable():
    """No category, no strain, no effects → None (fast path declines)."""
    assert try_extract_search_params(
        "hi there", [], is_beginner=False,
    ) is None
