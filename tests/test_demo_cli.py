"""Fixture demo path for first-contact setup."""

from __future__ import annotations

import pytest

from claude_design import server


@pytest.mark.asyncio
async def test_run_demo_creates_fixture_designs_without_model_call(monkeypatch):
    monkeypatch.setattr(
        server.Renderer,
        "readiness",
        staticmethod(lambda: {"ready": False, "available": True}),
    )

    report = await server._run_demo()

    assert report["ok"] is True
    assert report["count"] == 3
    assert report["rendered"] is False
    assert len(report["designs"]) == 3
    for design in report["designs"]:
        assert design["html_path"]
        assert design["usage"]["model"] == "fixture-demo"
    assert report["preview_url"].startswith("file:///")
