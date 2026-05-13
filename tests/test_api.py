"""Tests for backend/main.py API routes."""

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from backend.main import app, _product_manager
from backend.config import DB_PATH


@pytest.fixture(scope="module", autouse=True)
def load_products():
    """Ensure product manager is loaded before tests."""
    _product_manager.load(DB_PATH)


@pytest.fixture(scope="module")
def client():
    """TestClient for the FastAPI app."""
    return TestClient(app)


def _mock_llm(reply_text: str):
    """Return a context manager that patches get_recommendation."""
    return patch(
        "backend.main.get_recommendation",
        return_value=reply_text,
    )


def test_health_endpoint(client):
    """Verify GET /health returns ok status and product count."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["products_loaded"] == 217


def test_chat_endpoint_normal(client):
    """Verify POST /chat non-beginner request returns correct response."""
    with _mock_llm("Here is my recommendation for you."):
        response = client.post("/chat", json={
            "session_id": "test-session-1",
            "messages": [],
            "is_beginner": False,
            "user_message": "I want something to relax.",
        })
    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Here is my recommendation for you."
    assert data["session_id"] == "test-session-1"
    assert "response_time_ms" in data
    assert isinstance(data["response_time_ms"], float)
    assert data["response_time_ms"] >= 0


def test_chat_endpoint_beginner(client):
    """Verify POST /chat beginner request returns valid response."""
    # Beginner safety filtering now handled inside agent via tool calling parameters
    with _mock_llm("Start low and go slow! Try a low-dose edible."):
        response = client.post("/chat", json={
            "session_id": "test-session-2",
            "messages": [],
            "is_beginner": True,
            "user_message": "I'm a complete beginner.",
        })

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Start low and go slow! Try a low-dose edible."
    assert data["session_id"] == "test-session-2"


def test_chat_endpoint_invalid_request(client):
    """Verify empty user_message returns 400."""
    response = client.post("/chat", json={
        "session_id": "test-session-3",
        "messages": [],
        "is_beginner": False,
        "user_message": "   ",
    })
    assert response.status_code == 400


def test_chat_endpoint_with_history(client):
    """Verify chat with conversation history passes history to LLM."""
    captured_args = {}

    def capture_call(history, user_message, product_manager, is_beginner=False, **_kwargs):
        captured_args["history"] = history
        return "Based on your history, I recommend..."

    with patch("backend.main.get_recommendation", side_effect=capture_call):
        response = client.post("/chat", json={
            "session_id": "test-session-4",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello!"},
            ],
            "is_beginner": False,
            "user_message": "I need help.",
        })

    assert response.status_code == 200
    assert len(captured_args["history"]) == 2
    assert captured_args["history"][0]["role"] == "user"


def test_cors_headers(client):
    """Verify CORS headers are set correctly."""
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" in response.headers


def test_get_products(client):
    """Verify GET /products returns 217 products including sale fields on some."""
    response = client.get("/products")
    assert response.status_code == 200
    data = response.json()
    assert "products" in data
    assert "total" in data
    assert data["total"] == 217
    assert len(data["products"]) == 217
    # At least 1 of the first 50 products should carry the optional sale fields.
    has_sale_field = any(p.get("sale") for p in data["products"][:50])
    assert has_sale_field, "Expected at least one product in the first 50 to be on sale"


def test_chat_includes_ui_action_on_search(client):
    """Verify /chat populates ui_action when get_recommendation runs a smart_search."""

    def fake_get_recommendation(*args, **kwargs):
        trace = kwargs.get("trace")
        if trace is not None:
            trace["profile"] = {}
            trace["last_smart_search"] = {
                "args": {"category": "Flower", "strain_type": "Sativa"},
                "result": {
                    "products": [{"id": 1, "s": "Test", "cat": "Flower"}],
                    "total": 1,
                },
            }
        return "Here you go!"

    with patch("backend.main.get_recommendation", side_effect=fake_get_recommendation):
        response = client.post(
            "/chat",
            json={
                "session_id": "test-session-ui-action",
                "messages": [],
                "is_beginner": False,
                "user_message": "I want sativa flower.",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Here you go!"
    assert data["ui_action"] is not None
    assert data["ui_action"]["filters"] == {
        "category": "Flower",
        "strain_type": "Sativa",
    }
    assert data["ui_action"]["total_matched"] == 1


def test_chat_no_ui_action_on_greeting(client):
    """Verify /chat fast-path greeting bypasses get_recommendation and returns ui_action=null."""
    # No mock — the router fast-path should short-circuit "hi" without
    # ever invoking get_recommendation. The response should still be valid
    # and ui_action should be null.
    response = client.post(
        "/chat",
        json={
            "session_id": "test-session-greeting",
            "messages": [],
            "is_beginner": False,
            "user_message": "hi",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ui_action"] is None


def test_chat_with_removed_filters(client):
    """Verify /chat accepts removed_filters with empty user_message and injects a system signal."""
    captured = {}

    def fake_get_recommendation(history, user_message, product_manager, **kwargs):
        captured["history"] = history
        captured["user_message"] = user_message
        trace = kwargs.get("trace")
        if trace is not None:
            trace["profile"] = {}
            trace["last_smart_search"] = {
                "args": {"category": "Flower"},
                "result": {
                    "products": [{"id": 1, "s": "Test Flower", "cat": "Flower"}],
                    "total": 1,
                },
            }
        return "Sure, opening up beyond Sativa."

    with patch("backend.main.get_recommendation", side_effect=fake_get_recommendation):
        response = client.post(
            "/chat",
            json={
                "session_id": "test-session-removed-filters",
                "messages": [],
                "is_beginner": False,
                "user_message": "",
                "removed_filters": {"strain_type": "Sativa"},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["reply"] == "Sure, opening up beyond Sativa."
    # The synthetic system message must have been prepended to the history.
    assert any(
        msg["role"] == "system" and "strain_type=Sativa" in msg["content"]
        for msg in captured["history"]
    ), f"Expected a UI SIGNAL system message in history, got: {captured['history']}"
    # The handler should have synthesized a non-empty user_message internally.
    assert captured["user_message"].strip() != ""


def test_chat_removed_filters_empty_user_message_still_400_when_both_empty(client):
    """Verify empty user_message AND empty removed_filters still 400s."""
    response = client.post(
        "/chat",
        json={
            "session_id": "test-session-both-empty",
            "messages": [],
            "is_beginner": False,
            "user_message": "",
            "removed_filters": {},
        },
    )
    assert response.status_code == 400
