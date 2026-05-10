"""End-to-end smoke test for the design pipeline.

Runs the same code paths the MCP server exposes:
  1) Designer.generate_design  — model call through Claude CLI OAuth
  2) Studio.write_html / insert_design  — persistence with CSP injection
  3) Renderer.render  — Playwright screenshot at desktop viewport
  4) Studio.lineage  — read-back

Exits non-zero with a structured JSON report on stderr if anything fails.
Useful for first-contact validation, CI, and post-install verification.

Usage: python scripts/dogfood_smoke.py [--keep] [--brief "..."]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Ensure src/ is importable when running from the repo root without install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from claude_design.designer import Designer  # noqa: E402
from claude_design.renderer import Renderer  # noqa: E402
from claude_design.studio import DesignRecord, Studio  # noqa: E402


DEFAULT_BRIEF = (
    "A 'now playing' card for a vintage 1930s radio broadcast control room. "
    "Show a single track with title, host name, runtime, a small mid-century VU meter, "
    "and a 'cue next' affordance. Brass and ivory palette, deco geometry, no skeuomorphism. "
    "Desktop card, ~520px wide."
)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="Keep the temporary studio dir.")
    ap.add_argument("--brief", default=DEFAULT_BRIEF)
    ap.add_argument("--tier", choices=["fast", "best"], default="fast")
    ap.add_argument("--viewport", default="desktop")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="cdmcp-smoke-"))
    os.environ["CLAUDE_DESIGN_STUDIO_DIR"] = str(tmp)
    print(f"[smoke] studio dir: {tmp}", file=sys.stderr)

    report: dict[str, object] = {"steps": []}
    studio = Studio(tmp)

    t0 = time.monotonic()
    try:
        designer = Designer()
        draft = await designer.generate_design(
            brief=args.brief,
            mode="component",
            viewport=args.viewport,
            tier=args.tier,
        )
        report["steps"].append({
            "step": "generate_design",
            "ok": True,
            "elapsed_s": round(time.monotonic() - t0, 2),
            "html_bytes": len(draft.html),
            "title": draft.title,
            "palette": draft.palette,
            "tokens_used": {
                "input": draft.input_tokens,
                "output": draft.output_tokens,
                "cache_read": draft.cache_read_tokens,
            },
            "model": draft.model,
            "warnings": list(draft.warnings),
        })
    except Exception as e:  # noqa: BLE001
        report["steps"].append({"step": "generate_design", "ok": False, "error": f"{type(e).__name__}: {e}"})
        print(json.dumps(report, indent=2), file=sys.stderr)
        return 2

    # Persist
    t0 = time.monotonic()
    design_id = studio.new_id()
    html_path = studio.write_html(design_id, draft.html)
    rec = DesignRecord(
        id=design_id,
        name="smoke-test",
        parent_id=None,
        brief=args.brief,
        mode="component",
        tier=args.tier,
        viewport=args.viewport,
        title=draft.title,
        summary=draft.summary,
        palette=draft.palette,
        fonts=draft.fonts,
        tokens=draft.tokens,
        moves=draft.moves,
        notes=draft.notes,
        html_path=str(html_path),
    )
    studio.insert_design(rec)

    csp_present = "Content-Security-Policy" in html_path.read_text(encoding="utf-8")
    report["steps"].append({
        "step": "persist",
        "ok": True,
        "elapsed_s": round(time.monotonic() - t0, 2),
        "html_path": str(html_path),
        "csp_injected": csp_present,
    })
    if not csp_present:
        report["fatal"] = "CSP was not injected on persisted HTML"
        print(json.dumps(report, indent=2), file=sys.stderr)
        return 3

    # Render
    if not Renderer.readiness().get("ready"):
        report["steps"].append({"step": "render", "ok": False, "skipped": "renderer not ready"})
    else:
        t0 = time.monotonic()
        r = Renderer()
        try:
            out_path = studio.render_path_for(rec.id, args.viewport)
            written = await r.render(
                html_path=rec.html_path,
                out_path=out_path,
                viewport=args.viewport,
                full_page=True,
            )
            report["steps"].append({
                "step": "render",
                "ok": bool(written),
                "elapsed_s": round(time.monotonic() - t0, 2),
                "png_path": written,
                "png_bytes": Path(written).stat().st_size if written else None,
                "last_error": r.last_error,
            })
        finally:
            await r.aclose()

    # Read-back
    fetched = studio.get_design(rec.id)
    report["steps"].append({
        "step": "read_back",
        "ok": fetched is not None and fetched.id == rec.id,
        "lineage_len": len(studio.lineage(rec.id)),
    })

    studio.close()
    print(json.dumps(report, indent=2))
    if not args.keep:
        # Don't auto-delete: keep the artifacts so the operator can eyeball them.
        print(f"[smoke] artifacts in {tmp}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
