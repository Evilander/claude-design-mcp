"""Emit and validate Google DESIGN.md documents from stored design systems."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .studio import SystemRecord

_SPEC_VERSION = "0.1"
_GENERATOR = "claude-design-mcp"

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_CANONICAL_COLOR_ORDER = ("bg", "fg", "accent", "muted")
_CANONICAL_TYPE_ORDER = ("display", "body", "mono")
_CANONICAL_SHADOW_ORDER = ("low", "med", "high")
_NEGATIVE_DIRECTIVES = (
    "do not",
    "don't",
    "dont",
    "never",
    "avoid",
    "stop",
    "kill",
)
_CLI_UNAVAILABLE_MARKERS = (
    "could not determine executable",
    "enoent",
    "enotfound",
    "eai_again",
    "network",
    "npm err!",
    "fetch failed",
    "certificate",
)


def emit_design_md(
    system: SystemRecord, *, generated_at: datetime | None = None
) -> str:
    """Render a SystemRecord as a DESIGN.md document."""
    when = generated_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(timezone.utc)

    sections = [
        _front_matter(system, when),
        _overview(system),
        _colors(system),
        _typography(system),
        _layout(system),
        _elevation(system),
        _shapes(system),
        _components(system),
        _dos_and_donts(system),
    ]
    return "\n\n".join(section.rstrip() for section in sections) + "\n"


def validate_design_md_via_cli(path: str, *, timeout_s: float = 30.0) -> dict:
    """Run `npx @google/design.md lint <path>`; return a structured result."""
    try:
        npx = _npx_executable()
        proc = subprocess.run(
            [
                npx,
                "-y",
                "-p",
                "@google/design.md",
                _designmd_command_name(npx),
                "lint",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return _cli_unavailable("designmd CLI not available; `npx` was not found on PATH.")
    except subprocess.TimeoutExpired as e:
        output = _join_output(e.stdout, e.stderr)
        return {
            "ok": None,
            "warnings": [],
            "errors": [],
            "wcag_failures": [],
            "raw_output": output
            or f"designmd CLI not available; lint timed out after {timeout_s:.0f}s.",
            "error": f"designmd lint timed out after {timeout_s:.0f}s.",
        }
    except OSError as e:
        return _cli_unavailable(f"designmd CLI not available; {type(e).__name__}: {e}")

    raw_output = _join_output(proc.stdout, proc.stderr)
    if proc.returncode != 0 and _looks_like_cli_unavailable(raw_output):
        return _cli_unavailable(
            "designmd CLI not available; `npx @google/design.md lint` could not run.",
            raw_output=raw_output,
        )

    parsed = _parse_lint_output(raw_output)
    if proc.returncode != 0 and not parsed["errors"]:
        parsed["errors"] = [line for line in _output_lines(raw_output)] or [
            f"designmd lint exited with status {proc.returncode}."
        ]
    return {
        "ok": proc.returncode == 0,
        "warnings": parsed["warnings"],
        "errors": parsed["errors"],
        "wcag_failures": parsed["wcag_failures"],
        "raw_output": raw_output,
        "error": None,
    }


def _front_matter(system: SystemRecord, generated_at: datetime) -> str:
    source_ids = [str(value) for value in system.source_ids if value]
    lines = [
        "---",
        f"name: {_yaml_scalar(system.name or 'untitled-system')}",
        f"generated_by: {_yaml_scalar(_GENERATOR)}",
        f"generated_at: {_yaml_scalar(_iso_utc(generated_at))}",
        f"source_system_id: {_yaml_scalar(system.id)}",
        "source_designs:",
    ]
    if source_ids:
        lines.extend(f"  - {_yaml_scalar(value)}" for value in source_ids)
    else:
        lines.append("  []")
    lines.extend([
        f'spec_version: "{_SPEC_VERSION}"',
        "---",
    ])
    return "\n".join(lines)


def _overview(system: SystemRecord) -> str:
    summary = _clean_text(system.summary) or "A design system extracted by claude-design-mcp."
    return f"## Overview\n\n{summary}"


def _colors(system: SystemRecord) -> str:
    colors = _dict_token(system.tokens, "color")
    if not colors:
        return "## Colors\n\n_No colors recorded._"
    rows = ["## Colors", "", "| Token | Value | Role |", "|-------|-------|------|"]
    for key in _ordered_keys(colors, _CANONICAL_COLOR_ORDER):
        value = colors.get(key)
        if value is None:
            continue
        rows.append(f"| {key} | {_format_color_value(value)} | {_color_role(key)} |")
    if len(rows) == 4:
        rows.append("_No colors recorded._")
    return "\n".join(rows)


def _typography(system: SystemRecord) -> str:
    type_tokens = _dict_token(system.tokens, "type") or _dict_token(
        system.tokens, "typography"
    )
    scale = _dict_token(system.tokens, "scale")
    lines = ["## Typography"]
    emitted = False

    if type_tokens:
        lines.extend(["", "| Role | Family |", "|------|--------|"])
        for key in _ordered_keys(type_tokens, _CANONICAL_TYPE_ORDER):
            value = type_tokens.get(key)
            if value is not None:
                lines.append(f"| {key} | {value} |")
                emitted = True

    if scale:
        if emitted:
            lines.append("")
        lines.extend(["### Scale", "", "| Step | Size |", "|------|------|"])
        for key in _scale_keys(scale):
            value = scale.get(key)
            if value is not None:
                lines.append(f"| {key} | {value} |")
                emitted = True

    if not emitted:
        lines.extend(["", "_No typography recorded._"])
    return "\n".join(lines)


def _layout(system: SystemRecord) -> str:
    space = _dict_token(system.tokens, "space")
    layout = _dict_token(system.tokens, "layout")
    if not space and not layout:
        return "## Layout\n\n_No layout tokens recorded._"

    lines = ["## Layout", ""]
    if space is not None:
        lines.append(f"- **Base unit:** {space.get('unit') or '8px'}")
        lines.append(f"- **Rhythm:** {space.get('rhythm') or '1.5'}")
        for key in sorted(k for k in space if k not in {"unit", "rhythm"}):
            value = space.get(key)
            if value is not None:
                lines.append(f"- **{_humanize_key(key)}:** {value}")
    if layout is not None:
        lines.append(f"- **Container max:** {layout.get('container') or '1320px'}")
        for key in sorted(k for k in layout if k != "container"):
            value = layout.get(key)
            if value is not None:
                lines.append(f"- **{_humanize_key(key)}:** {value}")
    return "\n".join(lines)


def _elevation(system: SystemRecord) -> str:
    shadows = _dict_token(system.tokens, "shadow")
    if not shadows:
        return "## Elevation & Depth\n\n_No elevation tokens recorded._"
    lines = ["## Elevation & Depth", "", "| Level | Shadow |", "|-------|--------|"]
    for key in _ordered_keys(shadows, _CANONICAL_SHADOW_ORDER):
        value = shadows.get(key)
        if value is not None:
            lines.append(f"| {key} | {value} |")
    if len(lines) == 4:
        lines.append("_No elevation tokens recorded._")
    return "\n".join(lines)


def _shapes(system: SystemRecord) -> str:
    radius = _dict_token(system.tokens, "radius")
    border = _dict_token(system.tokens, "border")
    if not radius and not border:
        return "## Shapes\n\n_No shape tokens recorded._"

    lines = ["## Shapes", "", "| Token | Value |", "|-------|-------|"]
    for prefix, values in (("radius", radius), ("border", border)):
        if not values:
            continue
        for key in sorted(values):
            value = values.get(key)
            if value is not None:
                lines.append(f"| {prefix}.{key} | {value} |")
    if len(lines) == 4:
        lines.append("_No shape tokens recorded._")
    return "\n".join(lines)


def _components(system: SystemRecord) -> str:
    if not system.components:
        return "## Components\n\n_No components recorded._"

    lines = ["## Components"]
    for component in system.components:
        name = _clean_text(component.get("name")) or "unnamed-component"
        notes = _clean_text(component.get("notes")) or (
            f"{name} component extracted by claude-design-mcp."
        )
        lines.extend(["", f"### {name}", "", notes, "", "**HTML**", ""])
        html = component.get("html")
        if html:
            lines.append(_fenced(str(html), "html"))
        else:
            lines.append("_(no HTML recorded)_")
        lines.extend(["", "**CSS**", ""])
        css = component.get("css")
        if css:
            lines.append(_fenced(str(css), "css"))
        else:
            lines.append("_(no CSS recorded)_")
    return "\n".join(lines)


def _dos_and_donts(system: SystemRecord) -> str:
    dos: list[str] = []
    donts: list[str] = []
    for principle in system.principles:
        text = _clean_text(principle)
        if not text:
            continue
        stripped = _strip_negative_directive(text)
        if stripped is None:
            dos.append(text)
        else:
            donts.append(stripped)

    if not dos and not donts:
        return "## Do's and Don'ts\n\n_No principles recorded._"

    lines = ["## Do's and Don'ts"]
    if dos:
        lines.extend(["", "**Do**", ""])
        lines.extend(f"- {item}" for item in dos)
    if donts:
        lines.extend(["", "**Don't**", ""])
        lines.extend(f"- {item}" for item in donts)
    return "\n".join(lines)


def _dict_token(tokens: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = tokens.get(key)
    return value if isinstance(value, dict) and value else None


def _ordered_keys(values: dict[str, Any], canonical: tuple[str, ...]) -> list[str]:
    present = [key for key in canonical if key in values]
    present.extend(sorted(key for key in values if key not in canonical))
    return present


def _scale_keys(values: dict[str, Any]) -> list[str]:
    numeric: list[tuple[int, str]] = []
    other: list[str] = []
    for key in values:
        try:
            numeric.append((int(str(key)), key))
        except ValueError:
            other.append(key)
    return [key for _, key in sorted(numeric)] + other


def _format_color_value(value: Any) -> str:
    text = str(value)
    if _HEX_RE.fullmatch(text):
        return text
    return f"`{text}`"


def _color_role(key: str) -> str:
    roles = {
        "bg": "Page background",
        "fg": "Primary ink",
        "accent": "Accent / highlight",
        "muted": "Secondary / muted",
    }
    return roles.get(key, _humanize_key(key))


def _humanize_key(key: str) -> str:
    return str(key).replace("_", " ").replace("-", " ").strip().title()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _strip_negative_directive(text: str) -> str | None:
    lowered = text.strip().lower()
    for directive in _NEGATIVE_DIRECTIVES:
        if lowered == directive:
            return ""
        if lowered.startswith(directive + " "):
            return _uppercase_first(text[len(directive):].strip(" :;,-"))
    return None


def _fenced(body: str, language: str) -> str:
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}{language}\n{body}\n{fence}"


def _yaml_scalar(value: Any) -> str:
    text = str(value)
    if not text:
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_.:/@+-]+", text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _uppercase_first(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


def _npx_executable() -> str:
    return shutil.which("npx.cmd") or shutil.which("npx") or "npx"


def _designmd_command_name(npx: str) -> str:
    # The package's bin is named `design.md`. On Windows, invoking that bare
    # name can route through the Markdown file association, so ask npx for the
    # generated .cmd shim explicitly.
    if Path(npx).suffix.lower() == ".cmd":
        return "design.md.cmd"
    return "design.md"


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _join_output(stdout: Any, stderr: Any) -> str:
    parts = []
    for value in (stdout, stderr):
        if not value:
            continue
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        parts.append(str(value).strip())
    return "\n".join(part for part in parts if part)


def _cli_unavailable(message: str, *, raw_output: str | None = None) -> dict:
    return {
        "ok": None,
        "warnings": [],
        "errors": [],
        "wcag_failures": [],
        "raw_output": raw_output or message,
        "error": message,
    }


def _looks_like_cli_unavailable(raw_output: str) -> bool:
    lowered = raw_output.lower()
    return any(marker in lowered for marker in _CLI_UNAVAILABLE_MARKERS)


def _parse_lint_output(raw_output: str) -> dict[str, list]:
    warnings: list[str] = []
    errors: list[str] = []
    wcag_failures: list[dict[str, str]] = []
    for line in _output_lines(raw_output):
        lowered = line.lower()
        if "wcag" in lowered and ("fail" in lowered or "error" in lowered):
            wcag_failures.append({"message": line})
        if "warning" in lowered or lowered.startswith("warn"):
            warnings.append(line)
        elif "error" in lowered or lowered.startswith("fail"):
            errors.append(line)
    return {"warnings": warnings, "errors": errors, "wcag_failures": wcag_failures}


def _output_lines(raw_output: str) -> list[str]:
    return [
        _ANSI_RE.sub("", line).strip()
        for line in raw_output.splitlines()
        if _ANSI_RE.sub("", line).strip()
    ]
