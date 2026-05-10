"""Claude Agent SDK integration for claude-design-mcp.

This module routes design generation through ``claude_agent_sdk.query()``,
which spawns the local ``claude`` CLI as a subprocess. That means design
calls inherit *whatever* OAuth login Claude Code is currently using —
no ``ANTHROPIC_API_KEY`` needed, no separate billing pool, no extra
credential management. If you can run ``claude`` interactively, this
package can call Claude.

We deliberately disable Claude Code's tool surface for these calls
(``tools=[]``, ``permission_mode="dontAsk"``,
``max_turns=1``) so a design generation is exactly that — one turn of
text-out, no filesystem access, no shell, no MCP recursion.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    CLIConnectionError,
    CLINotFoundError,
    ResultMessage,
    TextBlock,
    query,
)

from . import prompts

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hardcoded fallbacks. The actual model used is resolved per-construction
# from the env so .env edits / monkeypatches take effect without re-import.
_DEFAULT_FAST_FALLBACK = "claude-sonnet-4-6"
_DEFAULT_BEST_FALLBACK = "claude-opus-4-7"


def _env_model_fast() -> str:
    return os.environ.get("CLAUDE_DESIGN_MODEL") or _DEFAULT_FAST_FALLBACK


def _env_model_best() -> str:
    return os.environ.get("CLAUDE_DESIGN_MODEL_OPUS") or _DEFAULT_BEST_FALLBACK


# Public aliases retained for callers that imported the constant directly.
DEFAULT_MODEL_FAST = _env_model_fast()
DEFAULT_MODEL_BEST = _env_model_best()

# Caps on the metadata block we accept from the model. These prevent a
# prompt-injected response from ballooning the SQLite row.
_META_STRING_MAX = 8 * 1024
_META_LIST_MAX = 32
_META_DEPTH_MAX = 8

# Cap on per-design HTML we forward into a multi-design prompt (extract_system).
# 8000 chars ≈ 2k tokens; 10 designs × 2k = 20k tokens budget for inputs.
_EXTRACT_HTML_PER_DESIGN_MAX = 8000

# Wall-clock cap on a single SDK query. Designs can be slow, but waiting
# forever on a stuck CLI subprocess is worse than failing fast.
DEFAULT_QUERY_TIMEOUT_S = 240.0
DEFAULT_MAX_BUFFER_SIZE = 8 * 1024 * 1024

_ALLOWED_EFFORTS = {"low", "medium", "high", "max"}


def _env_effort() -> str | None:
    raw = (os.environ.get("CLAUDE_DESIGN_EFFORT") or "low").strip().lower()
    if raw in {"", "none", "off", "0", "false", "no"}:
        return None
    if raw not in _ALLOWED_EFFORTS:
        return "low"
    return raw


def _env_thinking() -> dict[str, str] | None:
    raw = (os.environ.get("CLAUDE_DESIGN_THINKING") or "disabled").strip().lower()
    if raw in {"", "none", "off"}:
        return None
    if raw in {"adaptive", "auto"}:
        return {"type": "adaptive"}
    if raw in {"disabled", "0", "false", "no"}:
        return {"type": "disabled"}
    return {"type": "disabled"}


def _env_max_buffer_size() -> int:
    raw = os.environ.get("CLAUDE_DESIGN_MAX_BUFFER_BYTES")
    if not raw:
        return DEFAULT_MAX_BUFFER_SIZE
    try:
        return max(1024 * 1024, int(raw))
    except ValueError:
        return DEFAULT_MAX_BUFFER_SIZE


def _env_cli_path() -> str | None:
    raw = (os.environ.get("CLAUDE_DESIGN_CLI_PATH") or "").strip()
    if raw:
        return raw
    return shutil.which("claude") or shutil.which("claude.exe")


# Env vars that force the `claude` CLI off OAuth and onto an API/provider path.
# Setting any of these in the parent shell would mean every design call gets
# billed against an API account (or a third-party provider) instead of the
# user's logged-in Claude Code session. claude-design-mcp is documented as
# OAuth-only, so we scrub them before spawning the subprocess. Users who
# actually want the API/provider path can set CLAUDE_DESIGN_ALLOW_API_KEY=1.
_AUTH_OVERRIDE_ENV_VARS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)


def _allow_api_key_override() -> bool:
    raw = (os.environ.get("CLAUDE_DESIGN_ALLOW_API_KEY") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def auth_override_state() -> dict[str, Any]:
    """Report which auth-override env vars are set in the parent process.

    Used by `--check` to warn operators that an inherited API key would
    silently route through API billing if the scrub were disabled.
    """
    present = [name for name in _AUTH_OVERRIDE_ENV_VARS if os.environ.get(name)]
    return {
        "present": present,
        "scrub_enabled": not _allow_api_key_override(),
        "allow_override_env": "CLAUDE_DESIGN_ALLOW_API_KEY",
    }


def _build_oauth_safe_env() -> dict[str, str]:
    """Copy os.environ minus any var that would force the CLI off OAuth.

    If ``CLAUDE_DESIGN_ALLOW_API_KEY=1`` is set we pass the env through
    unchanged so power users on API/Bedrock/Vertex still work.

    NOTE: This dict is what ``ClaudeAgentOptions.env`` receives, but the SDK
    *merges* it on top of inherited ``os.environ`` rather than replacing —
    so passing this alone does NOT remove an inherited ANTHROPIC_API_KEY.
    The actual scrub happens in :func:`_oauth_only_environ`, which the
    Designer uses as a process-level context manager around the SDK call.
    """
    env = {k: v for k, v in os.environ.items() if v is not None}
    if _allow_api_key_override():
        return env
    for name in _AUTH_OVERRIDE_ENV_VARS:
        env.pop(name, None)
    return env


from contextlib import contextmanager  # noqa: E402 — grouped with helpers above


@contextmanager
def _oauth_only_environ():
    """Temporarily remove auth-override env vars from ``os.environ``.

    The Claude Agent SDK merges its ``options.env`` on top of the inherited
    process environment, so an ANTHROPIC_API_KEY set in the parent still
    flows into the spawned ``claude`` CLI even if we omit it from
    ``options.env``. Mutating the real process env for the duration of the
    SDK call is the only reliable way to force OAuth.

    The mutation is restored on exit, including on exception. Concurrent
    SDK calls in the same process share the same env, which is fine here
    because we always restore the same key set — the worst that can happen
    is one call restores an already-restored key.
    """
    if _allow_api_key_override():
        yield
        return
    saved: dict[str, str] = {}
    try:
        for name in _AUTH_OVERRIDE_ENV_VARS:
            if name in os.environ:
                saved[name] = os.environ.pop(name)
        yield
    finally:
        for name, value in saved.items():
            os.environ[name] = value


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DesignDraft:
    """A parsed design returned by the designer."""

    html: str
    metadata: dict[str, Any]
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cost_usd: float | None = None
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def title(self) -> str | None:
        return self.metadata.get("title")

    @property
    def summary(self) -> str | None:
        return self.metadata.get("summary")

    @property
    def palette(self) -> list[str]:
        return list(self.metadata.get("palette") or [])

    @property
    def fonts(self) -> list[str]:
        return list(self.metadata.get("fonts") or [])

    @property
    def tokens(self) -> dict[str, Any]:
        return dict(self.metadata.get("tokens") or {})

    @property
    def moves(self) -> list[str]:
        return list(self.metadata.get("moves") or [])

    @property
    def notes(self) -> str | None:
        return self.metadata.get("notes")


@dataclass
class VariantDraftResult:
    """One requested variant: either a parsed draft or a caller-safe error."""

    index: int
    draft: DesignDraft | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.draft is not None


# ---------------------------------------------------------------------------
# Designer
# ---------------------------------------------------------------------------


class DesignerError(RuntimeError):
    """Raised when the model returns something we can't parse, or auth fails."""


