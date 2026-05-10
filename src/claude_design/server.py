"""FastMCP entry point for claude-design-mcp.

Run via ``python -m claude_design`` or the ``claude-design-mcp`` console script.
The server exposes tools that route design requests through Claude's frontier
visual-design capability and stores everything in a local studio.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .designer import Designer, DesignDraft, DesignerError, auth_override_state
from .models import (
    DesignApplySystemInput,
    DesignCreateInput,
    DesignExportInput,
    DesignExtractSystemInput,
    DesignGetInput,
    DesignIterateInput,
    DesignListInput,
    DesignPreviewInput,
    DesignRenderInput,
    DesignVariantsInput,
    ResponseFormat,
)
from .preview import build_components_page, build_index
from .renderer import Renderer
from .studio import (
    DesignRecord,
    Studio,
    SystemRecord,
    _atomic_write_text,
    inject_csp,
)

# ---------------------------------------------------------------------------
# Bootstrap — .env is loaded in claude_design/__init__.py before any submodule
# imports so module-scope env reads (e.g. designer.DEFAULT_MODEL_FAST) see it.
# ---------------------------------------------------------------------------

_PKG_ROOT = Path(__file__).resolve().parent.parent.parent

CHARACTER_LIMIT = 25_000

# Hard cap on the wall-clock duration of any single tool call. Sized to be
# more generous than the Anthropic client timeout so transient retries fit.
TOOL_TIMEOUT_S = 240.0

# Roots we refuse to use as studio or export targets. Short-list of high-
# regret prefixes; the goal is "stop accidents and dumb prompt injection",
# not "prevent a determined attacker who already controls argv/env".
_FORBIDDEN_ROOTS: tuple[Path, ...] = tuple(
    Path(p).resolve()
    for p in (
        os.environ.get("SystemRoot", r"C:\Windows"),
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.path.expanduser("~/.ssh"),
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
    )
)


def _auto_render_default() -> bool:
    """Decide whether to auto-render. Defaults to true only if rendering is ready."""
    flag = (os.environ.get("CLAUDE_DESIGN_AUTO_RENDER") or "auto").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    return bool(Renderer.readiness().get("ready"))


def _resolve_studio_dir() -> Path:
    """Re-read the studio dir env each time the lazy singleton initializes."""
    raw = os.environ.get("CLAUDE_DESIGN_STUDIO_DIR") or str(_PKG_ROOT / "studio")
    resolved = Path(raw).expanduser().resolve()
    _assert_path_safe(resolved, label="CLAUDE_DESIGN_STUDIO_DIR")
    if not (os.environ.get("CLAUDE_DESIGN_STUDIO_DIR") or "").strip():
        os.environ["CLAUDE_DESIGN_STUDIO_DIR"] = str(resolved)
    return resolved


def _assert_path_safe(p: Path, *, label: str) -> None:
    """Refuse paths that touch known-sensitive system locations.

    The "filesystem root" check is path-portable: on POSIX a single-part
    path is ``/``; on Windows a single-part path is the drive root like
    ``C:\\``. Either way, ``len(parts) <= 1`` means there's nothing below
    the root, so a write would clobber high-value system state.
    """
    if len(p.parts) <= 1:
        raise ValueError(f"{label} cannot be the filesystem or drive root.")
    for forbidden in _FORBIDDEN_ROOTS:
        try:
            p.relative_to(forbidden)
        except ValueError:
            continue
        raise ValueError(
            f"{label} resolves under a protected system directory ({forbidden}). "
            "Pick a path under your home or project tree."
        )


# Lazily constructed singletons — Designer construction does no I/O, but we
# still keep setup cheap so `--help` and `design_list` work without a model call.
_studio: Studio | None = None
_designer: Designer | None = None
_renderer: Renderer | None = None


def studio() -> Studio:
    global _studio
    if _studio is None:
        _studio = Studio(_resolve_studio_dir())
    return _studio


def designer() -> Designer:
    global _designer
    if _designer is None:
        _designer = Designer()
    return _designer


def renderer() -> Renderer:
    global _renderer
    if _renderer is None:
        _renderer = Renderer()
    return _renderer


def _reset_singletons() -> None:
    """Test/CLI helper — drop cached instances so the next call re-reads env."""
    global _studio, _designer, _renderer
    if _studio is not None:
        try:
            _studio.close()
        except Exception:  # noqa: BLE001
            pass
    _studio = _designer = _renderer = None


# ---------------------------------------------------------------------------
# Lifespan — keep the warm browser alive for the server's lifetime, and
# tear it down + close the SQLite connection on shutdown.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(_app):
    try:
        yield {}
    finally:
        if _renderer is not None:
            try:
                await _renderer.aclose()
            except Exception as e:  # noqa: BLE001
                print(
                    f"[claude-design-mcp] renderer shutdown: {type(e).__name__}: {e}",
                    file=sys.stderr,
                    flush=True,
                )
        if _studio is not None:
            try:
                _studio.close()
            except Exception as e:  # noqa: BLE001
                print(
                    f"[claude-design-mcp] studio shutdown: {type(e).__name__}: {e}",
                    file=sys.stderr,
                    flush=True,
                )


# ---------------------------------------------------------------------------
# Tool wrapper — uniform timeout + safety net so a single bad call can never
# kill the MCP transport. Per-tool try/except for DesignerError is still kept
# because those produce caller-friendly messages.
# ---------------------------------------------------------------------------


def _tool(fn):
    import functools
    import traceback

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await asyncio.wait_for(fn(*args, **kwargs), timeout=TOOL_TIMEOUT_S)
        except asyncio.TimeoutError:
            return _err(
                f"{fn.__name__} timed out after {TOOL_TIMEOUT_S:.0f}s. "
                "Try a smaller scope, the `fast` tier, or fewer variants."
            )
        except DesignerError as e:
            return _err(str(e))
        except ValueError as e:
            # Most often: input model_validator rejection or path-safety reject.
            return _err(str(e))
        except Exception as e:  # noqa: BLE001 — last resort, must not propagate
            # Log full traceback so the operator can diagnose, but never leak
            # internals back to the caller (could include API tokens / paths).
            print(
                f"[claude-design-mcp] {fn.__name__} crashed: {type(e).__name__}: {e}",
                file=sys.stderr,
                flush=True,
            )
            traceback.print_exc(file=sys.stderr)
            return _err(
                f"{fn.__name__} failed unexpectedly ({type(e).__name__}). "
                "Check the MCP server's stderr log for details."
            )

    return wrapper


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("claude_design_mcp", lifespan=_lifespan)


# ---- Tool: design_create -----------------------------------------------


@mcp.tool(
    name="design_create",
    annotations={
        "title": "Create Design",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_tool
async def design_create(params: DesignCreateInput) -> str:
    """Generate a brand-new visual design from a brief, using Claude's design ability.

    The model returns a complete, self-contained HTML document plus structured
    metadata (palette, fonts, design tokens, list of design moves, follow-up
    notes). The HTML is written to disk; if Playwright is installed and
    auto-render is enabled, a screenshot is also produced. Both file paths and
    file:// URLs are returned so the caller can open the design in a browser
    or read the screenshot back into context.

    Args:
        params (DesignCreateInput): see model — at minimum, a `brief`.

    Returns:
        str: JSON with keys: design_id, name, title, summary, palette, fonts,
        tokens, moves, notes, html_path, html_url, render_path, render_url,
        usage (input/output/cache tokens), parent_id (always null for create).

    Examples:
        - "Hero section for a privacy-focused note-taking app, dark mode, glassmorphism."
        - "App settings page for a meditation app, brutalist typography, paper texture."
        - "Newsletter signup card for a literary magazine, editorial layout, serif headlines."

    Errors:
        - "`claude` CLI was not found" — install Claude Code and run `claude login`.
        - "model did not return an HTML block" — retry, possibly with a more concrete brief.
    """
    # DesignerError + unexpected exceptions are caught by the @_tool wrapper.
    draft = await designer().generate_design(
        brief=params.brief,
        mode=params.mode.value,
        viewport=params.viewport.value,
        tier=params.tier.value,
        references=await _resolve_references(params.references),
    )

    rec = _persist_design(
        draft=draft,
        brief=params.brief,
        mode=params.mode.value,
        tier=params.tier.value,
        viewport=params.viewport.value,
        name=params.name,
        parent_id=None,
        iteration_of=None,
        instructions=None,
    )
    rec = await _maybe_render(rec, draft, viewport=params.viewport.value, override=params.auto_render)
    return _ok(_design_response(rec, draft))


# ---- Tool: design_iterate ----------------------------------------------


@mcp.tool(
    name="design_iterate",
    annotations={
        "title": "Iterate on Design",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_tool
async def design_iterate(params: DesignIterateInput) -> str:
    """Refine an existing design with new instructions, creating a child version.

    The original design is preserved; the result is a new design with `parent_id`
    set, so you can walk lineage with `design_get` or render an iteration tree.

    Args:
        params (DesignIterateInput): design_id + natural-language instructions.

    Returns:
        str: JSON with the same fields as `design_create`, plus the parent_id link.

    Examples:
        - "Keep the layout, but make the CTA gradient more vivid."
        - "Swap the serif headline for a wide grotesk; tighten line-height."
        - "Add a sticky table of contents on the left."
    """
    parent = studio().get_design(params.design_id)
    if not parent:
        return _err(f"No design with id {params.design_id!r}. Use design_list to find ids.")
    prior_html = studio().get_design_html(params.design_id)
    if not prior_html:
        return _err(f"Design {params.design_id!r} has no HTML on disk; cannot iterate.")

    prior_meta = parent.to_summary()
    draft = await designer().iterate_design(
        prior_html=prior_html,
        prior_meta=prior_meta,
        instructions=params.instructions,
        tier=params.tier.value,
    )

    rec = _persist_design(
        draft=draft,
        brief=parent.brief,
        mode=parent.mode,
        tier=params.tier.value,
        viewport=parent.viewport,
        name=parent.name,
        parent_id=parent.id,
        iteration_of=parent.id,
        instructions=params.instructions,
    )
    rec = await _maybe_render(rec, draft, viewport=parent.viewport, override=params.auto_render)
    return _ok(_design_response(rec, draft))


# ---- Tool: design_variants ---------------------------------------------


@mcp.tool(
    name="design_variants",
    annotations={
        "title": "Generate Design Variants",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_tool
async def design_variants(params: DesignVariantsInput) -> str:
    """Generate N parallel variants exploring a single design dimension.

    Variants are produced concurrently — wall-clock time is roughly the same as
    one design (give or take). If `design_id` is provided, variants branch from
    that design as siblings; otherwise they all share the supplied `brief`.

    Args:
        params (DesignVariantsInput): see model. Either `design_id` or `brief` required.

    Returns:
        str: JSON with `count` and a `variants` array of design responses.

    Examples:
        - From a base design, vary `color`: 3 palettes, same layout.
        - From a fresh brief, vary `mood`: 4 takes — playful, brutalist, editorial, minimal.
    """
    # Pydantic's model_validator guarantees one of (design_id, brief) is set,
    # but we still surface a clean error if a referenced design vanished.
    base_brief = params.brief
    base_html: str | None = None
    base_meta: dict | None = None
    parent: DesignRecord | None = None
    mode = "auto"
    viewport = "desktop"
    name: str | None = None

    if params.design_id:
        parent = studio().get_design(params.design_id)
        if not parent:
            return _err(f"No design with id {params.design_id!r}.")
        base_html = studio().get_design_html(params.design_id)
        base_meta = parent.to_summary()
        base_brief = parent.brief
        mode = parent.mode
        viewport = parent.viewport
        name = parent.name

    variant_results = await designer().variants(
        count=params.count,
        dimension=params.dimension.value,
        base_brief=base_brief,
        base_html=base_html,
        base_meta=base_meta,
        tier=params.tier.value,
    )
    successes = [r for r in variant_results if r.draft is not None]
    failures = [
        {"index": r.index + 1, "error": r.error or "unknown error"}
        for r in variant_results
        if r.draft is None
    ]
    if not successes:
        detail = "; ".join(f"#{f['index']}: {f['error']}" for f in failures[:3])
        return _err(f"All {params.count} variants failed. {detail}")

    # Persist all drafts first (DB writes are <1ms each); then render them
    # in parallel. With the warm browser pool, N renders run concurrently
    # in their own contexts — wall-clock time stays close to one render.
    recs: list[DesignRecord] = []
    drafts: list[DesignDraft] = []
    for result in successes:
        draft = result.draft
        if draft is None:
            continue
        drafts.append(draft)
        rec = _persist_design(
            draft=draft,
            brief=base_brief or "",
            mode=mode,
            tier=params.tier.value,
            viewport=viewport,
            name=f"{name}-v{result.index + 1}" if name else None,
            parent_id=parent.id if parent else None,
            iteration_of=None,
            instructions=f"variant-{params.dimension.value}-{result.index + 1}",
        )
        recs.append(rec)

    rendered = await asyncio.gather(
        *(
            _maybe_render(rec, draft, viewport=viewport, override=params.auto_render)
            for rec, draft in zip(recs, drafts)
        )
    )
    out = [_design_response(rec, draft) for rec, draft in zip(rendered, drafts)]

    body: dict[str, Any] = {
        "count": len(out),
        "dimension": params.dimension.value,
        "parent_id": parent.id if parent else None,
        "variants": out,
    }
    if failures:
        body["partial"] = True
        body["requested_count"] = params.count
        body["failed_count"] = len(failures)
        body["failures"] = failures
    return _ok(body)


# ---- Tool: design_render -----------------------------------------------


@mcp.tool(
    name="design_render",
    annotations={
        "title": "Render Design Screenshot",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_tool
async def design_render(params: DesignRenderInput) -> str:
    """Render (or re-render) a design's HTML to a PNG at a chosen viewport.

    Requires Playwright. Subsequent calls with the same id+viewport overwrite
    the previous PNG. The latest render path is also stored on the design row
    so it's returned by `design_get`.

    Returns:
        str: JSON with render_path, render_url, viewport, and full_page boolean.
        If Playwright is not installed, returns a clear error explaining how to enable it.
    """
    rec = studio().get_design(params.design_id)
    if not rec:
        return _err(f"No design with id {params.design_id!r}.")
    ready = Renderer.readiness()
    if not ready.get("ready"):
        return _err(_render_readiness_error(ready))
    out_path = studio().render_path_for(rec.id, params.viewport.value)
    r = renderer()
    written = await r.render(
        html_path=rec.html_path,
        out_path=out_path,
        viewport=params.viewport.value,
        full_page=params.full_page,
    )
    if not written:
        detail = r.last_error or "unknown Playwright failure"
        return _err(f"Render failed: {detail}")
    studio().update_render_path(rec.id, written)
    return _ok({
        "design_id": rec.id,
        "viewport": params.viewport.value,
        "full_page": params.full_page,
        "render_path": written,
        "render_url": studio().file_url(written),
    })


# ---- Tool: design_get --------------------------------------------------


@mcp.tool(
    name="design_get",
    annotations={
        "title": "Get Design",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_tool
async def design_get(params: DesignGetInput) -> str:
    """Retrieve a design's metadata, lineage, and (optionally) raw HTML."""
    rec = studio().get_design(params.design_id)
    if not rec:
        return _err(f"No design with id {params.design_id!r}.")
    lineage = [r.to_summary() for r in studio().lineage(rec.id)]
    body: dict[str, Any] = rec.to_summary()
    body["lineage"] = lineage
    if params.include_html:
        html = studio().get_design_html(rec.id) or ""
        if len(html) > CHARACTER_LIMIT:
            body["html"] = html[:CHARACTER_LIMIT]
            body["html_truncated"] = True
            body["html_truncation_message"] = (
                f"HTML truncated from {len(html)} to {CHARACTER_LIMIT} chars. "
                f"Read the full file at {rec.html_path}."
            )
        else:
            body["html"] = html
    if params.response_format == ResponseFormat.MARKDOWN:
        return _design_markdown(body)
    return _ok(body)


