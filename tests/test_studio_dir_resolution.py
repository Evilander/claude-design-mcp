"""Tests for _resolve_studio_dir env precedence + safety."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_design.server import _resolve_studio_dir, studio


def test_env_override_takes_effect(monkeypatch, tmp_path: Path):
    target = tmp_path / "elsewhere"
    monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", str(target))
    import claude_design.server as srv

    srv._reset_singletons()
    assert _resolve_studio_dir() == target.resolve()
    assert studio().root == target.resolve()


def test_filesystem_root_rejected(monkeypatch):
    if os.name == "nt":
        monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", "C:\\")
    else:
        monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", "/")
    with pytest.raises(ValueError, match="root"):
        _resolve_studio_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path")
def test_windows_system_root_rejected(monkeypatch):
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", str(Path(sysroot) / "Temp" / "x"))
    with pytest.raises(ValueError, match="protected"):
        _resolve_studio_dir()
