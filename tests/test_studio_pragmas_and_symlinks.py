"""Verify SQLite WAL pragmas land + atomic write refuses symlinks."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_design.studio import Studio, _atomic_write_text


@pytest.fixture()
def studio(tmp_path: Path) -> Studio:
    return Studio(tmp_path / "studio")


def test_wal_journal_mode_applied(studio: Studio):
    with studio._conn() as c:
        mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_busy_timeout_applied(studio: Studio):
    with studio._conn() as c:
        bt = c.execute("PRAGMA busy_timeout").fetchone()[0]
    assert bt == 10000


def test_foreign_keys_enabled(studio: Studio):
    with studio._conn() as c:
        fk = c.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_atomic_write_refuses_existing_symlink(tmp_path: Path):
    # Skip the test cleanly on Windows non-dev installs where symlinks need admin.
    real = tmp_path / "real.txt"
    real.write_text("original", encoding="utf-8")
    target = tmp_path / "studio-file.txt"
    try:
        target.symlink_to(real)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"symlinks unavailable: {e}")

    _atomic_write_text(target, "new content")

    # The symlink should have been removed before the write — `target` is now
    # a regular file with the new content, and the original `real` is untouched.
    assert target.is_file()
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "new content"
    assert real.read_text(encoding="utf-8") == "original"


def test_atomic_write_creates_temp_with_unique_suffix(tmp_path: Path, monkeypatch):
    """Two concurrent writes to the same final path use distinct tmp paths."""
    target = tmp_path / "x.txt"
    seen = []
    real_replace = os.replace

    def fake_replace(src, dst):
        seen.append(str(src))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", fake_replace)
    _atomic_write_text(target, "a")
    _atomic_write_text(target, "b")
    assert len(seen) == 2
    assert seen[0] != seen[1]  # unique suffixes


def test_meta_refresh_stripped_by_inject_csp():
    from claude_design.studio import inject_csp

    hostile = (
        '<!doctype html><html><head>'
        '<meta http-equiv="refresh" content="0;url=https://attacker.example/">'
        '</head><body></body></html>'
    )
    out = inject_csp(hostile)
    assert "http-equiv=\"refresh\"" not in out
    assert "Content-Security-Policy" in out


def test_form_action_locked_down():
    from claude_design.studio import inject_csp

    out = inject_csp("<!doctype html><html><head></head><body></body></html>")
    assert "form-action 'none'" in out
