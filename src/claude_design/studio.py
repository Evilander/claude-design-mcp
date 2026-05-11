"""Persistence layer for claude-design-mcp.

The studio is just three things on disk:

  ``studio/designs.db``       — SQLite database (designs, systems, lineage)
  ``studio/designs/<id>.html`` — full HTML documents
  ``studio/renders/<id>-<viewport>.png`` — Playwright screenshots
  ``studio/exports/<id>/``    — exported bundles

Keeping it filesystem-first means anything in the studio is browsable directly
without the MCP running, and the SQLite layer is just an index.

Designs are written through ``write_html`` which injects a strict
Content-Security-Policy ``<meta>`` tag *before* persisting. The CSP keeps
model-authored JavaScript from exfiltrating data to arbitrary domains or
reaching out to network resources beyond an explicit font/image allowlist.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from html import escape as html_escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS designs (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    parent_id   TEXT REFERENCES designs(id) ON DELETE SET NULL,
    brief       TEXT NOT NULL,
    mode        TEXT NOT NULL,
    tier        TEXT NOT NULL,
    viewport    TEXT NOT NULL,
    title       TEXT,
    summary     TEXT,
    palette     TEXT,    -- JSON array
    fonts       TEXT,    -- JSON array
    tokens      TEXT,    -- JSON object
    moves       TEXT,    -- JSON array
    notes       TEXT,
    html_path   TEXT NOT NULL,
    render_path TEXT,
    created_at  REAL NOT NULL,
    iteration_of TEXT REFERENCES designs(id) ON DELETE SET NULL,
    instructions TEXT
);

CREATE INDEX IF NOT EXISTS idx_designs_created ON designs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_designs_parent  ON designs(parent_id);
CREATE INDEX IF NOT EXISTS idx_designs_name    ON designs(name);

CREATE TABLE IF NOT EXISTS systems (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    summary      TEXT,
    tokens       TEXT NOT NULL,   -- JSON
    components   TEXT,             -- JSON
    principles   TEXT,             -- JSON
    source_ids   TEXT NOT NULL,   -- JSON array
    created_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_systems_created ON systems(created_at DESC);
"""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class DesignRecord:
    id: str
    name: str | None
    parent_id: str | None
    brief: str
    mode: str
    tier: str
    viewport: str
    title: str | None
    summary: str | None
    palette: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)
    tokens: dict[str, Any] = field(default_factory=dict)
    moves: list[str] = field(default_factory=list)
    notes: str | None = None
    html_path: str = ""
    render_path: str | None = None
    created_at: float = field(default_factory=time.time)
    iteration_of: str | None = None
    instructions: str | None = None

    def to_summary(self) -> dict[str, Any]:
        """A compact, agent-friendly view (no HTML body)."""
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "summary": self.summary,
            "mode": self.mode,
            "tier": self.tier,
            "viewport": self.viewport,
            "palette": self.palette,
            "fonts": self.fonts,
            "tokens": self.tokens,
            "moves": self.moves,
            "notes": self.notes,
            "parent_id": self.parent_id,
            "iteration_of": self.iteration_of,
            "html_path": self.html_path,
            "render_path": self.render_path,
            "preview_url": _file_url(self.html_path) if self.html_path else None,
            "render_url": _file_url(self.render_path) if self.render_path else None,
            "created_at": self.created_at,
        }