# ---- Tool: design_list -------------------------------------------------


@mcp.tool(
    name="design_list",
    annotations={
        "title": "List Designs",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_tool
async def design_list(params: DesignListInput) -> str:
    """List recent designs in the studio, newest first.

    Supports pagination and a substring filter against name/title/summary.
    Returns at most 100 records per page (default 20).
    """
    records, has_more = studio().list_designs(
        limit=params.limit,
        offset=params.offset,
        name_contains=params.name_contains,
    )
    if params.response_format == ResponseFormat.MARKDOWN:
        return _list_markdown(
            records, has_more, params.offset, params.limit, params.name_contains
        )
    body = {
        "count": len(records),
        "offset": params.offset,
        "has_more": has_more,
        "next_offset": params.offset + len(records) if has_more else None,
        "designs": [r.to_summary() for r in records],
    }
    out = _ok(body)
    if len(out) > CHARACTER_LIMIT:
        # Halve the result set, keep the metadata, attach truncation notice.
        body["designs"] = body["designs"][: max(1, len(records) // 2)]
        body["truncated"] = True
        body["truncation_message"] = (
            "Response truncated; lower `limit` or use `name_contains` to filter."
        )
        out = _ok(body)
    return out


# ---- Tool: design_extract_system ---------------------------------------


@mcp.tool(
    name="design_extract_system",
    annotations={
        "title": "Extract Design System",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_tool
async def design_extract_system(params: DesignExtractSystemInput) -> str:
    """Extract a coherent design system (tokens + components + principles) from designs.

    Pass 1-10 design ids. Claude analyzes them, picks the strongest direction,
    and returns a portable token bundle plus reusable component snippets. The
    system is persisted with its own id so it can be applied later via
    `design_apply_system`.

    Returns:
        str: JSON with system_id, name, summary, tokens, components, principles, source_ids.
    """
    designs: list[dict] = []
    for did in params.design_ids:
        rec = studio().get_design(did)
        if not rec:
            return _err(f"No design with id {did!r}.")
        html = studio().get_design_html(did) or ""
        designs.append({
            "id": rec.id,
            "name": rec.name or rec.title or rec.id,
            "html": html,
        })

    extracted = await designer().extract_system(designs=designs, tier=params.tier.value)

    sys_rec = SystemRecord(
        id=studio().new_id(),
        name=params.name or extracted.get("name"),
        summary=extracted.get("summary"),
        tokens=extracted.get("tokens", {}),
        components=extracted.get("components", []),
        principles=extracted.get("principles", []),
        source_ids=params.design_ids,
    )
    studio().insert_system(sys_rec)
    return _ok({"system_id": sys_rec.id, **sys_rec.to_summary()})


# ---- Tool: design_apply_system -----------------------------------------


@mcp.tool(
    name="design_apply_system",
    annotations={
        "title": "Apply Design System to Brief",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_tool
async def design_apply_system(params: DesignApplySystemInput) -> str:
    """Generate a new design that strictly follows a previously extracted system."""
    sys_rec = studio().get_system(params.system_id)
    if not sys_rec:
        return _err(f"No design system with id {params.system_id!r}.")

    system_blob = {
        "name": sys_rec.name,
        "tokens": sys_rec.tokens,
        "components": sys_rec.components,
        "principles": sys_rec.principles,
    }
    draft = await designer().apply_system(
        system=system_blob,
        brief=params.brief,
        mode=params.mode.value,
        tier=params.tier.value,
    )

    rec = _persist_design(
        draft=draft,
        brief=params.brief,
        mode=params.mode.value,
        tier=params.tier.value,
        viewport="desktop",
        name=None,
        parent_id=None,
        iteration_of=None,
        instructions=f"apply-system:{params.system_id}",
    )
    rec = await _maybe_render(rec, draft, viewport="desktop", override=params.auto_render)
    return _ok(_design_response(rec, draft))


# ---- Tool: design_export -----------------------------------------------


@mcp.tool(
    name="design_export",
    annotations={
        "title": "Export Design",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_tool
async def design_export(params: DesignExportInput) -> str:
    """Export a design (or system) as a portable bundle.

    For designs: produces a folder with index.html and (if available) screenshot.png.
    For systems: produces tokens.json and components.html.

    Returns the bundle's directory path and a zip of the same contents.
    """
    if not params.design_id and not params.system_id:
        return _err("Provide design_id or system_id to export.")

    try:
        target_root = _resolve_export_dir(params.target_dir)
    except ValueError as e:
        return _err(str(e))
    target_root.mkdir(parents=True, exist_ok=True)

    if params.design_id:
        rec = studio().get_design(params.design_id)
        if not rec:
            return _err(f"No design with id {params.design_id!r}.")
        out_dir = target_root / f"design-{rec.id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        index = out_dir / "index.html"
        # Re-inject CSP on the way out (defense in depth — a design persisted
        # before CSP injection landed wouldn't otherwise carry one).
        _atomic_write_text(
            index, inject_csp(studio().get_design_html(rec.id) or "")
        )
        if rec.render_path and Path(rec.render_path).exists():
            _safe_copy_png(rec.render_path, out_dir / "screenshot.png")
        _atomic_write_text(
            out_dir / "design.json", json.dumps(rec.to_summary(), indent=2)
        )
        zip_path = target_root / f"design-{rec.id}.zip"
        _zip_dir(out_dir, zip_path)
        return _ok({
            "design_id": rec.id,
            "output_dir": str(out_dir),
            "zip_path": str(zip_path),
            "preview_url": studio().file_url(str(index)),
        })

    sys_rec = studio().get_system(params.system_id)  # type: ignore[arg-type]
    if not sys_rec:
        return _err(f"No design system with id {params.system_id!r}.")
    out_dir = target_root / f"system-{sys_rec.id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(out_dir / "tokens.json", json.dumps(sys_rec.tokens, indent=2))
    _atomic_write_text(
        out_dir / "system.json", json.dumps(sys_rec.to_summary(), indent=2)
    )
    _atomic_write_text(out_dir / "components.html", build_components_page(sys_rec))
    zip_path = target_root / f"system-{sys_rec.id}.zip"
    _zip_dir(out_dir, zip_path)
    return _ok({
        "system_id": sys_rec.id,
        "output_dir": str(out_dir),
        "zip_path": str(zip_path),
    })


# ---- Tool: design_preview ----------------------------------------------


@mcp.tool(
    name="design_preview",
    annotations={
        "title": "Get Preview URL",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_tool
async def design_preview(params: DesignPreviewInput) -> str:
    """Return a file:// URL to preview a design (or the contact-sheet of all designs)."""
    if params.design_id:
        rec = studio().get_design(params.design_id)
        if not rec:
            return _err(f"No design with id {params.design_id!r}.")
        return _ok({
            "design_id": rec.id,
            "preview_url": studio().file_url(rec.html_path),
            "render_url": studio().file_url(rec.render_path),
        })
    if params.rebuild_index:
        records, _ = studio().list_designs(limit=100, offset=0)
        index_path = build_index(studio(), records)
    else:
        index_path = studio().root / "_index.html"
        if not index_path.exists():
            records, _ = studio().list_designs(limit=100, offset=0)
            index_path = build_index(studio(), records)
    return _ok({
        "studio_dir": str(studio().root),
        "index_path": str(index_path),
        "preview_url": studio().file_url(str(index_path)),
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _persist_design(
    *,
    draft: DesignDraft,
    brief: str,
    mode: str,
    tier: str,
    viewport: str,
    name: str | None,
    parent_id: str | None,
    iteration_of: str | None,
    instructions: str | None,
) -> DesignRecord:
    s = studio()
    design_id = s.new_id()
    html_path = s.write_html(design_id, draft.html)
    rec = DesignRecord(
        id=design_id,
        name=name or s.slug_for(draft.title or brief)[:48] or design_id,
        parent_id=parent_id,
        brief=brief,
        mode=mode,
        tier=tier,
        viewport=viewport,
        title=draft.title,
        summary=draft.summary,
        palette=draft.palette,
        fonts=draft.fonts,
        tokens=draft.tokens,
        moves=draft.moves,
        notes=draft.notes,
        html_path=str(html_path),
        render_path=None,
        iteration_of=iteration_of,
        instructions=instructions,
    )
    s.insert_design(rec)
    return rec


async def _maybe_render(
    rec: DesignRecord,
    draft: DesignDraft,
    *,
    viewport: str,
    override: bool | None,
) -> DesignRecord:
    """Auto-render the design's screenshot if Playwright is available.

    Render failures are non-fatal — we surface a warning on ``draft`` so the
    calling agent sees that the screenshot is missing without having to scrape
    stderr. The design itself was already persisted before this runs.
    """
    should = override if override is not None else _auto_render_default()
    if not should:
        return rec
    ready = Renderer.readiness()
    if not ready.get("ready"):
        draft.warnings.append(f"screenshot generation skipped: {_render_readiness_error(ready)}")
        return rec
    out_path = studio().render_path_for(rec.id, viewport)
    r = renderer()
    written = await r.render(
        html_path=rec.html_path,
        out_path=out_path,
        viewport=viewport,
        full_page=True,
    )
    if written:
        studio().update_render_path(rec.id, written)
        rec.render_path = written
    else:
        detail = r.last_error or "unknown Playwright failure"
        draft.warnings.append(
            f"screenshot generation failed: {detail}. "
            "Design saved without a render; run design_render to retry."
        )
    return rec


def _render_readiness_error(readiness: dict[str, Any]) -> str:
    """Turn renderer readiness diagnostics into a caller-actionable message."""
    if not readiness.get("available"):
        return (
            "Playwright is not installed. Run "
            "`pip install \"claude-design-mcp[render]\" && playwright install chromium`."
        )
    temp_dir = readiness.get("temp_dir") or {}
    if not temp_dir.get("ok"):
        return (
            "Playwright cannot create temporary files "
            f"under {temp_dir.get('path')!r}: {temp_dir.get('error')}. "
            "Set CLAUDE_DESIGN_PLAYWRIGHT_TMP to a writable local directory."
        )
    browsers = readiness.get("browsers") or {}
    if not browsers.get("ok"):
        return (
            f"{browsers.get('error') or 'Playwright Chromium is not ready'} "
            f"{browsers.get('hint') or 'Run `playwright install chromium`.'}"
        ).strip()
    return "Playwright renderer is not ready; run `claude-design-mcp --check-json` for details."


async def _resolve_references(ref_ids: list[str]) -> list[dict]:
    """Turn reference design ids into compact metadata dicts for the prompt."""
    out: list[dict] = []
    for rid in ref_ids:
        rec = studio().get_design(rid)
        if not rec:
            continue
        out.append({
            "id": rec.id,
            "name": rec.name or rec.title or rec.id,
            "palette": rec.palette,
            "tokens": rec.tokens,
        })
    return out


def _design_response(rec: DesignRecord, draft: DesignDraft) -> dict[str, Any]:
    body = rec.to_summary()
    body["usage"] = {
        "input_tokens": draft.input_tokens,
        "output_tokens": draft.output_tokens,
        "cache_creation_input_tokens": draft.cache_creation_tokens,
        "cache_read_input_tokens": draft.cache_read_tokens,
        "model": draft.model,
    }
    if draft.warnings:
        body["warnings"] = list(draft.warnings)
    return body


def _design_markdown(body: dict[str, Any]) -> str:
    lines = [
        f"# {body.get('title') or body.get('name') or body.get('id')}",
        "",
        body.get("summary") or "",
        "",
        f"- **id**: `{body.get('id')}`",
        f"- **mode**: {body.get('mode')}",
        f"- **tier**: {body.get('tier')}",
        f"- **viewport**: {body.get('viewport')}",
        f"- **palette**: {' '.join(body.get('palette') or [])}",
        f"- **fonts**: {', '.join(body.get('fonts') or [])}",
        f"- **html**: `{body.get('html_path')}`",
        f"- **preview**: {body.get('preview_url')}",
    ]
    if body.get("render_url"):
        lines.append(f"- **screenshot**: {body['render_url']}")
    if body.get("moves"):
        lines.append("\n**Moves:**")
        for m in body["moves"]:
            lines.append(f"- {m}")
    if body.get("notes"):
        lines.append(f"\n**Notes:** {body['notes']}")
    if body.get("lineage"):
        lines.append("\n**Lineage:**")
        for r in body["lineage"]:
            lines.append(f"- `{r['id']}` — {r.get('title') or r.get('name')}")
    return "\n".join(lines)


def _list_markdown(
    records: list[DesignRecord],
    has_more: bool,
    offset: int,
    limit: int,
    name_contains: str | None,
) -> str:
    if not records:
        msg = "_No designs yet._"
        if name_contains:
            msg = f"_No designs match `{name_contains}`._"
        return msg
    lines = [f"# Studio · {len(records)} designs (showing this page)"]
    if name_contains:
        lines.append(f"Filter: `{name_contains}`")
    lines.append("")
    for r in records:
        title = r.title or r.name or r.id
        palette = " ".join(r.palette[:5])
        lines.append(f"- **{title}** · `{r.id}` · {r.mode}/{r.tier} · {palette}")
        if r.summary:
            lines.append(f"  > {r.summary}")
    if has_more:
        lines.append(f"\n_…more designs available. Use offset={offset+limit}._")
    return "\n".join(lines)


def _zip_dir(src: Path, dest: Path) -> None:
    """Zip every regular file under ``src`` into ``dest``.

    Symlinks are skipped: ``p.is_file()`` returns True for symlinks-to-files
    which would let a hostile artifact placed inside the export staging dir
    leak its target's contents (e.g. ``~/.ssh/id_rsa``) into the bundle.
    """
    if dest.exists():
        dest.unlink()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in src.rglob("*"):
            if p.is_symlink():
                continue
            if p.is_file():
                zf.write(p, p.relative_to(src))


def _resolve_export_dir(target_dir: str | None) -> Path:
    """Resolve ``target_dir`` for export, blocking obviously dangerous targets.

    If ``target_dir`` is None we use the studio's exports/ folder. Otherwise we
    require an absolute path (no ambient cwd surprises), refuse UNC paths, the
    filesystem root, any system directories in ``_FORBIDDEN_ROOTS``, and any
    path that resolves into the studio root *outside* of its own exports/ —
    we don't want exports clobbering canonical designs or the contact sheet.
    """
    if not target_dir:
        return studio().exports_dir

    requested_str = str(target_dir).strip()
    # Reject UNC paths up front — they bypass the studio's filesystem and
    # often involve credential prompts on Windows.
    if requested_str.startswith(("\\\\", "//")):
        raise ValueError(
            "target_dir must not be a UNC path; choose a local absolute path."
        )
    requested = Path(requested_str).expanduser()
    if not requested.is_absolute():
        raise ValueError(
            f"target_dir must be an absolute path; got {target_dir!r}. "
            "Pass a full path like 'B:/exports/my-bundle' or omit to use the default."
        )
    resolved = requested.resolve()
    _assert_path_safe(resolved, label="target_dir")

    # Within the studio root, only the exports/ subdir is fair game. Anything
    # else (designs/, renders/, _index.html) would let exports clobber state
    # the studio relies on.
    studio_root = studio().root
    try:
        resolved.relative_to(studio_root)
    except ValueError:
        return resolved  # outside the studio entirely — fine
    try:
        resolved.relative_to(studio().exports_dir)
        return resolved
    except ValueError:
        raise ValueError(
            f"target_dir resolves inside the studio ({studio_root}) but not under "
            f"its exports/ subdir. Pick a path outside the studio, or omit "
            f"target_dir to use the default."
        )


def _safe_copy_png(src: str | Path, dst: Path) -> None:
    """Copy a PNG to ``dst`` atomically, refusing to overwrite a symlink target."""
    if dst.is_symlink():
        dst.unlink()
    tmp = dst.with_suffix(f"{dst.suffix}.{os.getpid()}-tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _ok(body: Any) -> str:
    return json.dumps(body, indent=2, default=str)


def _err(msg: str) -> str:
    return json.dumps({"error": msg}, indent=2)


def _claude_cli_status() -> dict[str, Any]:
    """Probe the local `claude` CLI for `--check` to report on it.

    Returns dict with keys ``ok`` (bool) and ``line`` (printable status).
    """
    import subprocess

    configured = (os.environ.get("CLAUDE_DESIGN_CLI_PATH") or "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        found = str(candidate) if candidate.exists() else shutil.which(configured)
        if not found:
            return {
                "ok": False,
                "line": f"CLAUDE_DESIGN_CLI_PATH is set but not executable: {configured}",
            }
    else:
        found = shutil.which("claude") or shutil.which("claude.exe")
    if not found:
        return {
            "ok": False,
            "line": (
                "NOT FOUND on PATH — install Claude Code "
                "(https://docs.claude.com/en/docs/claude-code/) and run "
                "`claude login`."
            ),
        }
    try:
        out = subprocess.run(
            [found, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"ok": False, "line": f"FOUND at {found} but failed to run ({e})"}
    version = (out.stdout or out.stderr or "").strip().splitlines()[:1]
    version_str = version[0] if version else "(unknown version)"
    return {"ok": True, "line": f"{version_str} ({found})"}


def _build_check_report() -> dict[str, Any]:
    """Build a machine-readable readiness report for humans and automation."""
    auth_overrides = auth_override_state()
    report: dict[str, Any] = {
        "ok": True,
        "authentication": {
            "mode": "claude-code-oauth",
            "api_key_required": False,
            "setup": "Run `claude login`; no ANTHROPIC_API_KEY is used.",
            "env_overrides_present": auth_overrides["present"],
            "env_overrides_scrubbed": auth_overrides["scrub_enabled"],
            "preserve_overrides_env": auth_overrides["allow_override_env"],
        },
        "studio_dir": {"ok": True, "path": None, "error": None},
        "playwright": {},
        "claude_cli": {},
        "studio_init": {"ok": True, "error": None},
    }

    try:
        resolved = _resolve_studio_dir()
    except ValueError as e:
        report["ok"] = False
        report["studio_dir"] = {"ok": False, "path": None, "error": str(e)}
        report["studio_init"] = {"ok": False, "error": "studio dir invalid"}
        return report

    report["studio_dir"] = {"ok": True, "path": str(resolved), "error": None}
    renderer_readiness = Renderer.readiness()
    report["playwright"] = renderer_readiness

    cli_status = _claude_cli_status()
    report["claude_cli"] = cli_status
    if not cli_status["ok"]:
        report["ok"] = False
    if not renderer_readiness.get("ready"):
        # Rendering is optional: do not fail overall readiness, but expose the
        # precise blocker so install/support scripts can warn before auto-render.
        report["playwright"]["required_for_core"] = False

    try:
        studio()
    except OSError as e:
        report["ok"] = False
        report["studio_init"] = {"ok": False, "error": str(e)}

    return report


def _print_check_report(report: dict[str, Any]) -> None:
    studio_dir = report["studio_dir"]
    if studio_dir["ok"]:
        print(f"studio dir   : {studio_dir['path']}", file=sys.stderr)
    else:
        print(f"studio dir   : INVALID — {studio_dir['error']}", file=sys.stderr)
    print(
        f"playwright   : {'ready' if report['playwright'].get('ready') else 'not ready'}",
        file=sys.stderr,
    )
    if not report["playwright"].get("ready"):
        print(
            f"render hint  : {_render_readiness_error(report['playwright'])}",
            file=sys.stderr,
        )
    print(f"claude CLI   : {report['claude_cli'].get('line', 'not checked')}", file=sys.stderr)
    auth = report["authentication"]
    print(
        "auth         : Claude Code OAuth (`claude login`); no API key required",
        file=sys.stderr,
    )
    overrides = auth.get("env_overrides_present") or []
    if overrides:
        scrubbed = auth.get("env_overrides_scrubbed")
        if scrubbed:
            print(
                "auth (note)  : detected "
                + ", ".join(overrides)
                + " in env. The MCP scrubs these before spawning the CLI so "
                "design calls use OAuth, not the API. Set "
                f"{auth.get('preserve_overrides_env')}=1 to preserve them.",
                file=sys.stderr,
            )
        else:
            print(
                "auth (warn)  : "
                + ", ".join(overrides)
                + " is set AND override-preservation is enabled. Design calls "
                "will bill against the API account, not OAuth.",
                file=sys.stderr,
            )
    studio_init = report["studio_init"]
    if studio_init["ok"]:
        print("studio init  : ok", file=sys.stderr)
    else:
        print(f"studio init  : FAILED — {studio_init['error']}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(prog="claude-design-mcp")
    parser.add_argument(
        "--studio-dir",
        help="Override CLAUDE_DESIGN_STUDIO_DIR for this run.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify config and exit (does not start the MCP server).",
    )
    parser.add_argument(
        "--check-json",
        action="store_true",
        help="Print machine-readable readiness JSON and exit.",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio"],
        help="Transport (only stdio is supported in v0.1).",
    )
    args = parser.parse_args()

    if args.studio_dir:
        os.environ["CLAUDE_DESIGN_STUDIO_DIR"] = args.studio_dir
        _reset_singletons()  # next studio() call re-reads the env

    if args.check or args.check_json:
        report = _build_check_report()
        if args.check_json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            _print_check_report(report)
        sys.exit(0 if report["ok"] else 1)

    mcp.run()


if __name__ == "__main__":
    main()
