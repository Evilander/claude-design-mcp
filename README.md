# Claude Design MCP

[![Tests](https://github.com/Evilander/claude-design-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/Evilander/claude-design-mcp/actions/workflows/test.yml)

Claude Design MCP turns Claude Code into a persistent design studio. It gives Claude MCP tools for generating HTML/CSS designs, iterating on them, comparing variants, rendering screenshots, extracting reusable design systems, and exporting Google `DESIGN.md` files.

It is not a thin prompt wrapper. Designs are saved as plain HTML on disk, indexed in SQLite, lineage is preserved, screenshots can be rendered through Playwright, and every model call is routed through the local Claude Code OAuth session instead of an Anthropic API key.

## What You Get

| Capability | What it does |
| --- | --- |
| Persistent designs | Stores every design as a browsable `.html` file under a local studio directory. |
| Iteration history | Keeps parent/child lineage so agents can refine a design without losing the original. |
| Parallel variants | Fans out multiple takes across mood, layout, palette, density, or any other dimension. |
| Screenshot rendering | Uses Playwright to render mobile, tablet, desktop, wide, and HD PNGs. |
| Contact-sheet preview | Builds a local gallery of the studio so designs can be compared quickly. |
| Design-system extraction | Distills tokens, components, principles, and optional Google `DESIGN.md` output. |
| Safe export | Packages designs or systems as portable folders and zip files. |
| First-contact demo | Creates local fixture designs without spending OAuth/model calls. |

## Quick Start

Prerequisites:

- Python 3.10 or newer.
- [`uv`](https://github.com/astral-sh/uv) for local tool installation.
- Claude Code installed and logged in with OAuth.

**From PyPI** (recommended once `v0.2.0` is published):

```powershell
claude login
uv tool install "claude-design-mcp[render]"
playwright install chromium

claude mcp add --scope user claude-design -- claude-design-mcp
claude-design-mcp --check-json
claude-design-mcp --demo
```

**From source** (current path until the PyPI release lands):

```powershell
git clone https://github.com/Evilander/claude-design-mcp.git
cd claude-design-mcp

claude login
uv tool install ".[render]"
playwright install chromium

claude mcp add --scope user claude-design -- claude-design-mcp
claude-design-mcp --check-json
claude-design-mcp --demo
```

`--check-json` prints machine-readable readiness diagnostics for the Claude CLI, studio path, Playwright, temp directory, and browser payload. `--demo` creates three local demo designs without calling a model, which makes install validation cheap and repeatable.

> **Render extra:** the `[render]` qualifier installs Playwright. Without it, design generation and persistence still work; only screenshot rendering is disabled. `--check-json` reports this explicitly.

## Using It From Claude

After registration, ask Claude Code for design work naturally:

- "Use claude-design to create a dashboard for a court calendar system, dense but calm."
- "Make 4 variants of this design: editorial, utilitarian, playful, and luxury."
- "Iterate on the second variant and make the empty state clearer."
- "Extract a design system from the last three designs and apply it to a checkout page."
- "Export a DESIGN.md from this system so another coding agent can use it."
- "Open the studio contact sheet."

## MCP Tools

| Tool | Purpose |
| --- | --- |
| `design_create` | Generate a self-contained HTML/CSS design from a brief. |
| `design_iterate` | Refine an existing design while preserving lineage. |
| `design_variants` | Generate parallel alternatives from a source brief or design. |
| `design_render` | Render a saved design to PNG at a named viewport. |
| `design_preview` | Build and open a local contact-sheet gallery. |
| `design_extract_system` | Extract tokens, components, and principles from one or more designs. |
| `design_validate_design_md` | Validate `DESIGN.md` output against Google's parser and lint rules. |
| `design_apply_system` | Create a new design constrained by an extracted system. |
| `design_get` | Fetch a design summary and optional HTML. |
| `design_list` | Browse saved designs with pagination and search. |
| `design_export` | Export a design or system as a folder plus zip archive. |

## Security Model

Model-authored HTML is treated as untrusted.

- Claude calls run through the local `claude` CLI with OAuth by default.
- `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Bedrock, and Vertex env vars are scrubbed from Claude subprocesses unless `CLAUDE_DESIGN_ALLOW_API_KEY=1` is set.
- Claude design calls use no tools, no slash commands, no session persistence, one turn, and isolated settings.
- Generated HTML is saved with a strict Content Security Policy.
- Inline scripts receive a fresh CSP nonce; model-authored nonces are stripped. Inline event handlers (`onclick`, `onload`, etc.) are blocked by the CSP via `script-src 'nonce-...'` + absence of `'unsafe-inline'`.
- Persisted design HTML is capped at 2 MiB. Larger model output (e.g. prompt-injected base64 amplification) is refused at write time with a clear error.
- Playwright rendering disables JavaScript, blocks service workers, uses a fresh browser context, and aborts requests outside the local file plus approved image/font hosts.
- Export paths refuse traversal, symlink, junction, and reparse-point staging targets.
- Cwd `.env` files are ignored. Only an explicit `CLAUDE_DESIGN_ENV_FILE` is loaded, and only `CLAUDE_DESIGN_*` keys are accepted.

This setup still allows visual HTML/CSS exploration while making prompt-injected exfiltration paths much harder to reach.

## DESIGN.md Export

Claude Design MCP can emit and validate Google `DESIGN.md` documents:

```text
design_extract_system(format="design-md", source_ids=[...])
design_validate_design_md(design_md_path="...")
```

Use this when a visual direction should move from design exploration into implementation. `DESIGN.md` gives downstream coding agents stable tokens, component guidance, accessibility notes, and implementation constraints without copying giant HTML blobs through chat.

> **Scope in 0.2:** export is one-way. We emit valid 8-section `DESIGN.md` and shell out to `npx @google/design.md lint` to validate it. Import (`DESIGN.md` → `SystemRecord` → `design_apply_system`) lands in 0.3 along with `design_diff` and region-pinned iterate. Track the roadmap in `notes/ultraplan-2026-05-10/ship-claude-design-mcp.md`.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `CLAUDE_DESIGN_MODEL` | `claude-sonnet-4-6` | Fast-tier model for design calls. |
| `CLAUDE_DESIGN_MODEL_OPUS` | `claude-opus-4-7` | Best-tier model for deeper design calls. |
| `CLAUDE_DESIGN_STUDIO_DIR` | `~/.claude-design/studio` | Local studio root for designs, renders, exports, and SQLite index. |
| `CLAUDE_DESIGN_AUTO_RENDER` | `auto` | `1`, `0`, or `auto`; controls screenshots after create/iterate. |
| `CLAUDE_DESIGN_CLI_PATH` | auto | Optional absolute path to the `claude` executable. Relative paths are refused. |
| `CLAUDE_DESIGN_PLAYWRIGHT_TMP` | auto | Writable temp directory for Playwright launch and download work. |
| `CLAUDE_DESIGN_PLAYWRIGHT_BROWSERS_PATH` | auto | Optional browser payload directory for local Playwright installs. |
| `CLAUDE_DESIGN_CHROMIUM_SANDBOX` | `auto` | `auto`, `1`, or `0`; controls Chromium sandbox fallback. |
| `CLAUDE_DESIGN_EFFORT` | `low` | Claude Code effort level. Use `none` to omit. |
| `CLAUDE_DESIGN_THINKING` | `disabled` | Thinking mode: `disabled`, `adaptive`, or `none`. |
| `CLAUDE_DESIGN_MAX_BUFFER_BYTES` | `8388608` | SDK stdout JSON buffer cap for large HTML responses. |
| `CLAUDE_DESIGN_ALLOW_API_KEY` | `0` | Set `1` to keep API-key, Bedrock, or Vertex auth env vars in the subprocess. |
| `CLAUDE_DESIGN_ENV_FILE` | unset | Optional explicit dotenv file. Only `CLAUDE_DESIGN_*` keys are loaded. |

## Manual Claude Desktop Config

Claude Code users should prefer `claude mcp add`. For manual MCP clients:

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

## Project Layout

```text
src/claude_design/
  server.py        MCP server and tool definitions
  designer.py      Claude Code OAuth call path and HTML extraction
  studio.py        Filesystem and SQLite persistence
  renderer.py      Playwright screenshot renderer
  design_md.py     DESIGN.md validation and emission helpers
  preview.py       Contact-sheet generation
scripts/
  smoke_mcp_stdio.py
tests/
```

The default studio lives at `~/.claude-design/studio` and contains:

```text
designs/      saved HTML documents
renders/      PNG screenshots
exports/      portable export folders and zips
designs.db    SQLite index with lineage and metadata
_index.html   optional contact sheet
```

## Development

```powershell
python -m pip install -e ".[dev,render]"
python -m ruff check src tests scripts
python -m pytest -q
python scripts\smoke_mcp_stdio.py
python -m build
```

Useful local checks:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m claude_design --check-json
python -m claude_design --demo
```

## Current Status

Claude Design MCP is beta software with a hardened local release path:

- OAuth-first auth path with explicit API-key opt-in.
- MCP stdio smoke coverage.
- Demo mode for model-free setup validation.
- CI for lint, tests, and build.
- Release workflow for tagged publishes.
- DESIGN.md extraction and validation.
- CSP, renderer, export, and dotenv hardening for untrusted model HTML.

## License

MIT.
