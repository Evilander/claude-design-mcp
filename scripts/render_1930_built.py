"""Render the wired-in 1930 operator-console.html (after build-operator-console.mjs)
to verify the v3 layout actually displays correctly with real project state.

Usage: python scripts/render_1930_built.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from claude_design.renderer import Renderer  # noqa: E402


SOURCE = Path(r"B:\projects\claude\1930\out\operator-console.html")
OUT_DIR = Path(r"B:\projects\claude\1930\out\redesign-2026-05-10")


async def main() -> int:
    if not os.environ.get("CLAUDE_DESIGN_STUDIO_DIR"):
        os.environ["CLAUDE_DESIGN_STUDIO_DIR"] = str(_REPO_ROOT / "studio")

    if not SOURCE.exists():
        print(f"[render] {SOURCE} not found — run npm run ui:console first", file=sys.stderr)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    r = Renderer()
    try:
        for viewport in ("desktop", "mobile"):
            out_path = OUT_DIR / f"operator-console-built-{viewport}.png"
            written = await r.render(
                html_path=str(SOURCE),
                out_path=out_path,
                viewport=viewport,
                full_page=True,
            )
            if written:
                print(f"[render] {viewport} → {written}", file=sys.stderr)
            else:
                print(f"[render] {viewport} FAILED — {r.last_error}", file=sys.stderr)
    finally:
        await r.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
