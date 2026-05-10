"""Contact-sheet index generator + components-page renderer for claude-design-mcp.

We deliberately avoid running an HTTP server: every design is just an HTML file,
so ``file://`` URLs work everywhere with no port conflicts and no lifecycle
management. The contact-sheet page embeds each design in an iframe so you can
flip between them visually.

Both pages emitted from this module pass through ``inject_csp`` and are written
atomically — same security posture as the studio's persisted designs.
"""

from __future__ import annotations

import html as _html
import json
import re
from pathlib import Path
from typing import Iterable

from .studio import DesignRecord, Studio, SystemRecord, _atomic_write_text, inject_csp


_INDEX_FILENAME = "_index.html"

# Permissive enough for hex / rgb / rgba / hsl / named colors but rejects
# anything that would let a model smuggle a URL into a CSS background.
_COLOR_RE = re.compile(
    r"^\s*("
    r"#[0-9a-fA-F]{3,8}"
    r"|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)"
    r"|rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*[0-9.]+\s*\)"
    r"|hsl\(\s*\d+\s*,\s*\d+%\s*,\s*\d+%\s*\)"
    r"|hsla\(\s*\d+\s*,\s*\d+%\s*,\s*\d+%\s*,\s*[0-9.]+\s*\)"
    r"|[a-zA-Z]{3,32}"            # CSS named color
    r")\s*$"
)


def _safe_color(value: str) -> str:
    """Return ``value`` if it parses as a CSS color, else a neutral gray.

    The contact sheet renders palette swatches as ``style="background:VAL"``,
    which is a CSS context — HTML escaping doesn't help. Validating against
    a color shape blocks ``url(...)`` injection and keeps the page intact.
    """
    if not value or not isinstance(value, str):
        return "#888"
    return value if _COLOR_RE.match(value) else "#888"


def build_index(studio: Studio, designs: Iterable[DesignRecord]) -> Path:
    """Write the contact-sheet HTML to ``studio.root / _index.html`` and return its path."""
    designs = list(designs)
    cards = "\n".join(_card(d, studio) for d in designs) or _empty_state()
    page = _PAGE_TEMPLATE.replace("{{CARDS}}", cards).replace(
        "{{COUNT}}", str(len(designs))
    )
    out = studio.root / _INDEX_FILENAME
    _atomic_write_text(out, inject_csp(page))
    return out


def build_components_page(sys_rec: SystemRecord) -> str:
    """Render a system's components into a single-file HTML preview.

    Component ``name`` and ``css`` are HTML-escaped before interpolation. The
    ``html`` field is intentionally raw so components render — but the page
    is wrapped in the same CSP injected by ``inject_csp``, so any hostile
    script the model wrote can't reach external resources.
    """
    name = _html.escape(sys_rec.name or "design system")
    summary = _html.escape(sys_rec.summary or "")
    parts: list[str] = [
        "<!doctype html>",
        "<html lang='en'><head>",
        "<meta charset='utf-8'>",
        f"<title>{name}</title>",
        "<style>body{font-family:system-ui;padding:32px;background:#fafaf7}",
        "h2{margin-top:32px}",
        "pre{background:#1a1a1d;color:#f1efe9;padding:12px;border-radius:6px;overflow:auto}",
        "</style></head><body>",
        f"<h1>{name}</h1>",
        f"<p>{summary}</p>",
    ]
    for c in sys_rec.components or []:
        cname = _html.escape(str(c.get("name", "component")))
        parts.append(f"<h2>{cname}</h2>")
        if c.get("html"):
            parts.append(f"<div>{c['html']}</div>")
        if c.get("css"):
            parts.append(f"<pre><code>{_html.escape(str(c['css']))}</code></pre>")
    parts.append("</body></html>")
    return inject_csp("".join(parts))


