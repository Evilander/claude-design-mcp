"""claude-design-mcp — route design intents through Claude's frontier design capability.

This package exposes an MCP server that turns Claude into a persistent design studio:
  • Generate distinctive HTML/CSS designs from natural-language briefs.
  • Iterate on designs with version-tree lineage.
  • Spawn parallel variants exploring a single dimension (color, layout, mood).
  • Render screenshots via Playwright (optional).
  • Extract reusable design tokens (a "design system") from one or more designs.

Entry point: ``claude_design.server.main``.
"""

import os as _os
from pathlib import Path as _Path

from dotenv import dotenv_values as _dotenv_values


_ENV_KEY_PREFIX = "CLAUDE_DESIGN_"
_EXPLICIT_ENV_FILE = (_os.environ.get("CLAUDE_DESIGN_ENV_FILE") or "").strip()


def _load_explicit_env_file(raw_path: str) -> None:
    path = _Path(raw_path).expanduser().resolve()
    if not path.is_file():
        return
    for key, value in _dotenv_values(path).items():
        if not key.startswith(_ENV_KEY_PREFIX) or value is None:
            continue
        _os.environ.setdefault(key, value)


if _EXPLICIT_ENV_FILE:
    _load_explicit_env_file(_EXPLICIT_ENV_FILE)

__version__ = "0.2.0"
