# Codebase recon — extension points for ship-claude-design-mcp

Returned by code-explorer agent (2026-05-10). Persisted by the ultraplan
orchestrator because the agent's policy forbids writing files.

## Load-bearing pointers

### New MCP tool wiring (for `design_keep`, `design_discard`, `design_diff`, `design_capture_url`, `design_score`)

- Add @mcp.tool entry next to `design_get` at **`server.py:567`**.
- Wrap with `@_tool` decorator at **`server.py:196`** for uniform timeout + error surface.
- Pydantic input model in **`models.py:198`** using the shared `_ID_PATTERN` at **`models.py:56`**.

### Schema additions for kept/discarded/scored signal capture

- Extend `_SCHEMA` at **`studio.py:38-77`** — add columns `kept_at REAL`, `discarded_at REAL`,
  `iteration_reason TEXT`, `eval_score REAL`, `eval_breakdown TEXT` (JSON).
- Mirror onto `DesignRecord` dataclass at **`studio.py:85-129`**.
- Row mapper at **`studio.py:618-640`** needs the new fields.
- **Already exists:** `iteration_of` IS the `parent_id_iterated_from` column. No new column needed for that.

### Renderer cache (M8 fix)

- Memoize at `Renderer.readiness()` at **`renderer.py:225-252`** on an env-var fingerprint
  (PLAYWRIGHT_BROWSERS_PATH + CLAUDE_DESIGN_STUDIO_DIR).
- Invalidate via `_reset_singletons` at **`server.py:147-155`** for tests and `--check`.
- Expensive call to memoize: `_browser_install_status` at **`renderer.py:255-302`** which
  shells out to `python -m playwright install --dry-run` on every miss (~15s subprocess).

### PyPI gaps in `pyproject.toml`

Missing fields for a real release:
- `[project.urls]` (Homepage, Issues, Source, Changelog)
- `authors` table
- OS/Topic classifiers
- `dynamic = ["version"]` paired with `[tool.hatch.version].path = "src/claude_design/__init__.py"`
- sdist target (currently only wheel)
- `[tool.pytest.ini_options]`
- `CHANGELOG.md` does not exist

### Install scripts

- `install.ps1` is **Windows-only**.
- No `install.sh`, `Makefile`, or `justfile` exists.
- Cross-platform installer is a real gap.

### Demo subcommand path

Cleanest implementation:
- Add `--demo` flag at **`server.py:1279`**.
- Dispatch right after the `--check` / `--check-json` block at **`server.py:1286-1292`**.
- Lift the smoke-test body from `scripts/dogfood_smoke.py:43-162` into a reusable
  `demo()` function in `server.py` so it doesn't depend on the scripts/ tree.

### Reusable abstractions to extend (not reinvent)

| Abstraction | File:line | Reuse for |
|---|---|---|
| `Studio.lineage` | `studio.py:577-616` | `design_diff` — pass lineage chain into the diff tool. |
| `Designer.variants` | `designer.py:343-381` | Parallel `design_score` — judge N candidates concurrently. |
| `Renderer.render` (split) | `renderer.py:414-551` | `design_capture_url` — reuse browser pool, swap `html_path` for `url`. |
| `_persist_design` | `server.py:838-874` | Any new tool that creates a design (apply_system, capture_url result). |
| `_oauth_only_environ` | `designer.py:173-199` | **Mandatory wrap** for any new tool that spawns the Claude CLI. |
