"""Raw MCP stdio smoke: initialize the server and assert tools/list works."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
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


def _pump(stream, lines: queue.Queue) -> None:
    for line in stream:
        lines.put(line)
    lines.put(None)


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
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True).start()
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
        proc.stdin.write(request)
        proc.stdin.flush()
        # stdin stays open until tools/list is answered. Closing it straight
        # after the writes lets the server read EOF and exit before it replies,
        # which made this smoke fail now and then.
        by_id: dict[Any, dict[str, Any]] = {}
        seen: list[bytes] = []
        deadline = time.monotonic() + 15
        while 2 not in by_id:
            try:
                line = lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError(f"MCP stdio smoke timed out. stdout={b''.join(seen)!r}") from None
            if line is None:
                break
            seen.append(line)
            if line.strip():
                message = json.loads(line)
                if "id" in message:
                    by_id[message["id"]] = message
        stdout = b"".join(seen)
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
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()


if __name__ == "__main__":
    raise SystemExit(main())
