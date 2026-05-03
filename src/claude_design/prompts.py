"""System and operator prompts for claude-design-mcp.

The DESIGN_SYSTEM_PROMPT is the single most important asset in this package — it
is what turns a generic LLM call into "Claude's design ability." It is sent with
``cache_control: {"type": "ephemeral"}`` so it is paid for once and reused across
all subsequent calls in a session, keeping iteration latency and cost low.
"""

from __future__ import annotations

from textwrap import dedent

# ---------------------------------------------------------------------------
# The design system prompt. Verbose by design — every paragraph here removes
# a class of bad outputs we have observed in practice.
# ---------------------------------------------------------------------------

DESIGN_SYSTEM_PROMPT = dedent(
    """
    You are operating as **Claude's frontier design surface** — a senior visual designer
    and front-end engineer fused into one. Your output is rendered directly in a
    browser; it is not a sketch, not a wireframe, not a placeholder. Treat every call
    as a finished portfolio piece.

    ## Output contract

    Return EXACTLY one fenced code block, language `html`, containing a complete,
    self-contained HTML document beginning with `<!doctype html>`. No prose before or
    after the code block. No commentary. The document must:

    1. Be a single file. Inline all CSS in a `<style>` block. Inline any JS in a
       `<script>` block. Do not use external stylesheets or build steps.
    2. Be loadable from `file://` with no external dependencies *except*:
         • Google Fonts via `<link rel="preconnect">` + a single Google Fonts CSS link.
         • Free SVG icons inlined directly (no icon CDNs).
         • Unsplash / picsum / placehold.co for placeholder imagery only when needed.
       Do NOT import Tailwind, Bootstrap, Alpine, React, or any other framework.
    3. Render correctly on first paint with no JS dependency. JS may enhance, never gate.
    4. Be responsive: mobile (390px), tablet (834px), and desktop (1440px) must all
       look intentional, not just shrunk.
    5. Respect `prefers-reduced-motion: reduce`.
    6. Use semantic HTML (`<header>`, `<main>`, `<nav>`, `<section>`, `<article>`,
       `<footer>`) and meet WCAG AA contrast.

    ## Visual standards (non-negotiable)

    - **No generic SaaS look.** No purple-to-blue gradients on a white card with
      rounded corners. No "Get Started" + three feature columns + testimonials.
      If your first instinct is a centered hero with a subhead and two buttons,
      do something else.
    - **Composition over centering.** Use asymmetry, off-grid placement, layered
      panels, ruled lines, marginalia, sidebars, vertical text, kicker labels —
      whichever serves the brief. Avoid the vertically-stacked-card cliché.
    - **Real type systems.** Pair fonts with intent (e.g., a display serif against
      a grotesk; a mono accent for metadata). Set tight, deliberate hierarchy
      using size, weight, tracking, and case — not just bold/regular.
    - **Cohesive color.** Pick a palette (3–6 colors) that says something. Avoid
      Bootstrap defaults. Earth tones, monochrome with one accent, neon on
      bone, paper-and-ink — choose a posture and commit. State `--color-*` tokens
      in `:root`.
    - **Distinctive details.** Add at least two of: precise hairline rules, a
      ticker/marquee, a number index, a footnote, a hand-drawn or noise texture
      (CSS-only), a status pill, a draggable seek bar, a custom focus ring, an
      animated cursor, a marginal kicker, a section index in the corner.
    - **Tasteful motion.** Spring-feeling easing (`cubic-bezier(0.2, 0.9, 0.3, 1.2)`),
      400-700ms entrances, gated by `prefers-reduced-motion`. No motion on body
      typography. No infinite spinners as decoration.
    - **Imagery is optional.** When you use images, prefer Unsplash with deliberate
      crops, or compose imagery from CSS gradients/SVG — never decorative stock
      photos chosen at random.

    ## Information architecture

    Read the brief carefully. Identify:
      (a) the audience and their state of mind,
      (b) the single most important action or moment, and
      (c) two or three supporting beats.
    Compose around those, not around boilerplate sections. If the brief is short,
    invent specific, believable content (real-sounding product names, real-sounding
    quotes, plausible numbers) — never use "Lorem ipsum" or "Feature One / Feature
    Two." Filler text is a critique-worthy bug.

    ## Document head requirements

    Always include:
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>...</title>            (concise, specific, not "Untitled")
      <meta name="description" ...> (one sentence, specific)
      <meta name="generator" content="claude-design-mcp">

    ## Self-describing metadata

    Immediately AFTER the closing ``` of the html block, append a second fenced
    block, language `json`, containing a single JSON object describing what you
    built:

    ```json
    {
      "title": "...",
      "summary": "one-sentence description",
      "palette": ["#...", "#..."],
      "fonts": ["Family A", "Family B"],
      "tokens": {
        "color": { "bg": "#...", "fg": "#...", "accent": "#...", "muted": "#..." },
        "type":  { "display": "...", "body": "...", "mono": "..." },
        "space": { "unit": "8px", "rhythm": "1.5" },
        "motion": { "easing": "cubic-bezier(...)", "duration": "..." },
        "radius": "..."
      },
      "moves": ["short labels for the 3-7 design moves you made"],
      "notes": "what to try next, or what you would push further with more time"
    }
    ```

    Both blocks are required. Nothing else outside the two blocks.

    ## What "great" looks like

    - The design has a *posture* — opinionated, specific, willing to be wrong.
    - Every region earns its place. If a section could be deleted without loss,
      delete it before shipping.
    - The page reads like it was made by one person who cared, not assembled
      from a kit.
    - On reload, the design is identifiable from a 50px thumbnail.
    """
).strip()


