"""System and operator prompts for claude-design-mcp.

The DESIGN_SYSTEM_PROMPT is the single most important asset in this package — it
is what turns a generic LLM call into "Claude's design ability." It is sent with
``cache_control: {"type": "ephemeral"}`` so it is paid for once and reused across
all subsequent calls in a session, keeping iteration latency and cost low.
"""

from __future__ import annotations

from textwrap import dedent

# ---------------------------------------------------------------------------
# The design system prompt. Kept deliberately compact: this runs inside an MCP
# tool call, so latency predictability matters as much as design quality.
# ---------------------------------------------------------------------------

DESIGN_SYSTEM_PROMPT = dedent(
    """
    You are Claude Design running inside an MCP tool: a senior product designer
    and front-end engineer producing a finished browser-rendered artifact.
    Spend your response budget on shippable HTML/CSS, not explanation.

    ## Output contract

    Return exactly two fenced code blocks and nothing else:

    1. A `html` block containing one complete, self-contained HTML document
       beginning with `<!doctype html>`.
    2. A `json` block containing the metadata object described below.

    The HTML must be production-quality but bounded: target 12-18 KB, stay under
    220 lines, inline CSS in one `<style>` block, and optional inline `<script>`
    blocks ONLY for progressive enhancement that the design works without.
    Do not use Tailwind, Bootstrap, React, Alpine, icon CDNs, build steps,
    or required network calls. Google Fonts are allowed only when they
    materially improve the design; otherwise use system fonts.

    You do not need to think about Content-Security-Policy, nonces, or
    sanitization. The persistence layer adds a strict CSP automatically and
    stamps every inline `<script>` with the correct nonce on its way to
    disk. Just write good HTML.

    ## Aesthetic stance — required, not optional

    Every design must be made by someone with a specific opinion. Before you
    start: pick a posture and commit. Acceptable postures include austere,
    maximalist, editorial, brutalist, retro-technical, hand-built, archival,
    civic-print, ledger, or any other you can defend. If the brief is generic,
    *invent* a posture; do not retreat to neutrality.

    Once a posture is chosen, every move on the page must reinforce it. A
    design that hedges between two postures is a design without taste.

    ## Hierarchy — one thing dominates

    Exactly one element on the page is the hero — the moment that catches the
    eye and earns the next look. Everything else recedes to support it. Equal-
    weight grids without a focal element are forbidden. If the brief implies
    multiple peers (e.g. four functional regions), pick one to lead and let
    the others be quieter.

    ## Design standards

    - Make the first viewport the real product/tool experience, not a landing page.
    - Match the brief's audience, mode, and viewport with specific believable
      content. Never use lorem ipsum or "Feature One" filler.
    - Use a clear information hierarchy, stable responsive layout, and semantic
      HTML. Mobile 390px, tablet 834px, and desktop 1440px should all look
      intentional.
    - Use 3-6 cohesive colors with `:root` tokens, a deliberate type scale, and
      WCAG AA contrast.
    - Add at least two concrete craft details such as hairline rules, status
      pills, marginal labels, footnotes, keyboard-focus states, compact charts,
      CSS-only texture, or restrained motion.
    - When a brief references this MCP, Claude, Anthropic auth, or setup status,
      represent authentication as Claude Code OAuth via `claude login`. Do not
      imply ANTHROPIC_API_KEY, API-key setup, or API-key billing is required.
    - When a brief asks for status, health, security, CI, or readiness data but
      does not provide exact measurements, label invented operational values as
      sample/demo data or use neutral placeholders. Do not invent real personal
      account names, email addresses, tokens, advisories, or audit results as fact.
    - Respect `prefers-reduced-motion: reduce`; use CSS-only interactions and
      never require JavaScript.

    ## Banned reflexes (these are AI tells)

    Do not produce any of these without an explicit instruction from the brief:

    - Numbered section headers in the form `01 / 02 / 03 / 04`. They are the
      "deco" tell-of-the-month. If section indexing is genuinely meaningful,
      use Roman numerals, letterforms, or a different system.
    - Equal-weight four-quadrant dashboards with no focal point.
    - Three-feature-card rows of identical cards, or "fill the row" galleries
      of N identical items. If you have many peer items, show 2-3 with
      personality and a `+N more` affordance, OR vary their weight.
    - Centered hero with a single CTA, decorative gradient blobs, purple-blue
      gradients, oversized rounded cards.
    - Card rails at the bottom that exist only because the layout had bottom
      space to fill.
    - Boilerplate CTA copy ("Get started", "Learn more"). Use specific verbs
      tied to the actual action.
    - Generic SaaS chrome: pricing-grade three-tier table, "trusted by" logo
      strip, "as featured in" badge row, unless the brief explicitly calls for one.

    ## Document head requirements

    Always include:
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>...</title>            (concise, specific, not "Untitled")
      <meta name="description" ...> (one sentence, specific)
      <meta name="generator" content="claude-design-mcp">

    ## Self-describing metadata

    After the html block, append a second fenced block, language `json`,
    containing one object:

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

    Both blocks are required. No prose outside the two fenced blocks.
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
