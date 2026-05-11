# DESIGN.md ↔ SystemRecord mapping spec (emitter v0)

This document is binding for tonight's commit. The emitter in
`src/claude_design/design_md.py` MUST produce output matching this mapping. If
the upstream spec changes, this file is updated FIRST, code follows.

## Canonical sections (per github.com/google-labs-code/design.md, fetched 2026-05-10)

Eight ordered top-level H2 sections. Variants are inline component entries
(e.g. `button-primary-hover`), NOT a separate section.

1. Overview
2. Colors
3. Typography
4. Layout
5. Elevation & Depth
6. Shapes
7. Components
8. Do's and Don'ts

## YAML front matter

Required. Emitted before the first H2.

```yaml
---
name: <SystemRecord.name or "untitled-system">
generated_by: claude-design-mcp
generated_at: <ISO 8601 UTC of emission time>
source_system_id: <SystemRecord.id>
source_designs: <SystemRecord.source_ids as a YAML list>
spec_version: "0.1"
---
```

We deliberately omit a `version` field for the system itself — DESIGN.md spec
allows it but our SystemRecord has no version concept yet. `spec_version`
tracks which DESIGN.md spec we targeted.

## Section-by-section emission rules

### 1. Overview

```markdown
## Overview

<SystemRecord.summary or "A design system extracted by claude-design-mcp.">
```

- If `summary` is empty, emit the fallback string above.
- One paragraph. No principles or component summaries here — those have their
  own sections.

### 2. Colors

Source: `SystemRecord.tokens.color` (a dict like `{bg, fg, accent, muted, …}`)
plus any other keys under `tokens.color`.

```markdown
## Colors

| Token | Value | Role |
|-------|-------|------|
| bg    | #eee5d2 | Page background |
| fg    | #171412 | Primary ink |
| accent | #d0a64f | Brass accent / highlight |
| muted | #6b5b35 | Secondary type |
```

Rules:
- Emit ALL keys present under `tokens.color`. Sort by canonical order
  (`bg, fg, accent, muted, …`) then alphabetically for unknown keys.
- Token name in column 1 is the key from the dict.
- `Role` column gets a humanized description derived from the key:
  - `bg` → "Page background"
  - `fg` → "Primary ink"
  - `accent` → "Accent / highlight"
  - `muted` → "Secondary / muted"
  - any other key → key humanized (snake → Title Case).
- If `tokens.color` is empty or missing, emit the section header and a single
  line: `_No colors recorded._` Do NOT skip the section.
- Hex values are emitted verbatim. Non-hex values are emitted as-is in a
  monospace inline code span: `` `currentColor` ``.

### 3. Typography

Source: `SystemRecord.tokens.type` (or `tokens.typography` — accept both keys,
prefer `type` if both exist).

```markdown
## Typography

| Role | Family |
|------|--------|
| display | Georgia, "Times New Roman", serif |
| body | Inter, system-ui, sans-serif |
| mono | "JetBrains Mono", ui-monospace, monospace |

### Scale

| Step | Size |
|------|------|
| 0 | 12px |
| 1 | 14px |
| ... | ... |
```

Rules:
- Family table: emit display/body/mono in that order if present, then any other
  keys alphabetically.
- Scale subsection: emitted only if `tokens.scale` is a non-empty dict. Sort
  numeric step keys ascending. Non-numeric keys come after numeric in
  insertion order.
- Both subsections missing → `_No typography recorded._`

### 4. Layout

Source: `SystemRecord.tokens.space` plus `tokens.layout` if present.

```markdown
## Layout

- **Base unit:** <tokens.space.unit or "8px">
- **Rhythm:** <tokens.space.rhythm or "1.5">
- **Container max:** <tokens.layout.container or "1320px">
- **Gutter:** <tokens.layout.gutter or omit>
```

Rules:
- Emit bullets only for keys actually present. Defaults shown above apply
  when the parent dict exists but the specific key doesn't.
- If neither `space` nor `layout` exists, emit `_No layout tokens recorded._`

### 5. Elevation & Depth

Source: `SystemRecord.tokens.shadow`.

```markdown
## Elevation & Depth

| Level | Shadow |
|-------|--------|
| low | 0 1px 2px rgba(0,0,0,.08) |
| med | 0 4px 12px rgba(0,0,0,.12) |
| high | 0 14px 22px rgba(0,0,0,.35) |
```

