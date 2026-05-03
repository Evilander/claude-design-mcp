"""Claude API integration for claude-design-mcp.

Wraps Anthropic's async client. The DESIGN_SYSTEM_PROMPT is sent with
``cache_control: {"type": "ephemeral"}`` so it is paid for once per ~5-minute
window and reused across all subsequent calls — keeping iteration cheap.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from anthropic.types import Message, MessageParam

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

# Generous max_tokens — designs are large (HTML + inline CSS often exceeds
# 4k tokens). Anthropic clamps this server-side based on the model.
MAX_TOKENS = 16000

# Hard cap on a single API call. Designs aren't worth waiting forever for.
DEFAULT_REQUEST_TIMEOUT_S = 180.0

# Caps on the metadata block we accept from the model. These prevent a
# prompt-injected response from ballooning the SQLite row.
_META_STRING_MAX = 8 * 1024
_META_LIST_MAX = 32
_META_DEPTH_MAX = 8

# Cap on per-design HTML we forward into a multi-design prompt (extract_system).
# 8000 chars ≈ 2k tokens; 10 designs × 2k = 20k tokens budget for inputs.
_EXTRACT_HTML_PER_DESIGN_MAX = 8000


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


# ---------------------------------------------------------------------------
# Designer
# ---------------------------------------------------------------------------


class DesignerError(RuntimeError):
    """Raised when the model returns something we can't parse."""


class Designer:
    """High-level wrapper around Anthropic's async client for design generation."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        fast_model: str | None = None,
        best_model: str | None = None,
        max_tokens: int = MAX_TOKENS,
        request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise DesignerError(
                "ANTHROPIC_API_KEY is not set. Add it to your shell environment "
                "or a .env file next to the studio root."
            )
        self._client = AsyncAnthropic(api_key=key, timeout=request_timeout_s, max_retries=2)
        # Re-read env on construction so .env edits / monkeypatches take effect.
        self._fast_model = fast_model or _env_model_fast()
        self._best_model = best_model or _env_model_best()
        self._max_tokens = max_tokens

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
    ) -> list[DesignDraft]:
        """Generate `count` variants in parallel."""
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

        return await asyncio.gather(*(one(i) for i in range(count)))

    async def extract_system(
        self, *, designs: list[dict], tier: str = "fast"
    ) -> dict[str, Any]:
        """Return a parsed design-system JSON object."""
        # Cap each design's HTML so a few large designs can't blow the prompt.
        capped = [
            {**d, "html": (d.get("html") or "")[:_EXTRACT_HTML_PER_DESIGN_MAX]}
            for d in designs
        ]
        user_msg = prompts.extract_system_user_prompt(designs=capped)
        # System extraction returns *only* JSON — bypass the HTML parser.
        message = await self._raw_call(model=self._pick_model(tier), user=user_msg)
        text = _join_text(message)
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
        # _clamp_metadata caps strings, list lengths, and depth; the recursive
        # walk is bounded by those caps regardless of input size.
        return _clamp_metadata(parsed)

    async def apply_system(
        self,
        *,
        system: dict,
        brief: str,
        mode: str,
        tier: str = "fast",
    ) -> DesignDraft:
        user_msg = prompts.apply_system_user_prompt(system=system, brief=brief, mode=mode)
        return await self._call(model=self._pick_model(tier), user=user_msg)

    # -- Internals ---------------------------------------------------------

    def _pick_model(self, tier: str) -> str:
        return self._best_model if tier == "best" else self._fast_model

    async def _call(self, *, model: str, user: str) -> DesignDraft:
        message = await self._raw_call(model=model, user=user)
        text = _join_text(message)
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

        usage = message.usage
        return DesignDraft(
            html=html,
            metadata=metadata,
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            input_tokens=usage.input_tokens or 0,
            output_tokens=usage.output_tokens or 0,
            model=model,
            warnings=warnings,
        )

    async def _raw_call(self, *, model: str, user: str) -> Message:
        # System prompt is sent as a list with cache_control so subsequent calls
        # within ~5 minutes of each other read the cache instead of paying again.
        system_block = [
            {
                "type": "text",
                "text": prompts.DESIGN_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        messages: list[MessageParam] = [{"role": "user", "content": user}]
        try:
            return await self._client.messages.create(
                model=model,
                max_tokens=self._max_tokens,
                system=system_block,  # type: ignore[arg-type]  # SDK accepts list-of-blocks
                messages=messages,
            )
        except AuthenticationError as e:
            raise DesignerError(
                "Anthropic authentication failed. Check that ANTHROPIC_API_KEY is "
                "valid and not expired."
            ) from e
        except RateLimitError as e:
            raise DesignerError(
                "Anthropic rate limit hit. Wait a few seconds and retry, or lower "
                "`count` on design_variants."
            ) from e
        except BadRequestError as e:
            # 400 covers: insufficient credits, invalid model id, invalid params.
            msg = _extract_api_message(e) or str(e)
            raise DesignerError(f"Anthropic rejected the request: {msg}") from e
        except APITimeoutError as e:
            raise DesignerError(
                f"Anthropic API timed out after {self._client.timeout}s. "
                "Try the `fast` tier or a tighter brief."
            ) from e
        except APIConnectionError as e:
            raise DesignerError(
                "Could not reach the Anthropic API. Check your network connection "
                "and any proxy/VPN settings."
            ) from e
        except APIStatusError as e:
            msg = _extract_api_message(e) or str(e)
            raise DesignerError(
                f"Anthropic API error (status {e.status_code}): {msg}"
            ) from e


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _join_text(message: Any) -> str:
    """Concatenate all text content blocks from a Messages API response."""
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        # Anthropic SDK returns typed content blocks; text blocks have .text.
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


# CRLF-tolerant fences: many sources emit \r\n.
_HTML_FENCE_RE = re.compile(r"```(?:html|HTML)[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)
_JSON_FENCE_RE = re.compile(r"```(?:json|JSON)[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)
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


def _extract_api_message(err: APIStatusError) -> str | None:
    """Pull the human-readable message out of an Anthropic error response.

    Narrowly catches the attribute-shape errors we know can happen when the
    SDK changes its body representation; anything else propagates so it gets
    logged at the caller boundary instead of being silently swallowed.
    """
    try:
        body = getattr(err, "body", None) or {}
        if isinstance(body, dict):
            inner = body.get("error") or {}
            if isinstance(inner, dict):
                msg = inner.get("message")
                if isinstance(msg, str):
                    return msg
        msg = getattr(err, "message", None)
        if isinstance(msg, str):
            return msg
    except (AttributeError, TypeError, KeyError) as e:
        print(
            f"[claude-design-mcp] _extract_api_message: {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
    return None


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
        # Cap key set count too — same _META_LIST_MAX.
        keys = list(value.keys())[:_META_LIST_MAX]
        return {str(k)[:128]: _clamp_metadata(value[k], _depth + 1) for k in keys}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    # Anything else (sets, custom objects) becomes a truncated repr.
    return repr(value)[:_META_STRING_MAX]
