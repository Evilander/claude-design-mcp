"""OAuth-only production-readiness checks."""

from __future__ import annotations

import json
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
    monkeypatch.setattr(server.Renderer, "is_available", staticmethod(lambda: False))
    monkeypatch.setattr(
        server,
        "_claude_cli_status",
        lambda: {"ok": True, "line": "Claude Code 2.1.126 (/usr/local/bin/claude)"},
    )
    server._reset_singletons()

    report = server._build_check_report()
    encoded = json.dumps(report)

    assert report["ok"] is True
    assert report["authentication"] == {
        "mode": "claude-code-oauth",
        "api_key_required": False,
        "setup": "Run `claude login`; no ANTHROPIC_API_KEY is used.",
    }
    assert report["studio_init"]["ok"] is True
    assert "ANTHROPIC_API_KEY" in encoded
    assert "api_key_required" in encoded


def test_claude_cli_status_respects_configured_cli_path(monkeypatch):
    monkeypatch.setenv("CLAUDE_DESIGN_CLI_PATH", sys.executable)

    status = server._claude_cli_status()

    assert status["ok"] is True
    assert sys.executable in status["line"]


def test_claude_cli_status_reports_bad_configured_cli_path(monkeypatch):
    monkeypatch.setenv("CLAUDE_DESIGN_CLI_PATH", "/definitely/not/claude")

    status = server._claude_cli_status()

    assert status["ok"] is False
    assert "CLAUDE_DESIGN_CLI_PATH is set" in status["line"]
