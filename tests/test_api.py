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
    """Verify GET /products returns 217 products with sale + disc (demo data)."""
    response = client.get("/products")
    assert response.status_code == 200
    data = response.json()
    assert "products" in data
    assert "total" in data
    assert data["total"] == 217
    assert len(data["products"]) == 217
    # The seeder marks ~20% of products on-sale. The API surfaces `sale`
    # and `disc` fields for those, but never fabricates an `op` (original
    # price) — that would require a real pre-discount price in the DB.
    sale_items = [p for p in data["products"] if p.get("sale")]
    assert len(sale_items) > 0, "Expected some products on sale (demo data)"
    for p in sale_items:
        assert p["sale"] is True
        assert isinstance(p["disc"], int) and p["disc"] > 0
    for p in data["products"]:
        assert "op" not in p, "API must not fabricate a pre-discount price"


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


# ── GET /filters — filter-sidebar metadata ────────────────────────────────

def test_get_filters_endpoint_returns_complete_metadata(client):
    """Verify GET /filters returns categories, brands, strain_types, effects,
    ranges, and on_sale_count — everything the storefront sidebar needs.
    """
    response = client.get("/filters")
    assert response.status_code == 200
    data = response.json()
    for key in (
        "categories", "brands", "strain_types", "effects",
        "price_range", "thc_pct_range", "thc_mg_range",
        "on_sale_count", "total",
    ):
        assert key in data, f"missing key: {key}"

    assert data["total"] == 217
    assert len(data["categories"]) == 8  # Flower / Vape / Edibles / etc.
    assert len(data["strain_types"]) >= 3  # Indica / Sativa / Hybrid at minimum

    # Categories are sorted by descending count (most populous first).
    counts = [c["count"] for c in data["categories"]]
    assert counts == sorted(counts, reverse=True), "categories must be sorted desc by count"

    # Each filter item carries name + count.
    for cat in data["categories"]:
        assert isinstance(cat["name"], str) and cat["name"]
        assert isinstance(cat["count"], int) and cat["count"] >= 0

    # Price/THC ranges are well-formed floats.
    pr = data["price_range"]
    assert pr["min"] >= 0 and pr["max"] >= pr["min"]


# ── /chat with manual_filters ─────────────────────────────────────────────

def test_chat_injects_manual_filters_as_system_signal(client):
    """Sidebar state in `manual_filters` becomes a low-priority system message.

    Distinct from `removed_filters` (which forces an LLM acknowledgment):
    `manual_filters` is passive context — the AI should be aware of the
    sidebar narrowing but not announce it back to the customer.
    """
    captured = {}

    def fake_get_recommendation(history, user_message, product_manager, **kwargs):
        captured["history"] = history
        return "Sure, here's a recommendation."

    with patch("backend.main.get_recommendation", side_effect=fake_get_recommendation):
        response = client.post(
            "/chat",
            json={
                "session_id": "test-mf",
                "messages": [],
                "is_beginner": False,
                "user_message": "what do you have?",
                "manual_filters": {
                    "category": "Flower",
                    "strain_type": ["Sativa"],
                    "on_sale": True,
                },
            },
        )
    assert response.status_code == 200

    # The injected system message should describe the sidebar state and
    # explicitly NOT pose as a user message.
    signals = [
        msg for msg in captured["history"]
        if msg.get("role") == "system" and "[UI CONTEXT]" in msg.get("content", "")
    ]
    assert len(signals) == 1, f"expected 1 manual_filters signal, got {signals}"
    content = signals[0]["content"]
    assert "category=Flower" in content
    assert "strain_type=Sativa" in content
    assert "on_sale=True" in content


def test_chat_skips_manual_filters_injection_when_empty(client):
    """No `manual_filters` payload → no UI CONTEXT system message added."""
    captured = {}

    def fake_get_recommendation(history, user_message, product_manager, **kwargs):
        captured["history"] = history
        return "Hi!"

    with patch("backend.main.get_recommendation", side_effect=fake_get_recommendation):
        client.post(
            "/chat",
            json={
                "session_id": "test-no-mf",
                "messages": [],
                "is_beginner": False,
                "user_message": "What do you have?",
            },
        )

    assert not any(
        "[UI CONTEXT]" in msg.get("content", "")
        for msg in captured["history"]
    )


# ── /chat with compare_product_ids ────────────────────────────────────────

def test_chat_injects_compare_by_id_signal(client):
    """`compare_product_ids: [a, b, c]` injects a COMPARE_BY_ID system message
    that instructs the LLM to use get_product_details, not smart_search.
    """
    captured = {}

    def fake_get_recommendation(history, user_message, product_manager, **kwargs):
        captured["history"] = history
        return "Comparison coming up."

    with patch("backend.main.get_recommendation", side_effect=fake_get_recommendation):
        response = client.post(
            "/chat",
            json={
                "session_id": "test-cmp",
                "messages": [],
                "is_beginner": False,
                "user_message": "Please compare these products: A, B, C.",
                "compare_product_ids": [101, 202, 303],
            },
        )

    assert response.status_code == 200
    signals = [
        msg for msg in captured["history"]
        if msg.get("role") == "system" and "COMPARE_BY_ID:" in msg.get("content", "")
    ]
    assert len(signals) == 1, f"expected 1 compare-by-id signal, got {signals}"
    content = signals[0]["content"]
    # All three IDs must appear and instruct get_product_details usage.
    assert "101" in content and "202" in content and "303" in content
    assert "get_product_details" in content
    # Must explicitly tell the LLM not to use smart_search this turn.
    assert "smart_search" in content.lower()


