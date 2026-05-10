"""Renderer request allowlist tests."""

from __future__ import annotations

from pathlib import Path

from claude_design import renderer as renderer_module
from claude_design.renderer import (
    Renderer,
    _find_chromium_executable,
    _is_allowed_request_url,
    _sandbox_candidates,
)


def test_renderer_allows_local_and_exact_https_hosts():
    assert _is_allowed_request_url("file:///B:/studio/designs/abc.html") is True
    assert _is_allowed_request_url("data:image/png;base64,abc") is True
    assert _is_allowed_request_url("https://fonts.googleapis.com/css2?family=Inter") is True
    assert _is_allowed_request_url("https://images.unsplash.com/photo.jpg") is True


def test_renderer_blocks_substring_host_bypass():
    assert _is_allowed_request_url("https://evil.test/?next=fonts.googleapis.com") is False
    assert _is_allowed_request_url("https://fonts.googleapis.com.evil.test/css") is False
    assert _is_allowed_request_url("http://fonts.googleapis.com/css2?family=Inter") is False


def test_find_chromium_executable_recurses_install_root(tmp_path: Path):
    exe = tmp_path / "chromium_headless_shell-1208" / "chrome-headless-shell-win64"
    exe.mkdir(parents=True)
    target = exe / "chrome-headless-shell.exe"
    target.write_text("", encoding="utf-8")

    assert _find_chromium_executable(tmp_path) == str(target)


def test_runtime_environment_falls_back_to_studio_tmp(monkeypatch, tmp_path: Path):
    calls = []

    def fake_probe(parent=None):
        calls.append(parent)
        if parent is None:
            return {"ok": False, "path": "C:/bad-temp", "error": "denied"}
        return {"ok": True, "path": str(parent)}

    monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(renderer_module, "_probe_tmp_dir", fake_probe)

    status = renderer_module._configure_runtime_environment()

    assert status["temp_dir"]["ok"] is True
    assert status["temp_dir"]["preferred_used"] is True
    assert calls[1] == tmp_path / "studio" / "tmp-render"


def test_browser_status_uses_configured_browser_path_without_dry_run(
    monkeypatch,
    tmp_path: Path,
):
    exe_dir = tmp_path / "chromium-1208" / "chrome-win64"
    exe_dir.mkdir(parents=True)
    exe = exe_dir / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))

    def forbidden_run(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("dry-run should not be called when executable is present")

    monkeypatch.setattr(renderer_module.subprocess, "run", forbidden_run)

    assert Renderer._browser_install_status() == {"ok": True, "executable": str(exe)}


def test_sandbox_policy_env(monkeypatch):
    monkeypatch.delenv("CLAUDE_DESIGN_CHROMIUM_SANDBOX", raising=False)
    assert _sandbox_candidates() == [True, False]

    monkeypatch.setenv("CLAUDE_DESIGN_CHROMIUM_SANDBOX", "1")
    assert _sandbox_candidates() == [True]

    monkeypatch.setenv("CLAUDE_DESIGN_CHROMIUM_SANDBOX", "0")
    assert _sandbox_candidates() == [False]
