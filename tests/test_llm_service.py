"""Tests for backend/llm_service.py."""

from unittest.mock import MagicMock, patch
import pytest
import openai
from backend.llm_service import build_messages, get_recommendation
from backend.prompts import SYSTEM_PROMPT
from backend.router import (
    get_simple_response,
    is_medical_query,
    is_vague_query,
    is_form_unknown_query,
    is_occasion_ready_query,
    is_price_refinement_query,
    determine_tool_choice,
)
from backend.tool_executor import TOOLS_SCHEMA


# ── System prompt tests ───────────────────────────────────────────────────────

def test_build_system_prompt():
    """Verify system prompt contains role definition and core rules."""
    assert "AI Budtender" in SYSTEM_PROMPT
    assert "cannabis dispensary" in SYSTEM_PROMPT
    assert "MEDICAL PROTECTION" in SYSTEM_PROMPT
    assert "DISCOVERY-FIRST" in SYSTEM_PROMPT
    assert "ANTI-HALLUCINATION" in SYSTEM_PROMPT


def test_build_system_prompt_contains_mappings():
    """Verify system prompt includes semantic mapping examples."""
    assert "can't sleep" in SYSTEM_PROMPT
    assert "relax" in SYSTEM_PROMPT
    assert "hiking" in SYSTEM_PROMPT
    assert "party" in SYSTEM_PROMPT
    assert "OCCASION-READY DIRECT SEARCH" in SYSTEM_PROMPT
    assert "BEGINNER-READY DIRECT SEARCH" in SYSTEM_PROMPT
    # New prompt handles beginner internally, no hidden marker needed
    assert "beginner" in SYSTEM_PROMPT.lower()


# ── build_messages tests ───────────────────────────────────────────────────────

def test_build_messages():
    """Verify messages list structure: system + history + user."""
    history = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
    ]
    messages = build_messages(history, "I need something to sleep")

    assert messages[0]["role"] == "system"
    assert "AI Budtender" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "Hi"}
    assert messages[2] == {"role": "assistant", "content": "Hello!"}
    assert messages[-1]["role"] == "user"
    assert "I need something to sleep" in messages[-1]["content"]


def test_build_messages_with_profile():
    """Verify profile is serialized and appended to system prompt."""
    profile = {"experience_level": "beginner", "price_range": "budget"}
    messages = build_messages([], "Help me sleep", profile=profile)
    system_content = messages[0]["content"]
    assert "SESSION PROFILE" in system_content
    assert "beginner" in system_content
    assert "budget" in system_content


def test_build_messages_empty_history():
    """Verify messages work correctly with no history."""
    messages = build_messages([], "Hello")
    assert len(messages) == 2  # system + user
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_build_messages_no_products_injected():
    """Verify product data is NOT embedded in user message (tool calling handles it)."""
    messages = build_messages([], "Help me sleep")
    last_content = messages[-1]["content"]
    assert "Product catalog" not in last_content
    assert "[{" not in last_content


# ── Simple response tests ─────────────────────────────────────────────────────

def test_get_simple_response_greetings():
    """Verify simple greetings return canned replies."""
    assert get_simple_response("hi") is not None
    assert get_simple_response("hello") is not None
    assert get_simple_response("hey") is not None


def test_get_simple_response_thanks():
    """Verify thanks/bye return canned replies."""
    assert get_simple_response("thanks") is not None
    assert get_simple_response("bye") is not None
    assert get_simple_response("ok") is not None


def test_get_simple_response_none_for_real_query():
    """Verify real queries return None (need LLM)."""
    assert get_simple_response("I want something to relax") is None
    assert get_simple_response("Can you recommend a flower?") is None
    assert get_simple_response("I need help sleeping") is None


# ── Query classification tests ────────────────────────────────────────────────

def test_is_medical_query_positive():
    """Verify medical condition queries are detected."""
    assert is_medical_query("Can cannabis cure my anxiety disorder?")
    assert is_medical_query("Does weed treat epilepsy?")
    assert is_medical_query("Will this cure my cancer?")


def test_is_medical_query_negative():
    """Verify non-medical queries are not flagged."""
    assert not is_medical_query("I feel anxious and want to relax")
    assert not is_medical_query("Something for stress relief")
    assert not is_medical_query("I want to sleep better")