def _card(d: DesignRecord, studio: Studio) -> str:
    href = studio.file_url(d.html_path) or "#"
    render_url = studio.file_url(d.render_path)
    title = _html.escape(d.title or d.name or d.id)
    summary = _html.escape(d.summary or "")
    palette = d.palette or []
    swatches = "".join(
        # Swatch values are interpolated into CSS, not HTML — sanitize accordingly.
        f'<span class="sw" style="background:{_html.escape(_safe_color(c))}"></span>'
        for c in palette[:6]
    )
    moves_html = "".join(
        f"<li>{_html.escape(m)}</li>" for m in (d.moves or [])[:5]
    )
    thumb = (
        f'<img loading="lazy" src="{_html.escape(render_url)}" alt="screenshot of {title}">'
        if render_url
        else f'<iframe loading="lazy" src="{_html.escape(href)}" sandbox="allow-same-origin"></iframe>'
    )
    meta_blob = _html.escape(
        json.dumps(
            {"id": d.id, "mode": d.mode, "tier": d.tier, "viewport": d.viewport}
        )
    )
    return f"""
      <article class="card" data-meta='{meta_blob}'>
        <a class="frame" href="{_html.escape(href)}" target="_blank" rel="noopener">{thumb}</a>
        <header class="card-header">
          <h2>{title}</h2>
          <p>{summary}</p>
          <div class="palette">{swatches}</div>
          <ul class="moves">{moves_html}</ul>
          <footer>
            <code>{_html.escape(d.id)}</code>
            <span>·</span>
            <span>{_html.escape(d.mode)}</span>
            <span>·</span>
            <span>{_html.escape(d.tier)}</span>
          </footer>
        </header>
      </article>
    """


def _empty_state() -> str:
    return """
      <div class="empty">
        <h2>No designs yet.</h2>
        <p>Call <code>design_create</code> to make your first one.</p>
      </div>
    """


_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>claude-design-mcp · studio</title>
<meta name="generator" content="claude-design-mcp">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#0b0b0d; --fg:#f1efe9; --muted:#9b958a; --rule:#2a2a2e; --accent:#d6ff3d;
    --serif:'Inter',system-ui,sans-serif; --mono:'JetBrains Mono',ui-monospace,monospace;
  }
  *{box-sizing:border-box}
  html,body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--serif);font-size:15px;line-height:1.5}
  header.top{position:sticky;top:0;z-index:10;background:rgba(11,11,13,.84);backdrop-filter:blur(8px);
    border-bottom:1px solid var(--rule);padding:14px 24px;display:flex;gap:24px;align-items:baseline}
  header.top h1{margin:0;font-size:14px;letter-spacing:.18em;text-transform:uppercase;font-weight:700}
  header.top .count{color:var(--muted);font-family:var(--mono);font-size:12px}
  header.top .accent{color:var(--accent)}
  main{padding:32px 24px 80px;max-width:1600px;margin:0 auto}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:32px}
  .card{background:#111114;border:1px solid var(--rule);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;transition:transform .25s cubic-bezier(.2,.9,.3,1.2),border-color .25s}
  .card:hover{transform:translateY(-3px);border-color:#3a3a40}
  .frame{display:block;aspect-ratio:16/10;background:#000;position:relative}
  .frame iframe,.frame img{width:100%;height:100%;display:block;border:0;object-fit:cover;object-position:top}
  header.card-header{padding:18px 18px 16px}
  .card h2{margin:0 0 4px;font-size:18px;letter-spacing:-.01em}
  .card p{margin:0 0 12px;color:var(--muted);font-size:14px}
  .palette{display:flex;gap:6px;margin:0 0 12px}
  .sw{width:18px;height:18px;border-radius:4px;border:1px solid var(--rule)}
  ul.moves{margin:0 0 14px;padding:0 0 0 18px;color:var(--muted);font-size:13px}
  ul.moves li{margin:0 0 2px}
  .card footer{display:flex;gap:8px;align-items:center;color:var(--muted);font-family:var(--mono);font-size:11px;border-top:1px solid var(--rule);padding:12px 18px;background:#0d0d10}
  .card footer code{color:var(--accent)}
  .empty{padding:80px 24px;text-align:center;color:var(--muted)}
  .empty h2{color:var(--fg);margin:0 0 8px}
  @media (prefers-reduced-motion: reduce){ .card{transition:none} }
</style>
</head>
<body>
  <header class="top">
    <h1>claude-design-mcp <span class="accent">studio</span></h1>
    <span class="count">{{COUNT}} designs</span>
  </header>
  <main>
    <section class="grid">
      {{CARDS}}
    </section>
  </main>
</body>
</html>
"""