# Map ``AssistantMessage.error`` enum values to caller-friendly explanations.
_ASSISTANT_ERROR_MESSAGES = {
    "authentication_failed": (
        "Claude Code isn't logged in. Run `claude login` (or open Claude Code "
        "and sign in) to grant the design MCP an OAuth session."
    ),
    "billing_error": (
        "Claude Code reported a billing problem. Check your subscription / "
        "credit balance in the Claude account that's currently logged in."
    ),
    "rate_limit": (
        "Claude rate-limited the request. Wait a few seconds and retry, or "
        "lower `count` on design_variants."
    ),
    "invalid_request": (
        "Claude rejected the request. Try a more concrete brief or smaller scope."
    ),
    "server_error": "Claude server error; try again shortly.",
    "unknown": "Claude returned an unspecified error; check the MCP server log.",
}


class Designer:
    """High-level wrapper around the Claude Agent SDK for design generation.

    Construction does no I/O — instances are cheap. The first call to a
    public method spawns the ``claude`` CLI subprocess.
    """

    def __init__(
        self,
        *,
        fast_model: str | None = None,
        best_model: str | None = None,
        query_timeout_s: float = DEFAULT_QUERY_TIMEOUT_S,
    ) -> None:
        # Re-read env on construction so .env edits / monkeypatches take effect.
        self._fast_model = fast_model or _env_model_fast()
        self._best_model = best_model or _env_model_best()
        self._query_timeout_s = query_timeout_s

    # -- Public surface ----------------------------------------------------

    async def generate_design(
        self,
        *,
        brief: str,
        mode: str,
        viewport: str,
        tier: str = "fast",
        references: list[dict] | None = None,
    ) -> DesignDraft:
        user_msg = prompts.create_user_prompt(
            brief=brief, mode=mode, viewport=viewport, references=references or []
        )
        return await self._call(model=self._pick_model(tier), user=user_msg)

    async def iterate_design(
        self,
        *,
        prior_html: str,
        prior_meta: dict,
        instructions: str,
        tier: str = "fast",
    ) -> DesignDraft:
        user_msg = prompts.iterate_user_prompt(
            prior_html=prior_html, prior_meta=prior_meta, instructions=instructions
        )
        return await self._call(model=self._pick_model(tier), user=user_msg)

    async def variants(
        self,
        *,
        count: int,
        dimension: str,
        base_brief: str | None,
        base_html: str | None,
        base_meta: dict | None,
        tier: str = "fast",
    ) -> list[VariantDraftResult]:
        """Generate `count` variants in parallel, preserving partial successes."""

        async def one(i: int) -> DesignDraft:
            user_msg = prompts.variants_user_prompt(
                base_brief=base_brief,
                base_html=base_html,
                base_meta=base_meta,
                dimension=dimension,
                index=i,
                count=count,
            )
            return await self._call(model=self._pick_model(tier), user=user_msg)

        results = await asyncio.gather(
            *(one(i) for i in range(count)),
            return_exceptions=True,
        )
        out: list[VariantDraftResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                out.append(
                    VariantDraftResult(
                        index=i,
                        error=f"{type(result).__name__}: {result}",
                    )
                )
            else:
                out.append(VariantDraftResult(index=i, draft=result))
        return out

    async def extract_system(
        self, *, designs: list[dict], tier: str = "fast"
    ) -> dict[str, Any]:
        """Return a parsed design-system JSON object."""
        capped = [
            {**d, "html": (d.get("html") or "")[:_EXTRACT_HTML_PER_DESIGN_MAX]}
            for d in designs
        ]
        user_msg = prompts.extract_system_user_prompt(designs=capped)
        text, _ = await self._raw_query(
            model=self._pick_model(tier), user=user_msg
        )
        json_block = _extract_json_block(text)
        if not json_block:
            raise DesignerError(
                "Design-system extraction did not return a JSON block. "
                "Try again with fewer or smaller source designs."
            )
        try:
            parsed = json.loads(json_block)
        except json.JSONDecodeError as e:
            raise DesignerError(f"Extracted JSON was not valid: {e}") from e
        return _clamp_metadata(parsed)

    async def apply_system(
        self,
        *,
        system: dict,
        brief: str,
        mode: str,
        tier: str = "fast",
    ) -> DesignDraft:
        user_msg = prompts.apply_system_user_prompt(
            system=system, brief=brief, mode=mode
        )
        return await self._call(model=self._pick_model(tier), user=user_msg)

    # -- Internals ---------------------------------------------------------

    def _pick_model(self, tier: str) -> str:
        return self._best_model if tier == "best" else self._fast_model

    async def _call(self, *, model: str, user: str) -> DesignDraft:
        text, telemetry = await self._raw_query(model=model, user=user)
        html = _extract_html_block(text)
        meta_raw = _extract_json_block(text)
        warnings: list[str] = []
        if not html:
            raise DesignerError(
                "Model did not return an HTML block. Got:\n" + text[:600]
            )
        if meta_raw:
            try:
                metadata = _clamp_metadata(json.loads(meta_raw))
            except json.JSONDecodeError as e:
                msg = f"metadata JSON parse failed: {e}; using empty metadata"
                print(f"[claude-design-mcp] {msg}", file=sys.stderr, flush=True)
                metadata = {}
                warnings.append(msg)
        else:
            warnings.append("model did not return a metadata JSON block")
            metadata = {}

        return DesignDraft(
            html=html,
            metadata=metadata,
            cache_creation_tokens=telemetry.get("cache_creation_input_tokens", 0),
            cache_read_tokens=telemetry.get("cache_read_input_tokens", 0),
            input_tokens=telemetry.get("input_tokens", 0),
            output_tokens=telemetry.get("output_tokens", 0),
            cost_usd=telemetry.get("cost_usd"),
            duration_ms=telemetry.get("duration_ms", 0),
            model=telemetry.get("model") or model,
            warnings=warnings,
        )

    async def _raw_query(
        self, *, model: str, user: str
    ) -> tuple[str, dict[str, Any]]:
        """Run a single one-turn query through the SDK.

        Returns (joined text, telemetry-dict). Raises ``DesignerError`` for
        every failure mode the caller might care about, with a message that
        guides the operator toward a fix.
        """
        stderr_lines: list[str] = []

        def _capture_stderr(line: str) -> None:
            if len(stderr_lines) < 20:
                stderr_lines.append(line[:1000])

        def _log_stderr() -> None:
            if stderr_lines:
                print(
                    "[claude-design-mcp] Claude CLI stderr:\n"
                    + "\n".join(stderr_lines),
                    file=sys.stderr,
                    flush=True,
                )

        options = ClaudeAgentOptions(
            model=model,
            system_prompt=prompts.DESIGN_SYSTEM_PROMPT,
            tools=[],
            allowed_tools=[],
            permission_mode="dontAsk",
            max_turns=1,
            cli_path=_env_cli_path(),
            # Scrub ANTHROPIC_API_KEY / auth overrides so the spawned CLI
            # falls back to its OAuth session. This is the documented
            # contract — README states "ANTHROPIC_API_KEY is ignored" —
            # and without this scrub the CLI silently bills via API mode.
            env=_build_oauth_safe_env(),
            extra_args={
                "disable-slash-commands": None,
                "no-session-persistence": None,
            },
            max_buffer_size=_env_max_buffer_size(),
            stderr=_capture_stderr,
            thinking=_env_thinking(),
            effort=_env_effort(),
            # Don't pollute the design call with settings, skills, agents, or
            # tools the user has configured for normal Claude Code use.
            skills=[],
            setting_sources=[],
        )

        text_chunks: list[str] = []
        telemetry: dict[str, Any] = {}
        assistant_seen = False

        async def _consume() -> None:
            nonlocal assistant_seen
            # Hold an explicit handle to the async generator so we can
            # aclose() it on cancellation / timeout. Without this, the
            # underlying `claude` CLI subprocess can survive the parent
            # task being cancelled — accumulating zombies over time.
            agen = query(prompt=user, options=options)
            try:
                async for msg in agen:
                    if isinstance(msg, AssistantMessage):
                        await _handle_assistant(msg)
                    elif isinstance(msg, ResultMessage):
                        if msg.is_error:
                            joined = "; ".join(msg.errors or []) or "unknown error"
                            raise DesignerError(f"Claude returned an error: {joined}")
                        if msg.usage:
                            telemetry.update(msg.usage)
                        if msg.total_cost_usd is not None:
                            telemetry["cost_usd"] = msg.total_cost_usd
                        telemetry["duration_ms"] = msg.duration_ms
            finally:
                try:
                    await agen.aclose()
                except Exception:  # noqa: BLE001 — best-effort cleanup
                    pass

        async def _handle_assistant(msg: AssistantMessage) -> None:
            nonlocal assistant_seen
            assistant_seen = True
            if msg.error:
                raise DesignerError(
                    _ASSISTANT_ERROR_MESSAGES.get(
                        msg.error, _ASSISTANT_ERROR_MESSAGES["unknown"]
                    )
                )
            for block in msg.content:
                if isinstance(block, TextBlock):
                    text_chunks.append(block.text)
            if msg.usage:
                telemetry.update(msg.usage)
            if msg.model:
                telemetry.setdefault("model", msg.model)

        try:
            # Scrub auth-override env vars from os.environ for the duration of
            # the SDK call so the spawned `claude` CLI falls back to OAuth.
            # The SDK merges options.env *on top of* inherited os.environ, so
            # we must mutate the real process env — restoring on exit. The
            # mutation window is the SDK call only; concurrent callers in the
            # same process share the same env, which is fine because we
            # always restore the same key set.
            with _oauth_only_environ():
                await asyncio.wait_for(_consume(), timeout=self._query_timeout_s)
        except asyncio.TimeoutError as e:
            raise DesignerError(
                f"Claude did not respond within {self._query_timeout_s:.0f}s. "
                "Try the `fast` tier or a tighter brief."
            ) from e
        except CLINotFoundError as e:
            raise DesignerError(
                "The `claude` CLI was not found on PATH. Install Claude Code "
                "(https://docs.claude.com/en/docs/claude-code/) and run "
                "`claude login` to authorize it."
            ) from e
        except CLIConnectionError as e:
            raise DesignerError(
                "Could not connect to the `claude` CLI subprocess. Check that "
                "Claude Code launches normally with `claude --version`."
            ) from e
        except DesignerError:
            raise
        except ClaudeSDKError as e:
            _log_stderr()
            raise DesignerError(
                f"Claude Agent SDK error: {type(e).__name__}: {e}"
            ) from e
        except Exception as e:
            _log_stderr()
            raise DesignerError(
                f"Claude Agent SDK error: {type(e).__name__}: {e}"
            ) from e

        if not assistant_seen:
            raise DesignerError(
                "Claude returned no assistant response. The CLI may have "
                "rejected the prompt or the OAuth session expired — try "
                "`claude login` and retry."
            )
        return "".join(text_chunks), telemetry


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


# CRLF-tolerant fences: many sources emit \r\n.
_HTML_FENCE_RE = re.compile(
    r"```(?:html|HTML)[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL
)
_JSON_FENCE_RE = re.compile(
    r"```(?:json|JSON)[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL
)
# Match a full document either via <!doctype html>...</html> or a bare <html>...</html>.
_DOC_RE = re.compile(
    r"(<!doctype\s+html[^>]*>\s*<html[^>]*>.*?</html>|<html[^>]*>.*?</html>)",
    re.DOTALL | re.IGNORECASE,
)


def _extract_html_block(text: str) -> str | None:
    """Return the most likely full HTML document from ``text``.

    Strategy:
      1) Prefer the longest ``html`` fenced block — handles models that emit
         a tiny example fence followed by the real document.
      2) Fall back to a raw ``<!doctype html>...</html>`` or ``<html>...</html>``.
    """
    matches = _HTML_FENCE_RE.findall(text)
    if matches:
        return max(matches, key=len).strip()
    m = _DOC_RE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _extract_json_block(text: str) -> str | None:
    matches = _JSON_FENCE_RE.findall(text)
    if not matches:
        return None
    # Prefer the *last* JSON block — designs put metadata after the HTML.
    return matches[-1].strip()


def _clamp_metadata(value: Any, _depth: int = 0) -> Any:
    """Recursively cap string lengths, list lengths, and nesting depth.

    Defends downstream storage against pathologically large model output (e.g.
    a prompt-injection that asks for a 5MB ``notes`` field).
    """
    if _depth >= _META_DEPTH_MAX:
        return None
    if isinstance(value, str):
        return value[:_META_STRING_MAX]
    if isinstance(value, list):
        return [_clamp_metadata(v, _depth + 1) for v in value[:_META_LIST_MAX]]
    if isinstance(value, dict):
        keys = list(value.keys())[:_META_LIST_MAX]
        return {str(k)[:128]: _clamp_metadata(value[k], _depth + 1) for k in keys}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return repr(value)[:_META_STRING_MAX]
