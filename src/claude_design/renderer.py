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
import sys
import threading
from pathlib import Path
from typing import Any

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

        try:
            from playwright.async_api import (
                async_playwright,
                Error as PlaywrightError,
            )
        except ImportError:
            _stderr(
                "playwright is not installed; skipping render. "
                "Run `pip install claude-design-mcp[render] && playwright install chromium`."
            )
            return None

        try:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=_HARDENED_LAUNCH_ARGS,
                chromium_sandbox=True,
            )
        except PlaywrightError as e:
            _stderr(
                "render: failed to launch chromium "
                f"({e}). Run `playwright install chromium` once."
            )
            await self._teardown_pw_partial()
            return None
        except Exception as e:  # noqa: BLE001 — logged, not propagated
            _stderr(f"render: unexpected error launching playwright ({type(e).__name__}: {e}).")
            await self._teardown_pw_partial()
            return None

        return self._browser

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
            _stderr(
                "playwright is not installed; skipping render. "
                "Run `pip install claude-design-mcp[render] && playwright install chromium`."
            )
            return None

        if self._closed:
            _stderr("render: renderer is closed; cannot serve new render requests.")
            return None

        html_path = Path(html_path).resolve()
        out_path = Path(out_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if not html_path.exists():
            _stderr(f"render: html file does not exist: {html_path}")
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
                java_script_enabled=True,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "claude-design-mcp/0.1"
                ),
            )

            # Network allowlist — abort anything off the list.
            async def _route(route, request):
                u = request.url
                if u.startswith("file://") or u.startswith("data:"):
                    await route.continue_()
                    return
                if any(host in u for host in _ALLOWED_HOSTS):
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
                _stderr(f"render: screenshot failed ({e}); leaving prior PNG intact.")
                self._cleanup_tmp(tmp_path)
                return None
        except (PlaywrightError, OSError) as e:
            _stderr(f"render: playwright failure ({e}); design saved without screenshot.")
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
            _stderr(f"render: could not finalize PNG ({e}).")
            self._cleanup_tmp(tmp_path)
            return None
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
