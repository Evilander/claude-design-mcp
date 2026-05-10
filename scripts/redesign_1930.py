"""Generate a redesigned operator console + talkie studio for the 1930 project.

Uses the Designer/Studio/Renderer pipeline directly (no MCP transport needed)
so we exercise the same code paths the MCP tool surface exposes.

Outputs:
  studio/designs/<id>.html      — the generated HTML, with CSP injected
  studio/renders/<id>-<vp>.png  — Playwright screenshot
  B:\\projects\\claude\\1930\\out\\redesign-2026-05-10\\
      operator-console-v2.html
      operator-console-v2-desktop.png
      operator-console-v2-mobile.png
      talkie-studio-v2.html
      talkie-studio-v2-desktop.png
      talkie-studio-v2-mobile.png

Run:  python scripts/redesign_1930.py
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


OPERATOR_CONSOLE_BRIEF = """\
A vintage-radio broadcast control room interface for the 1930 voice/talkie
project ('W-AUD 1930 Control'). Functional regions stay the same as the
existing console — Broadcast Deck (audio queue), Signal Board (manifest /
generation metadata), Casting Ledger (ranked ElevenLabs voice candidates),
Release Gates (safety + MCP prune command) — but pushed to a higher craft
level than the current implementation.

Amplify these design moves; do NOT flatten them:
- Vintage-radio cabinet aesthetic: brass, ivory paper, ink, deep teal, and a
  restrained brick red for stop/danger. No purple, no neon, no glass blobs.
- Mid-century deco geometry: hairline rules, generous margin numbers, era-
  appropriate display serif paired with a clean monospaced caption face.
- Tactile materials: subtle paper grain, faint vertical column rules from
  old type galleys, hot-lead-print number indexes on ledger rows.
- A real dial element in the header (not a CSS toy) — concentric brass
  ring, indicator hand pointing at the current broadcast frequency '1930 kHz'.
- A 'tape spool' or analog VU-style meter as the signal-strength indicator
  in Signal Board — animated only at reduced-motion=no-preference.

Content slots (use these exactly; the build script wires real values later):
- Brand: 'W-AUD 1930 Control'
- Subtitle slot: 'Earnest Classic-Hollywood Leading Man · eleven_v3 · cut 2026-05-05 01:15'
- Status pills: '2 auditions · 640 KB scene · 2 blocked'
- Broadcast Deck: 3 audio tracks with rank badge (S, 1, 2), title,
  meta tags ('scene · seed 1930' / 'shared · standard · middle_aged · score 20' /
  'available · american · young · score 18'), inline waveform, play/pause, time scrubber.
- Signal Board: model id pill 'eleven_v3', persona pill 'earnest-leading-man',
  3-line scene manifest with text hashes (truncated 12 chars), safety badges
  (public_manifest · prompt_hidden · v3 · persona_boundary), '2 skipped'.
- Casting Ledger: 7 ranked rows with rank, voice name, source dot
  (shared/available), tag chips (accent/age), score number, status:
  rendered/queued, three-state filter buttons (All / Rendered / Queue).
- Release Gates: 'mcp prune queued' card with command codeblock and Copy
  button, plus three readiness checks (Local proof · Public manifest ·
  Persona boundary).

Hard rules:
- One HTML file, ~14-18KB. Inline <style> only.
- Functional polish first: every interactive element has a hover, focus-
  visible, and active state. Real semantic HTML (<header>, <main>,
  <section aria-labelledby>, <table> for the ledger, <button type=button>).
- Layout: desktop 1440px → 2-column grid (Deck+Meters on top row, Ledger+
  Gates on bottom). Tablet 834px → single column. Mobile 390px →
  collapsed cards, sticky play bar at the bottom.
- WCAG AA contrast everywhere. Focus ring is brass on dark, ink on light.
- prefers-reduced-motion: zero spool/dial animation. Otherwise: a slow
  brass dial sweep, restrained waveform pulse, no parallax, no auto-scroll.
- No external icon CDNs; inline SVG for the dial, spool, and status dots.

What 'distinct' means here: a viewer who saw the current
1930-console-desktop.png and this redesign side-by-side should immediately
read this one as the more confident, professional, era-true version —
not 'modernized', but 'finally drawn properly'.
"""


TALKIE_STUDIO_BRIEF = """\
A 'Talkie Studio' interface — sibling to the operator console — for
auditioning and stitching together multi-voice radio scenes in the 1930
project. Where the operator console is a broadcast cabinet (tight, dense,
ledger-led), this one is a director's table: it sits between the writer
and the broadcast, focused on shaping the cut.

Functional regions:
- 'Scene Bench': the in-progress radio scene, shown as a vertical timeline
  with role labels (announcer / leading-man / announcer), the line text
  preview (first 80 chars), waveform thumbnail, and a play handle.
