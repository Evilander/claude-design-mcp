"""claude-design-mcp — route design intents through Claude's frontier design capability.

This package exposes an MCP server that turns Claude into a persistent design studio:
  • Generate distinctive HTML/CSS designs from natural-language briefs.
  • Iterate on designs with version-tree lineage.
  • Spawn parallel variants exploring a single dimension (color, layout, mood).
  • Render screenshots via Playwright (optional).
  • Extract reusable design tokens (a "design system") from one or more designs.

Entry point: ``claude_design.server.main``.
"""

# Load .env BEFORE any submodule import so module-level env reads see it.
# Without this, ``designer.DEFAULT_MODEL_FAST`` would freeze to the hard-coded
# default before .env-set overrides became visible.
from pathlib import Path as _Path

from dotenv import load_dotenv as _load_dotenv

_PKG_ROOT = _Path(__file__).resolve().parent.parent.parent
for _candidate in (_PKG_ROOT / ".env", _Path.cwd() / ".env"):
    if _candidate.exists():
        _load_dotenv(_candidate, override=False)

__version__ = "0.1.0"
