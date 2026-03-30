"""Shared pytest fixtures for AI Budtender tests."""

import json
import pytest
from fastapi.testclient import TestClient
from backend.main import app, _product_manager
from backend.config import DB_PATH


@pytest.fixture(scope="session", autouse=True)
def load_products_once():
    """Load product DB once for the entire test session."""
    _product_manager.load(DB_PATH)


@pytest.fixture(scope="session")
def client():
    """Shared FastAPI TestClient for integration tests."""
    return TestClient(app)


@pytest.fixture
def mock_openai_reply(monkeypatch):
    """
    Factory fixture: returns a helper that patches get_recommendation
    with a fixed reply string.
    Usage: reply_fn = mock_openai_reply("Hello!"); reply_fn()
    """
    def factory(reply_text: str):
        monkeypatch.setattr(
            "backend.main.get_recommendation",
            lambda history, user_msg, products_json: reply_text,
        )
    return factory


@pytest.fixture
def sample_products_json():
    """Return a minimal compact JSON product list for unit tests."""
    products = [
        {
            "id": 1, "s": "Blue Dream", "c": "Brand A",
            "cat": "Flower", "sub": "Premium Flower",
            "t": "Hybrid", "thc": "22%", "p": 45.0, "pr": "Mid",
            "f": "Relaxed,Happy", "sc": "Relaxation", "tod": "Anytime",
            "xl": "Intermediate", "cm": "Smoke", "on": "5-10 min", "dur": "2-3 hrs",
        },
        {
            "id": 2, "s": "Granddaddy Purple", "c": "Brand B",
            "cat": "Flower", "sub": "Premium Flower",
            "t": "Indica", "thc": "18%", "p": 38.0, "pr": "Budget",
            "f": "Sleepy,Relaxed", "sc": "Sleep", "tod": "Nighttime",
            "xl": "Beginner", "cm": "Smoke", "on": "5-10 min", "dur": "3-4 hrs",
        },
    ]
    return json.dumps(products)