def test_is_vague_query():
    """Verify vague queries are detected."""
    assert is_vague_query("something good")
    assert is_vague_query("anything")
    assert is_vague_query("surprise me")


def test_is_vague_query_negative():
    """Verify non-vague queries are not flagged."""
    assert not is_vague_query("I need something to help me sleep")
    assert not is_vague_query("something good for relaxation")


def test_is_form_unknown_query():
    """Verify effect-but-no-form queries are detected."""
    assert is_form_unknown_query("I need something to help me sleep", [])
    assert is_form_unknown_query("I want to relax", [])


def test_is_form_unknown_query_with_form():
    """Verify queries with form are not flagged."""
    assert not is_form_unknown_query("I want a flower for sleep", [])
    assert not is_form_unknown_query("Give me an edible for relaxation", [])


def test_is_form_unknown_query_form_in_history():
    """Verify form in history suppresses flag."""
    history = [{"role": "user", "content": "I prefer edibles"}]
    assert not is_form_unknown_query("I want to relax", history)


def test_is_occasion_ready_query():
    """Verify representative occasion-ready requests all count as search-ready."""
    messages = [
        (
            "I want something for a date night where we feel relaxed, smiley, "
            "and connected, not knocked out."
        ),
        (
            "After hard workouts I want something for recovery and body relaxation, "
            "but I still want to stay mentally pretty clear."
        ),
        (
            "What would you suggest for a small house party if I want to stay social "
            "and upbeat but not paranoid?"
        ),
    ]
    for message in messages:
        assert is_occasion_ready_query(message, [])


def test_determine_tool_choice_keeps_plain_effect_query_on_none():
    """Verify standard effect-only discovery queries still ask for form first."""
    assert determine_tool_choice("I want to relax", []) == "none"


def test_determine_tool_choice_requires_search_for_occasion_ready_query():
    """Verify representative occasion-ready requests all force immediate search."""
    messages = [
        (
            "I want something for a date night where we feel relaxed, smiley, "
            "and connected, not knocked out."
        ),
        (
            "After hard workouts I want something for recovery and body relaxation, "
            "but I still want to stay mentally pretty clear."
        ),
        (
            "What would you suggest for a small house party if I want to stay social "
            "and upbeat but not paranoid?"
        ),
    ]
    for message in messages:
        assert determine_tool_choice(message, []) == "required"


def test_determine_tool_choice_requires_search_for_beginner_ready_query():
    """Verify beginner-safe no-form requests force immediate search."""
    messages = [
        (
            "I have never tried weed before and I am nervous about getting way too high. "
            "I want something super gentle for a quiet night at home."
        ),
        "I'm first time here, do you have anything to help me sleep?",
    ]
    for message in messages:
        assert determine_tool_choice(message, []) == "required"


def test_is_price_refinement_query_after_recommendations():
    """Verify cheaper follow-up after concrete recs is treated as refinement."""
    history = [
        {"role": "assistant", "content": "1. **Blue Dream** by Harvest\n   Price: $45 | THC: 24%\n2. **Cosmic Crashers** by Verde Lucido\n   Price: $32 | THC: 22%"},
    ]
    assert is_price_refinement_query(
        "Actually make it a little cheaper and keep the same vibe.",
        history,
    )


def test_determine_tool_choice_requires_search_for_price_refinement():
    """Verify cheaper follow-up after recommendations forces direct re-search."""
    history = [
        {"role": "assistant", "content": "1. **Blue Dream** by Harvest\n   Price: $45 | THC: 24%\n2. **Cosmic Crashers** by Verde Lucido\n   Price: $32 | THC: 22%"},
    ]
    assert determine_tool_choice(
        "That looks pricey. Can you give me a cheaper option instead?",
        history,
    ) == "required"


# ── Tools schema test ─────────────────────────────────────────────────────────

def test_tools_schema():
    """Verify tools schema has correct structure."""
    assert len(TOOLS_SCHEMA) == 2
    names = {t["function"]["name"] for t in TOOLS_SCHEMA}
    assert "smart_search" in names
    assert "get_product_details" in names


# ── get_recommendation tests ──────────────────────────────────────────────────

