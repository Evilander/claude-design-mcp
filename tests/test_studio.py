"""Persistence-layer tests. No API, no Playwright — just SQLite + filesystem."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_design.studio import DesignRecord, Studio, SystemRecord


@pytest.fixture()
def studio(tmp_path: Path) -> Studio:
    return Studio(tmp_path / "studio")


def _make_record(studio: Studio, **overrides) -> DesignRecord:
    rid = studio.new_id()
    html_path = studio.write_html(rid, "<!doctype html><html><body>x</body></html>")
    rec = DesignRecord(
        id=rid,
        name=overrides.get("name", f"design-{rid}"),
        parent_id=overrides.get("parent_id"),
        brief=overrides.get("brief", "test brief"),
        mode=overrides.get("mode", "auto"),
        tier=overrides.get("tier", "fast"),
        viewport=overrides.get("viewport", "desktop"),
        title=overrides.get("title", "Title"),
        summary=overrides.get("summary", "summary"),
        palette=overrides.get("palette", ["#fff", "#000"]),
        fonts=overrides.get("fonts", ["Inter"]),
        tokens=overrides.get("tokens", {"radius": "6px"}),
        moves=overrides.get("moves", ["editorial layout"]),
        notes=overrides.get("notes"),
        html_path=str(html_path),
        render_path=overrides.get("render_path"),
        iteration_of=overrides.get("iteration_of"),
        instructions=overrides.get("instructions"),
    )
    studio.insert_design(rec)
    return rec


def test_new_id_is_unique(studio: Studio):
    ids = {studio.new_id() for _ in range(50)}
    assert len(ids) == 50


def test_insert_and_get_design_round_trip(studio: Studio):
    rec = _make_record(studio)
    fetched = studio.get_design(rec.id)
    assert fetched is not None
    assert fetched.id == rec.id
    assert fetched.palette == ["#fff", "#000"]
    assert fetched.tokens == {"radius": "6px"}


def test_get_design_html_returns_file_contents(studio: Studio):
    rec = _make_record(studio)
    html = studio.get_design_html(rec.id)
    assert html is not None and "<!doctype html>" in html


def test_get_design_returns_none_for_missing_id(studio: Studio):
    assert studio.get_design("nonexistent") is None
    assert studio.get_design_html("nonexistent") is None


def test_lineage_walks_parent_chain(studio: Studio):
    a = _make_record(studio)
    b = _make_record(studio, parent_id=a.id, iteration_of=a.id)
    c = _make_record(studio, parent_id=b.id, iteration_of=b.id)
    chain = studio.lineage(c.id)
    assert [r.id for r in chain] == [a.id, b.id, c.id]


def test_lineage_handles_cycle_safely(studio: Studio):
    # Construct a cycle directly via SQL — paranoid defense against bad data.
    a = _make_record(studio)
    b = _make_record(studio, parent_id=a.id)
    # Force a self-cycle on a
    with studio._conn() as conn:
        conn.execute("UPDATE designs SET parent_id = ? WHERE id = ?", (b.id, a.id))
    chain = studio.lineage(b.id)
    # Must terminate, even though a→b→a→b...
    assert len(chain) <= 3
    assert b.id in {r.id for r in chain}


def test_list_designs_pagination_and_filter(studio: Studio):
    for i in range(5):
        _make_record(studio, name=f"design-{i}", title=f"Title {i}")
    records, has_more = studio.list_designs(limit=2, offset=0)
    assert len(records) == 2
    assert has_more is True

    records, has_more = studio.list_designs(limit=2, offset=4)
    assert len(records) == 1
    assert has_more is False

    records, has_more = studio.list_designs(limit=10, offset=0, name_contains="Title 3")
    assert len(records) == 1
    assert records[0].title == "Title 3"
    assert has_more is False


def test_update_render_path(studio: Studio):
    rec = _make_record(studio)
    studio.update_render_path(rec.id, "/tmp/x.png")
    assert studio.get_design(rec.id).render_path == "/tmp/x.png"


def test_system_round_trip(studio: Studio):
    rec = _make_record(studio)
    sys_rec = SystemRecord(
        id=studio.new_id(),
        name="bone",
        summary="paper-and-ink",
        tokens={"color": {"bg": "#fafaf7"}},
        components=[{"name": "btn", "html": "<button/>"}],
        principles=["restraint over decoration"],
        source_ids=[rec.id],
    )
    studio.insert_system(sys_rec)
    fetched = studio.get_system(sys_rec.id)
    assert fetched is not None
    assert fetched.tokens == {"color": {"bg": "#fafaf7"}}
    assert fetched.components[0]["name"] == "btn"
    assert fetched.source_ids == [rec.id]


def test_file_url_round_trip(studio: Studio, tmp_path: Path):
    target = tmp_path / "studio" / "designs" / "abc.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    url = studio.file_url(str(target))
    assert url is not None
    assert url.startswith("file:///")


def test_file_url_handles_none(studio: Studio):
    assert studio.file_url(None) is None


def test_to_summary_excludes_html_body(studio: Studio):
    rec = _make_record(studio)
    summary = rec.to_summary()
    assert "html" not in summary  # only path, never body
    assert summary["html_path"] == rec.html_path
    # Round-trip serializable
    json.dumps(summary, default=str)