@dataclass
class SystemRecord:
    id: str
    name: str | None
    summary: str | None
    tokens: dict[str, Any]
    components: list[dict[str, Any]]
    principles: list[str]
    source_ids: list[str]
    created_at: float = field(default_factory=time.time)

    def to_summary(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _file_url(path: str | None) -> str | None:
    """Convert a Windows or POSIX path into a file:// URL."""
    if not path:
        return None
    p = Path(path).resolve()
    return p.as_uri()


def _short_id() -> str:
    """A 12-char URL-safe id. Long enough to never collide in a personal studio."""
    return uuid.uuid4().hex[:12]


def _slugify(text: str, fallback: str = "untitled") -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback


# Windows reserved device names — refuse to write to these even if the
# sanitizer would otherwise produce them.
_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _safe_filename(name: str) -> str:
    """Sanitize a name for use in filesystem paths.

    We never pass user-controlled paths to disk; instead we always combine the
    studio root with a sanitized component, and reject any traversal characters
    or Windows reserved device names.
    """
    cleaned = "".join(c for c in name if c.isalnum() or c in "-_")
    cleaned = cleaned[:64]
    if not cleaned:
        raise ValueError(
            f"filename {name!r} is empty after sanitization; pass an alphanumeric "
            "or hyphenated id."
        )
    if cleaned.lower() in _WINDOWS_RESERVED:
        cleaned = f"{cleaned}-design"
    return cleaned


# Strict CSP injected into every persisted HTML document. The directives:
#   * default-src 'none'           — deny by default
#   * script-src 'nonce-...'       — allow only nonce-stamped inline scripts
#   * style-src 'unsafe-inline' + Google Fonts host
#   * font-src + img-src restricted to the same allowlist as renderer.py
#   * connect-src 'none'           — block fetch/XHR/sendBeacon exfil
#   * frame-ancestors 'none'       — designs may not be reframed
#   * form-action 'none'           — model can't bounce a submit to anywhere
def _csp_meta(nonce: str) -> str:
    return (
        "<meta http-equiv=\"Content-Security-Policy\" content=\""
        "default-src 'none'; "
        "base-uri 'self'; "
        "form-action 'none'; "
        "frame-ancestors 'none'; "
        f"script-src 'nonce-{nonce}'; "
        "style-src 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com data:; "
        "img-src 'self' data: https://images.unsplash.com https://picsum.photos "
        "https://fastly.picsum.photos https://placehold.co; "
        "connect-src 'none'\">"
    )


_DOCTYPE_RE = re.compile(r"<!doctype\s+html[^>]*>", re.IGNORECASE)


def _generate_nonce() -> str:
    return secrets.token_urlsafe(16)


class _HeadFinder(HTMLParser):
    """Find the byte offset of the first real <head> open tag.

    Uses Python's stdlib HTML parser, which correctly skips HTML comments,
    CDATA-like content inside ``<script>``/``<style>``, and decoy text. A
    decoy comment like ``<!-- <head> -->`` will never trigger this — only an
    actual parsed-as-HTML ``<head>`` element will. That closes the regex-only
    "comment-wrapped decoy" bypass that previously evaded CSP injection.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.head_start_offset: int | None = None
        self.head_end_offset: int | None = None
        self.head_open_count = 0
        self._template_depth = 0
        self._source: str = ""

    def feed_with_source(self, html: str) -> None:
        self._source = html
        self.feed(html)
        self.close()

    def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        tag_name = tag.lower()
        if tag_name == "template":
            self._template_depth += 1
            return
        if tag_name != "head" or self._template_depth:
            return
        self.head_open_count += 1
        if self.head_end_offset is None:
            # getpos() returns (line, col) — convert to absolute byte offset
            # in the *source string* and walk to the end of the tag.
            line, col = self.getpos()
            start_idx = _line_col_to_index(self._source, line, col)
            self.head_start_offset = start_idx
            # Advance to the first '>' after start to find end-of-tag.
            raw = self.get_starttag_text()
            if raw:
                self.head_end_offset = start_idx + len(raw)
            else:
                close = self._source.find(">", start_idx)
                self.head_end_offset = close + 1 if close != -1 else start_idx

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "template" and self._template_depth:
            self._template_depth -= 1


def _line_col_to_index(source: str, line: int, col: int) -> int:
    """Convert ``(line, col)`` (1-indexed line, 0-indexed col) to absolute idx."""
    idx = 0
    for _ in range(line - 1):
        nl = source.find("\n", idx)
        if nl == -1:
            return len(source)
        idx = nl + 1
    return min(idx + col, len(source))


def _strip_unsafe_meta_tags(html: str) -> str:
    """Remove ``<meta http-equiv>`` tags that browsers honor but CSP doesn't cover.

    Targets ``refresh`` (no CSP directive blocks auto-redirect), any existing
    ``Content-Security-Policy`` or ``Content-Security-Policy-Report-Only`` so
    the model can't downgrade our injected policy, and ``X-Frame-Options``
    which is parser-honored independent of ``frame-ancestors``.

    We use a stdlib HTML tokenizer-style pass rather than regex so a model
    can't smuggle a tag past with whitespace or attribute-order tricks.
    """
    parser = _UnsafeMetaStripper()
    parser.feed_with_source(html)
    return parser.cleaned


def _apply_script_nonces(html: str, nonce: str) -> str:
    parser = _ScriptNonceRewriter(nonce)
    parser.feed_with_source(html)
    return parser.cleaned


_PRE_POLICY_DROP_CONTENT_TAGS = frozenset({
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
    "video",
    "audio",
    "picture",
})
_PRE_POLICY_DROP_TAGS = frozenset({
    "base",
    "link",
    "meta",
    "img",
    "image",
    "source",
    "track",
})
_PRE_POLICY_URL_ATTRS = frozenset({
    "action",
    "data",
    "formaction",
    "href",
    "manifest",
    "poster",
    "src",
    "srcset",
    "xlink:href",
})


def _sanitize_pre_policy_prefix(html: str) -> str:
    parser = _PrePolicySanitizer()
    parser.feed_with_source(html)
    return parser.cleaned


class _UnsafeMetaStripper(HTMLParser):
    """Rewrite the source, dropping unsafe ``<meta http-equiv="...">`` tags."""

    _UNSAFE_VALUES = frozenset({
        "refresh",
        "content-security-policy",
        "content-security-policy-report-only",
        "x-frame-options",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.cleaned_chunks: list[str] = []
        self._source: str = ""
        self._cursor: int = 0

    @property
    def cleaned(self) -> str:
        return "".join(self.cleaned_chunks) + self._source[self._cursor:]

    def feed_with_source(self, html: str) -> None:
        self._source = html
        self.feed(html)
        self.close()

    def _flush_to(self, idx: int) -> None:
        if idx > self._cursor:
            self.cleaned_chunks.append(self._source[self._cursor:idx])
            self._cursor = idx

    def _tag_extent(self) -> tuple[int, int]:
        line, col = self.getpos()
        start = _line_col_to_index(self._source, line, col)
        close = self._source.find(">", start)
        end = close + 1 if close != -1 else start
        return start, end

    def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        if tag.lower() != "meta":
            return
        for name, value in attrs:
            if (name or "").lower() == "http-equiv" and (value or "").lower() in self._UNSAFE_VALUES:
                start, end = self._tag_extent()
                self._flush_to(start)
                self._cursor = end  # skip the unsafe tag
                return

    def handle_startendtag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        self.handle_starttag(tag, attrs)


class _PrePolicySanitizer(HTMLParser):
    """Neutralize active content before the CSP meta is parsed by a browser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.cleaned_chunks: list[str] = []
        self._source: str = ""
        self._cursor: int = 0
        self._drop_stack: list[str] = []

    @property
    def cleaned(self) -> str:
        tail = "" if self._drop_stack else self._source[self._cursor:]
        return "".join(self.cleaned_chunks) + tail

    def feed_with_source(self, html: str) -> None:
        self._source = html
        self.feed(html)
        self.close()

    def _flush_to(self, idx: int) -> None:
        if idx > self._cursor:
            self.cleaned_chunks.append(self._source[self._cursor:idx])
            self._cursor = idx

    def _tag_extent(self) -> tuple[int, int]:
        line, col = self.getpos()
        start = _line_col_to_index(self._source, line, col)
        raw = self.get_starttag_text()
        if raw:
            return start, start + len(raw)
        close = self._source.find(">", start)
        end = close + 1 if close != -1 else start
        return start, end

    def _drop_tag(self) -> None:
        start, end = self._tag_extent()
        self._flush_to(start)
        self._cursor = end

    def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        tag_name = tag.lower()
        if self._drop_stack:
            if tag_name in _PRE_POLICY_DROP_CONTENT_TAGS:
                self._drop_stack.append(tag_name)
            return
        if tag_name in _PRE_POLICY_DROP_CONTENT_TAGS:
            self._drop_tag()
            self._drop_stack.append(tag_name)
            return
        if tag_name in _PRE_POLICY_DROP_TAGS:
            self._drop_tag()
            return
        self._rewrite_tag_if_needed(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        if self._drop_stack:
            return
        tag_name = tag.lower()
        if tag_name in _PRE_POLICY_DROP_CONTENT_TAGS or tag_name in _PRE_POLICY_DROP_TAGS:
            self._drop_tag()
            return
        self._rewrite_tag_if_needed(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        if not self._drop_stack:
            return
        tag_name = tag.lower()
        if tag_name != self._drop_stack[-1]:
            return
        start, end = self._tag_extent()
        self._cursor = end
        self._drop_stack.pop()

    def _rewrite_tag_if_needed(self, tag: str, attrs: list, *, self_closing: bool) -> None:
        clean_attrs = []
        changed = False
        for name, value in attrs:
            attr_name = (name or "").lower()
            if attr_name.startswith("on") or attr_name in _PRE_POLICY_URL_ATTRS:
                changed = True
                continue
            clean_attrs.append((name, value))
        if not changed:
            return
        start, end = self._tag_extent()
        self._flush_to(start)
        self.cleaned_chunks.append(_build_start_tag(tag, clean_attrs, self_closing))
        self._cursor = end


class _ScriptNonceRewriter(HTMLParser):
    """Strip model-authored script nonces and nonce-stamp inline scripts."""

    def __init__(self, nonce: str) -> None:
        super().__init__(convert_charrefs=False)
        self.cleaned_chunks: list[str] = []
        self._source: str = ""
        self._cursor: int = 0
        self._nonce = nonce

    @property
    def cleaned(self) -> str:
        return "".join(self.cleaned_chunks) + self._source[self._cursor:]

    def feed_with_source(self, html: str) -> None:
        self._source = html
        self.feed(html)
        self.close()

    def _flush_to(self, idx: int) -> None:
        if idx > self._cursor:
            self.cleaned_chunks.append(self._source[self._cursor:idx])
            self._cursor = idx

    def _tag_extent(self) -> tuple[int, int]:
        line, col = self.getpos()
        start = _line_col_to_index(self._source, line, col)
        raw = self.get_starttag_text()
        if raw:
            return start, start + len(raw)
        close = self._source.find(">", start)
        end = close + 1 if close != -1 else start
        return start, end

    def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        if tag.lower() != "script":
            return
        self._rewrite_script_tag(attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
        if tag.lower() != "script":
            return
        self._rewrite_script_tag(attrs, self_closing=True)

    def _rewrite_script_tag(self, attrs: list, *, self_closing: bool) -> None:
        start, end = self._tag_extent()
        self._flush_to(start)
        clean_attrs = [
            (name, value)
            for name, value in attrs
            if (name or "").lower() != "nonce"
        ]
        has_src = any((name or "").lower() == "src" for name, _ in clean_attrs)
        if not has_src:
            clean_attrs.append(("nonce", self._nonce))
        self.cleaned_chunks.append(_build_script_start_tag(clean_attrs, self_closing))
        self._cursor = end


def _build_script_start_tag(attrs: list, self_closing: bool) -> str:
    return _build_start_tag("script", attrs, self_closing)


def _build_start_tag(tag: str, attrs: list, self_closing: bool) -> str:
    parts = [f"<{tag}"]
    for name, value in attrs:
        if not name:
            continue
        if value is None:
            parts.append(f" {name}")
        else:
            parts.append(f' {name}="{html_escape(str(value), quote=True)}"')
    parts.append(" />" if self_closing else ">")
    return "".join(parts)


def inject_csp(html: str) -> str:
    """Inject the strict CSP <meta> and strip unsafe model-authored meta tags.

    Uses Python's stdlib HTML parser to find the first real ``<head>``, which
    correctly ignores tag-shaped text inside comments, ``<script>``, and
    ``<style>``. Before injecting, we strip any existing CSP meta (so the
    model can't downgrade our policy), ``<meta http-equiv="refresh">``, and
    ``<meta http-equiv="X-Frame-Options">``.
    """
    nonce = _generate_nonce()
    csp_meta = _csp_meta(nonce)
    cleaned = _apply_script_nonces(_strip_unsafe_meta_tags(html), nonce)
    finder = _HeadFinder()
    finder.feed_with_source(cleaned)
    if finder.head_start_offset is not None and finder.head_end_offset is not None:
        prefix = _sanitize_pre_policy_prefix(cleaned[:finder.head_start_offset])
        head_and_rest = cleaned[finder.head_start_offset:]
        head_end = finder.head_end_offset - finder.head_start_offset
        return prefix + head_and_rest[:head_end] + "\n  " + csp_meta + head_and_rest[head_end:]

    # No real <head>: synthesize a policy-bearing head before all model content.
    body = _DOCTYPE_RE.sub("", cleaned, count=1).lstrip()
    insert = f"\n<head>\n  {csp_meta}\n</head>"
    return f"<!doctype html>{insert}\n{body}"


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text to ``path`` atomically: per-process tmp, symlink refuse, rename.

    Per-process unique tmp suffix prevents two MCP processes that share a studio
    from clobbering each other's tmp files mid-write.
    """
    if path.is_symlink():
        # Refuse to follow symlinks — protect against shared-folder attacks.
        path.unlink()
    tmp = path.with_suffix(
        f"{path.suffix}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Studio
# ---------------------------------------------------------------------------


class Studio:
    """Filesystem + SQLite-backed design persistence."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self.designs_dir = self.root / "designs"
        self.renders_dir = self.root / "renders"
        self.exports_dir = self.root / "exports"
        for d in (self.root, self.designs_dir, self.renders_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._db_path = self.root / "designs.db"
        self._lock = threading.RLock()
        # Cache one connection for the studio's lifetime. Pragmas are applied
        # once on creation; every subsequent ``_conn()`` reuses it under the
        # lock. WAL mode lets the connection survive long-lived without
        # blocking external readers.
        self._cached_conn: sqlite3.Connection | None = None
        self._init_schema()

    # -- DB plumbing --------------------------------------------------------

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            timeout=10.0,
            check_same_thread=False,  # the RLock guarantees serialized access
        )
        conn.row_factory = sqlite3.Row
        # WAL gives us safe concurrent reads while we write; busy_timeout
        # smooths over momentary contention from a second process touching
        # the same studio dir (e.g. CLI + MCP).
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._cached_conn is None:
                self._cached_conn = self._open_connection()
            conn = self._cached_conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def close(self) -> None:
        """Close the cached SQLite connection. Idempotent."""
        with self._lock:
            if self._cached_conn is not None:
                try:
                    self._cached_conn.close()
                except sqlite3.Error:
                    pass
                self._cached_conn = None

    def __del__(self) -> None:  # pragma: no cover — best-effort cleanup
        try:
            self.close()
        except Exception:
            pass

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)

    # -- Design CRUD --------------------------------------------------------

    def new_id(self) -> str:
        return _short_id()

    def write_html(self, design_id: str, html: str) -> Path:
        # Hard ceiling on persisted designs. The model's natural output is
        # ~10-30KB; anything pushing 2MB is almost certainly a prompt-injected
        # base64 amplification rather than a real design. The renderer would
        # also choke on such input. Cap at 2 MiB.
        max_bytes = 2 * 1024 * 1024
        encoded_len = len(html.encode("utf-8"))
        if encoded_len > max_bytes:
            raise ValueError(
                f"Design HTML is {encoded_len:,} bytes; refusing to persist > "
                f"{max_bytes:,}. The model output is unusually large — likely "
                "a prompt-injection amplification, not a real design. Retry "
                "with a tighter brief or set a smaller scope."
            )
        path = self.designs_dir / f"{_safe_filename(design_id)}.html"
        _atomic_write_text(path, inject_csp(html))
        return path

    def render_path_for(self, design_id: str, viewport: str) -> Path:
        return self.renders_dir / f"{_safe_filename(design_id)}-{_safe_filename(viewport)}.png"

    def insert_design(self, rec: DesignRecord) -> DesignRecord:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO designs (
                    id, name, parent_id, brief, mode, tier, viewport, title, summary,
                    palette, fonts, tokens, moves, notes, html_path, render_path,
                    created_at, iteration_of, instructions
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rec.id, rec.name, rec.parent_id, rec.brief, rec.mode, rec.tier,
                    rec.viewport, rec.title, rec.summary,
                    json.dumps(rec.palette), json.dumps(rec.fonts),
                    json.dumps(rec.tokens), json.dumps(rec.moves), rec.notes,
                    rec.html_path, rec.render_path, rec.created_at,
                    rec.iteration_of, rec.instructions,
                ),
            )
        return rec

    def update_render_path(self, design_id: str, render_path: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE designs SET render_path = ? WHERE id = ?",
                (render_path, design_id),
            )

    def get_design(self, design_id: str) -> DesignRecord | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM designs WHERE id = ?", (design_id,)
            ).fetchone()
        return self._row_to_design(row) if row else None

    def get_design_html(self, design_id: str) -> str | None:
        rec = self.get_design(design_id)
        if not rec or not rec.html_path:
            return None
        path = Path(rec.html_path)
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        except OSError:
            return None

    def list_designs(
        self,
        limit: int = 20,
        offset: int = 0,
        name_contains: str | None = None,
    ) -> tuple[list[DesignRecord], bool]:
        """Return (records, has_more) for a paginated list.

        Uses the ``limit + 1`` trick so we don't pay for a second
        ``SELECT COUNT(*)`` over the same filter — at the cost of giving up
        the exact total. Callers that need a total can compute one with a
        dedicated count query, but in practice the pager just needs to know
        whether to expose a "next" affordance.
        """
        with self._conn() as c:
            where = ""
            params: list[Any] = []
            if name_contains:
                where = (
                    "WHERE name LIKE ? ESCAPE '\\' "
                    "OR title LIKE ? ESCAPE '\\' "
                    "OR summary LIKE ? ESCAPE '\\'"
                )
                # Escape SQLite LIKE wildcards so user-supplied substrings can't
                # accidentally match everything via `_` or `%`.
                escaped = (
                    name_contains.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                like = f"%{escaped}%"
                params = [like, like, like]
            rows = c.execute(
                f"""SELECT * FROM designs {where}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?""",
                [*params, limit + 1, offset],
            ).fetchall()
        has_more = len(rows) > limit
        return [self._row_to_design(r) for r in rows[:limit]], has_more

    def lineage(self, design_id: str, *, max_depth: int = 64) -> list[DesignRecord]:
        """Return ancestors of a design, oldest first (root → ... → design).

        Single recursive CTE: one round-trip, depth-bounded in SQL. Cycles
        (which can only happen on corrupted data) get de-duped in Python —
        the CTE itself uses UNION ALL because SQLite's recursive UNION can't
        be combined with an ORDER BY. ``max_depth`` is a hard upper bound
        regardless.
        """
        with self._conn() as c:
            rows = c.execute(
                """
                WITH RECURSIVE chain(id, ancestor_id, depth) AS (
                    SELECT id, COALESCE(parent_id, iteration_of), 0
                      FROM designs
                     WHERE id = ?
                    UNION ALL
                    SELECT d.id, COALESCE(d.parent_id, d.iteration_of), c.depth + 1
                      FROM designs d
                      JOIN chain c ON d.id = c.ancestor_id
                     WHERE c.depth < ?
                )
                SELECT d.*, c.depth AS _chain_depth
                  FROM chain c
                  JOIN designs d ON d.id = c.id
                 ORDER BY c.depth ASC
                """,
                (design_id, max_depth),
            ).fetchall()
        # Dedupe by id while preserving first occurrence (which is shallowest).
        seen: set[str] = set()
        unique: list[sqlite3.Row] = []
        for r in rows:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            unique.append(r)
        # Caller expects oldest first (root → ... → design), so reverse the
        # depth-ascending order we got back.
        return [self._row_to_design(r) for r in reversed(unique)]

    @staticmethod
    def _row_to_design(row: sqlite3.Row) -> DesignRecord:
        return DesignRecord(
            id=row["id"],
            name=row["name"],
            parent_id=row["parent_id"],
            brief=row["brief"],
            mode=row["mode"],
            tier=row["tier"],
            viewport=row["viewport"],
            title=row["title"],
            summary=row["summary"],
            palette=json.loads(row["palette"] or "[]"),
            fonts=json.loads(row["fonts"] or "[]"),
            tokens=json.loads(row["tokens"] or "{}"),
            moves=json.loads(row["moves"] or "[]"),
            notes=row["notes"],
            html_path=row["html_path"],
            render_path=row["render_path"],
            created_at=row["created_at"],
            iteration_of=row["iteration_of"],
            instructions=row["instructions"],
        )

    # -- System CRUD --------------------------------------------------------

    def insert_system(self, rec: SystemRecord) -> SystemRecord:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO systems (id, name, summary, tokens, components, principles, source_ids, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    rec.id, rec.name, rec.summary,
                    json.dumps(rec.tokens),
                    json.dumps(rec.components),
                    json.dumps(rec.principles),
                    json.dumps(rec.source_ids),
                    rec.created_at,
                ),
            )
        return rec

    def get_system(self, system_id: str) -> SystemRecord | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM systems WHERE id = ?", (system_id,)
            ).fetchone()
        if not row:
            return None
        return SystemRecord(
            id=row["id"],
            name=row["name"],
            summary=row["summary"],
            tokens=json.loads(row["tokens"] or "{}"),
            components=json.loads(row["components"] or "[]"),
            principles=json.loads(row["principles"] or "[]"),
            source_ids=json.loads(row["source_ids"] or "[]"),
            created_at=row["created_at"],
        )

    # -- Convenience --------------------------------------------------------

    def file_url(self, path: str | None) -> str | None:
        return _file_url(path)

    def slug_for(self, *parts: str) -> str:
        return _slugify("-".join(parts))
