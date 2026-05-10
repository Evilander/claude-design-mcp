"""Verify the OAuth-safe env builder strips API/auth overrides before
spawning the `claude` CLI subprocess.

Background: when ANTHROPIC_API_KEY is set in the parent shell, the Claude CLI
silently prefers it over OAuth — every design call then bills against the API
account. The MCP is documented as OAuth-only, so designer._build_oauth_safe_env
must scrub these vars before they reach the subprocess.

These tests target the pure helpers (no subprocess), so they run in <100ms.
"""

from __future__ import annotations

from claude_design import designer


def _common_env(monkeypatch) -> None:
    # Some PATH-shaped vars the CLI relies on stay in env regardless of scrub.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/test")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\test")


def test_oauth_safe_env_strips_anthropic_api_key(monkeypatch):
    _common_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-secret")
    monkeypatch.delenv("CLAUDE_DESIGN_ALLOW_API_KEY", raising=False)

    env = designer._build_oauth_safe_env()

    assert "ANTHROPIC_API_KEY" not in env
    assert env.get("PATH") == "/usr/bin:/bin"  # unrelated vars survive


def test_oauth_safe_env_strips_auth_token_and_provider_overrides(monkeypatch):
    _common_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "alt-token")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("CLAUDE_CODE_USE_VERTEX", "1")
    monkeypatch.delenv("CLAUDE_DESIGN_ALLOW_API_KEY", raising=False)

    env = designer._build_oauth_safe_env()

    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "CLAUDE_CODE_USE_BEDROCK" not in env
    assert "CLAUDE_CODE_USE_VERTEX" not in env


def test_oauth_safe_env_preserves_api_key_when_opt_in_set(monkeypatch):
    """Power users on API/Bedrock/Vertex can keep their override active."""
    _common_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-secret")
    monkeypatch.setenv("CLAUDE_DESIGN_ALLOW_API_KEY", "1")

    env = designer._build_oauth_safe_env()

    assert env["ANTHROPIC_API_KEY"] == "sk-ant-api03-secret"


def test_oauth_safe_env_allow_flag_accepts_truthy_values(monkeypatch):
    for truthy in ("1", "true", "yes", "on", "TRUE", "Yes"):
        monkeypatch.setenv("CLAUDE_DESIGN_ALLOW_API_KEY", truthy)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-keep")
        env = designer._build_oauth_safe_env()
        assert env.get("ANTHROPIC_API_KEY") == "sk-keep", (
            f"value {truthy!r} should preserve override"
        )


def test_oauth_safe_env_allow_flag_rejects_falsy_values(monkeypatch):
    for falsy in ("", "0", "false", "no", "off", " "):
        monkeypatch.setenv("CLAUDE_DESIGN_ALLOW_API_KEY", falsy)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-drop")
        env = designer._build_oauth_safe_env()
        assert "ANTHROPIC_API_KEY" not in env, (
            f"value {falsy!r} should scrub the key"
        )


def test_auth_override_state_reports_scrub_when_no_opt_in(monkeypatch):
    _common_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-secret")
    monkeypatch.delenv("CLAUDE_DESIGN_ALLOW_API_KEY", raising=False)

    state = designer.auth_override_state()

    assert state["present"] == ["ANTHROPIC_API_KEY"]
    assert state["scrub_enabled"] is True
    assert state["allow_override_env"] == "CLAUDE_DESIGN_ALLOW_API_KEY"


def test_auth_override_state_reports_no_overrides_when_clean(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("CLAUDE_DESIGN_ALLOW_API_KEY", raising=False)

    state = designer.auth_override_state()

    assert state["present"] == []
    assert state["scrub_enabled"] is True
