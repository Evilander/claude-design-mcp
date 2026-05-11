"""Tests for CSP injection and metadata size-clamping."""

from __future__ import annotations

from claude_design.designer import _clamp_metadata, _extract_html_block
from claude_design.studio import inject_csp


def test_inject_csp_into_existing_head():
    html = "<!doctype html><html><head><title>x</title></head><body></body></html>"
    out = inject_csp(html)
    assert "Content-Security-Policy" in out
    # CSP must come immediately after <head>
    assert out.index("Content-Security-Policy") < out.index("<title>")


def test_inject_csp_synthesizes_head_if_missing():
    html = "<!doctype html><html><body>x</body></html>"
    out = inject_csp(html)
    assert "<head>" in out
    assert "Content-Security-Policy" in out


def test_inject_csp_idempotent():
    html = "<!doctype html><html><head><title>x</title></head><body></body></html>"
    once = inject_csp(html)
    twice = inject_csp(once)
    assert twice.count("Content-Security-Policy") == 1


def test_inject_csp_replaces_existing_weak_policy():
    html = (
        '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" '
        'content="default-src *; connect-src *"><title>x</title></head>'
        "<body></body></html>"
    )
    out = inject_csp(html)
    assert out.count("Content-Security-Policy") == 1
    assert "default-src *" not in out
    assert "connect-src 'none'" in out


def test_inject_csp_blocks_external_connections():
    out = inject_csp("<!doctype html><html><head></head><body></body></html>")
    # The directives we care about most:
    assert "default-src 'none'" in out
    assert "script-src 'nonce-" in out
    assert "unsafe-inline" not in out.partition("script-src")[2].split(";", 1)[0]
    assert "connect-src 'none'" in out
    assert "frame-ancestors 'none'" in out


def test_clamp_string_truncates():
    big = "x" * (100_000)
    out = _clamp_metadata(big)
    assert isinstance(out, str)
    assert len(out) <= 8 * 1024


def test_clamp_caps_list_length():
    out = _clamp_metadata(list(range(1000)))
    assert isinstance(out, list)
    assert len(out) <= 32


def test_clamp_caps_nesting_depth():
    nested: object = "leaf"
    for _ in range(20):
        nested = {"k": nested}
    out = _clamp_metadata(nested)
    # Walk back down — at some point we should hit None (depth cap).
    cur = out
    found_none = False
    for _ in range(20):
        if cur is None:
            found_none = True
            break
        if isinstance(cur, dict) and "k" in cur:
            cur = cur["k"]
        else:
            break
    assert found_none, "depth cap should produce a None terminator"


def test_clamp_handles_primitives():
    assert _clamp_metadata(42) == 42
    assert _clamp_metadata(3.14) == 3.14
    assert _clamp_metadata(True) is True
    assert _clamp_metadata(None) is None


def test_extract_html_prefers_longest_fence():
    text = (
        "Here's a hint:\n```html\n<!doctype html><html><body>tiny</body></html>\n```\n"
        "And the real document:\n```html\n<!doctype html><html><body>"
        + "BIG" * 200
        + "</body></html>\n```\n"
    )
    out = _extract_html_block(text)
    assert out is not None
    assert "BIG" * 100 in out  # came from the longer fence


def test_extract_html_handles_crlf():
    text = "```html\r\n<!doctype html><html></html>\r\n```"
    assert _extract_html_block(text) is not None


def test_extract_html_falls_back_to_bare_html_tag():
    text = "preface\n<html><body>no doctype</body></html>\nafter"
    out = _extract_html_block(text)
    assert out is not None
    assert "no doctype" in out
