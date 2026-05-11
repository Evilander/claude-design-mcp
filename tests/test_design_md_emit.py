from __future__ import annotations

import shutil
from datetime import datetime, timezone

import pytest

from claude_design.design_md import emit_design_md, validate_design_md_via_cli
from claude_design.studio import SystemRecord


_WHEN = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
_HEADINGS = [
    "## Overview",
    "## Colors",
    "## Typography",
    "## Layout",
    "## Elevation & Depth",
    "## Shapes",
    "## Components",
    "## Do's and Don'ts",
]


def _system(**overrides) -> SystemRecord:
    data = {
        "id": "abc123def456",
        "name": "archival",
        "summary": "earnest paper-ledger",
        "tokens": {},
        "components": [],
        "principles": [],
        "source_ids": ["feedface1234"],
    }
    data.update(overrides)
    return SystemRecord(**data)


def test_emit_empty_system_has_front_matter_and_all_sections():
    md = emit_design_md(_system(tokens={}, summary=None, source_ids=[]), generated_at=_WHEN)

    assert md.startswith("---\n")
    assert "name: archival\n" in md
    assert "generated_by: claude-design-mcp\n" in md
    assert "generated_at: 2026-05-10T12:00:00Z\n" in md
    assert "source_system_id: abc123def456\n" in md
    assert 'spec_version: "0.1"\n' in md
    assert "_No colors recorded._" in md
    assert "_No components recorded._" in md
    assert _section_positions(md) == sorted(_section_positions(md))
    assert all(md.count(heading) == 1 for heading in _HEADINGS)


def test_emit_full_system_maps_tokens_in_order():
    md = emit_design_md(
        _system(
            tokens={
                "color": {
                    "muted": "#6b5b35",
                    "bg": "#eee5d2",
                    "accent": "#d0a64f",
                    "fg": "#171412",
                    "current": "currentColor",
                },
                "type": {"body": "Inter, sans-serif", "display": "Georgia, serif"},
                "scale": {"1": "14px", "0": "12px", "label": "11px"},
                "space": {"unit": "10px"},
                "layout": {"gutter": "24px"},
                "shadow": {"high": "0 12px 24px rgba(0,0,0,.2)", "low": "0 1px 2px #0002"},
                "radius": {"md": "6px", "sm": "2px"},
                "border": {"hairline": "1px solid #0002"},
            },
        ),
        generated_at=_WHEN,
    )

    assert md.index("| bg | #eee5d2 | Page background |") < md.index(
        "| fg | #171412 | Primary ink |"
    )
    assert "| current | `currentColor` | Current |" in md
    assert "| display | Georgia, serif |" in md
    assert "| 0 | 12px |" in md
    assert "- **Base unit:** 10px" in md
    assert "- **Rhythm:** 1.5" in md
    assert "- **Container max:** 1320px" in md
    assert "| low | 0 1px 2px #0002 |" in md
    assert "| radius.sm | 2px |" in md
    assert "| border.hairline | 1px solid #0002 |" in md


def test_emit_splits_dos_and_donts_and_strips_directives():
    md = emit_design_md(
        _system(
            principles=[
                "Hero claims the page",
                "Don't use numbered headers",
                "Never stack four cards",
                "Avoid generic SaaS chrome",
            ],
        ),
        generated_at=_WHEN,
    )

    assert "**Do**" in md
    assert "- Hero claims the page" in md
    assert "**Don't**" in md
    assert "- Use numbered headers" in md
    assert "- Stack four cards" in md
    assert "- Generic SaaS chrome" in md
    assert "Don't use numbered headers" not in md


def test_emit_components_round_trip_markdown_and_escalates_fences():
    html = '<button class="btn-primary">Save changes</button>'
    css = ".btn-primary::after { content: '```'; }"
    md = emit_design_md(
        _system(
            components=[
                {
                    "name": "button-primary",
                    "notes": "Primary action button.",
                    "html": html,
                    "css": css,
                },
                {"name": "button-primary-hover", "html": "<button>Hover</button>"},
            ],
        ),
        generated_at=_WHEN,
    )

    assert "### button-primary\n" in md
    assert "### button-primary-hover\n" in md
    assert html in md
    assert "````css\n.btn-primary::after { content: '```'; }\n````" in md
    assert "_(no CSS recorded)_" in md


def test_emit_missing_colors_produces_empty_stub():
    md = emit_design_md(_system(tokens={"type": {"body": "Inter"}}), generated_at=_WHEN)

    assert "## Colors\n\n_No colors recorded._" in md


def test_front_matter_is_valid_yaml_when_yaml_is_available():
    yaml = pytest.importorskip("yaml")
    md = emit_design_md(_system(), generated_at=_WHEN)
    front_matter = md.split("---", 2)[1]

    parsed = yaml.safe_load(front_matter)

    assert parsed["name"] == "archival"
    assert parsed["source_designs"] == ["feedface1234"]


def test_emitted_fixture_passes_designmd_lint_when_cli_is_available(tmp_path):
    # This exercises Google's official CLI when npx is installed on the host.
    # Hosts without npx or with a cold/blocked npx package fetch skip rather than
    # making the local unit suite depend on Node network availability.
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        pytest.skip("npx is not available")
    path = tmp_path / "DESIGN.md"
    path.write_text(emit_design_md(_system(), generated_at=_WHEN), encoding="utf-8")

    result = validate_design_md_via_cli(str(path), timeout_s=5)

    if result["ok"] is None:
        pytest.skip(result["raw_output"])
    assert result["ok"] is True, result["raw_output"]


def _section_positions(md: str) -> list[int]:
    return [md.index(heading) for heading in _HEADINGS]
