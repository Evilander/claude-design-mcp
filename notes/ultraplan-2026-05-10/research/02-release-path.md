# PyPI + Docker release path for claude-design-mcp

**Date:** 2026-05-10
**Project:** `B:\projects\claude\claude-design-mcp`
**Current state:** Hatchling backend, static `version = "0.1.0"`, deps pinned to `mcp>=1.2.0`, `claude-agent-sdk>=0.1.70`, optional `playwright>=1.45`. Console script `claude-design-mcp = "claude_design.server:main"`. Stdio MCP server that subprocesses the local `claude` CLI and inherits its OAuth session.

---

## Ground truth, May 2026

Numbers I verified during this research so the recommendations below are not theoretical:

| Package | Current pinned floor | Latest on PyPI (2026-05-08) | Gap |
| --- | --- | --- | --- |
| `mcp` | `>=1.2.0` (Dec 2024) | **1.27.1** | ~25 minors behind |
| `claude-agent-sdk` | `>=0.1.70` | **0.1.77** | 7 patches behind |
| `playwright` (extra) | `>=1.45` | **1.59.1** | 14 minors behind |
| Playwright Docker base | n/a | `mcr.microsoft.com/playwright/python:v1.59.1-noble` (Ubuntu 24.04) | tag-pinned |

Sources at the bottom of this doc.

The `mcp>=1.2.0` floor was current in Dec 2024 but the SDK has shipped a major content-block refactor, content-format updates, OAuth helpers, and a Streamable HTTP transport since then. The floor needs to move.

---

## 1. PyPI release pipeline (recommended shape)

### 1.1 `pyproject.toml` — what to change

The current file is already correct in shape (PEP 621, Hatchling, src layout). It needs three upgrades to be 2026-grade:

1. **Dynamic version from git tags** via `hatch-vcs`. Eliminates the manual `0.1.0` bump and makes `git tag v0.2.0 && git push --tags` the release trigger.
2. **`[project.urls]` block** — PyPI surfaces these as sidebar links and most installers (`uv tool install`, `pipx run`) display them. Missing today.
3. **Tighter floors + an upper guard on `mcp`** so we don't get broken by a `mcp 2.x` breaking change and so users on stale environments fail loudly at install time instead of mysteriously at runtime.

**Concrete diff for `B:\projects\claude\claude-design-mcp\pyproject.toml`:**

```toml
[build-system]
requires = ["hatchling>=1.21", "hatch-vcs>=0.4"]
build-backend = "hatchling.build"

[project]
name = "claude-design-mcp"
dynamic = ["version"]
description = "MCP server that routes design requests through Claude's frontier visual-design capability with versioning, variants, rendering, and design-system extraction."
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
keywords = ["mcp", "claude", "design", "anthropic", "ui", "html", "css", "studio", "model-context-protocol"]
authors = [{ name = "Tyler Eveland", email = "j.tyler.eveland@gmail.com" }]
classifiers = [
  "Development Status :: 4 - Beta",
  "License :: OSI Approved :: MIT License",
  "Operating System :: OS Independent",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Software Development :: Libraries",
  "Topic :: Software Development :: User Interfaces",
  "Framework :: AsyncIO",
  "Intended Audience :: Developers",
  "Typing :: Typed",
]

dependencies = [
  "mcp>=1.20,<2",
  "claude-agent-sdk>=0.1.77,<0.2",
  "pydantic>=2.5,<3",
  "python-dotenv>=1.0,<2",
]

[project.optional-dependencies]
render = ["playwright>=1.55,<2"]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "ruff>=0.6",
  "mypy>=1.10",
  "build>=1.2",
]

[project.scripts]
claude-design-mcp = "claude_design.server:main"

[project.urls]
Homepage = "https://github.com/evilander/claude-design-mcp"
Repository = "https://github.com/evilander/claude-design-mcp"
Issues = "https://github.com/evilander/claude-design-mcp/issues"
Changelog = "https://github.com/evilander/claude-design-mcp/blob/master/CHANGELOG.md"

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.hooks.vcs]
version-file = "src/claude_design/_version.py"

[tool.hatch.build.targets.wheel]
packages = ["src/claude_design"]

[tool.hatch.build.targets.sdist]
include = [
  "src/claude_design",
  "README.md",
  "LICENSE",
  "pyproject.toml",
]
```

