# Framework docs (mcp / claude-agent-sdk / playwright) — current state and upgrade path

Research date: 2026-05-10. Project: `B:\projects\claude\claude-design-mcp`.
Installed snapshot (verified via `importlib.metadata`):

| Package | Pinned | Installed | Latest stable (2026-05-10) |
| --- | --- | --- | --- |
| `mcp` | `>=1.2.0` | **1.25.0** | **1.27.1** (v1.x branch, frozen for v2 work) |
| `claude-agent-sdk` | `>=0.1.70` | **0.1.72** | **0.1.80** (released 2026-05-09) |
| `playwright` | `>=1.45` | **1.58.0** | **1.59.0** (released 2026-04-29) |
| `pydantic` | `>=2.5` | **2.13.4** | 2.13.x line (2026-Q1) |
| `python-dotenv` | `>=1.0` | n/a here | n/a |

Everything below is filtered to what we *don't* already do. OAuth env scrub, HTML-parser-based CSP injection, `aclose()` on timeout, and the 2 MB HTML cap are out of scope.

---

## 1. `mcp` Python SDK

### 1.1 What's in 1.20 → 1.27 we should care about

The repo split branches at v1.25.0 (2025-12-18): `main` is v2 development with breaking changes; `v1.x` is maintenance-only with very rare backports. Current plan is a v2 release "some time in Q1 [2026]" tied to a spec-rewrite of the transport layer. Pin policy that ships with the SDK is now explicitly `mcp>=1.25,<2`.

Notable v1.x deltas relevant to this project, in chronological order:

| Version | Date | Item | Why it matters here |
| --- | --- | --- | --- |
| **1.19.0** | 2025-10-24 | `Allow CallToolResult to be returned directly to support _meta field for OpenAI Apps` (PR #1459) | Lets `design_create` return a `CallToolResult` whose `_meta` carries cost/usage telemetry **without** exposing it in the conversation transcript. Direct fit for our "cost in stderr but not in model context" goal. |
| **1.19.0** | 2025-10-24 | `Expose RequestParams._meta in ClientSession.call_tool` (PR #1231) | Inbound side; lets callers send progress/trace ids. |
| **1.19.0** | 2025-10-24 | `feat: add tool metadata in FastMCP.tool decorator` (PR #1463) | The `@mcp.tool(metadata=...)` kwarg now flows through. |
| **1.21.0** | 2025-11-06 | `Implement SEP-985: OAuth Protected Resource Metadata discovery fallback`, `Add get_server_capabilities()` | Not relevant to a stdio server. |
| **1.23.0** | 2025-12-02 | Bumped to MCP spec **2025-11-25**: `SEP-1577 Sampling With Tools`, `SEP-1330 Elicitation Enum Schema`, `SEP-986 Tool name validation` | Tool name validation is the only thing that could bite a server that uses underscores/dashes liberally. We're fine. |
| **1.23.3** | 2025-12-09 | `Skip empty SSE data to avoid parsing errors` | Irrelevant for stdio. |
| **1.24.0** | 2025-12-12 | `Add streamable_http_client which accepts httpx.AsyncClient` | Client-side. |
| **1.27.0** | 2026-04-02 | `feat: add idle timeout for StreamableHTTP sessions`, `add RFC 8707 resource validation to OAuth client` | Useful if/when we add an HTTP transport. |
| **1.27.1** | 2026-05-08 | `catch PydanticUserError when generating output schema (pydantic 2.13 compat)` | **Direct hit on our stack** — without this fix, pydantic 2.13 + `mcp<1.27.1` raises `PydanticUserError` at server import. Reason to upgrade. |

**Upgrade recommendation:** bump the floor to `mcp>=1.27.1,<2`. The 1.27.1 pydantic-2.13 patch alone justifies it; nothing in 1.20→1.27 breaks our existing usage of `FastMCP`, `@mcp.tool(annotations=...)`, or the stdio transport.

Sources: [MCP python-sdk releases](https://github.com/modelcontextprotocol/python-sdk/releases), [PR #1459 — CallToolResult/_meta](https://github.com/modelcontextprotocol/python-sdk/pull/1459).

### 1.2 `mcp.server.fastmcp` deprecation / rename status

**Not deprecated.** `from mcp.server.fastmcp import FastMCP` remains the canonical import on the v1.x branch and is what the SDK's own examples use. The standalone `fastmcp` PyPI package (now 2.x → 3.0 as of 2026-01-19) has diverged and is a separate project (`from fastmcp import FastMCP`); the official MCP SDK still bundles FastMCP 1.0 with no formal deprecation announced. Issue #1068 on the SDK repo still asks for the maintainers' long-term answer; none has been given.

Practical implication for us: leave `from mcp.server.fastmcp import FastMCP` alone. There is no migration to do.

Sources: [Issue #1068 — FastMCP 2.0 vs SDK](https://github.com/modelcontextprotocol/python-sdk/issues/1068), [FastMCP 3.0 changelog](https://gofastmcp.com/changelog).

### 1.3 `Image` / `ImageContent` return type for `design_create`

Two clean options, both in 1.19+ on the v1.x branch:

**(a) Return `Image` from `mcp.server.fastmcp`:**
```python
from mcp.server.fastmcp import FastMCP, Image

@mcp.tool(name="design_create_with_image", ...)
def design_create(...) -> Image:
    return Image(data=png_bytes, format="png")
```
Auto-wraps into a single `ImageContent` block. Convenient for "screenshot inline" cases.

**(b) Return `CallToolResult` directly with multiple content blocks plus `_meta`:**
```python
from mcp.types import CallToolResult, TextContent, ImageContent

@mcp.tool(name="design_create", ...)
def design_create(...) -> CallToolResult:
    return CallToolResult(
        content=[
            TextContent(type="text", text=json_summary),
            ImageContent(type="image", data=b64_png, mimeType="image/png"),
        ],
        _meta={
            "usage": {"input_tokens": ..., "output_tokens": ..., "cost_usd": ...},
            "design_id": rec.id,
        },
    )
```
This is the route OpenAI Apps SDK explicitly recommends for "telemetry that the host/widget consumes but the model never sees." The `_meta` field is inherited from the `Result` base class (`meta: dict[str, Any] | None = Field(alias="_meta", default=None)`) and is preserved end-to-end as of 1.19.

**Caveat we must respect:** `CallToolResult` must be returned directly — never wrapped in `Optional[...]` or `Union[...]`. For "no result" cases use `CallToolResult(content=[])`. Likewise, if a tool annotates its return as `Image`, the model gets the image data inline; for our `design_create` we want **both** the JSON record (so the agent can chain) and the screenshot (so the agent can *see* the design), so option (b) is the better fit.

**Recommended migration for `design_create`:**
- Return `CallToolResult` whose `content` is `[TextContent(JSON record), ImageContent(screenshot)]` when a render exists.
- Put `usage` + `cost_usd` + `duration_ms` + warnings under `_meta`.
- Drop `file://` URLs from the model-visible content (keep them in `_meta` for debugging).

This solves the "screenshot inline" goal *and* gets cost telemetry out of the model's context window.

Sources: [PR #1459](https://github.com/modelcontextprotocol/python-sdk/pull/1459), [FastMCP screenshot example](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/fastmcp/screenshot.py), [OpenAI Apps SDK — Define tools](https://developers.openai.com/apps-sdk/plan/tools).

### 1.4 `_meta` for out-of-band cost/usage telemetry

Confirmed above. The `_meta` field on `CallToolResult` is the documented channel for "data the host/widget uses but the model doesn't see." Microsoft's `agent-framework` filed a bug (#2284) for dropping `_meta` — i.e., compliant clients *do* preserve it.

**For our server:**
- Place per-call usage + cost there.
- Place `render_path` / `html_path` / `file://` URLs there too — agents that need to re-open them can read `_meta`, but the model's main reply stays tight.

### 1.5 Tool annotation field additions

The four flags we set (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) are **still the canonical set** on the v1.x branch (per `mcp.types.ToolAnnotations` and the OpenAI Apps SDK validation rules). No new fields were added on the v1.x branch in 1.20→1.27; SEP-973 added a separate `Icon` / metadata story on resources (1.15.0), not on tool annotations.

What did change:
- **OpenAI Apps SDK** now requires that `openWorldHint` and `destructiveHint` be set explicitly (not null) whenever `readOnlyHint=False`. Our `design_create`, `design_iterate`, `design_variants`, `design_apply_system`, `design_extract_system` all already set explicit booleans, so we're compliant.
- For `design_create` and friends, our current `openWorldHint=True` is correct (we spawn the `claude` CLI subprocess, which contacts Anthropic's network).
- For `design_render`, `openWorldHint=False` is correct *because* of our network allowlist (only fonts.googleapis.com/gstatic, unsplash, picsum, placehold). If we ever loosen that allowlist, flip `openWorldHint` to `True`.

Sources: [ToolAnnotations type](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/src/mcp/types.py), [OpenAI Apps SDK — Reference](https://developers.openai.com/apps-sdk/reference).

### 1.6 stdio vs streamable HTTP

stdio is still the default for local Claude Desktop / Claude Code integration. Streamable HTTP transport is production-grade as of 1.20 (Accept-header relaxations) → 1.27 (idle timeout, RFC 8707 resource validation, OAuth scope step-up). For a *local* design MCP server bound to one user's Claude session, stdio is correct and cheaper to operate.

Switch to streamable HTTP only if we add a multi-tenant or hosted variant; the relevant tools are `mcp.server.streamable_http_manager` and `mcp.client.streamable_http.streamable_http_client(...)` (the latter accepts `httpx.AsyncClient` directly as of 1.24.0).

Recommendation: keep stdio.

---

## 2. `claude-agent-sdk` Python

### 2.1 Releases since 0.1.70

| Version | Date | Highlights |
| --- | --- | --- |
| 0.1.70 | 2026-04-28 | Bumped `mcp>=1.19.0` floor (older `mcp` silently dropped `CallToolResult` from in-proc tools); trio nursery fix. |
| 0.1.71 | 2026-04-29 | `SandboxNetworkConfig` got `allowedDomains` / `deniedDomains` / `allowManagedDomainsOnly` / `allowMachLookup`. |
| 0.1.73 | 2026-05-04 | `session_store_flush="eager"` for live transcript tailing. |
| 0.1.74 | 2026-05-06 | `include_hook_events`, `defer` permission decision (`DeferredToolUse`), `strict_mcp_config`, enriched `ToolPermissionContext`, `updatedToolOutput` on `PostToolUseHookSpecificOutput`, **`"xhigh"` effort level for Opus 4.7**, atexit subprocess cleanup. |
| 0.1.76 | 2026-05-06 | **`ResultMessage.api_error_status: int | None`** (e.g. 429/500/529). |
| 0.1.77 | 2026-05-08 | Actionable error text instead of "exit code 1"; deprecation of `"Skill"` in `allowed_tools` in favor of `skills` option. |
| 0.1.78 | 2026-05-08 | CLI bump 2.1.136. |
| 0.1.79 | 2026-05-09 | CLI bump 2.1.137. |
| 0.1.80 | 2026-05-09 | CLI bump 2.1.138. |

**Upgrade recommendation:** bump floor to `claude-agent-sdk>=0.1.77,<0.2`. The three concrete wins for us:

1. **`"xhigh"` effort** (0.1.74) — lets us dial Opus 4.7 to its Opus-specific level for `tier="best"` design calls without falling back to the generic "max".
2. **`ResultMessage.api_error_status`** (0.1.76) — we can show "Claude 429" vs "Claude 500" instead of just "Claude returned an error" in `DesignerError`.
3. **Actionable error messages** (0.1.77) — "Reached maximum number of turns" instead of "Command failed with exit code 1". Useful because `designer._call` already inspects `AssistantMessage.error`.

### 2.2 `ClaudeAgentOptions` fields added since 0.1.70

Of the ones the user asked about:

| Field | Added | Type | Notes |
| --- | --- | --- | --- |
| `sandbox` (`SandboxSettings`) | pre-0.1.70 (existed); domain fields landed 0.1.71 | dataclass | See 2.3 below — **not usable on native Windows**. |
| `strict_mcp_config` | 0.1.74 | `bool` | When `True`, only the `mcp_servers` passed to options are loaded — user/project/global `.mcp.json` are ignored. For our `tools=[]` design call we don't need MCP servers at all, so this is irrelevant *for designer.py*. Worth setting `strict_mcp_config=True` defensively anyway. |
| `task_budget` | **not added** | — | The closest field that exists is `max_budget_usd: float \| None`, which has existed for longer. There is no `task_budget` field on `ClaudeAgentOptions` as of 0.1.80. |
| `effort` Literal | now `Literal["low","medium","high","xhigh","max"] \| int \| None` | str | `"xhigh"` was added 0.1.74 (issue #834, PR #914). Our `_env_effort()` allowlist `{low, medium, high, max}` should grow to include `xhigh`. |
| `thinking.display` | 0.1.65 | `str` | Override Opus 4.7's default `"omitted"`; pass `"summary"` to see thinking summaries. |
| `include_hook_events` | 0.1.74 | `bool` | We don't use hooks. |
| `skills` | 0.1.62 | `"all" \| list[str] \| []` | We already pass `skills=[]`. Good — fully suppresses skills. |
| `session_store_flush` | 0.1.73 | `"batched" \| "eager"` | Not relevant: we're a one-shot query, no resume. |

One-liner snippets:
```python
# xhigh for Opus 4.7
ClaudeAgentOptions(model="claude-opus-4-7", effort="xhigh")

# strict MCP set (don't inherit user/project servers)
ClaudeAgentOptions(strict_mcp_config=True, mcp_servers={})

# Read API error status on failure
async for msg in query(prompt=p, options=opts):
    if isinstance(msg, ResultMessage) and msg.is_error and msg.api_error_status == 429:
        raise DesignerError("Claude rate-limited (429). Wait and retry.")
```

**Concrete edit needed in `designer.py`:**
- `_ALLOWED_EFFORTS = {"low", "medium", "high", "xhigh", "max"}`
- Branch on `ResultMessage.api_error_status` inside `_consume()` and produce a distinct `DesignerError` per HTTP class (`429` → "rate-limited", `5xx` → "Claude server error, retry"), mapping to the existing `_ASSISTANT_ERROR_MESSAGES` strings.

### 2.3 `SandboxSettings` on Windows

**Not usable on native Windows in 2026-05.** Sandbox supports macOS (Seatbelt), Linux (bubblewrap + socat), and WSL2 (bubblewrap). Native Windows support is explicitly documented as "planned." For our use case it's largely a non-issue: the designer call already runs with `tools=[]`, `allowed_tools=[]`, `permission_mode="dontAsk"`, `max_turns=1` and the CLI never gets to call Bash/Write/etc. The sandbox would gate tool *execution*, but we've turned execution off at the API surface.

If we ever want to relax the tool surface (e.g., let the agent write to a scratchpad), and we want defense-in-depth on Linux/macOS hosts, the shape is:

```python
ClaudeAgentOptions(
    sandbox={
        "enabled": True,
        "network": {
            "allowedDomains": ["api.anthropic.com", "fonts.googleapis.com"],
            "deniedDomains": ["*"],
            "allowManagedDomainsOnly": False,
        },
        "autoAllowBashIfSandboxed": True,
        "excludedCommands": ["docker"],
    },
)
```
On Windows the CLI will log "Sandboxing requires WSL2" and (depending on `failIfUnavailable`) either degrade or fail. Default for `failIfUnavailable` when `enabled=True` is **true** — set it to `False` if you want graceful degradation.

Recommendation: **don't** wire sandbox into `designer.py`. Document in README that on Windows the safety surface is enforced by `tools=[]`, not by OS-level sandboxing, and that on macOS/Linux operators can layer sandbox on if they relax the tool surface.

### 2.4 Recommended pattern for one-shot text-only queries

What we already do (`tools=[]`, `permission_mode="dontAsk"`, `max_turns=1`, `setting_sources=[]`, `skills=[]`, `extra_args={"disable-slash-commands": None, "no-session-persistence": None}`, `cli_path=resolve_path`) is exactly the SDK-recommended pattern for "single text-out turn with no agentic behavior." Two minor additions to consider after upgrading:

1. `strict_mcp_config=True` — makes the design call deterministic regardless of user/project `.mcp.json`.
2. `thinking={"type": "disabled"}` (we already do this via `_env_thinking()`) plus optionally `thinking.display="summary"` when effort is `xhigh` and you want the operator to see a summary in stderr.

Sources: [claude-agent-sdk-python releases](https://github.com/anthropics/claude-agent-sdk-python/releases), [Sandboxing docs](https://code.claude.com/docs/en/sandboxing), [Issue #834 — xhigh typings](https://github.com/anthropics/claude-agent-sdk-python/issues/834).

---

## 3. `playwright` Python

### 3.1 Releases since 1.45

| Version | Date | Highlight relevant to us |
| --- | --- | --- |
| 1.48 | 2024-10-21 | `page.route_web_socket()` — not relevant to renderer. |
| 1.52 | 2025-04-30 | `to_contain_class()` — testing-only. |
| 1.54 | 2025-07-22 | Cookie `partition_key`, `--user-data-dir` flag. |
| 1.55 | 2025-08-28 | **Dropped Chromium extension manifest v2 support.** Chromium 140. |
| 1.56 | 2025-11-11 | `page.console_messages()`, `page.requests()` — useful for debugging poisoned-HTML renders, optional. |
| 1.57 | 2025-12-09 | **Switched from Chromium to Chrome for Testing builds.** Headed=`chrome`, headless=`chrome-headless-shell` by default. Arm64 Linux still uses Chromium. |
| 1.58 | 2026-01-30 | Trace viewer improvements; removed `_react` / `_vue` selectors and the `devtools` launch option. |
| 1.59 | 2026-04-29 | `page.screencast` API for action-annotated video — not relevant. |

### 3.2 `channel="chromium"` (new headless) vs default `chrome-headless-shell`

Playwright now ships **two** headless runtimes:

- **`chrome-headless-shell`** — the legacy minimal headless runtime; what `chromium.launch(headless=True)` uses by default. Smaller download, faster startup, but it is *not* the same code path real Chrome runs in headless mode and lacks some site-isolation and process-model parity. Stays as default to keep CI tests fast and reproducible.
- **New headless mode** (Chrome's "headless=new") — the real Chrome binary running headless, with full site isolation and modern process model. You opt in by setting `channel="chromium"` on launch (Playwright 1.57+ aliases this to the Chrome for Testing build).

**Security story:** new headless is closer to the real browser, so site-isolation, COOP/COEP enforcement, and out-of-process iframes match production Chrome. Headless shell is faster but the process model is simpler, which historically meant some sandboxing/site-isolation rules were weaker in edge cases. For *our* threat model — rendering one piece of model-authored HTML with all external network blocked at the Playwright route layer and a strict CSP injected at the HTML layer — **headless shell is fine**, but new headless is incrementally more defensive.

**Recommendation:** flip our launch to `channel="chromium"` for production, keeping `headless=True`:
```python
browser = await pw.chromium.launch(
    channel="chromium",      # new headless via Chrome for Testing
    headless=True,
    args=_HARDENED_LAUNCH_ARGS,
    chromium_sandbox=True,
)
```
This requires `playwright install chromium` to have pulled the full Chrome for Testing build (our `_browser_install_status` already looks for `chrome.exe` / `chrome-headless-shell.exe`, so it'll find either). Document the trade-off: roughly ~150ms slower cold-start, ~30 MB larger install, but real-Chrome site-isolation in headless mode.

If we want to *avoid* downloading the headless-shell payload entirely on hosts that only need new headless:
```
playwright install chromium --no-shell
```
Or to skip the full Chrome download and ship headless-shell only (current default):
```
playwright install --only-shell
```

### 3.3 Launch args worth adding / removing

Our `_HARDENED_LAUNCH_ARGS` (`--disable-dev-shm-usage`, `--disable-extensions`, `--disable-background-networking`, `--disable-features=Translate,BackForwardCache,AcceptCHFrame`, `--disable-default-apps`, `--no-first-run`, `--no-default-browser-check`, `--metrics-recording-only`, `--mute-audio`) is a sound minimal set for headless rendering of untrusted HTML. Worth considering:

| Arg | Why | Caveat |
| --- | --- | --- |
| `--disable-component-update` | Stops background CRX-fetching from Google update servers. | Some font/loader updates skipped — fine for our case since fonts.gstatic is allowlisted. |
| `--disable-component-extensions-with-background-pages` | Kills the bundled component extensions (Google Hangouts, etc.) — none should run anyway under `headless=true`, but belt-and-suspenders. | none |
| `--disable-features=MediaRouter,InterestFeedContentSuggestions,OptimizationHints,IsolateOrigins,site-per-process` | DO NOT add the last two — those would *weaken* site isolation. Mentioning so we don't accept a stray copy-paste from the web. | — |
| `--disable-blink-features=AutomationControlled` | Hides the `navigator.webdriver` flag. Useful for screenshots of sites that gate on it; we don't render external sites so it's optional. | none |
| `--enable-features=NetworkServiceInProcess` | The opposite of what we want for isolation. Skip. | — |
| `--allow-pre-commit-input` | Speeds startup ~30ms. | minor |
| `--js-flags=--no-expose-wasm` | If our HTML doesn't need WASM (it shouldn't — design output is HTML/CSS), disabling cuts attack surface. | If a designer fence ever includes Wasm-based viz, would break. |
| Remove `--disable-features=BackForwardCache` | Not needed for a one-shot screenshot — BFCache is irrelevant when we don't navigate back. Keeping it is harmless. | none |
| `--disable-background-timer-throttling`, `--disable-renderer-backgrounding`, `--disable-backgrounding-occluded-windows` | These *prevent* a backgrounded headless window from throttling JS. For predictable screenshots that wait on `fonts.ready`, worth adding. | none |

Don't add `--no-sandbox` under any circumstance — we already correctly pass `chromium_sandbox=True` and fall back only if the platform refuses.

### 3.4 `chromium_sandbox=` keyword status

Stable, available since well before 1.45, default `None` (which behaves as `False` per the long-standing bug we don't need to file again — Issue #2273 on `playwright-python`). Our code passes `chromium_sandbox=True` explicitly with a sandbox-disabled fallback when the platform can't honor it (Linux without user-namespaces, certain Docker images). That's the right pattern.

One nit: when we fall back to `chromium_sandbox=False` we still log to stderr. Consider raising the log level only when `CLAUDE_DESIGN_CHROMIUM_SANDBOX=required` was set explicitly and the platform refused — i.e., treat "auto → fallback" as INFO and "required → fail" as ERROR. Cosmetic, not security-critical.

### 3.5 Route handler reliability for service workers / preloads

This is the M6 finding worth being precise about. Playwright's documented behavior:

- `page.route()` and `browser_context.route()` **do not intercept** requests issued from inside a Service Worker fetch handler. Only the SW-owned outer request is routable.
- HAR replay (`route_from_har()`) **will not serve** SW-intercepted requests.
- The escape hatch is `BrowserContext.service_workers="block"` (option on `new_context()`).
- Chromium-only: SW network requests are reported and routable through the **BrowserContext** (not the Page), but only if `PLAYWRIGHT_DISABLE_SERVICE_WORKER_NETWORK` is unset (it's set by default in some CI images — check).

**For our renderer:**
We currently call `await ctx.route("**/*", _route)` with the allowlist. If model-authored HTML registers a service worker (e.g., `<script>navigator.serviceWorker.register('/sw.js')</script>`), the SW's *internal* `fetch(...)` calls can bypass our route handler. Even though CSP would block such a `<script>` if the model used inline-`<script>`, `connect-src` only constrains the SW's network reach, not its registration.

**Recommended hardening** (one-liner, in `Renderer.render` when creating the context):
```python
ctx = await browser.new_context(
    viewport={"width": w, "height": h},
    device_scale_factor=2,
    reduced_motion="reduce",
    storage_state=None,
    bypass_csp=False,
    java_script_enabled=True,
    service_workers="block",                     # NEW — closes the M6 gap
    user_agent="...",
)
```
This is the documented mitigation. With `service_workers="block"`, the page can't register a SW at all, so the route allowlist becomes the single source of truth for outbound network. Cost: zero — design output that legitimately needs a service worker is vanishingly rare for static screenshots.

We should also consider:
- `<link rel="preload">` and `<link rel="prefetch">` fire normal requests, which **are** caught by `ctx.route`. No change needed.
- `<link rel="modulepreload">` likewise.
- Speculation Rules (`<script type="speculationrules">`) — Chrome-only — *can* issue prerender fetches. They're caught by `ctx.route` too, but they may run *before* our route is installed if we set the route after `goto`. Our current order (`new_context → ctx.route → new_page → goto`) is correct; don't refactor.

Sources: [Playwright Python — Service Workers](https://playwright.dev/python/docs/service-workers), [Network docs](https://playwright.dev/python/docs/network).

---

## 4. `pydantic` v2

### 4.1 Anything in 2.6+ that simplifies `DesignVariantsInput`'s xor validator

Today we have:
```python
class DesignVariantsInput(BaseModel):
    design_id: str | None = None
    brief: str | None = None
    @model_validator(mode="after")
    def _require_one(self) -> "DesignVariantsInput":
        if not self.design_id and not self.brief:
            raise ValueError("Provide either design_id (to branch) or brief (to start fresh).")
        return self
```

**Honest answer:** discriminated unions don't really simplify this case. Discriminated unions excel at *type-tagged* polymorphism ("the input is one of these classes, identified by a tag field"); they don't directly express "exactly one of two optional fields, at least one must be present." The closest replacement is two separate models joined under a callable `Discriminator`, but that's *more* code than the current one-line `model_validator`.

Three things 2.6+ *did* add that are tangentially relevant:

1. **`Discriminator` + `Tag` for callable-based selection** (pydantic 2.5+, refined through 2.13): lets you route to one of several models from arbitrary input shape. Pattern:
   ```python
   def pick(v): return "from_id" if (isinstance(v, dict) and v.get("design_id")) else "from_brief"
   class DesignVariantsInput(RootModel[
       Annotated[
           Union[
               Annotated[VariantsFromDesign, Tag("from_id")],
               Annotated[VariantsFromBrief, Tag("from_brief")],
           ],
           Discriminator(pick),
       ]
   ]):
       ...
   ```
   Trade-off: better JSON-schema (the spec the MCP client sees gets two discriminated branches), at the cost of splitting `VariantsFromDesign` / `VariantsFromBrief` and a separate root model. Worth it if and only if we want the agent-visible schema to read as "either { design_id, dimension, ... } or { brief, dimension, ... }" rather than "all fields optional with a runtime check."

2. **Polymorphic serialization** (pydantic 2.13): not relevant to inputs.

3. **`exclude_if` for computed fields** (pydantic 2.13): not relevant.

**Recommendation:** **don't** rewrite. The current `model_validator` is the simplest expression of "xor with both required". If we want the *schema* the MCP host sees to be sharper (so an LLM agent gets clearer guidance), invest in better field descriptions and a `json_schema_extra={"oneOf": [...]}` annotation rather than a discriminated-union refactor.

### 4.2 Migration debt

- **pydantic 2.13 breaks `mcp<1.27.1`** because of an `OutputSchema` generation path; bumping `mcp` to ≥ 1.27.1 fixes it.
- `serialize_as_any` semantics shifted in 2.12 and again in 2.13 (the new `polymorphic_serialization` option). We don't use it, so no migration needed.
- Union serialization fixes in 2.13 may change order-of-evaluation for `str | int` style fields — verify with our existing tests; nothing in `models.py` uses ambiguous unions, so we should be clean.

Sources: [pydantic 2.13 release notes](https://pydantic.dev/articles/pydantic-v2-13-release), [pydantic Unions doc](https://docs.pydantic.dev/latest/concepts/unions/).

---

## 5. `html.parser` (stdlib) — 3.12 / 3.13 behavior

We replaced the regex CSP injector with `html.parser`. Behaviour deltas to know:

| Python | Change |
| --- | --- |
| 3.12 | No CSP-relevant changes; `convert_charrefs=True` remains the default. |
| 3.13 | No CSP-relevant changes either. Documentation wording on `convert_charrefs` clarifies "character references in `script`/`style` are not converted" — same behavior as 3.5–3.12, just sharper docs. |
| 3.14 (preview, ships 2026 Q4) | **New `scripting=False` constructor kwarg.** When false (default), `<noscript>` contents are parsed as markup (HTML5 conformant); when true, treated as raw text. Also expands CDATA element handling to `("script", "style", "xmp", "iframe", "noembed", "noframes")` and RCDATA to `("textarea", "title")` per the HTML5 spec — a parser correctness improvement that doesn't affect a CSP injector that only watches for `<head>` / `<meta charset>` / `<html>`. |

**For our CSP injector**, the only thing to be careful about is:

1. We *want* `convert_charrefs=True` (the default) so we don't mishandle `&amp;` inside attributes.
2. We must *not* assume the parser sees a `<head>` tag. Many model outputs skip it. We already insert before the first `<title>`/`<meta>` if `<head>` is missing — keep that branch.
3. 3.14's new `scripting=False` default is fine for us; we don't read `<noscript>` contents.

One concrete edge case worth a test (small, easy to add):
```python
"<!doctype html><html><body>only a body, no head</body></html>"
```
Make sure `inject_csp` either creates a `<head>` *or* injects before `<body>`. If it currently no-ops on missing-`<head>`, that's a defect.

Sources: [Python 3 html.parser docs](https://docs.python.org/3/library/html.parser.html), [CPython 3.14 parser.py](https://github.com/python/cpython/blob/3.14/Lib/html/parser.py).

---

## Action items, ordered by leverage

1. **`mcp>=1.27.1`** — fixes pydantic 2.13 compat; unlocks `CallToolResult` direct return for `_meta` cost telemetry and inline image content. (One-line `pyproject.toml` edit.)
2. **Rewrite `design_create`'s return** to `CallToolResult([TextContent(json), ImageContent(png)], _meta={"usage":..., "cost_usd":..., "html_path":..., "render_path":...})`. Lets agents see the screenshot inline; gets cost out of model context.
3. **`claude-agent-sdk>=0.1.77`** — gets `xhigh` effort, `api_error_status`, actionable CLI errors.
4. **Add `xhigh` to `_ALLOWED_EFFORTS`** and switch `tier="best"` calls to `effort="xhigh"` when the model is Opus 4.7.
5. **Branch on `ResultMessage.api_error_status`** in `designer._consume()` to differentiate 429 / 5xx in the `DesignerError` message.
6. **Add `service_workers="block"`** to `ctx = await browser.new_context(...)` in `renderer.py`. Closes the M6 service-worker route-bypass gap.
7. **Add `channel="chromium"`** to `pw.chromium.launch(...)` to opt into new headless / Chrome-for-Testing. Improves site-isolation; ~150ms cold-start cost.
8. **Add `strict_mcp_config=True`** to `ClaudeAgentOptions` in `designer.py` — deterministic regardless of user's `.mcp.json`.
9. **Test:** confirm `inject_csp` does the right thing with a doc that has no `<head>` and no `<title>`; if it no-ops, fix.

Items 1–7 are the high-leverage moves; 8–9 are cheap defense-in-depth.

---

## Sources

- [MCP python-sdk releases (1.20 → 1.27.1)](https://github.com/modelcontextprotocol/python-sdk/releases)
- [MCP python-sdk PR #1459 — CallToolResult direct return + _meta](https://github.com/modelcontextprotocol/python-sdk/pull/1459)
- [MCP python-sdk issue #1068 — FastMCP 2.0 vs SDK](https://github.com/modelcontextprotocol/python-sdk/issues/1068)
- [FastMCP screenshot example](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/fastmcp/screenshot.py)
- [OpenAI Apps SDK — Define tools (annotations + _meta requirements)](https://developers.openai.com/apps-sdk/plan/tools)
- [OpenAI Apps SDK — Reference](https://developers.openai.com/apps-sdk/reference)
- [claude-agent-sdk-python releases](https://github.com/anthropics/claude-agent-sdk-python/releases)
- [claude-agent-sdk-python issue #834 — xhigh effort typings](https://github.com/anthropics/claude-agent-sdk-python/issues/834)
- [Claude Code sandboxing docs](https://code.claude.com/docs/en/sandboxing)
- [Claude Agent SDK Python reference](https://code.claude.com/docs/en/agent-sdk/python)
- [Playwright Python releases (1.45 → 1.59)](https://github.com/microsoft/playwright-python/releases)
- [Playwright Python — Browsers (channels, new headless)](https://playwright.dev/python/docs/browsers)
- [Playwright Python — Service Workers](https://playwright.dev/python/docs/service-workers)
- [Playwright Python — Network](https://playwright.dev/python/docs/network)
- [Playwright Python issue #2273 — chromium_sandbox default](https://github.com/microsoft/playwright-python/issues/2273)
- [Pydantic 2.13 release notes](https://pydantic.dev/articles/pydantic-v2-13-release)
- [Pydantic Unions / Discriminator / Tag](https://docs.pydantic.dev/latest/concepts/unions/)
- [Pydantic changelog](https://docs.pydantic.dev/latest/changelog/)
- [Python html.parser docs](https://docs.python.org/3/library/html.parser.html)
- [CPython 3.14 Lib/html/parser.py](https://github.com/python/cpython/blob/3.14/Lib/html/parser.py)
