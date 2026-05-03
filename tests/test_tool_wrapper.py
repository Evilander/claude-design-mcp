"""Tests for the @_tool decorator: timeout, ValueError, and crash trap.

A regression here would silently kill the MCP transport or leak tracebacks
to the caller. We dummy out a coroutine and exercise each branch.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from claude_design.designer import DesignerError
from claude_design.server import _tool


@pytest.mark.asyncio
async def test_tool_wraps_designer_error():
    @_tool
    async def boom(_):
        raise DesignerError("api unhappy")

    out = json.loads(await boom(None))
    assert out == {"error": "api unhappy"}


@pytest.mark.asyncio
async def test_tool_wraps_value_error():
    @_tool
    async def boom(_):
        raise ValueError("bad path")

    out = json.loads(await boom(None))
    assert out == {"error": "bad path"}


@pytest.mark.asyncio
async def test_tool_traps_arbitrary_exception_without_leaking():
    @_tool
    async def boom(_):
        raise RuntimeError("internal: secret token=abc")

    out = json.loads(await boom(None))
    assert "error" in out
    # Caller must NOT see the raw exception text, ever.
    assert "secret token=abc" not in out["error"]
    assert "RuntimeError" in out["error"]


@pytest.mark.asyncio
async def test_tool_returns_timeout_error_on_long_run(monkeypatch):
    # Patch the constant so the test runs in milliseconds.
    monkeypatch.setattr("claude_design.server.TOOL_TIMEOUT_S", 0.1)

    @_tool
    async def slow(_):
        await asyncio.sleep(5)
        return "should not reach"

    out = json.loads(await slow(None))
    assert "timed out" in out["error"].lower()


@pytest.mark.asyncio
async def test_tool_passes_through_normal_return():
    @_tool
    async def ok(_):
        return '{"ok": true}'

    out = await ok(None)
    assert out == '{"ok": true}'
