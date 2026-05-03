"""Tests for build_components_page (formerly _components_html in server)."""

from __future__ import annotations

from claude_design.preview import build_components_page
from claude_design.studio import SystemRecord


def _make_system(**overrides) -> SystemRecord:
    return SystemRecord(
        id="abc123def456",
        name=overrides.get("name", "bone"),
        summary=overrides.get("summary", "paper-and-ink"),
        tokens=overrides.get("tokens", {"color": {"bg": "#fafaf7"}}),
        components=overrides.get("components", []),
        principles=overrides.get("principles", []),
        source_ids=overrides.get("source_ids", ["abc123def456"]),
    )


def test_components_page_includes_csp():
    page = build_components_page(_make_system())
    assert "Content-Security-Policy" in page


def test_components_page_escapes_hostile_name():
    sys_rec = _make_system(name="</style><script>alert(1)</script>")
    page = build_components_page(sys_rec)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_components_page_escapes_component_name_and_css():
    sys_rec = _make_system(
        components=[
            {
                "name": "</h2><script>x</script>",
                "html": "<button>OK</button>",
                "css": "body { color: red; } </code></pre><script>y</script>",
            }
        ]
    )
    page = build_components_page(sys_rec)
    # Hostile sequences in name + css must be escaped.
    assert "<script>x</script>" not in page
    assert "<script>y</script>" not in page
    # Component HTML field is intentionally raw (CSP-defended).
    assert "<button>OK</button>" in page


def test_components_page_handles_no_components():
    page = build_components_page(_make_system(components=[]))
    assert "<h1>" in page
    assert "Content-Security-Policy" in page


def test_components_page_summary_escaped():
    sys_rec = _make_system(summary="<img src=x onerror=alert(1)>")
    page = build_components_page(sys_rec)
    assert "<img src=x onerror" not in page
    assert "&lt;img" in page
