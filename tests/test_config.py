"""Tests for backend/config.py configuration module."""

import os
import importlib
import pytest


def reload_config(env_overrides: dict = None):
    """Reload config module with optional environment variable overrides."""
    import backend.config as config_module
    original = {}
    if env_overrides:
        for key, val in env_overrides.items():
            original[key] = os.environ.get(key)
            os.environ[key] = val
    importlib.reload(config_module)
    return config_module, original


def restore_env(original: dict):
    """Restore original environment variables."""
    for key, val in original.items():
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


def test_config_defaults():
    """Verify default config values are correct when no env vars set."""
    import backend.config as config
    assert config.CSV_PATH == "data/NYE4.0_v3.csv"
    assert config.MAX_HISTORY_MESSAGES == 20
    assert config.MODEL_NAME == "gpt-4o-mini"
    assert isinstance(config.BEGINNER_THC_LIMITS, dict)
    assert config.BEGINNER_THC_LIMITS["edibles_mg"] == 5
    assert config.BEGINNER_THC_LIMITS["flower_percent"] == 20
    assert config.BEGINNER_THC_LIMITS["vaporizers_percent"] == 70


def test_config_env_override():
    """Verify that environment variables override default config values."""
    import backend.config as _
    config, original = reload_config({
        "CSV_PATH": "custom/path.csv",
        "MAX_HISTORY_MESSAGES": "10",
        "MODEL_NAME": "gpt-4o",
    })
    try:
        assert config.CSV_PATH == "custom/path.csv"
        assert config.MAX_HISTORY_MESSAGES == 10
        assert config.MODEL_NAME == "gpt-4o"
    finally:
        restore_env(original)
        reload_config()


def test_chat_request_model():
    """Verify ChatRequest model fields and validation."""
    from backend.models import ChatRequest, Message

    req = ChatRequest(
        session_id="abc-123",
        messages=[Message(role="user", content="Hello")],
        is_beginner=False,
        user_message="I need something to help me sleep.",
    )
    assert req.session_id == "abc-123"
    assert len(req.messages) == 1
    assert req.messages[0].role == "user"
    assert req.is_beginner is False
    assert "sleep" in req.user_message


def test_chat_request_model_defaults():
    """Verify ChatRequest default values."""
    from backend.models import ChatRequest

    req = ChatRequest(session_id="xyz", user_message="hi")
    assert req.messages == []
    assert req.is_beginner is False


def test_chat_response_model():
    """Verify ChatResponse model fields."""
    from backend.models import ChatResponse

    resp = ChatResponse(reply="Here is my recommendation.", session_id="abc-123", response_time_ms=42.5)
    assert resp.reply == "Here is my recommendation."
    assert resp.session_id == "abc-123"
    assert resp.response_time_ms == 42.5
