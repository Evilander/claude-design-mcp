from __future__ import annotations

import json
import subprocess

import pytest

import claude_design.design_md as design_md
import claude_design.server as server
from claude_design.models import DesignValidateDesignMdInput


@pytest.mark.asyncio
async def test_validate_design_md_tool_returns_ok_true_when_cli_succeeds(
    monkeypatch, tmp_path
):
    path = tmp_path / "DESIGN.md"
    path.write_text("# DESIGN.md\n", encoding="utf-8")

    def fake_run(*args, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=["npx"],
            returncode=0,
            stdout="DESIGN.md lint passed\n",
            stderr="",
        )

    monkeypatch.setattr(design_md.subprocess, "run", fake_run)

    body = json.loads(
        await server.design_validate_design_md(
            DesignValidateDesignMdInput(design_md_path=str(path.resolve()))
        )
    )

    assert body["ok"] is True
    assert body["warnings"] == []
    assert body["errors"] == []
    assert body["wcag_failures"] == []
    assert "lint passed" in body["raw_output"]


def test_validate_design_md_via_cli_returns_null_when_npx_missing(monkeypatch, tmp_path):
    path = tmp_path / "DESIGN.md"
    path.write_text("# DESIGN.md\n", encoding="utf-8")

    def fake_run(*args, **kwargs):  # noqa: ARG001
        raise FileNotFoundError("npx")

    monkeypatch.setattr(design_md.subprocess, "run", fake_run)

    body = design_md.validate_design_md_via_cli(str(path))

    assert body["ok"] is None
    assert body["warnings"] == []
    assert body["errors"] == []
    assert body["wcag_failures"] == []
    assert "npx" in body["raw_output"]


def test_validate_design_md_via_cli_extracts_errors_and_wcag(monkeypatch, tmp_path):
    path = tmp_path / "DESIGN.md"
    path.write_text("# DESIGN.md\n", encoding="utf-8")

    def fake_run(*args, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=["npx"],
            returncode=1,
            stdout=(
                "Warning: missing optional component notes\n"
                "Error: section order is invalid\n"
                "WCAG AA contrast failure: fg on bg\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(design_md.subprocess, "run", fake_run)

    body = design_md.validate_design_md_via_cli(str(path))

    assert body["ok"] is False
    assert body["warnings"] == ["Warning: missing optional component notes"]
    assert body["errors"] == ["Error: section order is invalid"]
    assert body["wcag_failures"] == [{"message": "WCAG AA contrast failure: fg on bg"}]
