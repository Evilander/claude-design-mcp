"""Contact-sheet generation tests (no Playwright, no API)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_design.preview import build_index
from claude_design.studio import DesignRecord, Studio


@pytest.fixture()
def studio(tmp_path: Path) -> Studio:
    return Studio(tmp_path / "studio")


def _record(studio: Studio, **overrides) -> DesignRecord:
    rid = studio.new_id()
    html_path = studio.write_html(rid, "<!doctype html><html></html>")
    rec = DesignRecord(
        id=rid,
        name=overrides.get("name", f"design-{rid}"),
        parent_id=None,
        brief="brief",
        mode="auto",
        tier="fast",
        viewport="desktop",
        title=overrides.get("title", "Title"),
        summary=overrides.get("summary", "summary"),
        palette=overrides.get("palette", ["#fff", "#000"]),
        fonts=["Inter"],
        tokens={},
        moves=overrides.get("moves", ["one", "two"]),
        notes=None,
        html_path=str(html_path),
        render_path=overrides.get("render_path"),
    )
    studio.insert_design(rec)
    return rec


def test_build_index_writes_file(studio: Studio):
    a = _record(studio)
    out = build_index(studio, [a])
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert a.id in body
    assert "studio" in body.lower()
    assert '<header class="card-header">' in body


def test_build_index_handles_empty_list(studio: Studio):
    out = build_index(studio, [])
    body = out.read_text(encoding="utf-8")
    assert "No designs yet" in body


def test_build_index_escapes_hostile_titles(studio: Studio):
    a = _record(
        studio,
        title="</style><script>alert(1)</script>",
        summary="<img src=x onerror=alert(1)>",
        palette=["javascript:alert(1)"],
        moves=["</li><script>alert(1)</script>"],
    )
    out = build_index(studio, [a])
    body = out.read_text(encoding="utf-8")
    # The literal hostile sequences must NOT appear unescaped.
    assert "<script>alert(1)</script>" not in body
    assert "<img src=x onerror" not in body
    # But they should be present as escaped text.
    assert "&lt;script&gt;" in body or "&lt;img" in body


def test_build_index_uses_render_when_present(studio: Studio, tmp_path: Path):
    render = tmp_path / "shot.png"
    render.write_bytes(b"\x89PNG\r\n\x1a\n")
    a = _record(studio, render_path=str(render))
    body = build_index(studio, [a]).read_text(encoding="utf-8")
    assert "<img" in body
    assert str(render).replace("\\", "/") in body or render.name in body
