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

## Authentication

claude-design-mcp uses your **existing Claude Code OAuth login** — no
`ANTHROPIC_API_KEY`, no separate billing. Every model call is routed
through the local `claude` CLI via the
[Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/python),
inheriting whatever OAuth session Claude Code is currently using.

If `claude` runs interactively for you, this server can call Claude.

## Install

```powershell
# 1. Install Claude Code (https://docs.claude.com/en/docs/claude-code/)
#    and log in:
claude login

# 2. From this repo's directory:
pip install -e .

# 3. Optional: enable screenshot rendering
pip install -e ".[render]"
playwright install chromium

# 4. Verify everything is wired up
claude-design-mcp --check
claude-design-mcp --check-json
```

`--check` reports the studio dir, Playwright availability, and the
`claude` CLI version + path. There is no API key to set.
`--check-json` prints the same readiness signal as machine-readable JSON for
installers, CI, and support scripts.

## Wire it into Claude Code

Add to `~/.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "claude-design": {
      "command": "claude-design-mcp",
      "args": [],
      "env": {
        "CLAUDE_DESIGN_STUDIO_DIR": "${HOME}/.claude-design/studio"
      }
    }
  }
}
```

No env block at all is also fine — every variable has a default. See
`claude_desktop_config.example.json` for a Claude Desktop variant.

## Usage examples

Once wired up, just ask Claude:

- *"Use claude-design to make a hero section for a privacy-focused note app, dark mode, glassmorphism."*
- *"Make 4 variants of `<design-id>` exploring mood — playful, brutalist, editorial, minimal."*
- *"Extract a design system from the last three designs and apply it to a checkout page."*
- *"Open the studio contact sheet."*

## How it works

```
brief ─▶ designer.py ─▶ claude_agent_sdk.query() ─▶ HTML + JSON metadata
                              (subprocesses the `claude` CLI; OAuth-backed)
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

Each call sets `tools=[]`, `allowed_tools=[]`, `permission_mode="dontAsk"`,
`--disable-slash-commands`, `--no-session-persistence`, isolated setting
sources, and `max_turns=1` so a design generation is exactly that — one turn
of text-out, no filesystem access, no shell access, no MCP recursion, and no
conversation persistence. The warm Playwright browser amortizes Chromium launch
cost across renders.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `CLAUDE_DESIGN_MODEL` | `claude-sonnet-4-6` | Fast tier model. |
| `CLAUDE_DESIGN_MODEL_OPUS` | `claude-opus-4-7` | Best tier model. |
| `CLAUDE_DESIGN_STUDIO_DIR` | `./studio` | Where designs live. |
| `CLAUDE_DESIGN_AUTO_RENDER` | `auto` | `1`/`0`/`auto` — auto screenshot on create/iterate. |
| `CLAUDE_DESIGN_CLI_PATH` | auto | Optional explicit path to the `claude` CLI. |
| `CLAUDE_DESIGN_EFFORT` | `low` | Claude Code effort level for design calls. Use `none` to omit. |
| `CLAUDE_DESIGN_THINKING` | `disabled` | Thinking mode for design calls: `disabled`, `adaptive`, or `none`. |
| `CLAUDE_DESIGN_MAX_BUFFER_BYTES` | `8388608` | SDK stdout JSON buffer cap for large HTML responses. |

Authentication comes from the local `claude` CLI's OAuth session — there
is no API-key env var to set.

## License

MIT.
