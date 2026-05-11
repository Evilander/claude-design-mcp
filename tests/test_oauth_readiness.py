"""OAuth-only production-readiness checks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from claude_design import server


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_public_operator_guidance_never_asks_for_anthropic_api_key():
    """Docs and installer output must not contradict Claude Code OAuth auth."""
    forbidden_phrases = (
        "Set ANTHROPIC_API_KEY",
        "provide an API key",
        "requires an API key",
    )
    public_files = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "install.ps1",
        REPO_ROOT / "claude_desktop_config.example.json",
        REPO_ROOT / "src" / "claude_design" / "server.py",
        REPO_ROOT / "src" / "claude_design" / "designer.py",
    ]

    offenders = []
    for path in public_files:
        text = path.read_text(encoding="utf-8")
        if any(phrase in text for phrase in forbidden_phrases):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())

    assert offenders == []


def test_check_report_is_machine_readable_and_oauth_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", str(tmp_path / "studio"))
    # Start from a clean env so override detection is deterministic across hosts.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_USE_VERTEX", raising=False)
    monkeypatch.delenv("CLAUDE_DESIGN_ALLOW_API_KEY", raising=False)
    monkeypatch.setattr(
        server.Renderer,
        "readiness",
        staticmethod(lambda: {"ready": False, "available": True}),
    )
    monkeypatch.setattr(
        server,
        "_claude_cli_status",
        lambda: {"ok": True, "line": "Claude Code 2.1.126 (/usr/local/bin/claude)"},
    )
    server._reset_singletons()

    report = server._build_check_report()
    encoded = json.dumps(report)

    assert report["ok"] is True
    assert report["authentication"]["mode"] == "claude-code-oauth"
    assert report["authentication"]["api_key_required"] is False
    assert "ANTHROPIC_API_KEY" in report["authentication"]["setup"]
    assert report["authentication"]["env_overrides_present"] == []
    assert report["authentication"]["env_overrides_scrubbed"] is True
    assert report["authentication"]["preserve_overrides_env"] == "CLAUDE_DESIGN_ALLOW_API_KEY"
    assert report["studio_init"]["ok"] is True
    assert "ANTHROPIC_API_KEY" in encoded
    assert "api_key_required" in encoded


def test_check_report_warns_when_api_key_is_present(tmp_path, monkeypatch):
    """If ANTHROPIC_API_KEY is set in env, --check must surface that it was scrubbed."""
    monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test")
    monkeypatch.delenv("CLAUDE_DESIGN_ALLOW_API_KEY", raising=False)
    monkeypatch.setattr(
        server.Renderer,
        "readiness",
        staticmethod(lambda: {"ready": True, "available": True}),
    )
    monkeypatch.setattr(
        server,
        "_claude_cli_status",
        lambda: {"ok": True, "line": "Claude Code 2.1.126 (/usr/local/bin/claude)"},
    )
    server._reset_singletons()

    report = server._build_check_report()

    assert report["ok"] is True  # overall readiness unaffected
    assert "ANTHROPIC_API_KEY" in report["authentication"]["env_overrides_present"]
    assert report["authentication"]["env_overrides_scrubbed"] is True


def test_check_report_signals_preserved_override_when_allow_flag_set(tmp_path, monkeypatch):
    """Power users who set CLAUDE_DESIGN_ALLOW_API_KEY=1 should see the override is live."""
    monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test")
    monkeypatch.setenv("CLAUDE_DESIGN_ALLOW_API_KEY", "1")
    monkeypatch.setattr(
        server.Renderer,
        "readiness",
        staticmethod(lambda: {"ready": True, "available": True}),
    )
    monkeypatch.setattr(
        server,
        "_claude_cli_status",
        lambda: {"ok": True, "line": "Claude Code 2.1.126 (/usr/local/bin/claude)"},
    )
    server._reset_singletons()

    report = server._build_check_report()

    assert report["authentication"]["env_overrides_present"] == ["ANTHROPIC_API_KEY"]
    assert report["authentication"]["env_overrides_scrubbed"] is False


def test_resolve_studio_dir_exports_default_for_renderer(monkeypatch):
    monkeypatch.delenv("CLAUDE_DESIGN_STUDIO_DIR", raising=False)
    monkeypatch.setattr(server, "_can_create_under", lambda path: True)

    resolved = server._resolve_studio_dir()

    assert Path(os.environ["CLAUDE_DESIGN_STUDIO_DIR"]) == resolved
    assert resolved.name == "studio"
    assert resolved.parent.name == ".claude-design"


def test_claude_cli_status_respects_configured_cli_path(monkeypatch):
    monkeypatch.setenv("CLAUDE_DESIGN_CLI_PATH", sys.executable)

    status = server._claude_cli_status()

    assert status["ok"] is True
    assert sys.executable in status["line"]


def test_claude_cli_status_reports_bad_configured_cli_path(monkeypatch):
    monkeypatch.setenv("CLAUDE_DESIGN_CLI_PATH", "/definitely/not/claude")

    status = server._claude_cli_status()

    assert status["ok"] is False
    assert "CLAUDE_DESIGN_CLI_PATH must be an absolute executable path" in status["line"]


def test_render_readiness_error_names_temp_blocker():
    msg = server._render_readiness_error({
        "available": True,
        "temp_dir": {"ok": False, "path": "C:/Temp", "error": "Access denied"},
    })

    assert "C:/Temp" in msg
    assert "CLAUDE_DESIGN_PLAYWRIGHT_TMP" in msg


def test_render_readiness_error_names_missing_browser():
    msg = server._render_readiness_error({
        "available": True,
        "temp_dir": {"ok": True},
        "browsers": {"ok": False, "error": "Chromium missing", "hint": "install it"},
    })

    assert "Chromium missing" in msg
    assert "install it" in msg