# ---------------------------------------------------------------------------
# Brief-shaping prompts for each tool.
# These are short user-role messages; the bulk of the instructional weight
# lives in DESIGN_SYSTEM_PROMPT (which is cached).
# ---------------------------------------------------------------------------


def create_user_prompt(
    brief: str,
    mode: str,
    viewport: str,
    references: list[dict] | None = None,
) -> str:
    """Build the user message for ``design_create``."""
    parts: list[str] = []
    parts.append(f"# New design brief\n\n{brief.strip()}")
    parts.append(f"\n## Mode\n{mode}")
    parts.append(f"\n## Primary viewport\n{viewport}")
    if references:
        parts.append("\n## Style references")
        for ref in references:
            tokens = ref.get("tokens") or {}
            palette = ref.get("palette") or []
            parts.append(
                f"- **{ref.get('name') or ref.get('id')}** — palette {palette}, "
                f"tokens {tokens}. Borrow the *posture*, not the literal layout."
            )
    parts.append(
        "\nReturn the full HTML document and the JSON metadata block as specified "
        "in your system instructions."
    )
    return "\n".join(parts)


def iterate_user_prompt(prior_html: str, prior_meta: dict, instructions: str) -> str:
    """Build the user message for ``design_iterate``.

    We pass the prior design's HTML as a fenced block so Claude can edit precisely.
    """
    meta_summary = (
        f"Title: {prior_meta.get('title')!r}\n"
        f"Palette: {prior_meta.get('palette')}\n"
        f"Moves: {prior_meta.get('moves')}"
    )
    return dedent(
        f"""
        # Iterate on the design below

        ## What to change
        {instructions.strip()}

        ## Prior design metadata
        {meta_summary}

        ## Prior design HTML
        ```html
        {prior_html}
        ```

        Produce a *new* complete HTML document plus its JSON metadata block, applying
        the requested changes. Preserve everything that was working unless the
        instructions explicitly say to change it. Do not regress quality.
        """
    ).strip()


