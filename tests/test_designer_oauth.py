"""Verify the OAuth-routed Designer behaves correctly without an API key."""

from __future__ import annotations

import os

import pytest

from claude_design.designer import (
    Designer,
    DesignerError,
    _ASSISTANT_ERROR_MESSAGES,
)


def test_designer_constructs_without_api_key(monkeypatch):
    """No ANTHROPIC_API_KEY in the environment, but Designer() must not raise."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = Designer()
    # Default models still resolve from env or fallbacks.
    assert d._fast_model
    assert d._best_model


def test_designer_picks_env_models(monkeypatch):
    monkeypatch.setenv("CLAUDE_DESIGN_MODEL", "claude-sonnet-4-6-test")
    monkeypatch.setenv("CLAUDE_DESIGN_MODEL_OPUS", "claude-opus-4-7-test")
    d = Designer()
    assert d._fast_model == "claude-sonnet-4-6-test"
    assert d._best_model == "claude-opus-4-7-test"


def test_assistant_error_messages_cover_all_known_subtypes():
    """Every typed AssistantMessage.error literal must have a friendly message."""
    expected = {
        "authentication_failed",
        "billing_error",
        "rate_limit",
        "invalid_request",
        "server_error",
        "unknown",
    }
    assert expected == set(_ASSISTANT_ERROR_MESSAGES)


def test_assistant_error_messages_are_actionable():
    # Each message should mention what to do next (login / retry / check log).
    actionable_keywords = ("login", "retry", "wait", "check", "Try", "smaller")
    for key, msg in _ASSISTANT_ERROR_MESSAGES.items():
        assert any(k.lower() in msg.lower() for k in actionable_keywords), (
            f"{key!r} message is not actionable: {msg!r}"
        )


def test_designer_error_is_runtime_error_subclass():
    # Caller code (server.py @_tool wrapper) catches DesignerError specifically.
    assert issubclass(DesignerError, RuntimeError)
