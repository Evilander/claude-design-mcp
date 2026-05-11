"""Verify the OAuth-routed Designer behaves correctly without an API key."""

from __future__ import annotations

import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from claude_design import designer as designer_module
from claude_design.designer import (
    Designer,
    DesignerError,
    _ASSISTANT_ERROR_MESSAGES,
)
from claude_design.prompts import DESIGN_SYSTEM_PROMPT


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


def test_designer_prefers_path_claude_cli_when_env_absent(monkeypatch):
    monkeypatch.delenv("CLAUDE_DESIGN_CLI_PATH", raising=False)
    monkeypatch.setattr(
        designer_module.shutil,
        "which",
        lambda name: "/usr/local/bin/claude" if name == "claude" else None,
    )

    assert designer_module._env_cli_path() == "/usr/local/bin/claude"


def test_configured_cli_path_must_be_absolute(monkeypatch):
    monkeypatch.setenv("CLAUDE_DESIGN_CLI_PATH", ".\\fake-claude.exe")

    with pytest.raises(ValueError, match="absolute path"):
        designer_module._env_cli_path()


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


@pytest.mark.asyncio
async def test_designer_sdk_options_are_oauth_only_and_toolless(monkeypatch):
    captured = {}

    async def fake_query(*, prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        yield AssistantMessage(
            content=[
                TextBlock(
                    "```html\n<!doctype html><html><head><title>x</title></head>"
                    "<body>x</body></html>\n```\n```json\n"
                    '{"title":"x","summary":"x","palette":[],"fonts":[],'
                    '"tokens":{},"moves":[],"notes":"x"}\n```'
                )
            ],
            model="test-model",
            usage={"input_tokens": 1, "output_tokens": 1},
        )
        yield ResultMessage(
            subtype="success",
            duration_ms=10,
            duration_api_ms=10,
            is_error=False,
            num_turns=1,
            session_id="session",
            usage={"input_tokens": 1, "output_tokens": 1},
        )

    monkeypatch.setattr(designer_module, "query", fake_query)
    monkeypatch.delenv("CLAUDE_DESIGN_CLI_PATH", raising=False)

    draft = await Designer(query_timeout_s=5).generate_design(
        brief="Dashboard for OAuth design quality checks",
        mode="dashboard",
        viewport="desktop",
    )

    options = captured["options"]
    assert draft.html.startswith("<!doctype html>")
    assert options.tools == []
    assert options.allowed_tools == []
    assert options.disallowed_tools == ["*"]
    assert callable(options.can_use_tool)
    assert options.permission_mode == "dontAsk"
    assert options.extra_args == {
        "disable-slash-commands": None,
        "no-session-persistence": None,
    }
    assert options.setting_sources == []
    assert options.skills == []
    assert options.thinking == {"type": "disabled"}
    assert options.effort == "low"
    assert callable(options.stderr)


@pytest.mark.asyncio
async def test_oauth_environ_scrub_is_serialized(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test")
    observed = []

    async def scrubbed_window():
        async with designer_module._oauth_only_environ():
            observed.append("ANTHROPIC_API_KEY" not in designer_module.os.environ)
            await asyncio.sleep(0.01)
            observed.append("ANTHROPIC_API_KEY" not in designer_module.os.environ)

    await asyncio.gather(scrubbed_window(), scrubbed_window())

    assert observed == [True, True, True, True]
    assert designer_module.os.environ["ANTHROPIC_API_KEY"] == "sk-ant-api03-test"


def test_design_system_prompt_is_latency_bounded():
    # 6 KB is the cached-prompt budget: large enough to carry the aesthetic
    # stance + banned-reflex sections (added 2026-05-10 after the adversarial
    # review flagged generic AI output), small enough to keep first-token
    # latency under the 5s target on the fast tier.
    assert len(DESIGN_SYSTEM_PROMPT) < 6000
    assert "target 12-18 KB" in DESIGN_SYSTEM_PROMPT
    assert "220 lines" in DESIGN_SYSTEM_PROMPT


def test_design_system_prompt_carries_aesthetic_stance_and_banned_reflexes():
    """The post-adversary upgrade must keep the positive posture + the explicit AI-tell ban."""
    # Positive aesthetic stance — required, not optional
    assert "Aesthetic stance" in DESIGN_SYSTEM_PROMPT
    assert "posture" in DESIGN_SYSTEM_PROMPT
    # One element must dominate
    assert "one element on the page is the hero" in DESIGN_SYSTEM_PROMPT
    # Banned reflexes section catches the specific AI-tell patterns
    assert "Banned reflexes" in DESIGN_SYSTEM_PROMPT
    assert "01 / 02 / 03" in DESIGN_SYSTEM_PROMPT
    assert "Equal-weight four-quadrant" in DESIGN_SYSTEM_PROMPT
    assert "fill the row" in DESIGN_SYSTEM_PROMPT


def test_design_system_prompt_preserves_oauth_story():
    assert "Claude Code OAuth" in DESIGN_SYSTEM_PROMPT
    assert "claude login" in DESIGN_SYSTEM_PROMPT
    assert "API-key setup" in DESIGN_SYSTEM_PROMPT


def test_design_system_prompt_marks_unprovided_operational_data_as_demo():
    assert "sample/demo data" in DESIGN_SYSTEM_PROMPT
    assert "Do not invent real personal" in DESIGN_SYSTEM_PROMPT
