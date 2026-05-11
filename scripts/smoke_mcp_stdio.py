"""Raw MCP stdio smoke: initialize the server and assert tools/list works."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXPECTED_TOOLS = {
    "design_create",
    "design_iterate",
    "design_variants",
    "design_render",
    "design_get",
    "design_list",
    "design_extract_system",
    "design_apply_system",
    "design_export",
    "design_preview",
    "design_validate_design_md",
}


def _encode_message(body: dict[str, Any]) -> bytes:
    return (json.dumps(body, separators=(",", ":")) + "\n").encode("utf-8")


def _decode_messages(stdout: bytes) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line in stdout.decode("utf-8").splitlines():
        if not line.strip():
            continue
        messages.append(json.loads(line))
    return messages


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["CLAUDE_DESIGN_STUDIO_DIR"] = tempfile.mkdtemp(prefix="cdmcp-stdio-")
    env["CLAUDE_DESIGN_AUTO_RENDER"] = "0"

    proc = subprocess.Popen(
        [sys.executable, "-m", "claude_design"],
        cwd=str(ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        request = b"".join(
            [
                _encode_message(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {
                                "name": "claude-design-smoke",
                                "version": "0.2.0",
                            },
                        },
                    }
                ),
                _encode_message(
                    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
                ),
                _encode_message(
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
                ),
            ]
        )
        stdout, stderr = proc.communicate(input=request, timeout=15)
        if proc.returncode not in (0, None):
            raise RuntimeError(stderr.decode("utf-8", errors="replace"))
        messages = _decode_messages(stdout)
        by_id = {message.get("id"): message for message in messages if "id" in message}
        init = by_id.get(1)
        if init is None:
            raise RuntimeError(f"initialize response missing. stdout={stdout!r}")
        if "error" in init:
            raise RuntimeError(f"initialize failed: {init['error']}")
        listed = by_id.get(2)
        if listed is None:
            raise RuntimeError(f"tools/list response missing. stdout={stdout!r}")
        if "error" in listed:
            raise RuntimeError(f"tools/list failed: {listed['error']}")
        names = {tool["name"] for tool in listed.get("result", {}).get("tools", [])}
        missing = sorted(EXPECTED_TOOLS - names)
        if missing:
            raise RuntimeError(f"tools/list missing expected tools: {missing}")
        print(json.dumps({"ok": True, "tool_count": len(names), "tools": sorted(names)}))
        return 0
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise RuntimeError(
            "MCP stdio smoke timed out. "
            f"stdout={stdout!r} stderr={stderr.decode('utf-8', errors='replace')}"
        )
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
