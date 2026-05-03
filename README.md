# claude-design-mcp

> A Model Context Protocol server that turns Claude's frontier visual-design
> ability into a persistent design studio — with versioning, parallel variants,
> screenshot rendering, and design-system extraction.

This is **not** a wrapper around `messages.create`. It's a real design REPL:

- `design_create` — generate a self-contained HTML/CSS design from a brief.
- `design_iterate` — refine an existing design, preserving lineage as a tree.
- `design_variants` — fan out N parallel takes along one dimension (color, mood, layout, density…).
- `design_render` — Playwright-rendered screenshots at mobile / tablet / desktop / wide / hd.
- `design_extract_system` — distill a coherent design system (tokens, components, principles) from one or more designs.
- `design_apply_system` — generate a new design that strictly follows a saved system.
- `design_get` / `design_list` — browse the studio.
- `design_export` — package any design or system as a portable folder + zip.
- `design_preview` — open a contact-sheet of every design in your default browser.

Designs live on disk as plain `.html` files in `studio/designs/` — nothing locked
in a database, nothing stuck behind a server. The SQLite layer is just an index.

## Why this exists

When you ask Claude for "a design" in normal chat, the output evaporates the
moment the conversation ends. You can't iterate on it without copy-pasting
huge HTML blobs. You can't compare three takes side-by-side. You can't say
"apply the design system from yesterday's hero to today's checkout page."

This MCP fixes all of that.

## Install

```powershell
# From this directory:
pip install -e .

# Optional: enable screenshot rendering
pip install -e ".[render]"
playwright install chromium
```

Set your API key:

```powershell
copy .env.example .env
# then edit .env and put your ANTHROPIC_API_KEY in
```

Verify the install:

```powershell
claude-design-mcp --check
```

## Wire it into Claude Code

Add to `~/.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "claude-design": {
      "command": "claude-design-mcp",
      "args": [],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

Or via the Python module form:

```json
{
  "mcpServers": {
    "claude-design": {
      "command": "python",
      "args": ["-m", "claude_design"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "CLAUDE_DESIGN_STUDIO_DIR": "${HOME}/.claude-design/studio"
      }
    }
  }
}
```

See `claude_desktop_config.example.json` for a Claude Desktop variant.

## Usage examples

Once wired up, just ask Claude:

- *"Use claude-design to make a hero section for a privacy-focused note app, dark mode, glassmorphism."*
- *"Make 4 variants of `<design-id>` exploring mood — playful, brutalist, editorial, minimal."*
- *"Extract a design system from the last three designs and apply it to a checkout page."*
- *"Open the studio contact sheet."*

## How it works

```
brief ─▶ designer.py ─▶ Anthropic Messages API ─▶ HTML + JSON metadata
                              (system prompt cached via cache_control)
                                          │
                                          ▼
              studio.py ◀─ persistence ─◀ DesignDraft
                  │
                  ▼
         studio/designs/<id>.html        ─▶ file:// preview
         studio/renders/<id>-<vp>.png    ◀─ renderer.py (Playwright)
         studio/_index.html              ◀─ preview.py (contact sheet)
         studio/designs.db               ◀─ index + lineage
```

The system prompt is sent with `cache_control: {"type": "ephemeral"}`. The
first call pays for ~2-3k tokens of design instructions; every call within the
next ~5 minutes reads from the cache for a fraction of the cost.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Required. |
| `CLAUDE_DESIGN_MODEL` | `claude-sonnet-4-6` | Fast tier model. |
| `CLAUDE_DESIGN_MODEL_OPUS` | `claude-opus-4-7` | Best tier model. |
| `CLAUDE_DESIGN_STUDIO_DIR` | `./studio` | Where designs live. |
| `CLAUDE_DESIGN_AUTO_RENDER` | `auto` | `1`/`0`/`auto` — auto screenshot on create/iterate. |

## License

MIT.