- 'Voice Drawer': a horizontal scrollable rail of voice cards (8 visible
  before scrolling). Each card: voice name, ElevenLabs id (truncated),
  accent badge, age, source provenance (shared / available), 'try' button.
- 'Cue Sheet': the current script being read, with each line attributed,
  with a Cue button next to each unrendered line and a Rendered checkmark
  next to completed lines.
- 'Director Notes': a compact panel for prompt fragments and constraint
  notes the operator has set for the scene.

Aesthetic: same vocabulary as the operator console (brass, ivory paper,
ink, teal, brick red) but the layout is wider, calmer, and more typographic.
Think 'studio script with margins' rather than 'broadcast cabinet'. The
brand strip across the top is restrained — just 'Talkie Studio · W-AUD 1930'
in the same display serif.

Content slots:
- Scene Bench: 3 timeline rows for the existing earnest-leading-man scene.
- Voice Drawer: 8 voice cards with sample names ('Tom — Warm Smooth and
  Hesitant', 'Toby — Bright and Earnest', 'Bradley — Earnest Narrator',
  'Bill Oxley — Clear Stable Mature', 'David — Confident Professional',
  'Sebastian Everheart — Deep Monotone', 'Rakshit — Deep Romantic
  Expressive', 'Walter Mae — Aged Stage Actor').
- Cue Sheet: 5 lines, 3 rendered, 2 pending.
- Director Notes: 3 short bullets about the persona boundary and the model
  pin (eleven_v3, seed 1930).

Hard rules:
- One HTML file, ~14-18KB. Inline <style> only.
- Real semantic HTML, full keyboard navigation, WCAG AA contrast.
- Desktop 1440px → 3-column (Scene Bench | Cue Sheet | Director Notes),
  with the Voice Drawer pinned across the bottom. Tablet 834px → 2-col
  with Drawer below. Mobile 390px → single column, Drawer scrolls
  horizontally.
- prefers-reduced-motion: only the brass-bar gain meter pulses; no
  card auto-rotate, no waveform animation.
- No CDN scripts, no icon fonts. Inline SVG for everything.

The bar here is the same as the console: this should read as 'someone who
loves radio drama drew this on purpose', not 'I prompted Claude for a UI'.
"""


async def generate_one(
    designer: Designer,
    studio: Studio,
    renderer_inst: Renderer,
    *,
    brief: str,
    name: str,
    tier: str = "best",
) -> dict[str, str]:
    print(f"\n[redesign] generating {name!r} on tier={tier} ...", file=sys.stderr, flush=True)
    t0 = time.monotonic()
    draft = await designer.generate_design(
        brief=brief,
        mode="app_ui",
        viewport="desktop",
        tier=tier,
    )
    elapsed = time.monotonic() - t0
    print(
        f"[redesign] {name}: {len(draft.html):,} bytes in {elapsed:.1f}s "
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
        brief=brief,
        mode="app_ui",
        tier=tier,
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

    renders: dict[str, str] = {"html": str(html_path)}
    for viewport in ("desktop", "mobile"):
        out_path = studio.render_path_for(design_id, viewport)
        written = await renderer_inst.render(
            html_path=str(html_path),
            out_path=out_path,
            viewport=viewport,
            full_page=True,
        )
        if written:
            renders[viewport] = written
            print(f"[redesign] {name}: {viewport} → {written}", file=sys.stderr, flush=True)
        else:
            print(
                f"[redesign] {name}: {viewport} render FAILED — {renderer_inst.last_error}",
                file=sys.stderr,
                flush=True,
            )

    return renders


def copy_to_project(name: str, artifacts: dict[str, str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if "html" in artifacts:
        shutil.copy2(artifacts["html"], OUT_DIR / f"{name}.html")
    for vp in ("desktop", "mobile"):
        if vp in artifacts:
            shutil.copy2(artifacts[vp], OUT_DIR / f"{name}-{vp}.png")


async def main() -> int:
    if not os.environ.get("CLAUDE_DESIGN_STUDIO_DIR"):
        os.environ["CLAUDE_DESIGN_STUDIO_DIR"] = str(_REPO_ROOT / "studio")

    studio = Studio(os.environ["CLAUDE_DESIGN_STUDIO_DIR"])
    designer = Designer()
    renderer_inst = Renderer()

    try:
        operator_artifacts = await generate_one(
            designer,
            studio,
            renderer_inst,
            brief=OPERATOR_CONSOLE_BRIEF,
            name="1930-operator-console-v2",
            tier="best",
        )
        copy_to_project("operator-console-v2", operator_artifacts)

        studio_artifacts = await generate_one(
            designer,
            studio,
            renderer_inst,
            brief=TALKIE_STUDIO_BRIEF,
            name="1930-talkie-studio-v2",
            tier="best",
        )
        copy_to_project("talkie-studio-v2", studio_artifacts)
    finally:
        await renderer_inst.aclose()
        studio.close()

    print(f"\n[redesign] outputs in {OUT_DIR}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
