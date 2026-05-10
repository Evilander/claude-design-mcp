"""Re-run the 1930 operator console with the upgraded system prompt.

The prompt now requires (a) a stated aesthetic posture, (b) one dominant
hero element, and (c) explicit ban on numbered-section reflex + equal-weight
quadrants + 'fill the row' identical-card galleries. We add a posture hint to
the brief so the model commits up-front instead of hedging.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from claude_design.designer import Designer  # noqa: E402
from claude_design.renderer import Renderer  # noqa: E402
from claude_design.studio import DesignRecord, Studio  # noqa: E402


PROJECT_ROOT = Path(r"B:\projects\claude\1930")
OUT_DIR = PROJECT_ROOT / "out" / "redesign-2026-05-10"


OPERATOR_CONSOLE_V3_BRIEF = """\
The operator console for the 1930 voice/talkie broadcast tool, W-AUD 1930
Control. Same functional surface as before (Broadcast Deck, Signal Board,
Casting Ledger, Release Gates) but redrawn under a deliberate aesthetic
posture and with a real focal hierarchy.

## Posture: archival-broadcast-ledger

Period-true, not period-cosplay. Reference points: actual 1930 NBC
broadcast logs (typewritten on ruled paper, all-caps labels, hand-stamped
timecodes, ink stamps, marginal annotations from the engineer on duty,
hairline column rules). Not "vintage radio dashboard." A ledger sheet that
happens to be interactive.

## Hero: the current broadcast

The single dominant element is the now-airing reel. It takes ~50-60% of
the first viewport's optical weight. Big stamped reel title in display
serif, the actual line text being read in italic, a running waveform that
is the *centerpiece* (not a thumbnail), an active-line cue counter ("LINE
2 of 7"), and a single brass STOP button that's the second-largest
element on the page.

Everything else — Signal Board, Casting Ledger, Release Gates — lives
below the fold or in the margin, in smaller, calmer treatment. They are
support material for the hero, not peers.

## Anti-instructions (do not do these)

- Do NOT use `01 / 02 / 03 / 04` numbered section headers.
- Do NOT lay out the page as four equal quadrants. The Broadcast Deck
  dominates; everything else is secondary.
- Do NOT render 7 identical Casting Ledger rows. Show the top 3 candidates
  with real character (name + portrait-line + one quote of the matched
  term), and a quieter "+ 4 more" affordance.
- Do NOT use a card rail at the bottom unless it materially serves the
  hero. (It does not.)

## Materials, type, palette

- Paper-cream `#eee5d2` ground; dark ink `#171412` body; warm-brass
  `#d0a64f` for the live cue indicator and stamp marks; deep oxidized
  teal `#1f4d4a` only for muted secondary chrome; brick red `#8b1a1a`
  only for STOP / blocked / errors.
- Display serif (Georgia or similar) for stamped labels at small caps,
  letter-spaced wide. Body in a humanist sans (Inter / Source Sans).
  Mono for timecodes, hashes, and the MCP prune command.
- Hairline column rules. Tiny "engineer's stamp" red marks beside any
  status that needs operator attention. Real margin annotations (one or
  two per section in handwriting-flavored type) where the brief implies
  operator decisions.

## Content slots (use exactly)

- Masthead: 'W-AUD 1930 Control · Earnest Classic-Hollywood Leading Man
  · eleven_v3 · 2026-05-05 01:15'
- Hero broadcast: 'Reel A — "The Last Letter"', cue 'LINE 2 of 7',
  line text '"…and on the porch, Margaret answered without turning. We
  pause now for station identification—"', timecode 02:14 / 04:32,
  waveform displayed.
- Signal Board (smaller, below): model `eleven_v3`, persona
  `earnest-leading-man`, manifest hashes (3 lines, trunc 12), four safety
  badges (public_manifest, prompt_hidden, v3, persona_boundary),
  '2 skipped' in muted red.
- Casting Ledger (compact, 3 named + 4 more): Tom — Warm Smooth Hesitant
  (score 20, rendered); Toby — Bright and Earnest (18, rendered);
  Bradley — Earnest Narrator (15, queued); '+ 4 more candidates'.
- Release Gates: 3-line readiness checklist (Local proof OK ·
  Public manifest OK · Persona boundary OK), MCP prune command in mono
  block with Copy button. Show 'QUEUED' next to the command.

## Hard rules

- One HTML file, ~14-18KB. Inline <style> only.
- Semantic HTML, full keyboard nav, focus-visible everywhere, WCAG AA.
- Desktop 1440 → hero spans full width above the fold; Signal Board +
  Casting Ledger + Release Gates form a quieter footer band.
- Tablet 834 → hero stays dominant, support sections stack.
- Mobile 390 → hero condenses to title + waveform + STOP; ledger and
  gates collapse into expandable sections.
- prefers-reduced-motion: waveform freezes on a representative frame;
  no animations. Otherwise: slow waveform pulse, no parallax.
- No external icon CDNs; inline SVG for the brass stamp marks, waveform
  bars, and meter strokes.
"""


async def main() -> int:
    if not os.environ.get("CLAUDE_DESIGN_STUDIO_DIR"):
        os.environ["CLAUDE_DESIGN_STUDIO_DIR"] = str(_REPO_ROOT / "studio")

    studio = Studio(os.environ["CLAUDE_DESIGN_STUDIO_DIR"])
    designer = Designer()
    renderer_inst = Renderer()

    name = "1930-operator-console-v3"
    try:
        print(f"\n[redesign-v3] generating {name} on best tier ...", file=sys.stderr, flush=True)
        t0 = time.monotonic()
        draft = await designer.generate_design(
            brief=OPERATOR_CONSOLE_V3_BRIEF,
            mode="app_ui",
            viewport="desktop",
            tier="best",
        )
        elapsed = time.monotonic() - t0
        print(
            f"[redesign-v3] {name}: {len(draft.html):,} bytes in {elapsed:.1f}s "
            f"(in/out tokens {draft.input_tokens}/{draft.output_tokens})",
            file=sys.stderr,
            flush=True,
        )

        design_id = studio.new_id()
        html_path = studio.write_html(design_id, draft.html)
        rec = DesignRecord(
            id=design_id,
            name=name,
            parent_id=None,
            brief=OPERATOR_CONSOLE_V3_BRIEF,
            mode="app_ui",
            tier="best",
            viewport="desktop",
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

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(html_path, OUT_DIR / "operator-console-v3.html")

        for viewport in ("desktop", "mobile"):
            out_path = studio.render_path_for(design_id, viewport)
            written = await renderer_inst.render(
                html_path=str(html_path),
                out_path=out_path,
                viewport=viewport,
                full_page=True,
            )
            if written:
                shutil.copy2(written, OUT_DIR / f"operator-console-v3-{viewport}.png")
                print(f"[redesign-v3] {viewport} → {written}", file=sys.stderr, flush=True)
            else:
                print(
                    f"[redesign-v3] {viewport} render FAILED — {renderer_inst.last_error}",
                    file=sys.stderr,
                    flush=True,
                )

        print(f"\n[redesign-v3] palette={draft.palette}", file=sys.stderr, flush=True)
        print(f"[redesign-v3] moves={draft.moves}", file=sys.stderr, flush=True)
    finally:
        await renderer_inst.aclose()
        studio.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
