"""Tests for backend/main.py API routes."""

from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient
from backend.main import app, _product_manager


@pytest.fixture(scope="module", autouse=True)
def load_products():
    """Ensure product manager is loaded before tests."""
    _product_manager.load("data/NYE4.0_v3.csv")


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

    def capture_call(history, user_message, product_manager, is_beginner=False):
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