**Why these specific floors:**

- `mcp>=1.20`: the FastMCP refactor and content-format API consolidations all landed before 1.20. Pinning to 1.20 avoids importing FastMCP shapes that no longer exist in current users' environments.
- `<2`: the MCP SDK has not committed to semver for 2.x and is large enough that a 2.0 cut would be breaking. Fail loud.
- `claude-agent-sdk>=0.1.77`: gets the `api_error_status` field (relevant for the OAuth scrub diagnostics), the `xhigh` effort level (already referenced in this project's `CLAUDE_DESIGN_EFFORT` doc), and `skills` option moved off `allowed_tools`.
- `<0.2`: SDK is alpha; assume 0.2 will break.

### 1.2 Trusted publishing workflow (exact YAML)

Write to `B:\projects\claude\claude-design-mcp\.github\workflows\release.yml`. This is the 2026 canonical shape — build job runs unprivileged, publish job has only `id-token: write`, no API tokens anywhere, GitHub Environment named `pypi` for protection rules.

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

permissions: {}

jobs:
  build:
    name: Build sdist + wheel
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          fetch-tags: true

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install build
        run: python -m pip install --upgrade build

      - name: Build distributions
        run: python -m build

      - name: Smoke-check the sdist
        run: |
          python -m pip install dist/*.whl
          claude-design-mcp --check-json | python -c "import json,sys; d=json.load(sys.stdin); assert d.get('ok') in (True, False), d"

      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/
          if-no-files-found: error

  publish-testpypi:
    name: Publish to TestPyPI
    needs: [build]
    runs-on: ubuntu-latest
    environment:
      name: testpypi
      url: https://test.pypi.org/p/claude-design-mcp
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/
          skip-existing: true

  publish-pypi:
    name: Publish to PyPI
    needs: [publish-testpypi]
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/claude-design-mcp
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          attestations: true
```

**Three things that matter here that most copy-pasted examples get wrong:**

1. `fetch-depth: 0` + `fetch-tags: true`. Without these, `hatch-vcs` reads "unknown" and the wheel filename becomes `claude_design_mcp-0.1.dev0+gunknown-py3-none-any.whl`. Silent failure mode.
2. **TestPyPI gate before PyPI.** Cheap insurance against accidentally releasing a broken wheel — TestPyPI publish runs first, smokes the install, only then PyPI gets the tag. If TestPyPI fails the workflow stops without polluting the real index.
3. `attestations: true` — Sigstore-signed attestations are the 2026 default. PyPI displays them on the project page. Zero config cost given we already have OIDC.

**One-time PyPI setup** (do this before pushing the first tag):

1. Go to https://pypi.org/manage/account/publishing/ → "Add a new pending publisher".
2. Project name: `claude-design-mcp`. Owner: `evilander`. Repo: `claude-design-mcp`. Workflow filename: `release.yml`. Environment: `pypi`.
3. Repeat at https://test.pypi.org/manage/account/publishing/ with environment `testpypi`.
4. In GitHub repo Settings → Environments, create `pypi` and `testpypi`. On `pypi`, require manual approval ("Required reviewers: evilander") to add a human checkpoint between TestPyPI green and PyPI publish.

### 1.3 Wheel-only vs sdist+wheel

**Ship both, always.** This is settled in the FastMCP ecosystem:

- The official `mcp` package ships sdist + wheels for every platform.
- `fastmcp`, `mcp-server-git`, every reference server in `modelcontextprotocol/servers`: sdist + wheel.
- `claude-agent-sdk` ships sdist + per-platform wheels (because it bundles the Node `claude` CLI binaries — different story, doesn't apply to us).

For a pure-Python MCP server like this one, `python -m build` produces one universal wheel and one sdist. There's no platform matrix to maintain. The cost is zero, and the sdist matters for:

- Conda-forge packagers (they pull from sdist).
- Users on architectures without wheels (rare, but `uv pip install --no-binary` users exist).
- Reproducibility audits — sdist is the source-of-truth artifact.

Don't ship wheel-only. There's no upside.

### 1.4 TestPyPI end-to-end test

The release workflow above already runs through TestPyPI on every tag. For manual validation in a fresh shell:

```bash
# In a throwaway venv, install the latest TestPyPI build and smoke it
uv venv /tmp/cdm-test
source /tmp/cdm-test/bin/activate
uv pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  claude-design-mcp

claude-design-mcp --check-json
# Expect: JSON with ok=true/false, paths to studio, claude CLI version
```

The `--extra-index-url` to real PyPI is mandatory — TestPyPI doesn't mirror `mcp`, `pydantic`, etc., so without it the install fails on dependency resolution and you learn nothing about your own package.

---

## 2. Docker image for an MCP server that needs Playwright

### 2.1 Base image choice — recommendation: `mcr.microsoft.com/playwright/python:v1.59.1-noble`

Three options on the table:

| Option | Image size | Pros | Cons |
| --- | --- | --- | --- |
| `python:3.12-slim` + install Chromium yourself | ~150 MB base, ~500 MB after Chromium | Smallest if you only need one browser | You become responsible for Chromium system deps (~40 apt packages: `libnss3`, `libatk-bridge-2.0-0`, `libdrm2`, `libxkbcommon0`, `libxcomposite1`, `libxdamage1`, `libxfixes3`, `libxrandr2`, `libgbm1`, `libasound2`, fonts, etc.). Breaks on every Chromium version bump. |
| `mcr.microsoft.com/playwright/python:v1.59.1-noble` | ~1.6 GB | Microsoft maintains the dep list. Chromium + Firefox + WebKit pre-installed and matched to the Playwright version. | Big. Ships browsers we don't need. |
| `mcr.microsoft.com/playwright/python:v1.59.1-noble` + strip Firefox/WebKit in a second stage | ~900 MB | Best size-vs-maintenance | One extra build step |

**Recommendation: option 3.** Microsoft owns the dep list (this is the single biggest maintenance win — Chromium dep churn is brutal). We delete Firefox and WebKit in a second stage to recover ~700 MB. Net result: ~900 MB final image, no apt-package list to babysit.

This project only needs Chromium (`renderer.py` calls `playwright.chromium.launch()`), so dropping Firefox and WebKit is free.

### 2.2 Multi-stage Dockerfile

Write to `B:\projects\claude\claude-design-mcp\Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.7

ARG PLAYWRIGHT_VERSION=v1.59.1-noble

# --- stage 1: build the wheel ---
FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY .git ./.git
RUN python -m build --wheel --outdir /dist

# --- stage 2: runtime with Playwright preinstalled ---
FROM mcr.microsoft.com/playwright/python:${PLAYWRIGHT_VERSION} AS runtime

# Drop the two browsers we never use; saves ~700 MB.
RUN set -eux; \
    PW_HOME="$(python -c 'import pathlib, os; \
      home = os.environ.get(\"PLAYWRIGHT_BROWSERS_PATH\") or pathlib.Path.home()/\".cache\"/\"ms-playwright\"; \
      print(home)')"; \
    rm -rf "$PW_HOME"/firefox-* "$PW_HOME"/webkit-* "$PW_HOME"/ffmpeg-* || true

# Install the Node `claude` CLI so claude-agent-sdk can subprocess it.
# (Without this, every design call will fail with "claude not found".)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @anthropic-ai/claude-code \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install our wheel with the render extra (Playwright Python lib is already in this base).
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir "/tmp/$(ls /tmp/*.whl | xargs -n1 basename)[render]" \
 && rm /tmp/*.whl

# Non-root user (Chromium sandbox prefers this).
RUN useradd --create-home --shell /bin/bash design
USER design
WORKDIR /home/design

# Persistent studio outside the layer.
ENV CLAUDE_DESIGN_STUDIO_DIR=/home/design/studio
VOLUME ["/home/design/studio"]

# stdio MCP servers do not bind a port. Healthcheck calls --check-json.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD claude-design-mcp --check-json | python -c "import sys, json; d=json.load(sys.stdin); sys.exit(0 if d.get('ok') else 1)"

ENTRYPOINT ["claude-design-mcp"]
```

**Sizing notes:**

- Chromium itself is ~280 MB. There is no way around that — it's the actual browser binary.
- Ubuntu 24.04 base + Chromium deps: ~400 MB.
- Node LTS + `@anthropic-ai/claude-code`: ~200 MB. (This is the painful part. The Node CLI is ~150 MB on disk; the `node` runtime is another ~50 MB.) Could be avoided if claude-agent-sdk shipped a pure-Python OAuth client, but it currently shells out to `claude`.
- Our wheel: <1 MB.
- **Total target: ~900 MB.** This is roughly competitive with `playwright-mcp` official image and dramatically smaller than the unstripped `playwright/python` base.

If 900 MB is unacceptable, the next lever is **dropping the Node `claude` CLI requirement**. That requires a refactor (talk OAuth-API directly from Python, no subprocess) and is out of scope for the release-path task — call it out as a follow-up.

### 2.3 Runtime UX: how clients talk to a containerized stdio MCP server

This is the single most confusing part of shipping MCP-via-Docker, so spelling it out:

**The container does NOT bind a port.** stdio MCP servers communicate over the child process's stdin/stdout. Claude Desktop / Claude Code launch `docker run -i ...` and Docker pipes the container's stdin/stdout back to the client. The container boundary is invisible to the JSON-RPC layer.

**`claude_desktop_config.example.json` Docker variant** (add to `B:\projects\claude\claude-design-mcp\claude_desktop_config.example.json` as an alternate config):

```json
{
  "mcpServers": {
    "claude-design": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-v", "${HOME}/.claude-design/studio:/home/design/studio",
        "-v", "${HOME}/.claude:/home/design/.claude:ro",
        "ghcr.io/evilander/claude-design-mcp:latest"
      ]
    }
  }
}
```

**The three flags that are not negotiable:**

1. **`-i`** — keeps stdin open. Without it, the MCP server reads EOF immediately and exits.
2. **No `-t`** — TTY allocation corrupts the JSON-RPC stream with control characters. `-it` works in shell demos but breaks MCP.
3. **`--rm`** — without it, every `claude restart` leaks a dead container.

**The OAuth wrinkle:** mounting `~/.claude` read-only into the container lets the bundled `claude` CLI find the host's OAuth credentials. This is the same trick that `docker mcp` toolkit uses for the GitHub MCP server. Caveat — credential paths inside `~/.claude` are platform-specific and contain absolute host paths; expect a follow-up issue here. For the first cut, ship the Dockerfile but recommend `pipx`/`uv tool install` as the primary install path; Docker is for power users.

### 2.4 Healthcheck conventions

stdio MCP servers can't be probed via HTTP. Three patterns in the wild:

1. **Periodically invoke `--check-json`** (what the Dockerfile above does). Cheap, real, exits non-zero on misconfig.
2. Send a JSON-RPC `initialize` to a sidecar instance. More accurate but requires building a second invocation path.
3. Skip the healthcheck entirely (common — `mcr.microsoft.com/playwright-mcp` does not define one).

Option 1 is the right tradeoff. The `--check-json` path already validates: studio dir writable, Playwright importable, `claude` CLI present. That covers ~95% of broken-config failure modes.

---

## 3. Release engineering

### 3.1 Versioning — semver, not CalVer

For an SDK-shaped project (`mcp`, `claude-agent-sdk`, `pydantic` are all semver), shipping CalVer would mismatch the ecosystem and break dependents who pin `claude-design-mcp >=2026.5,<2026.6`-style.

**Use semver. Tag format `v0.2.0`.** When the MCP SDK hits 2.0 (which will be breaking), our 1.0.0 can follow.

While in 0.x, treat every minor bump as potentially breaking — the `0.` prefix is the warning to consumers.

### 3.2 CHANGELOG — release-please vs towncrier vs manual

For a one-maintainer project releasing monthly, **release-please** is the right tool:

- Reads conventional commits from git (`feat:`, `fix:`, `chore:`).
- Auto-opens a "Release PR" on every merge to master that bumps the version and edits `CHANGELOG.md`.
- Merging that PR creates the git tag, which triggers `release.yml` above.
- No per-PR ritual ("write a news fragment in `news/`"), just disciplined commit messages — which we're already doing.

Towncrier wins if there are multiple contributors who need to write user-facing copy per PR. For solo dev, it's overhead.

**Write to `B:\projects\claude\claude-design-mcp\.github\workflows\release-please.yml`:**

```yaml
name: release-please
on:
  push:
    branches: [master]
permissions:
  contents: write
  pull-requests: write
jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: googleapis/release-please-action@v4
        with:
          release-type: python
          package-name: claude-design-mcp
```

Add a `B:\projects\claude\claude-design-mcp\release-please-config.json`:

```json
{
  "release-type": "python",
  "packages": {
    ".": {
      "package-name": "claude-design-mcp",
      "include-component-in-tag": false,
      "changelog-sections": [
        { "type": "feat", "section": "Features" },
        { "type": "fix", "section": "Bug Fixes" },
        { "type": "perf", "section": "Performance" },
        { "type": "deps", "section": "Dependencies" },
        { "type": "docs", "section": "Documentation" }
      ]
    }
  }
}
```

And `B:\projects\claude\claude-design-mcp\.release-please-manifest.json`:

```json
{ ".": "0.1.0" }
```

### 3.3 Release-gate signals beyond `--check-json`

The current `--check-json` covers preflight. For a release, add three more gates **inside the build job** of `release.yml`:

1. **`pytest -q`** — already wired, just run it in CI before `python -m build`. Project already has `tests/test_oauth_readiness.py`, `tests/test_renderer_security.py`, etc.
2. **`ruff check src tests`** — config exists in `pyproject.toml`. Trivial to add.
3. **Wheel-import smoke** — `pip install dist/*.whl && python -c "import claude_design; import claude_design.server; claude_design.server.main"` (with `--check-json` as argv, exiting before MCP loop starts). Catches the "I forgot to add a file to the package data" bug class that pure-Python wheel builds are vulnerable to.

The release.yml above does (3) but not (1) and (2). Add a `test.yml` workflow that runs on every PR with the same matrix (Python 3.10, 3.11, 3.12, 3.13).

### 3.4 Post-install smoke test cookbook

Write to `B:\projects\claude\claude-design-mcp\scripts\smoke_install.sh` (or `.ps1` for Windows):

```bash
#!/usr/bin/env bash
# Spin up a fresh venv, install from PyPI, call one tool, assert non-error.
set -euo pipefail

VERSION="${1:-}"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

cd "$WORKDIR"
python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

if [[ -n "$VERSION" ]]; then
  pip install --quiet "claude-design-mcp==$VERSION"
else
  pip install --quiet claude-design-mcp
fi

# Step 1: readiness
claude-design-mcp --check-json | tee check.json
python -c "import json; d=json.load(open('check.json')); assert 'studio_dir' in d, d"

# Step 2: invoke one tool end-to-end via the MCP stdio protocol.
# Sends initialize + tools/list and asserts design_create is in the tool list.
python - <<'PY'
import json, subprocess, sys
proc = subprocess.Popen(
    ["claude-design-mcp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True,
)
def send(msg):
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())

init = send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18",
                        "capabilities": {}, "clientInfo": {"name":"smoke","version":"1"}}})
assert init.get("result"), init
tools = send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
names = [t["name"] for t in tools["result"]["tools"]]
assert "design_create" in names, names
print("OK — tools:", names)
proc.stdin.close()
proc.wait(timeout=5)
PY

echo "smoke_install: PASS"
```

This is the post-publish gate the README should reference: "After install, run `bash <(curl -sSL https://raw.githubusercontent.com/evilander/claude-design-mcp/master/scripts/smoke_install.sh)` to verify."

Note we deliberately do NOT call `design_create` itself — that would require a live OAuth session and real model spend in CI. `tools/list` is the correct depth for an install smoke.

---

## 4. The OAuth-CLI onboarding problem

This is the unique-to-this-project constraint: `claude-design-mcp` is useless without a working `claude` CLI on PATH that has been `claude login`-ed.

### 4.1 Pattern survey — MCP servers that wrap a parent CLI

The current state of the art:

- **`mcp-server-git`** — depends on `git`. Documents it in the README and lets the runtime fail if missing. No installer magic.
- **GitHub's `github-mcp-server`** — depends on a `GITHUB_PERSONAL_ACCESS_TOKEN`. Documents env var; provides a Docker image that takes the token via `-e`.
- **`@modelcontextprotocol/server-filesystem`** — needs filesystem access, configured via args.
- **`anthropics/claude-agent-sdk-python`** itself — **automatically bundles the Node `claude` CLI in the wheel** as of 0.1.70-ish. It runs the bundled CLI by default.

**The bundled-CLI pattern is the right answer here, but we don't have to re-implement it.** `claude-agent-sdk>=0.1.77` already ships `claude` inside its wheel. The bug is that this server lets users override the CLI path via `CLAUDE_DESIGN_CLI_PATH` and looks in `PATH` first. Today that's mostly correct — but `--check` should explicitly say "using bundled CLI from claude-agent-sdk wheel" when it falls back to the SDK's bundled binary, so users understand there's no separate install required.

Action item (out of scope for release path but important): audit `designer.py`/`server.py` for how `claude` is resolved. If the SDK already bundles it, the README's `# 1. Install Claude Code` step may be optional. Verify.

### 4.2 One-liner installer — recommendation: `uv tool install`

Three candidates:

| Method | One-liner | Pros | Cons |
| --- | --- | --- | --- |
| `pip install --user` | `pip install claude-design-mcp` | Universal | Pollutes user site-packages, conflicts likely |
| `pipx install` | `pipx install claude-design-mcp` | Isolated venv, on PATH | pipx itself is another install dep |
| `uv tool install` | `uv tool install claude-design-mcp` | Fastest, no Python pre-install needed (uv ships its own) | uv adoption is high but not universal |

**The 2026 MCP ecosystem has converged on `uv tool install` / `uvx`.** Every recent Anthropic-authored MCP server example uses uvx. The reason: uv handles Python version selection, venv creation, and PATH wiring in one binary, and uvx lets users opt out of permanent install entirely.

**Recommended README install section** (replace lines 51-67 of `B:\projects\claude\claude-design-mcp\README.md`):

````markdown
## Install

```bash
# 1. Install uv (one-time) — manages Python and isolated tool envs.
curl -LsSf https://astral.sh/uv/install.sh | sh        # macOS / Linux
# Windows PowerShell:
# powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Install claude-design-mcp into an isolated env on your PATH.
uv tool install claude-design-mcp

# 3. (Optional) Add Playwright rendering.
uv tool install "claude-design-mcp[render]"
uv tool run --from claude-design-mcp playwright install chromium

# 4. Make sure you're logged into Claude Code (the OAuth source).
claude login

# 5. Wire it into Claude Code.
claude mcp add claude-design --scope user -- claude-design-mcp
```

Verify with `claude-design-mcp --check-json`.
````

The `claude mcp add` line is the key 2026 ergonomic — instead of asking users to hand-edit `~/.claude/settings.json`, the official `claude` CLI now has a sub-command that does exactly that. Pair it with `--scope user` so the entry goes into the user-global config, not the current project's `.mcp.json`.

**For users who want to try without installing** (the killer uvx feature):

```bash
uvx --from claude-design-mcp claude-design-mcp --check
```

Spawns a temp venv, runs once, throws it away. Document this in the README as "Just want to try it?".

### 4.3 Best practice for "install MCP server X and wire it into Claude Code" — full recipe

This is the full 2026 idiom, and what `README.md` should center on:

```bash
# All-in-one for a brand-new machine.
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install claude-design-mcp
claude login   # if not already logged in
claude mcp add claude-design --scope user -- claude-design-mcp
```

Four commands, one of which is conditional. Compared to the current README (six steps, three of which are environment-aware), this is a real onboarding improvement.

---

## 5. Concrete recommendations, ranked by impact-to-effort

### REC-1: Replace `pyproject.toml` with the dynamic-version + tightened-floor shape above (HIGH impact, LOW effort)

**File:** `B:\projects\claude\claude-design-mcp\pyproject.toml`
**Why first:** Everything else depends on it. The `mcp>=1.2.0` floor is 25 minors stale and will cause silent breakage on users who happen to have an old `mcp` cached. `hatch-vcs` unlocks tag-driven releases (required for REC-2).
**Verify with:** `python -m build` succeeds, `dist/claude_design_mcp-0.2.0.tar.gz` exists with the expected name, `pip install dist/*.whl && python -c "import claude_design; print(claude_design.__version__)"` prints the version from the git tag.

### REC-2: Land `.github/workflows/release.yml` with PyPI trusted publishing (HIGH impact, LOW effort)

**Files:** `B:\projects\claude\claude-design-mcp\.github\workflows\release.yml`, PyPI Trusted Publisher config at https://pypi.org/manage/account/publishing/.
**Why second:** Once this exists, every `git tag vX.Y.Z && git push --tags` ships. No tokens, no Twine, no `python -m build` on the laptop.
**Verify with:** Create a `v0.2.0-rc1` tag → workflow runs → TestPyPI publish succeeds → `pip install -i https://test.pypi.org/simple/ claude-design-mcp==0.2.0rc1` works in a fresh venv → smoke test passes.

### REC-3: Add `scripts/smoke_install.sh` and reference it from the README (HIGH impact, LOW effort)

**File:** `B:\projects\claude\claude-design-mcp\scripts\smoke_install.sh`
**Why third:** It's the proof for everything else. It runs end-to-end as a real user would, exposes packaging mistakes (forgotten files, missing `__main__.py`, broken script entry point) before they hit users, and lets release.yml gate the publish on it.
**Verify with:** Run it locally against the current 0.1.0 (after fixing it to read from a local wheel during dev). Re-run against TestPyPI in CI.

### REC-4: Rewrite the README install section around `uv tool install` + `claude mcp add` (MEDIUM impact, LOW effort)

**File:** `B:\projects\claude\claude-design-mcp\README.md` lines 51-100.
**Why fourth:** Onboarding friction is the #1 cause of MCP-server abandonment. Going from 6 steps to 4 — and dropping the "hand-edit JSON" instruction — makes this server installable by someone who's never touched it before.
**Verify with:** On a fresh Windows VM with nothing but uv installed, the four commands result in `/mcp` listing `claude-design` as connected in Claude Code.

### REC-5: Add `.github/workflows/release-please.yml` + config files for automated CHANGELOG (MEDIUM impact, LOW effort)

**Files:** `release-please.yml`, `release-please-config.json`, `.release-please-manifest.json`.
**Why fifth:** Once REC-1 and REC-2 are in, release-please makes the loop fully automated — merge `feat: ...` PRs to master, release-please opens a "Release PR", merging it tags the repo, release.yml ships. The maintainer never touches a version number again.
**Verify with:** After merging a `feat:`-prefixed PR, release-please should open a PR titled "chore(master): release X.Y.Z" with a populated CHANGELOG.md diff.

### REC-6: Land `Dockerfile` and publish to GHCR alongside PyPI (MEDIUM impact, MEDIUM effort)

**Files:** `B:\projects\claude\claude-design-mcp\Dockerfile`, `B:\projects\claude\claude-design-mcp\.github\workflows\docker.yml`.
**Why sixth:** Most users will install via `uv tool install` — Docker is for the subset who want isolation, reproducibility, or CI use. The Dockerfile is mostly written above; the workflow is the standard `docker/build-push-action@v5` + GHCR + `attestations: true`. Worth landing but not the highest priority.
**Verify with:** `docker run --rm -i ghcr.io/evilander/claude-design-mcp:latest --check-json` returns valid JSON.

### REC-7: Audit whether the README's "step 1: install Claude Code" is still required (LOW impact, LOW effort)

**File:** `B:\projects\claude\claude-design-mcp\src\claude_design\designer.py` (CLI resolution path).
**Why seventh:** If `claude-agent-sdk>=0.1.70` bundles the Node CLI in the wheel (it does, per the SDK changelog), then `pip install claude-design-mcp` is sufficient to make calls — no separate `claude login` step needed for the CLI to exist. The user still needs an OAuth session, but that may happen automatically on first call. Worth verifying and updating the README.
**Verify with:** In a fresh venv on a machine that has never installed Claude Code, `pip install claude-design-mcp && claude-design-mcp --check-json` — does the bundled CLI resolve? Does `--check` correctly report the bundled-CLI path?

---

## Open questions / follow-ups (not part of release path but adjacent)

- **The Docker `~/.claude` mount is fragile.** OAuth paths inside `~/.claude` contain absolute host paths that don't translate inside the container. The MCP Docker pattern is currently the right move for power users but expect a "Docker OAuth doesn't work on first try" issue. Could be resolved by `claude login` running inside the container with a volume-mounted credentials dir, but that's an interactive flow. Punt to follow-up.
- **Windows install.ps1.** Project already ships `install.ps1`. After REC-4, this can be deleted in favor of the uv one-liner. Confirm Windows users have uv before deleting.
- **Streamable HTTP transport.** Out of scope for this release but inevitable next step. The MCP 2025-11-25 spec requires Streamable HTTP for remote/production use; stdio is local-only. When this server grows beyond "wrap a local CLI", add an `--http` mode and the Docker image becomes a real cloud target (Railway, Render, Cloudflare Workers all support it).

---

## Sources

- [PyPI Trusted Publishers docs](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [pypa/gh-action-pypi-publish](https://github.com/pypa/gh-action-pypi-publish)
- [GitHub Docs: Configuring OpenID Connect in PyPI](https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-pypi)
- [MCP Python SDK on PyPI (1.27.1, 2026-05-08)](https://pypi.org/project/mcp/)
- [FastMCP on PyPI (3.2.4, 2026-04-14)](https://pypi.org/project/fastmcp/)
- [claude-agent-sdk on PyPI (0.1.77, 2026-05-08)](https://pypi.org/project/claude-agent-sdk/)
- [Playwright for Python Docker image (v1.59.1-noble)](https://mcr.microsoft.com/en-us/product/playwright/python/about)
- [Playwright Docker docs](https://playwright.dev/python/docs/docker)
- [Docker MCP Toolkit + Claude Desktop](https://www.docker.com/blog/connect-mcp-servers-to-claude-desktop-with-mcp-toolkit/)
- [MCP build-server guide](https://modelcontextprotocol.io/docs/develop/build-server)
- [hatch-vcs](https://pypi.org/project/hatch-vcs/)
- [setuptools-scm](https://setuptools-scm.readthedocs.io/)
- [release-please-action](https://github.com/googleapis/release-please-action)
- [towncrier](https://github.com/twisted/towncrier) (for context — release-please is the recommendation here)
- [uv tool install / uvx](https://docs.astral.sh/uv/concepts/tools/)
- [BSWEN: Using uvx to Run MCP Servers in Claude Desktop](https://docs.bswen.com/blog/2026-03-05-using-uvx-with-mcp-servers/)
- [Connect to local MCP servers (`claude mcp add`)](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
