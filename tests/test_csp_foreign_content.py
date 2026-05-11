"""Adversarial tests for foreign-content meta refresh + nested-script edge cases.

The frontier-red-team review of v0.2.0-rc1 flagged two specific concerns
about the parser-driven CSP injection:

1. Python's stdlib ``HTMLParser`` does not implement HTML5 foreign-content
   insertion rules — a ``<svg>`` or ``<math>`` subtree may tokenize meta
   tags differently than a browser does. If the model can land a
   ``<meta http-equiv="refresh">`` inside a foreign-content subtree that
   the stripper misses, the redirect-to-evil channel is back open.
2. Nested ``<script>`` tags inside foreign content (``<svg><script>``)
   should still get nonce-stamped.

These tests assert both. The network allowlist in renderer.py is a
second wall, but defense-in-depth is the whole point of the parser pass.
"""

from __future__ import annotations

import re

from claude_design.studio import inject_csp


def _csp_nonce(html: str) -> str:
    m = re.search(
        r"script-src 'nonce-([A-Za-z0-9_-]+)'",
        html,
    )
    assert m, f"CSP nonce not found in:\n{html}"
    return m.group(1)


def test_script_inside_svg_gets_nonced():
    """A <svg><script>...</script></svg> nest still has its script nonced."""
    html = (
        "<!doctype html><html><head></head><body>"
        '<svg width="10"><script>console.log("svg-script")</script></svg>'
        "</body></html>"
    )
    out = inject_csp(html)
    nonce = _csp_nonce(out)
    script_tags = re.findall(r"<script(\s[^>]*)?>", out)
    assert script_tags, "expected at least one <script> open tag in output"
    for attrs in script_tags:
        assert nonce in (attrs or ""), (
            f"script tag without document nonce: {attrs!r}"
        )


def test_meta_refresh_inside_svg_is_stripped_or_neutralized():
    """A foreign-content meta refresh must not survive into the persisted doc."""
    html = (
        "<!doctype html><html><head>"
        '<svg><meta http-equiv="refresh" content="0;url=https://evil.example/" /></svg>'
        "</head><body>ok</body></html>"
    )
    out = inject_csp(html)
    pattern = re.compile(
        r"<meta\b[^>]*http-equiv\s*=\s*['\"]?refresh['\"]?[^>]*>",
        re.IGNORECASE,
    )
    matches = pattern.findall(out)
    assert not matches, (
        f"active meta-refresh survived the stripper: {matches!r}"
    )
    assert "evil.example" not in out


def test_deeply_nested_script_still_nonced():
    """<script> deep inside the DOM still gets stamped."""
    html = (
        "<!doctype html><html><head></head><body>"
        "<div><section><article>"
        "<script>document.body.dataset.ready='1'</script>"
        "</article></section></div>"
        "</body></html>"
    )
    out = inject_csp(html)
    nonce = _csp_nonce(out)
    script_open = re.search(r"<script(\s[^>]*)?>", out)
    assert script_open is not None
    assert nonce in (script_open.group(1) or ""), (
        f"deeply-nested script tag did not get nonce: {script_open.group(0)!r}"
    )


def test_meta_refresh_at_root_is_still_stripped():
    """Regression test for the baseline meta-refresh strip behaviour."""
    html = (
        '<!doctype html><html><head>'
        '<meta http-equiv="refresh" content="0;url=https://evil.example/">'
        '</head><body>x</body></html>'
    )
    out = inject_csp(html)
    assert "evil.example" not in out
    assert "http-equiv=\"refresh\"" not in out.lower()
