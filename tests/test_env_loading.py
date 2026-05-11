"""Import-time dotenv behavior must not trust arbitrary cwd .env files."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _run_import(cwd: Path, env: dict[str, str]) -> str:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, sys; "
                f"sys.path.insert(0, {str(SRC)!r}); "
                "import claude_design; "
                "print(os.environ.get('CLAUDE_DESIGN_MODEL', ''))"
            ),
        ],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def test_cwd_dotenv_is_ignored(tmp_path: Path):
    (tmp_path / ".env").write_text("CLAUDE_DESIGN_MODEL=hijacked\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("CLAUDE_DESIGN_MODEL", None)
    env.pop("CLAUDE_DESIGN_ENV_FILE", None)

    assert _run_import(tmp_path, env) == ""


def test_explicit_env_file_loads_only_claude_design_keys(tmp_path: Path):
    explicit = tmp_path / "safe.env"
    explicit.write_text(
        "CLAUDE_DESIGN_MODEL=from-explicit-file\nANTHROPIC_API_KEY=sk-nope\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("CLAUDE_DESIGN_MODEL", None)
    env["CLAUDE_DESIGN_ENV_FILE"] = str(explicit)

    assert _run_import(tmp_path, env) == "from-explicit-file"
