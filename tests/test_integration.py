"""Integration tests for AI Budtender end-to-end chat flows."""

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from backend.main import app, _product_manager


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _patch_llm(reply_text: str):
    """Return patch context for get_recommendation."""
    return patch("backend.main.get_recommendation", return_value=reply_text)


# ── Full flow tests ───────────────────────────────────────────────────────────

def test_full_chat_flow_normal(client):
    """Full non-beginner chat: request → backend → LLM → response."""
    captured = {}

    def capture(history, user_msg, product_manager, is_beginner=False):
        captured["user_msg"] = user_msg
        captured["pm"] = product_manager
        return "I recommend Blue Dream for relaxation."

    with patch("backend.main.get_recommendation", side_effect=capture):
        response = client.post("/chat", json={
            "session_id": "integration-1",
            "messages": [],
            "is_beginner": False,
            "user_message": "I want to relax after work.",
        })

    assert response.status_code == 200
    assert response.json()["reply"] == "I recommend Blue Dream for relaxation."
    assert "relax" in captured["user_msg"]
    # product_manager instance is passed (not products_json string)
    assert captured["pm"] is _product_manager


def test_full_chat_flow_beginner(client):
    """Full beginner chat: endpoint accepts and returns valid response."""
    # Beginner safety now handled via tool calling parameters inside agent,
    # not by pre-filtering the product catalog. The LLM will use exclude_categories
    # and max_thc parameters in smart_search to enforce safety rules.
    with _patch_llm("Welcome! Let's find something gentle for you."):
        response = client.post("/chat", json={
            "session_id": "integration-2",
            "messages": [],
            "is_beginner": True,
            "user_message": "I've never tried cannabis before.",
        })

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Welcome! Let's find something gentle for you."
    assert data["response_time_ms"] >= 0


# ── Conversation path tests ───────────────────────────────────────────────────

def test_path_a_unclear(client):
    """Path A: unclear need — LLM is called with product_manager."""
    captured = {}

    def capture(history, user_msg, product_manager, is_beginner=False):
        captured["called"] = True
        captured["user_msg"] = user_msg
        return "What effect are you looking for today?"

    with patch("backend.main.get_recommendation", side_effect=capture):
        response = client.post("/chat", json={
            "session_id": "path-a",
            "messages": [],
            "is_beginner": False,
            "user_message": "I'm not sure what I want.",
        })

    assert response.status_code == 200
    assert captured["called"] is True


def test_path_d_beginner(client):
    """Path D: first-time user — endpoint processes request correctly."""
    with _patch_llm("Welcome! Let's find something gentle. Here's a beginner-friendly option."):
        response = client.post("/chat", json={
            "session_id": "path-d",
            "messages": [],
            "is_beginner": True,
            "user_message": "I've never done this before.",
        })

    assert response.status_code == 200
    assert response.json()["reply"] != ""


def test_path_e_price(client):
    """Path E: price-first customer — LLM is called."""
    captured = {}

    def capture(history, user_msg, product_manager, is_beginner=False):
        captured["user_msg"] = user_msg
        return "Great budget question! What effect are you after first?"

    with patch("backend.main.get_recommendation", side_effect=capture):
        response = client.post("/chat", json={
            "session_id": "path-e",
            "messages": [],
            "is_beginner": False,
            "user_message": "What's the cheapest thing you have?",
        })

    assert response.status_code == 200
    assert "cheapest" in captured["user_msg"]


# ── Fast path tests ───────────────────────────────────────────────────────────

def test_simple_greeting_fast_path(client):
    """Verify simple greetings skip LLM entirely (response_time_ms == 0)."""
    response = client.post("/chat", json={
        "session_id": "fast-path-1",
        "messages": [],
        "is_beginner": False,
        "user_message": "hi",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["response_time_ms"] == 0.0
    assert data["reply"] != ""


def test_simple_thanks_fast_path(client):
    """Verify thanks skips LLM entirely."""
    response = client.post("/chat", json={
        "session_id": "fast-path-2",
        "messages": [],
        "is_beginner": False,
        "user_message": "thanks",
    })
    assert response.status_code == 200
    assert response.json()["response_time_ms"] == 0.0


# ── Conversation history limit ────────────────────────────────────────────────

def test_history_limit(client):
    """Verify backend accepts requests with up to 20 history messages."""
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i}"}
        for i in range(20)
    ]

    with _patch_llm("Here's my suggestion."):
        response = client.post("/chat", json={
            "session_id": "history-limit",
            "messages": history,
            "is_beginner": False,
            "user_message": "Final question.",
        })

    assert response.status_code == 200
