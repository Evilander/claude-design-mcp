"""Tests for the @_tool decorator: timeout, ValueError, and crash trap.

A regression here would silently kill the MCP transport or leak tracebacks
to the caller. We dummy out a coroutine and exercise each branch.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest

if sys.version_info < (3, 11):  # pragma: no cover - exercised only on 3.10
    from exceptiongroup import BaseExceptionGroup  # noqa: A004

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


@pytest.mark.asyncio
async def test_tool_contains_base_exception_group():
    """The Claude Agent SDK's anyio task groups / cancel scopes raise a
    BaseExceptionGroup on 3.11+ when a child op errors. That group is NOT an
    Exception subclass, so an `except Exception` wrapper would let it escape
    into the MCP server's shared request task group and tear down the whole
    stdio transport -> every concurrent call gets `-32000: Connection closed`.
    The wrapper must contain it as an error payload for THIS call only.
    """

    @_tool
    async def boom(_):
        raise BaseExceptionGroup(
            "sdk subprocess scope",
            [RuntimeError("internal: secret token=xyz"), asyncio.CancelledError()],
        )

    # Must NOT raise — must return a contained error payload.
    out = json.loads(await boom(None))
    assert "error" in out
    # Caller must never see raw internals.
    assert "secret token=xyz" not in out["error"]


@pytest.mark.asyncio
async def test_tool_reraises_genuine_cancellation():
    """A bare CancelledError (cooperative shutdown / client disconnect) must
    propagate, not be swallowed into a normal result."""

    @_tool
    async def cancelled(_):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cancelled(None)


@pytest.mark.asyncio
async def test_tool_reraises_pure_cancellation_group():
    """A BaseExceptionGroup that is *only* cancellation (no real error) should
    re-raise as cancellation so cooperative shutdown still unwinds cleanly."""

    @_tool
    async def cancelled_group(_):
        raise BaseExceptionGroup("cancel", [asyncio.CancelledError()])

    with pytest.raises(asyncio.CancelledError):
        await cancelled_group(None)