# ── /chat/stream — typed SSE protocol ─────────────────────────────────────

def test_chat_stream_simple_greeting_emits_one_chunk_and_done(client):
    """Greeting fast path: single chunk + [DONE], no ui_action/spoken events."""
    response = client.post(
        "/chat/stream",
        json={
            "session_id": "stream-greet",
            "messages": [],
            "is_beginner": False,
            "user_message": "hi",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("text/event-stream")
    body = response.text
    assert "data: {" in body  # at least one chunk event
    assert "data: [DONE]" in body
    assert "event: ui_action" not in body  # no smart_search → no ui_action
    assert "event: spoken" not in body


def test_chat_stream_emits_ui_action_when_search_runs(client):
    """When the LLM stream resolves a smart_search via trace, the endpoint
    emits an `event: ui_action` event BEFORE the text chunks and an
    `event: spoken` event after the reply is complete.
    """
    # Stub the stream generator to populate the trace mid-iteration just
    # like the real one does after agent-loop tool execution.
    def fake_stream(history, user_message, product_manager, **kwargs):
        trace = kwargs.get("trace")
        if trace is not None:
            trace["profile"] = {}
            trace["last_smart_search"] = {
                "args": {"category": "Flower", "strain_type": "Sativa"},
                "result": {
                    "products": [
                        {"id": 1, "s": "Test Sativa Flower", "cat": "Flower"},
                    ],
                    "total": 1,
                },
            }
        yield "Test Sativa Flower is great."

    with patch("backend.main.get_recommendation_stream", side_effect=fake_stream):
        response = client.post(
            "/chat/stream",
            json={
                "session_id": "stream-search",
                "messages": [],
                "is_beginner": False,
                "user_message": "sativa flower",
            },
        )

    assert response.status_code == 200
    body = response.text
    # ui_action event present and contains the expected filter payload.
    assert "event: ui_action" in body
    assert "\"strain_type\":\"Sativa\"" in body or "\"strain_type\": \"Sativa\"" in body
    # ui_action's picks field must be empty under the spoken-driven scheme
    # (picks arrive via a separate `picks` event after the reply finishes).
    assert "\"picks\":[]" in body
    # spoken event fires after we scan the reply for product names.
    assert "event: spoken" in body
    # picks event fires after spoken when at least one product was named.
    assert "event: picks" in body
    # The picks payload must contain a pick_reason for the spoken product.
    assert "pick_reason" in body
    # Reply text appears in chunk(s).
    assert "Test Sativa Flower" in body
    # Terminator present.
    assert "data: [DONE]" in body


def test_chat_stream_skips_picks_event_when_reply_mentions_no_products(client):
    """No product name in the reply → no `event: picks` (and no `event: spoken`).

    Lock the contract: the Top Pick row should NOT be populated when the AI
    never names a product (e.g. info-gathering follow-ups after a search).
    """
    def fake_stream(history, user_message, product_manager, **kwargs):
        trace = kwargs.get("trace")
        if trace is not None:
            trace["profile"] = {}
            trace["last_smart_search"] = {
                "args": {"category": "Flower"},
                "result": {
                    "products": [
                        {"id": 1, "s": "Test Sativa Flower", "cat": "Flower"},
                    ],
                    "total": 1,
                },
            }
        yield "Want something calming or energizing?"

    with patch("backend.main.get_recommendation_stream", side_effect=fake_stream):
        response = client.post(
            "/chat/stream",
            json={
                "session_id": "stream-no-mention",
                "messages": [],
                "is_beginner": False,
                "user_message": "what should I get",
            },
        )

    assert response.status_code == 200
    body = response.text
    assert "event: ui_action" in body
    assert "event: spoken" not in body
    assert "event: picks" not in body
    assert "data: [DONE]" in body


def test_chat_stream_with_compare_product_ids_injects_signal(client):
    """/chat/stream honors compare_product_ids the same way /chat does."""
    captured = {}

    def fake_stream(history, user_message, product_manager, **kwargs):
        captured["history"] = history
        yield "stub"

    with patch("backend.main.get_recommendation_stream", side_effect=fake_stream):
        client.post(
            "/chat/stream",
            json={
                "session_id": "stream-cmp",
                "messages": [],
                "is_beginner": False,
                "user_message": "Compare these.",
                "compare_product_ids": [10, 20],
            },
        )

    assert any(
        "COMPARE_BY_ID:" in msg.get("content", "")
        for msg in captured["history"]
    )
