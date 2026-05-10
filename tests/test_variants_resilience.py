"""Partial-success behavior for design_variants."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_design import server
from claude_design.designer import DesignDraft, Designer, DesignerError, VariantDraftResult
from claude_design.models import DesignVariantsInput


def _draft(title: str) -> DesignDraft:
    return DesignDraft(
        html=f"<!doctype html><html><head><title>{title}</title></head><body>{title}</body></html>",
        metadata={
            "title": title,
            "summary": f"{title} summary",
            "palette": ["#111111"],
            "fonts": ["Inter"],
            "tokens": {},
            "moves": ["focused layout"],
            "notes": "ok",
        },
        model="test-model",
    )


@pytest.mark.asyncio
async def test_designer_variants_preserves_partial_successes(monkeypatch):
    async def fake_call(self, *, model, user):  # noqa: ARG001
        if "variant 2 of 3" in user:
            raise DesignerError("rate limited")
        return _draft("variant")

    monkeypatch.setattr(Designer, "_call", fake_call)

    results = await Designer(query_timeout_s=1).variants(
        count=3,
        dimension="mood",
        base_brief="Dashboard for partial variant resilience",
        base_html=None,
        base_meta=None,
    )

    assert [r.ok for r in results] == [True, False, True]
    assert results[1].index == 1
    assert "rate limited" in (results[1].error or "")


@pytest.mark.asyncio
async def test_design_variants_persists_successes_and_reports_failures(monkeypatch):
    class FakeDesigner:
        async def variants(self, **kwargs):  # noqa: ARG002
            return [
                VariantDraftResult(index=0, draft=_draft("first")),
                VariantDraftResult(index=1, error="DesignerError: rate limited"),
                VariantDraftResult(index=2, draft=_draft("third")),
            ]

    monkeypatch.setattr(server, "designer", lambda: FakeDesigner())

    params = DesignVariantsInput(
        brief="Design a dense operations dashboard for resilience testing",
        count=3,
    )
    body = json.loads(await server.design_variants(params))

    assert body["count"] == 2
    assert body["partial"] is True
    assert body["requested_count"] == 3
    assert body["failed_count"] == 1
    assert body["failures"] == [{"index": 2, "error": "DesignerError: rate limited"}]
    assert [v["title"] for v in body["variants"]] == ["first", "third"]
    assert all(Path(v["html_path"]).exists() for v in body["variants"])


@pytest.mark.asyncio
async def test_design_variants_reports_all_failed_batches(monkeypatch):
    class FakeDesigner:
        async def variants(self, **kwargs):  # noqa: ARG002
            return [
                VariantDraftResult(index=0, error="DesignerError: first failed"),
                VariantDraftResult(index=1, error="DesignerError: second failed"),
            ]

    monkeypatch.setattr(server, "designer", lambda: FakeDesigner())

    params = DesignVariantsInput(
        brief="Design a dense operations dashboard for all-failed variant testing",
        count=2,
    )
    body = json.loads(await server.design_variants(params))

    assert "error" in body
    assert "All 2 variants failed" in body["error"]
    assert "#1: DesignerError: first failed" in body["error"]
