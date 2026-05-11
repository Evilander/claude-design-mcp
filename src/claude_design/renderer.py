"""Playwright-based screenshot renderer for claude-design-mcp.

Rendering is *optional*. If Playwright is not installed (or its browsers are
not), every render call returns ``None`` cleanly and the rest of the studio
keeps working — designs are still written to disk and openable in a browser.

Performance posture
-------------------
A single Chromium browser is kept alive for the lifetime of the process
(``Renderer._ensure_browser``). Each render creates a fresh context (~30-80ms)
and tears it down — far cheaper than relaunching the browser (~500ms+) on
every call. Concurrent renders run in parallel within their own contexts;
the browser instance itself is created under a lock to avoid double-launch.
``Renderer.aclose()`` shuts the browser down cleanly when the server stops.

Security posture
----------------
Model-authored HTML is treated as untrusted. Every page is loaded:

  * with Chromium's default sandbox enabled (we never pass --no-sandbox);
  * inside a fresh per-render ``BrowserContext`` so cookies/storage never
    persist;
  * with a strict allowlist of outbound network hosts (Google Fonts +
    Unsplash + picsum + placehold). Everything else is aborted at the
    request layer, so a poisoned design can't exfiltrate via
    ``<img src=//evil/?q=…>``;
  * with per-call timeouts on goto, font readiness, and screenshot capture.

A failure at any layer returns ``None`` and is logged to stderr — never raised
into the MCP transport.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

# ---------------------------------------------------------------------------
# Viewport presets
# ---------------------------------------------------------------------------

VIEWPORTS: dict[str, tuple[int, int]] = {
    "mobile":  (390, 844),
    "tablet":  (834, 1112),
    "desktop": (1440, 900),
    "wide":    (1920, 1080),
    "hd":      (2560, 1440),
}


def viewport_size(name: str) -> tuple[int, int]:
    return VIEWPORTS.get(name, VIEWPORTS["desktop"])


# Hosts we'll let the rendered page reach. Aligned with the CSP injected by
# studio.inject_csp(). Anything else gets aborted before the request leaves
# the box — defense in depth on top of CSP.
_ALLOWED_HOSTS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "images.unsplash.com",
    "picsum.photos",
    "fastly.picsum.photos",
    "placehold.co",
)

_INSTALL_LOCATION_RE = re.compile(r"^\s*Install location:\s*(.+?)\s*$", re.MULTILINE)
_READINESS_CACHE_LOCK = threading.Lock()
_READINESS_CACHE: tuple[tuple[str | None, ...], dict[str, Any]] | None = None


def _is_allowed_request_url(
    url: str,
    *,
    main_file_url: str | None = None,
    local_root: Path | None = None,
) -> bool:
    """Return True only for local/data URLs or exact HTTPS host allowlist hits."""
    if url.startswith("data:"):
        return True
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme == "file":
        if main_file_url and url == main_file_url:
            return True
        if local_root is None:
            return main_file_url is None
        try:
            file_path = Path(url2pathname(unquote(parsed.path))).resolve()
            file_path.relative_to(local_root.resolve())
            return True
        except (OSError, ValueError):
            return False
    if parsed.scheme != "https":
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname in _ALLOWED_HOSTS


def _preferred_tmp_dir() -> Path | None:
    raw = (os.environ.get("CLAUDE_DESIGN_PLAYWRIGHT_TMP") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    studio_dir = (os.environ.get("CLAUDE_DESIGN_STUDIO_DIR") or "").strip()
    if studio_dir:
        return Path(studio_dir).expanduser().resolve() / "tmp-render"
    return None


def _probe_tmp_dir(parent: Path | None = None) -> dict[str, Any]:
    try:
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix="claude-design-mcp-", dir=parent))
        else:
            tmp = Path(tempfile.mkdtemp(prefix="claude-design-mcp-"))
        shutil.rmtree(tmp, ignore_errors=True)
        return {"ok": True, "path": str(parent or Path(tempfile.gettempdir()).resolve())}
    except OSError as e:
        return {"ok": False, "path": str(parent) if parent else tempfile.gettempdir(), "error": str(e)}


def _configure_runtime_environment(*, apply: bool = True) -> dict[str, Any]:
    """Probe Playwright temp/browser paths; optionally apply them to ``os.environ``.

    ``apply=False`` is the *read-only* mode used by :meth:`Renderer.readiness`
    so a routine readiness check doesn't silently overwrite process-wide
    ``TMP``/``TEMP``/``TMPDIR``/``PLAYWRIGHT_BROWSERS_PATH`` for every other
    library in the same Python process. ``apply=True`` is used by
    :meth:`Renderer._ensure_browser` right before actually launching Chromium.
    """
    system_temp_status = _probe_tmp_dir()
    temp_status = system_temp_status
    preferred = _preferred_tmp_dir()
    if preferred is not None:
        preferred_status = _probe_tmp_dir(preferred)
        if preferred_status["ok"]:
            if apply:
                os.environ["TMP"] = str(preferred)
                os.environ["TEMP"] = str(preferred)
                os.environ["TMPDIR"] = str(preferred)
            temp_status = {
                **preferred_status,
                "preferred_used": True,
                "system_temp_path": system_temp_status.get("path"),
            }
            if not system_temp_status["ok"]:
                temp_status["original_error"] = system_temp_status.get("error")

    browsers_path: str | None = None
    browser_path = (os.environ.get("CLAUDE_DESIGN_PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if browser_path:
        browsers_path = str(Path(browser_path).expanduser().resolve())
    elif not (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "").strip():
        studio_dir = (os.environ.get("CLAUDE_DESIGN_STUDIO_DIR") or "").strip()
        if studio_dir:
            candidate = Path(studio_dir).expanduser().resolve() / "playwright-browsers"
            if candidate.exists():
                browsers_path = str(candidate)
    if browsers_path is not None and apply:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

    return {
        "temp_dir": temp_status,
        "browsers_path": browsers_path or os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
    }


def _find_chromium_executable(root: Path) -> str | None:
    names = {
        "chrome-headless-shell.exe",
        "chrome-headless-shell",
        "chrome.exe",
        "chrome",
        "chromium",
    }
    if not root.exists():
        return None
    for path in root.rglob("*"):
        if path.is_file() and path.name in names:
            return str(path)
    return None


def _sandbox_candidates() -> list[bool]:
    raw = (os.environ.get("CLAUDE_DESIGN_CHROMIUM_SANDBOX") or "auto").strip().lower()
    if raw in {"1", "true", "yes", "on", "required"}:
        return [True]
    if raw in {"0", "false", "no", "off", "disabled"}:
        return [False]
    return [True, False]


def _readiness_fingerprint() -> tuple[str | None, ...]:
    return (
        os.environ.get("CLAUDE_DESIGN_PLAYWRIGHT_TMP"),
        os.environ.get("CLAUDE_DESIGN_STUDIO_DIR"),
        os.environ.get("CLAUDE_DESIGN_PLAYWRIGHT_BROWSERS_PATH"),
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
        sys.executable,
    )

_RENDER_NAV_TIMEOUT_MS = 25_000
_RENDER_FONTS_TIMEOUT_S = 8.0
_RENDER_SCREENSHOT_TIMEOUT_S = 30.0

_HARDENED_LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-features=Translate,BackForwardCache,AcceptCHFrame",
    "--disable-default-apps",
    "--no-first-run",
    "--no-default-browser-check",
    "--metrics-recording-only",
    "--mute-audio",
]


class Renderer:
    """Headless-Chromium HTML→PNG renderer with a warm browser pool.

    The first call to ``render()`` lazily launches Chromium and Playwright;
    subsequent calls reuse the same browser, paying only ~30-80ms per
    context+page+screenshot rather than the ~500-700ms launch cost.

    Call ``await renderer.aclose()`` on shutdown to tear down the browser
    cleanly. Skipping it is safe — the OS reaps Chromium when the process
    exits — but explicit shutdown avoids zombie sub-processes during tests.
    """

    @staticmethod
    def is_available() -> bool:
        """True if `playwright` is importable. Browsers may still need install."""
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def readiness() -> dict[str, Any]:
        """Return import/temp/browser diagnostics without launching Chromium.

        Pure probe — does NOT mutate ``os.environ``. The actual env apply
        happens lazily in :meth:`_ensure_browser` just before launch.
        """
        global _READINESS_CACHE
        fingerprint = _readiness_fingerprint()
        with _READINESS_CACHE_LOCK:
            if _READINESS_CACHE is not None and _READINESS_CACHE[0] == fingerprint:
                return dict(_READINESS_CACHE[1])

        runtime = _configure_runtime_environment(apply=False)
        try:
            import playwright  # noqa: F401
        except ImportError as e:
            result = {
                "ready": False,
                "available": False,
                "error": str(e),
                **runtime,
                "browsers": {"ok": False, "error": "playwright is not installed"},
            }
            with _READINESS_CACHE_LOCK:
                _READINESS_CACHE = (fingerprint, result)
            return dict(result)

        browsers = Renderer._browser_install_status(
            candidate_path=runtime.get("browsers_path")
        )
        ready = bool(runtime["temp_dir"]["ok"] and browsers["ok"])
        result = {
            "ready": ready,
            "available": True,
            **runtime,
            "browsers": browsers,
        }
        with _READINESS_CACHE_LOCK:
            _READINESS_CACHE = (fingerprint, result)
        return dict(result)

    @staticmethod
    def clear_readiness_cache() -> None:
        """Drop cached readiness diagnostics after env changes or tests."""
        global _READINESS_CACHE
        with _READINESS_CACHE_LOCK:
            _READINESS_CACHE = None

    @staticmethod
    def _browser_install_status(*, candidate_path: str | None = None) -> dict[str, Any]:
        # Probe the same path that _configure_runtime_environment resolved,
        # even when readiness() ran in apply=False mode so PLAYWRIGHT_BROWSERS_PATH
        # wasn't actually exported to os.environ. Without this, readiness lies
        # on hosts that keep Chromium under <studio>/playwright-browsers/.
        candidates: list[str] = []
        for value in (candidate_path, os.environ.get("PLAYWRIGHT_BROWSERS_PATH")):
            if value and value.strip() and value not in candidates:
                candidates.append(value.strip())
        for path in candidates:
            executable = _find_chromium_executable(Path(path).expanduser())
            if executable:
                return {"ok": True, "executable": executable}

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium", "--dry-run"],
                capture_output=True,
                text=True,
                timeout=15,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": f"could not inspect Playwright browsers: {e}"}

        text = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
        locations = [Path(p).expanduser() for p in _INSTALL_LOCATION_RE.findall(text)]
        executable = None
        for location in locations:
            executable = _find_chromium_executable(location)
            if executable:
                break
        if executable:
            return {"ok": True, "executable": executable}

        hint = "Run `playwright install chromium`."
        browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if browsers_path:
            hint = (
                "Run `playwright install chromium` with "
                f"PLAYWRIGHT_BROWSERS_PATH={browsers_path!r}."
            )
        return {
            "ok": False,
            "error": "Chromium browser payload is not installed or not discoverable.",
            "install_locations": [str(p) for p in locations],
            "hint": hint,
        }

    def __init__(self) -> None:
        # asyncio.Lock for in-flight render serialization (only the launch
        # path needs it — context creation is parallel-safe). threading.Lock
        # guards lock-creation itself so a multi-thread first call doesn't
        # install two locks.
        self._render_lock: asyncio.Lock | None = None
        self._lock_init = threading.Lock()
        # Browser-pool state. Only touched while holding _render_lock.
        self._pw: Any = None      # playwright.async_api.Playwright
        self._browser: Any = None  # playwright.async_api.Browser
        self._closed = False
        self.last_error: str | None = None

    def _fail(self, msg: str) -> None:
        self.last_error = msg
        _stderr(msg)

    def _get_lock(self) -> asyncio.Lock:
        if self._render_lock is None:
            with self._lock_init:
                if self._render_lock is None:
                    self._render_lock = asyncio.Lock()
        return self._render_lock

    async def _ensure_browser(self) -> Any | None:
        """Lazily start Playwright and launch Chromium. Reused across calls.

        Returns the live browser instance, or None if Playwright/Chromium are
        unavailable. Caller must hold ``_render_lock``.
        """
        if self._browser is not None and self._browser.is_connected():
            return self._browser

        _configure_runtime_environment()
        try:
            from playwright.async_api import (
                async_playwright,
                Error as PlaywrightError,
            )
        except ImportError:
            self._fail(
                "playwright is not installed; skipping render. "
                "Run `pip install claude-design-mcp[render] && playwright install chromium`."
            )
            return None

        last_error: str | None = None
        try:
            self._pw = await async_playwright().start()
            for sandbox in _sandbox_candidates():
                browser = None
                try:
                    browser = await self._pw.chromium.launch(
                        headless=True,
                        args=_HARDENED_LAUNCH_ARGS,
                        channel="chromium",
                        chromium_sandbox=sandbox,
                    )
                    ctx = await browser.new_context(service_workers="block")
                    try:
                        page = await ctx.new_page()
                        await page.close()
                    finally:
                        await ctx.close()
                    self._browser = browser
                    if not sandbox:
                        _stderr(
                            "render: Chromium sandbox unavailable; using "
                            "CLAUDE_DESIGN_CHROMIUM_SANDBOX=auto fallback."
                        )
                    return self._browser
                except (PlaywrightError, OSError) as e:
                    last_error = f"{type(e).__name__}: {e}"
                    if browser is not None:
                        try:
                            await browser.close()
                        except Exception:  # noqa: BLE001
                            pass
                    self._browser = None
        except Exception as e:  # noqa: BLE001 — logged, not propagated
            last_error = f"{type(e).__name__}: {e}"

        self._fail(
            "render: failed to launch a usable Chromium browser "
            f"({last_error or 'unknown error'}). Run `playwright install chromium` once."
        )
        await self._teardown_pw_partial()
        return None

    async def _teardown_pw_partial(self) -> None:
        """Best-effort cleanup if a launch attempt fails halfway."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None

    async def aclose(self) -> None:
        """Shut down the warm browser. Idempotent."""
        if self._closed:
            return
        self._closed = True
        await self._teardown_pw_partial()

    async def render(
        self,
        *,
        html_path: str | os.PathLike[str],
        out_path: str | os.PathLike[str],
        viewport: str = "desktop",
        full_page: bool = True,
        timeout_ms: int = _RENDER_NAV_TIMEOUT_MS,
    ) -> str | None:
        """Render ``html_path`` to ``out_path`` (PNG). Returns the path written, or None."""
        try:
            from playwright.async_api import (
                Error as PlaywrightError,
                TimeoutError as PlaywrightTimeoutError,
            )
        except ImportError:
            self._fail(
                "playwright is not installed; skipping render. "
                "Run `pip install claude-design-mcp[render] && playwright install chromium`."
            )
            return None

        if self._closed:
            self._fail("render: renderer is closed; cannot serve new render requests.")
            return None

        self.last_error = None
        html_path = Path(html_path).resolve()
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not html_path.exists():
            self._fail(f"render: html file does not exist: {html_path}")
            return None

        w, h = viewport_size(viewport)
        url = html_path.as_uri()

        # Per-call unique tmp prevents cross-process races on shared studios.
        tmp_path = out_path.with_suffix(
            f"{out_path.suffix}.{os.getpid()}-tmp"
        )

        # Acquire the browser (lazy launch). The lock only guards the launch
        # window itself; rendering proceeds in parallel after the browser
        # exists, so multiple variant renders run concurrently.
        async with self._get_lock():
            browser = await self._ensure_browser()
        if browser is None:
            self._cleanup_tmp(tmp_path)
            return None

        ctx = None
        try:
            ctx = await browser.new_context(
                viewport={"width": w, "height": h},
                device_scale_factor=2,
                reduced_motion="reduce",
                storage_state=None,
                bypass_csp=False,
                service_workers="block",
                java_script_enabled=False,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "claude-design-mcp/0.1"
                ),
            )

            # Network allowlist — abort anything off the list.
            async def _route(route, request):
                if _is_allowed_request_url(
                    request.url,
                    main_file_url=url,
                    local_root=html_path.parent,
                ):
                    await route.continue_()
                    return
                await route.abort("blockedbyclient")

            await ctx.route("**/*", _route)

            page = await ctx.new_page()
            page.set_default_navigation_timeout(timeout_ms)
            page.set_default_timeout(timeout_ms)

            try:
                await page.goto(url, wait_until="networkidle")
            except PlaywrightTimeoutError:
                _stderr(
                    f"render: networkidle timeout for {url}; "
                    "proceeding with whatever has loaded."
                )

            # Wrap fonts.ready in a function expression so Playwright awaits
            # the returned Promise instead of evaluating eagerly.
            try:
                await asyncio.wait_for(
                    page.evaluate(
                        "() => document.fonts ? document.fonts.ready : null"
                    ),
                    timeout=_RENDER_FONTS_TIMEOUT_S,
                )
            except (asyncio.TimeoutError, PlaywrightError) as e:
                _stderr(
                    f"render: fonts.ready did not resolve "
                    f"({type(e).__name__}); proceeding."
                )

            try:
                await asyncio.wait_for(
                    page.screenshot(
                        path=str(tmp_path),
                        full_page=full_page,
                        type="png",
                    ),
                    timeout=_RENDER_SCREENSHOT_TIMEOUT_S,
                )
            except (asyncio.TimeoutError, PlaywrightError) as e:
                self._fail(f"render: screenshot failed ({e}); leaving prior PNG intact.")
                self._cleanup_tmp(tmp_path)
                return None
        except (PlaywrightError, OSError) as e:
            self._fail(f"render: playwright failure ({e}); design saved without screenshot.")
            self._cleanup_tmp(tmp_path)
            return None
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:  # noqa: BLE001
                    pass

        # Atomic publish — refuse symlinks just like studio.write_html does.
        try:
            if out_path.is_symlink():
                out_path.unlink()
            os.replace(tmp_path, out_path)
        except OSError as e:
            self._fail(f"render: could not finalize PNG ({e}).")
            self._cleanup_tmp(tmp_path)
            return None
        self.last_error = None
        return str(out_path)

    @staticmethod
    def _cleanup_tmp(tmp_path: Path) -> None:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _stderr(msg: str) -> None:
    """Stderr logging only — stdout is owned by the MCP protocol."""
    print(f"[claude-design-mcp] {msg}", file=sys.stderr, flush=True)