def test_get_recommendation_success():
    """Verify successful API call returns reply text (mocked OpenAI)."""
    mock_choice = MagicMock()
    mock_choice.message.content = "I recommend Blue Dream for relaxation."
    mock_choice.message.tool_calls = None
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_pm = MagicMock()
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("backend.llm_service._openai_client", mock_client):
        result = get_recommendation([], "Help me relax", mock_pm)

    assert result == "I recommend Blue Dream for relaxation."


def test_get_recommendation_error():
    """Verify API timeout raises RuntimeError with descriptive message."""
    mock_pm = MagicMock()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = openai.APITimeoutError(
        request=MagicMock()
    )

    with patch("backend.llm_service._openai_client", mock_client):
        with pytest.raises(RuntimeError, match="timed out"):
            get_recommendation([], "Hello", mock_pm)


def test_get_recommendation_tool_call():
    """Verify agent loop executes tool call and returns final reply."""
    # First response: has tool call
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_001"
    mock_tool_call.function.name = "smart_search"
    mock_tool_call.function.arguments = '{"category": "Flower"}'

    mock_msg_with_tool = MagicMock()
    mock_msg_with_tool.tool_calls = [mock_tool_call]
    mock_msg_with_tool.content = None

    mock_resp1 = MagicMock()
    mock_resp1.choices = [MagicMock(message=mock_msg_with_tool)]

    # Second response: final answer
    mock_msg_final = MagicMock()
    mock_msg_final.tool_calls = None
    mock_msg_final.content = "Here is a Flower recommendation!"

    mock_resp2 = MagicMock()
    mock_resp2.choices = [MagicMock(message=mock_msg_final)]

    mock_pm = MagicMock()
    mock_pm.search_products.return_value = {"products": [], "total": 0}

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [mock_resp1, mock_resp2]

    with patch("backend.llm_service._openai_client", mock_client):
        result = get_recommendation([], "I want a flower for sleep", mock_pm)

    assert result == "Here is a Flower recommendation!"
    # Fast path extracts effects from "sleep" keyword in addition to category
    mock_pm.search_products.assert_called_once_with(
        category="Flower", effects=["Relaxed", "Sleepy"]
    )


def test_get_recommendation_price_refinement_uses_lower_price_cap():
    """Verify cheaper follow-up preserves context and searches below prior floor."""
    mock_choice = MagicMock()
    mock_choice.message.content = "Here are some cheaper flower options."
    mock_choice.message.tool_calls = None
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    history = [
        {"role": "user", "content": "I want a flower for weekend drawing sessions, uplifting but not racey."},
        {"role": "assistant", "content": "1. **Blue Dream** by Harvest\n   Sativa\n   Size: 3.5g | Price: $45 | THC: 24%\n2. **Cosmic Crashers** by Verde Lucido\n   Hybrid\n   Size: 3.5g | Price: $32 | THC: 22%"},
    ]

    mock_pm = MagicMock()
    mock_pm.search_products.return_value = {"products": [], "total": 0}
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("backend.llm_service._openai_client", mock_client):
        result = get_recommendation(
            history,
            "Actually make it a little cheaper and keep the same vibe.",
            mock_pm,
        )

    assert result == "Here are some cheaper flower options."
    mock_pm.search_products.assert_called_once_with(
        category="Flower",
        effects=["Energetic", "Uplifted"],
        max_price=31.99,
    )


def test_get_recommendation_beginner_ready_defaults_to_edibles():
    """Verify beginner no-form gentle requests search beginner-safe edibles directly."""
    mock_choice = MagicMock()
    mock_choice.message.content = "Here are some gentle beginner-friendly edibles."
    mock_choice.message.tool_calls = None
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_pm = MagicMock()
    mock_pm.search_products.return_value = {"products": [], "total": 0}
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    with patch("backend.llm_service._openai_client", mock_client):
        result = get_recommendation(
            [],
            "I'm first time here, do you have anything to help me sleep?",
            mock_pm,
            is_beginner=True,
        )

    assert result == "Here are some gentle beginner-friendly edibles."
    mock_pm.search_products.assert_called_once_with(
        category="Edibles",
        effects=["Relaxed", "Sleepy"],
        is_beginner=True,
    )
