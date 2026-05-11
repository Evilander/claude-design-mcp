from __future__ import annotations

import re
from html.parser import HTMLParser

from claude_design.studio import inject_csp

_CSP_NONCE_RE = re.compile(r"script-src 'nonce-([^']+)'")
_SCRIPT_NONCE_RE = re.compile(r"\bnonce=\"([^\"]+)\"", re.IGNORECASE)


def test_nonce_in_csp_and_scripts():
    html = '<!doctype html><html><head></head><body><script>console.log("hi")</script></body></html>'
    out = inject_csp(html)
    csp_nonce = _csp_nonce(out)

    scripts = _script_tags(out)
    assert scripts == [f'<script nonce="{csp_nonce}">']


def test_existing_nonce_stripped():
    html = '<!doctype html><html><head></head><body><script nonce="evil">run()</script></body></html>'
    out = inject_csp(html)
    csp_nonce = _csp_nonce(out)

    assert "evil" not in out
    assert _script_tags(out) == [f'<script nonce="{csp_nonce}">']


def test_external_script_unaffected():
    html = (
        "<!doctype html><html><head></head><body>"
        '<script src="https://example.invalid/x.js" nonce="evil"></script>'
        "</body></html>"
    )
    out = inject_csp(html)

    assert _csp_nonce(out)
    assert _script_tags(out) == ['<script src="https://example.invalid/x.js">']
    assert "evil" not in out


def test_no_scripts_no_breakage():
    html = "<!doctype html><html><head></head><body><main>No JS</main></body></html>"
    out = inject_csp(html)

    assert _csp_nonce(out)
    assert _script_tags(out) == []
    assert "<main>No JS</main>" in out


def test_multiple_scripts_same_nonce():
    html = (
        "<!doctype html><html><head></head><body>"
        '<script type="application/json">{"ok":true}</script>'
        "<script>console.log(1)</script>"
        "</body></html>"
    )
    out = inject_csp(html)
    csp_nonce = _csp_nonce(out)
    script_nonces = _script_nonces(out)

    assert script_nonces == [csp_nonce, csp_nonce]


def test_nonce_per_document():
    html = "<!doctype html><html><head></head><body><script>run()</script></body></html>"

    assert _csp_nonce(inject_csp(html)) != _csp_nonce(inject_csp(html))


def test_decoy_script_in_comment_no_nonce_added():
    html = (
        "<!doctype html><html><head></head><body>"
        "<!-- <script>fake</script> -->"
        "</body></html>"
    )
    out = inject_csp(html)

    assert "<!-- <script>fake</script> -->" in out
    assert _script_tags(out) == []


def test_csp_idempotent_nonce_preserved():
    html = (
        "<!doctype html><html><head></head><body>"
        '<script nonce="stale">one()</script>'
        "<script>two()</script>"
        "</body></html>"
    )
    once = inject_csp(html)
    twice = inject_csp(once)
    csp_nonce = _csp_nonce(twice)

    assert twice.count("Content-Security-Policy") == 1
    assert "stale" not in twice
    assert _script_nonces(twice) == [csp_nonce, csp_nonce]
    assert all(tag.count("nonce=") == 1 for tag in _script_tags(twice))


def test_copy_button_script_gets_nonce():
    html = (
        "<!doctype html><html><head></head><body>"
        '<button id="copyBtn">Copy</button>'
        "<script>"
        "const copyBtn = document.getElementById('copyBtn');"
        "copyBtn.addEventListener('click', () => navigator.clipboard.writeText('x'));"
        "</script>"
        "</body></html>"
    )
    out = inject_csp(html)
    csp_nonce = _csp_nonce(out)
    tags = _script_tags(out)

    assert "copyBtn.addEventListener" in out
    assert len(tags) == 1
    assert _script_nonces(out) == [csp_nonce] * len(tags)


def _csp_nonce(html: str) -> str:
    match = _CSP_NONCE_RE.search(html)
    assert match is not None
    return match.group(1)


def _script_tags(html: str) -> list[str]:
    collector = _ScriptTagCollector()
    collector.feed(html)
    collector.close()
    return collector.tags


def _script_nonces(html: str) -> list[str]:
    return [
        match.group(1)
        for tag in _script_tags(html)
        for match in [_SCRIPT_NONCE_RE.search(tag)]
        if match is not None
    ]


class _ScriptTagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self.tags.append(self.get_starttag_text() or "<script>")