def variants_user_prompt(
    base_brief: str | None,
    base_html: str | None,
    base_meta: dict | None,
    dimension: str,
    index: int,
    count: int,
) -> str:
    """Build the user message for one variant in a parallel batch."""
    header = f"# Variant {index + 1} of {count} — exploring `{dimension}`"
    if base_brief and not base_html:
        body = (
            f"## Brief\n{base_brief.strip()}\n\n"
            f"This is variant {index + 1} of {count}. Explore the **{dimension}** "
            f"axis aggressively while keeping the brief's intent intact. The other "
            f"variants are exploring the same axis differently — make this one "
            f"distinct from any obvious first answer."
        )
    else:
        meta_summary = (
            f"Palette: {(base_meta or {}).get('palette')}\n"
            f"Moves: {(base_meta or {}).get('moves')}"
        )
        body = (
            f"## Base design metadata\n{meta_summary}\n\n"
            f"## Base design HTML\n```html\n{base_html or ''}\n```\n\n"
            f"This is variant {index + 1} of {count} branching from the base design. "
            f"Explore the **{dimension}** axis. Keep the brief's content intact "
            f"unless the dimension demands a content shift."
        )
    return f"{header}\n\n{body}\n\nReturn the HTML and JSON blocks as specified."


def extract_system_user_prompt(designs: list[dict]) -> str:
    """Build the user message for ``design_extract_system``."""
    bullets: list[str] = []
    for d in designs:
        bullets.append(
            f"### {d.get('name') or d.get('id')}\n"
            f"```html\n{d.get('html', '')[:6000]}\n```"
        )
    joined = "\n\n".join(bullets)
    return dedent(
        f"""
        # Extract a coherent design system from the designs below

        Return a single fenced `json` block with this shape — no other prose:

        ```json
        {{
          "name": "short kebab-case system name",
          "summary": "one-sentence posture",
          "tokens": {{
            "color": {{ "bg": "#...", "fg": "#...", "accent": "#...", "muted": "#...", "...": "..." }},
            "type":  {{ "display": "Family, fallbacks", "body": "...", "mono": "..." }},
            "scale": {{ "0": "12px", "1": "14px", "2": "16px", "3": "20px", "4": "24px", "5": "32px", "6": "48px", "7": "72px" }},
            "space": {{ "unit": "8px", "rhythm": "1.5" }},
            "radius": {{ "sm": "...", "md": "...", "lg": "..." }},
            "motion": {{ "easing": "...", "fast": "180ms", "med": "320ms", "slow": "560ms" }},
            "shadow": {{ "low": "...", "high": "..." }}
          }},
          "components": [
            {{ "name": "button-primary", "css": "...", "html": "<button class='btn'>...</button>" }},
            {{ "name": "card", "css": "...", "html": "..." }}
          ],
          "principles": ["3-6 short imperative principles unique to this system"]
        }}
        ```

        Be opinionated. If the designs disagree, pick the strongest direction and
        say so in `principles`. Components must be drop-in usable.

        ## Designs

        {joined}
        """
    ).strip()


def apply_system_user_prompt(system: dict, brief: str, mode: str) -> str:
    """Build the user message for ``design_apply_system``."""
    import json as _json

    tokens_blob = _json.dumps(system.get("tokens", {}), indent=2)
    components_blob = _json.dumps(system.get("components", []), indent=2)
    principles = system.get("principles", []) or []

    return dedent(
        f"""
        # New design — apply the design system below verbatim

        ## Brief
        {brief.strip()}

        ## Mode
        {mode}

        ## Design system tokens (use exactly these CSS variable values)
        ```json
        {tokens_blob}
        ```

        ## Reusable components (drop in or extend; do not contradict their style)
        ```json
        {components_blob}
        ```

        ## Principles
        {chr(10).join(f"- {p}" for p in principles)}

        Produce the HTML + JSON metadata blocks as specified in your system
        instructions. The new design must look like it ships from the same studio
        as the system above.
        """
    ).strip()
