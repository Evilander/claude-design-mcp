"""Path-traversal protection on design_export's target_dir."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_design.server import _resolve_export_dir, studio


def test_resolve_export_dir_default_returns_studio_exports():
    assert _resolve_export_dir(None) == studio().exports_dir


def test_resolve_export_dir_rejects_relative():
    with pytest.raises(ValueError, match="absolute"):
        _resolve_export_dir("relative/path")


def test_resolve_export_dir_rejects_filesystem_root():
    if os.name == "nt":
        with pytest.raises(ValueError):
            _resolve_export_dir("C:\\")
    else:
        with pytest.raises(ValueError):
            _resolve_export_dir("/")


def test_resolve_export_dir_rejects_unc_path():
    with pytest.raises(ValueError, match="UNC"):
        _resolve_export_dir(r"\\server\share\evil")


@pytest.mark.skipif(os.name != "nt", reason="Windows-only system path test")
def test_resolve_export_dir_rejects_windows_system_root():
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    with pytest.raises(ValueError, match="protected"):
        _resolve_export_dir(str(Path(sysroot) / "Temp" / "x"))


def test_resolve_export_dir_accepts_safe_absolute(tmp_path: Path):
    out = _resolve_export_dir(str(tmp_path / "exports"))
    assert out == (tmp_path / "exports").resolve()
