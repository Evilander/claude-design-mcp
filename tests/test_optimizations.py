"""Tests for the optimization pass: connection caching, CTE lineage, list+1."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_design.studio import Studio


@pytest.fixture()
def studio(tmp_path: Path) -> Studio:
    return Studio(tmp_path / "studio")


def _seed(studio: Studio, n: int) -> list[str]:
    from claude_design.studio import DesignRecord
    ids: list[str] = []
    for i in range(n):
        rid = studio.new_id()
        ids.append(rid)
        path = studio.write_html(rid, "<!doctype html><html><body>x</body></html>")
        rec = DesignRecord(
            id=rid,
            name=f"d{i}",
            parent_id=ids[i - 1] if i > 0 else None,
            brief="b",
            mode="auto",
            tier="fast",
            viewport="desktop",
            title=f"t{i}",
            summary=None,
            html_path=str(path),
        )
        studio.insert_design(rec)
    return ids


def test_connection_is_cached_and_reused(studio: Studio):
    # Trigger a few queries; the cached connection object should be the same
    # across them — that's the optimization.
    studio.list_designs(limit=1)
    first = studio._cached_conn
    assert first is not None
    studio.list_designs(limit=1)
    studio.get_design("nonexistent")
    second = studio._cached_conn
    assert first is second


def test_close_drops_connection(studio: Studio):
    studio.list_designs(limit=1)
    assert studio._cached_conn is not None
    studio.close()
    assert studio._cached_conn is None
    # close() is idempotent
    studio.close()


def test_lineage_cte_returns_full_chain(studio: Studio):
    ids = _seed(studio, 5)  # d0 ← d1 ← d2 ← d3 ← d4
    chain = studio.lineage(ids[-1])
    assert [r.id for r in chain] == ids


def test_lineage_cte_depth_bounded(studio: Studio):
    # Build a 3-deep chain, ask for max_depth=1: only the leaf + its parent.
    ids = _seed(studio, 3)
    chain = studio.lineage(ids[-1], max_depth=1)
    assert len(chain) == 2
    assert chain[-1].id == ids[-1]


def test_list_designs_has_more_signal(studio: Studio):
    _seed(studio, 7)
    rows, has_more = studio.list_designs(limit=3, offset=0)
    assert len(rows) == 3 and has_more is True
    rows, has_more = studio.list_designs(limit=3, offset=3)
    assert len(rows) == 3 and has_more is True
    rows, has_more = studio.list_designs(limit=3, offset=6)
    assert len(rows) == 1 and has_more is False
