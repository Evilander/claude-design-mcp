# claude-design-mcp

> A Model Context Protocol server that turns Claude's frontier visual-design
> ability into a persistent design studio — with versioning, parallel variants,
> screenshot rendering, and design-system extraction.

This is **not** a wrapper around `messages.create`. It's a real design REPL.
Designs export to Google DESIGN.md so other tools (Claude Code, Cursor, Stitch)
can consume the system directly — no JSON wrangling.

- `design_create` — generate a self-contained HTML/CSS design from a brief.
- `design_iterate` — refine an existing design, preserving lineage as a tree.
- `design_variants` — fan out N parallel takes along one dimension (color, mood, layout, density…).
- `design_render` — Playwright-rendered screenshots at mobile / tablet / desktop / wide / hd.
- `design_extract_system(format="design-md")` — distill a coherent design system from one or more designs and optionally emit Google DESIGN.md.
- `design_validate_design_md` — lint a DESIGN.md document with Google's validator and surface spec/WCAG results.
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

> **Important on env vars:** the `claude` CLI silently prefers
> `ANTHROPIC_API_KEY` (and `ANTHROPIC_AUTH_TOKEN` / `CLAUDE_CODE_USE_BEDROCK` /
> `CLAUDE_CODE_USE_VERTEX`) over OAuth when any of them are set in your shell.
> claude-design-mcp scrubs these variables from the subprocess environment
> for the duration of each design call so OAuth wins. `--check` will list
> any that were detected so you can decide whether the scrub is what you
> want. To opt out and use your API key / Bedrock / Vertex anyway, set
> `CLAUDE_DESIGN_ALLOW_API_KEY=1`.

## Install

```powershell
# 1. Install Claude Code (https://docs.claude.com/en/docs/claude-code/)
#    and log in:
claude login

# 2. From this repo's directory, install the MCP as a tool:
uv tool install ".[render]"

# 3. Install Chromium for screenshot rendering:
playwright install chromium

# 4. Wire it into Claude Code:
claude mcp add --scope user claude-design -- claude-design-mcp

# 5. Verify everything is wired up, then create local demo designs:
claude-design-mcp --check-json
claude-design-mcp --demo
```

`--check` reports the studio dir, Playwright availability, and the
`claude` CLI version + path. There is no API key to set.
`--check-json` prints the same readiness signal as machine-readable JSON for
installers, CI, and support scripts.
`--demo` creates three fixture designs without making a Claude model call, so
first-contact setup can be tested without OAuth spend or network dependency.

On locked-down Windows hosts, Playwright may be unable to use the default
user temp directory. Set `CLAUDE_DESIGN_PLAYWRIGHT_TMP` to a writable local
folder. If you install Chromium into a project-local folder, point
`CLAUDE_DESIGN_PLAYWRIGHT_BROWSERS_PATH` at it so `design_render` can find it.
`CLAUDE_DESIGN_CHROMIUM_SANDBOX=auto` tries Chromium sandboxing first and falls
back only when the host closes sandboxed pages before rendering.

## Wire it into Claude Code

The `claude mcp add` command above writes the Claude Code config for you. For
manual Claude Desktop setup, use:

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

No env block at all is also fine — the default studio is
`~/.claude-design/studio`. See
`claude_desktop_config.example.json` for a Claude Desktop variant.

## Usage examples

Once wired up, just ask Claude:

- *"Use claude-design to make a hero section for a privacy-focused note app, dark mode, glassmorphism."*
- *"Make 4 variants of `<design-id>` exploring mood — playful, brutalist, editorial, minimal."*
- *"Extract a design system from the last three designs and apply it to a checkout page."*
- *"Extract a DESIGN.md from your last three designs and hand it to Claude Code."*
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
| `CLAUDE_DESIGN_STUDIO_DIR` | `~/.claude-design/studio` | Where designs live. |
| `CLAUDE_DESIGN_AUTO_RENDER` | `auto` | `1`/`0`/`auto` — auto screenshot on create/iterate. |
| `CLAUDE_DESIGN_CLI_PATH` | auto | Optional absolute path to the `claude` CLI. Relative paths are refused. |
| `CLAUDE_DESIGN_PLAYWRIGHT_TMP` | auto | Writable temp directory for Playwright launch/download operations. |
| `CLAUDE_DESIGN_PLAYWRIGHT_BROWSERS_PATH` | auto | Optional browser payload directory for local Playwright installs. |
| `CLAUDE_DESIGN_CHROMIUM_SANDBOX` | `auto` | `auto`, `1`, or `0`; controls Chromium sandbox fallback for screenshots. |
| `CLAUDE_DESIGN_EFFORT` | `low` | Claude Code effort level for design calls. Use `none` to omit. |
| `CLAUDE_DESIGN_THINKING` | `disabled` | Thinking mode for design calls: `disabled`, `adaptive`, or `none`. |
| `CLAUDE_DESIGN_MAX_BUFFER_BYTES` | `8388608` | SDK stdout JSON buffer cap for large HTML responses. |
| `CLAUDE_DESIGN_ALLOW_API_KEY` | `0` | Set `1` to keep `ANTHROPIC_API_KEY` / Bedrock / Vertex env vars in the subprocess instead of scrubbing for OAuth. |
| `CLAUDE_DESIGN_ENV_FILE` | unset | Optional explicit dotenv file. Only `CLAUDE_DESIGN_*` keys are loaded; cwd `.env` files are ignored. |

Authentication comes from the local `claude` CLI's OAuth session — there
is no API-key env var to set.

## License

MIT.