Rules:
- Sort by canonical order `low, med, high` then alphabetically.
- Empty → `_No elevation tokens recorded._`

### 6. Shapes

Source: `SystemRecord.tokens.radius` plus `tokens.border` if present.

```markdown
## Shapes

| Token | Value |
|-------|-------|
| radius.sm | 2px |
| radius.md | 6px |
| radius.lg | 12px |
| border.hairline | 1px solid rgba(0,0,0,.12) |
```

Rules:
- Prefix `radius.` and `border.` to keys to disambiguate.
- Empty → `_No shape tokens recorded._`

### 7. Components

Source: `SystemRecord.components` — a list of `{name, css, html}` dicts.

```markdown
## Components

### button-primary

<short narrative if SystemRecord.components[i].notes exists, else 1-line stub>

**HTML**

```html
<button class="btn-primary">Save changes</button>
```

**CSS**

```css
.btn-primary { ... }
```

### card

...
```

Rules:
- One `### <name>` heading per component.
- Each component entry has `**HTML**` + fenced `html` block (verbatim, no
  escaping), then `**CSS**` + fenced `css` block.
- If `html` is missing, emit `_(no HTML recorded)_` below `**HTML**`.
- If `css` is missing, emit `_(no CSS recorded)_` below `**CSS**`.
- Variants are component entries with names like `button-primary-hover` —
  treat them like any other component, do NOT special-case.
- If `components` is empty, emit the section header and
  `_No components recorded._`

### 8. Do's and Don'ts

Source: `SystemRecord.principles` — a list of imperative strings.

```markdown
## Do's and Don'ts

**Do**

- Hero claims the page — one element dominates.
- Use the ledger column rules to anchor data-dense panels.

**Don't**

- Use numbered `01 / 02 / 03` section headers.
- Stack four equal-weight quadrants.
```

Rules:
- A principle is a "Do" if it does NOT start with one of `do not`, `don't`,
  `never`, `avoid`, `stop`, `kill` (case-insensitive after trim).
- Otherwise it's a "Don't" and the leading directive word is stripped from
  the bullet text:
  - `"Don't use numbered headers"` → `Use numbered headers`
  - `"Never stack four cards"` → `Stack four cards`
  - `"Avoid generic SaaS chrome"` → `Generic SaaS chrome`
- If only Dos or only Don'ts exist, emit only the present sub-heading.
- If both lists are empty, emit `_No principles recorded._`

## Edge cases

- **Unicode in token values:** emit verbatim, UTF-8 encoded.
- **HTML in component bodies:** never auto-escape; component HTML is meant to
  be raw. The receiving DESIGN.md consumer is responsible for sandboxing.
- **CSS containing triple backticks:** very unlikely from our system prompt
  but defend with fence-length escalation — if the body contains ` ``` `, use
  ` ```` ` for the fence.
- **Very long components (>8 KB CSS):** emit fully; size limits are caller
  responsibility, not the emitter's.
- **Null / None values:** treat as absent; do not emit `null` or `None`.

## Output validation

The emitter's first integration test asserts:
1. Front matter is a valid YAML document.
2. All 8 H2 headings appear, in order, exactly once.
3. No two `### <component-name>` headings collide.
4. `npx @google/design.md lint` exits 0 (when the CLI is installed; skip
   assertion otherwise).

## Out of scope tonight

- Importer (`parse_design_md`) — M2.
- Diffing two DESIGN.md files — M2.
- Tailwind / shadcn export — M2.
- WCAG contrast validation inside the emitter — `design_validate_design_md`
  shells out to `@google/design.md lint` for that.

## Function signatures Codex must implement

```python
def emit_design_md(system: SystemRecord, *, generated_at: datetime | None = None) -> str:
    """Render a SystemRecord as a DESIGN.md document.

    `generated_at` defaults to datetime.now(timezone.utc). Pass an explicit
    value for deterministic test output. Returns the full markdown string
    starting with `---\\n` front matter.
    """

def validate_design_md_via_cli(path: str, *, timeout_s: float = 30.0) -> dict:
    """Run `npx @google/design.md lint <path>`; return a structured result.

    Returns: {"ok": bool | None, "warnings": list[str], "errors": list[str],
              "wcag_failures": list[dict], "raw_output": str}
    `ok` is None when the CLI is not available; warnings/errors are empty in
    that case and raw_output explains.
    """
```
