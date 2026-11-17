from __future__ import annotations

import asyncio
import json
import subprocess
import time

import pytest

import claude_design.design_md as design_md
import claude_design.server as server
from claude_design.models import DesignValidateDesignMdInput


@pytest.mark.asyncio
async def test_validate_design_md_tool_returns_ok_true_when_cli_succeeds(
    monkeypatch, tmp_path
):
    path = tmp_path / "DESIGN.md"
    path.write_text("# DESIGN.md\n", encoding="utf-8")

    def fake_run(*args, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=["npx"],
            returncode=0,
            stdout="DESIGN.md lint passed\n",
            stderr="",
        )

    monkeypatch.setattr(design_md.subprocess, "run", fake_run)

    body = json.loads(
        await server.design_validate_design_md(
            DesignValidateDesignMdInput(design_md_path=str(path.resolve()))
        )
    )

    assert body["ok"] is True
    assert body["warnings"] == []
    assert body["errors"] == []
    assert body["wcag_failures"] == []
    assert "lint passed" in body["raw_output"]


def test_validate_design_md_via_cli_returns_null_when_npx_missing(monkeypatch, tmp_path):
    path = tmp_path / "DESIGN.md"
    path.write_text("# DESIGN.md\n", encoding="utf-8")

    def fake_run(*args, **kwargs):  # noqa: ARG001
        raise FileNotFoundError("npx")

    monkeypatch.setattr(design_md.subprocess, "run", fake_run)

    body = design_md.validate_design_md_via_cli(str(path))

    assert body["ok"] is None
    assert body["warnings"] == []
    assert body["errors"] == []
    assert body["wcag_failures"] == []
    assert "npx" in body["raw_output"]


def test_validate_design_md_via_cli_extracts_errors_and_wcag(monkeypatch, tmp_path):
    path = tmp_path / "DESIGN.md"
    path.write_text("# DESIGN.md\n", encoding="utf-8")

    def fake_run(*args, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=["npx"],
            returncode=1,
            stdout=(
                "Warning: missing optional component notes\n"
                "Error: section order is invalid\n"
                "WCAG AA contrast failure: fg on bg\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(design_md.subprocess, "run", fake_run)

    body = design_md.validate_design_md_via_cli(str(path))

    assert body["ok"] is False
    assert body["warnings"] == ["Warning: missing optional component notes"]
    assert body["errors"] == ["Error: section order is invalid"]
    assert body["wcag_failures"] == [{"message": "WCAG AA contrast failure: fg on bg"}]


@pytest.mark.asyncio
async def test_validate_design_md_tool_does_not_block_event_loop(monkeypatch, tmp_path):
    """Regression: a slow lint subprocess must not stall the asyncio loop that
    serves the JSON-RPC transport. Before the fix, the synchronous
    subprocess.run inside the async handler froze the loop for the duration of
    the lint, so a concurrent transport coroutine could not run and the client
    dropped the connection (-32000: Connection closed).

    We assert *concurrency* via wall-clock: a 0.4s blocking lint and a ~0.4s
    heartbeat that overlap finish in ~0.4s when the lint is offloaded to a
    thread, but serialize to ~0.8s when the lint blocks the loop. A 0.65s
    ceiling cleanly separates the two regimes.
    """
    path = tmp_path / "DESIGN.md"
    path.write_text("# DESIGN.md\n", encoding="utf-8")

    # Simulate a lint that takes a while (the real cost is the first-run npx
    # fetch). This is a *blocking* sleep, exactly like subprocess.run.
    def slow_blocking_run(*args, **kwargs):  # noqa: ARG001
        time.sleep(0.4)
        return subprocess.CompletedProcess(
            args=["npx"], returncode=0, stdout="DESIGN.md lint passed\n", stderr=""
        )

    monkeypatch.setattr(design_md.subprocess, "run", slow_blocking_run)

    async def heartbeat():
        # ~0.4s of cooperative work that can only overlap the lint if the loop
        # stays free while subprocess.run runs.
        for _ in range(20):
            await asyncio.sleep(0.02)

    validate = server.design_validate_design_md(
        DesignValidateDesignMdInput(design_md_path=str(path.resolve()))
    )
    start = time.perf_counter()
    result, _ = await asyncio.gather(validate, heartbeat())
    elapsed = time.perf_counter() - start

    body = json.loads(result)
    assert body["ok"] is True
    # Concurrent execution proves the loop stayed responsive during the lint.
    assert elapsed < 0.65, f"lint blocked the event loop (took {elapsed:.2f}s)"


@pytest.mark.asyncio
async def test_validate_design_md_tool_returns_structured_result_on_unexpected_error(
    monkeypatch, tmp_path
):
    """The handler must never let an exception escape: any failure yields the
    documented structured result with ok=None, not a raised exception."""
    path = tmp_path / "DESIGN.md"
    path.write_text("# DESIGN.md\n", encoding="utf-8")

    def exploding_run(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("unexpected npx explosion")

    monkeypatch.setattr(design_md.subprocess, "run", exploding_run)

    body = json.loads(
        await server.design_validate_design_md(
            DesignValidateDesignMdInput(design_md_path=str(path.resolve()))
        )
    )

    assert body["ok"] is None
    assert body["warnings"] == []
    assert body["errors"] == []
    assert body["wcag_failures"] == []
    assert "unexpected npx explosion" in body["raw_output"]
