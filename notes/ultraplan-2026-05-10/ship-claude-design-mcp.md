# Ship claude-design-mcp

**Status:** draft
**Created:** 2026-05-10
**Owner:** Tyler

## Goal (one sentence)
Land claude-design-mcp v0.2 on PyPI/GHCR with all five rubric blockers (OBVIOUS, ALIVE, MONEY, READY, ORIGINAL) scoring ≥7 by positioning it as the OAuth-native, codebase-grounded, DESIGN.md-speaking interop layer for agent-callable design — before Anthropic's first-party design skill closes the wedge in 6–9 months.

## Why now
- Anthropic will ship a managed `design` Agent Skill in 6–9 months (Claude Design launched 2026-04-17; pptx/xlsx/docx/pdf skills already exist; design is the obvious gap). Our window is fixed.
- AIDesigner MCP shipped 2026-04-07 occupying the $25/mo "agent-callable design MCP" slot, so head-on competition is lost; the remaining defensible wedge is the OAuth-pay-once + DESIGN.md interop layer.
- Five rubric blockers are measured against the 136-test/ruff-clean baseline: READY 6 (no PyPI/CI/Docker), OBVIOUS 6 (no `--demo`, multi-step setup), ALIVE 6 (no gallery/POV), MONEY 4 (collides with claude.ai/design), ORIGINAL 6 (niche narrow/time-limited).

## Approach
Build in three thirty-day waves anchored to a single positioning thesis: **claude-design-mcp is the interop bridge, not a destination studio.** Wave 1 closes shipping mechanics and the M-class agent findings so the package is real. Wave 2 ships DESIGN.md import/export + region-pinned iterate + web-capture — the positioning research's single highest-leverage 60-day shippable. Wave 3 closes HUMAN DEPENDENCY with tournament-judged variants and a DSPy distillation loop on local SQLite. The one most-important tradeoff: we deliberately do not chase v0/Claude Design on UX surface; we accept lifestyle scale (≤$300K–$3M ARR ceiling per positioning research) and optimize for being installed everywhere via `uv tool install`, not monetized.

## Alternatives considered
- **Compete head-on with claude.ai/design as a human studio (open-question 1a):** rejected — Anthropic owns OAuth, model, and brand; we lose within 12 months. Loses MONEY further.
- **Internal-only Eveland tool (open-question 1c):** rejected for now — the M-class findings and packaging work pay for themselves even if external adoption is zero, and DESIGN.md emission is leveraged for Tyler's own Book Club / Audrey UIs.
- **Skip PyPI, ship Docker only:** rejected — `uv tool install` is the 2026 MCP idiom (every Anthropic example uses uvx); Docker is power-user-only per release-path research §2.3.
- **Telemetry-based feedback loop (open-question 5b/c):** rejected — local-only is the genuinely novel differentiator vs Copilot/v0 per feedback-loops §5; "your design system learns, nothing leaves your box" is the moat.
- **Discriminated-union refactor of `DesignVariantsInput` (framework-docs §4.1):** rejected — current `model_validator` is simpler; spend the budget on prompt clarity instead.

## Files to touch

**Milestone 1 (Day 1-30):**
- `src/claude_design/renderer.py:225-252` — memoize `Renderer.readiness()` keyed on `(PLAYWRIGHT_BROWSERS_PATH, CLAUDE_DESIGN_STUDIO_DIR)` fingerprint; invalidate via `_reset_singletons` (M8 fix).
- `src/claude_design/renderer.py:255-302` — wrap `_browser_install_status` so its ~15s `playwright install --dry-run` subprocess only runs on cache miss.
- `src/claude_design/renderer.py` (in `Renderer.render` context creation) — add `service_workers="block"` to `browser.new_context(...)` (M6 closure; HIGH).
- `src/claude_design/renderer.py` (in `pw.chromium.launch(...)` call) — add `channel="chromium"` for Chrome-for-Testing new-headless (framework-docs §3.2).
- `src/claude_design/studio.py` (CSP injector) — replace `'unsafe-inline'` in `script-src` with per-document nonce; system prompt instructs model to attach the nonce. Add test in `tests/test_csp_and_clamp.py`.
- `src/claude_design/designer.py` (`_ALLOWED_EFFORTS`) — add `"xhigh"`; switch `tier="best"` on Opus 4.7 to `effort="xhigh"`.
- `src/claude_design/designer.py` (`_consume`) — branch on `ResultMessage.api_error_status` (429 vs 5xx vs other) per framework-docs §2.2.
- `src/claude_design/designer.py:173-199` (`_oauth_only_environ`) — add `strict_mcp_config=True` to `ClaudeAgentOptions`.
- `pyproject.toml` — replace with dynamic-version (hatch-vcs) shape from release-path §1.1; floors `mcp>=1.27.1,<2`, `claude-agent-sdk>=0.1.77,<0.2`, `playwright>=1.55,<2`; add `[project.urls]`, classifiers, sdist target.
- `src/claude_design/server.py:1279` — add `--demo` flag dispatch immediately after `--check`/`--check-json` block at 1286-1292.
- `src/claude_design/server.py:147-155` (`_reset_singletons`) — also reset renderer-readiness cache.
- `src/claude_design/server.py:838-874` (`_persist_design`) — emit lineage `parent_id` automatically on iterate (already exists as `iteration_of` column per recon).
- `README.md` (lines ~51-100) — rewrite install section around `uv tool install` + `claude mcp add --scope user`; drop hand-edit-JSON instructions.
- `install.ps1` — keep but mark deprecated; reference uv path in README.

**Milestone 2 (Day 31-60):**
- `src/claude_design/studio.py:38-77` (`_SCHEMA`) — add `kept_at REAL`, `discarded_at REAL`, `iteration_reason TEXT`, `eval_score REAL`, `eval_breakdown TEXT`, `accept_signal TEXT` columns. Mirror onto `DesignRecord` at `studio.py:85-129` and row mapper at `studio.py:618-640`.
- `src/claude_design/renderer.py` — inject stable `data-cd-id="<8-char-hash>"` (sha256 of element_path + normalized_text, first 8 chars) on semantic elements (`button`, `a`, `h1-h6`, `section`, `article`, `nav`, `main`, `aside`).
- `src/claude_design/server.py:567` — add `@mcp.tool` entries for `design_capture_url`, `design_iterate_region`, `design_diff`, `design_export_design_md`. All wrapped by `@_tool` (server.py:196).
- `src/claude_design/models.py:198` — Pydantic input models for the four new tools using shared `_ID_PATTERN` at `models.py:56`.
- `src/claude_design/designer.py:343-381` (`Designer.variants`) — reuse for parallel `design_score` judge calls.
- `src/claude_design/renderer.py:414-551` (`Renderer.render`) — split for `design_capture_url`: reuse browser pool, swap `html_path` for `url`.

**Milestone 3 (Day 61-90):**
- `src/claude_design/studio.py:38-77` (`_SCHEMA`) — add `variant_judgments` table: `(variant_id TEXT, criterion TEXT, score REAL, judge_model TEXT, rubric_version TEXT, created_at REAL)`. Add `rejected_candidates` table for self-rejection losers.
- `src/claude_design/server.py:567` — `design_keep`, `design_discard`, `design_score`, `design_stats`, `design_lineage`, `design_distill` tool entries.
- `src/claude_design/designer.py` — add tournament logic (single-elim, A/B order randomized per round); judge prompt + 4-criterion rubric (hierarchy, contrast/WCAG, token coherence, non-generic aesthetic).
- `src/claude_design/prompts.py` — load optimized prompt from `prompts/design_create.optimized.txt` if it beats baseline on held-out validation set ≥60%.

## Files to create

**Milestone 1:**
- `.github/workflows/release.yml` — trusted-publishing PyPI workflow (release-path §1.2), TestPyPI gate, attestations.
- `.github/workflows/test.yml` — matrix on Python 3.10–3.13; `pytest -q && ruff check src tests`.
- `.github/workflows/release-please.yml` + `release-please-config.json` + `.release-please-manifest.json` — automated CHANGELOG/version PRs.
- `Dockerfile` — multi-stage Playwright-base image, ~900 MB, healthcheck via `--check-json` (release-path §2.2).
- `.github/workflows/docker.yml` — GHCR publish on tag push; `docker/build-push-action@v5` + `attestations: true`.
- `scripts/smoke_install.sh` — TestPyPI install + `tools/list` JSON-RPC handshake assert (release-path §3.4).
- `scripts/smoke_install.ps1` — Windows equivalent.
- `CHANGELOG.md` — bootstrap entry for v0.2.0.
- `examples/` directory — `examples/01-operator-console.html`, `02-pricing-table.html`, `03-marketing-hero.html`, each with the prompt that produced it + the rendered PNG. Drives ALIVE.
- `examples/README.md` — gallery index with POV statement ("what this tool refuses to ship") and side-by-side vs v0/AIDesigner outputs.

**Milestone 2:**
- `src/claude_design/design_md.py` — DESIGN.md (Apache-2.0 spec, github.com/google-labs-code/design.md) emitter + parser. YAML front-matter, 9 ordered sections per feedback-loops §3.
- `src/claude_design/web_capture.py` — Playwright DOM + computed-styles + screenshot extractor; produces a `DesignRecord` equivalent to a generated design.
- `src/claude_design/regions.py` — `data-cd-id` hash logic; `str_replace`-style narrow-patch helpers for `design_iterate_region`.
- `tests/test_design_md_roundtrip.py` — emit → parse → re-emit yields byte-identical output.
- `tests/test_web_capture.py` — capture a known local fixture page, assert tokens extracted.
- `tests/test_regions.py` — stable hash across iterations; orphan-comment resolution.

**Milestone 3:**
- `src/claude_design/judge.py` — tournament dispatch, A/B randomization, Bradley-Terry rating, rubric versioning.
- `src/claude_design/distill.py` — DSPy `BootstrapFewShot` over last-30-days kept designs; held-out validation harness; saves `prompts/design_create.optimized.txt`.
- `src/claude_design/visual_eval.py` — `pixelmatch`-style Playwright + Pillow diff harness for regression detection.
- `tests/test_visual_eval.py` — golden-image baselines for the three example designs.
- `tests/test_tournament_judge.py` — position-bias check (swap order, score must not flip > 30%).
- `notes/ultraplan-2026-05-10/context/rubric-snapshot-90day.md` — re-scored rubric proving dimensions ≥7.

## Implementation sequence (30 / 60 / 90 day cadence)

### Milestone 1 — Day 1-30: "shippable v0.2"
**Target rubric movement:** READY 6→8, OBVIOUS 6→7, ALIVE 6→7. Apply remaining agent findings (M4, M7, M8, M10; HIGH-2 nonce CSP).

1. **M8 renderer-cache fix.** Memoize `Renderer.readiness()` on env fingerprint; invalidate via `_reset_singletons`. **Acceptance:** new test `tests/test_renderer_security.py::test_readiness_cached` — second call must not invoke subprocess; `--check` p95 drops from ~15s to <1s on warm path. **Files:** `renderer.py:225-302`, `server.py:147-155`.
2. **SDK pin tightening.** Bump `pyproject.toml` to `mcp>=1.27.1,<2`, `claude-agent-sdk>=0.1.77,<0.2`, `playwright>=1.55,<2`. **Acceptance:** `python -m build` succeeds; `pip install dist/*.whl && python -c "import claude_design; print(claude_design.__version__)"` prints a hatch-vcs-derived version string.
3. **HIGH-2 nonce-based CSP.** Replace `script-src 'unsafe-inline'` with per-document nonce; inject nonce into both CSP and any `<script>` the model emits. Update system prompt to instruct nonce usage. **Acceptance:** `tests/test_csp_and_clamp.py::test_inline_script_requires_nonce` — design with un-nonced inline script renders blocked; nonced script renders. v3 copy-button demo still works.
4. **service_workers="block" + channel="chromium".** Apply both per framework-docs §3.2/§3.5. **Acceptance:** new `tests/test_renderer_security.py::test_service_worker_blocked` — HTML registering an SW must not exfiltrate via SW fetch handler.
5. **xhigh effort + api_error_status branching + strict_mcp_config.** Per framework-docs §2.2. **Acceptance:** `tests/test_designer_oauth.py::test_xhigh_effort_accepted` and `test_429_message_distinct`.
6. **`--demo` subcommand.** Lift `scripts/dogfood_smoke.py:43-162` into a reusable `demo()` function in `server.py`. **Acceptance:** `claude-design-mcp --demo` runs without OAuth (uses cached fixture HTML); produces 3 rendered PNGs in `${CLAUDE_DESIGN_STUDIO_DIR}/demo/`; exit code 0.
7. **PyPI shipping pipeline.** Land `release.yml` + `test.yml` + `release-please.yml`; configure Trusted Publisher at pypi.org and test.pypi.org; create `pypi`/`testpypi` GitHub Environments. **Acceptance:** push `v0.2.0-rc1` tag → workflow green → `uv pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple claude-design-mcp==0.2.0rc1` in a throwaway venv; `claude-design-mcp --check-json` returns `ok=true`.
8. **Dockerfile + GHCR.** Multi-stage Playwright base, strip Firefox/WebKit, install bundled `claude` CLI, non-root user, healthcheck via `--check-json`. **Acceptance:** `docker run --rm -i ghcr.io/evilander/claude-design-mcp:0.2.0 --check-json` returns `ok=true`; image size <1.1 GB.
9. **README rewrite.** Four-command install (`uv tool install` → `claude login` → `claude mcp add --scope user`). **Acceptance:** fresh Windows VM with only `uv` installed completes the four commands and `/mcp` in Claude Code lists `claude-design` as connected.
10. **Examples gallery + POV.** `examples/` with three flagship designs + their prompts + side-by-side renders vs a v0/AIDesigner equivalent. README links it. **Acceptance:** `examples/README.md` exists with ≥3 case studies; each has prompt, output PNG, and 1–2 sentence POV ("what this refuses to ship: numbered quadrants, eight identical cards, generic AI hero pattern"). Drives ALIVE 6→7.

**Exit gate:** 136 baseline tests pass, ruff clean; new tests bring suite to ~150; `v0.2.0` tag published to PyPI; `ghcr.io/evilander/claude-design-mcp:0.2.0` pulls; `--demo` produces visible output; rubric re-score shows READY=8, OBVIOUS=7, ALIVE=7.

### Milestone 2 — Day 31-60: "interop layer"
**Target rubric movement:** ORIGINAL 6→8 via DESIGN.md import/export, web-capture, region-pinned iterate. MONEY 4→6 (positioning narrative becomes credible). Plus feedback-loop A (lineage + accept-rate).

11. **SQLite schema additions for signal capture.** Migrate `_SCHEMA` and `DesignRecord`/row mapper per codebase-recon §"Schema additions". **Acceptance:** `tests/test_studio_migration.py::test_v0_2_to_v0_3_migration` — load a v0.2 DB file, run migration, columns present, no data loss.
12. **DESIGN.md emitter.** `design_extract_system(format="design-md")` emits valid spec output. **Acceptance:** `tests/test_design_md_roundtrip.py` passes; `npx @google/design.md lint extracted.md` exits 0 against fixture output.
13. **DESIGN.md importer.** `design_apply_system` accepts a `design_md_path` argument; tokens flow into prompt context. **Acceptance:** `tests/test_design_md_apply.py::test_tokens_flow_into_prompt` — invoking with a known DESIGN.md produces output where prompt-context dump contains exact colors/typography from the file.
14. **`design_validate_design_md` tool.** Shells out to `designmd lint` (with `designmd` alias on Windows per feedback-loops §3); surfaces WCAG contrast results in MCP response. **Acceptance:** running against a fixture with deliberate AA-fail contrast returns `wcag_failures` array with the failing pair.
15. **`design_capture_url(url=...)`.** Playwright DOM + computed styles + screenshot; produces a `DesignRecord` persisted via `_persist_design`. **Acceptance:** `tests/test_web_capture.py` captures a local fixture HTML page, asserts colors/fonts/spacing tokens extracted; `design_get(captured_id)` returns the record.
16. **`data-cd-id` injection.** Renderer hashes semantic elements; IDs survive iterations. **Acceptance:** `tests/test_regions.py::test_id_stability` — iterate a design twice with non-text-changing edits, IDs of unchanged elements identical.
17. **`design_iterate_region(design_id, element_id, instruction)`.** `str_replace`-style narrow patch; rest of design locked. **Acceptance:** `tests/test_regions.py::test_outside_region_byte_identical` — diff outside the targeted subtree must be empty.
18. **`design_diff(id_a, id_b)`.** Uses `Studio.lineage` (studio.py:577-616) + Playwright side-by-side render + JSON token diff. **Acceptance:** `design_diff` between two known designs returns structured `{tokens_changed: [...], visual_diff_png_path: "..."}`.
19. **Feedback loop A (lineage + accept-rate).** `design_iterate` auto-sets `parent_id` and parent `accepted_at`; `design_export`/`design_apply_system` mark `accept_signal`. `design_stats()` returns aggregate. **Acceptance:** `tests/test_lineage.py::test_accept_rate_computed` — after a scripted 10-design session with 4 iterations and 2 exports, `design_stats()` reports `accept_rate >= 0.6`.

**Exit gate:** suite >160 tests, ruff clean; `v0.3.0` published; DESIGN.md roundtrip externally validated by `npx @google/design.md lint`; rubric re-score shows ORIGINAL=8, MONEY=6, ALIVE still ≥7. README opens with "the OAuth-native, DESIGN.md-speaking design interop layer."

### Milestone 3 — Day 61-90: "self-improving design"
**Target rubric movement:** ALIVE 6→8 via tournament-judged variants + DSPy distillation. MONEY 6→7 (compounding-quality story is real). Closes HUMAN DEPENDENCY via `design_keep` / `design_discard` / `design_score`.

20. **`design_keep` / `design_discard` tools.** Explicit signal capture; updates `kept_at`/`discarded_at`/`iteration_reason` columns from M2. **Acceptance:** `tests/test_keep_discard.py::test_signals_persisted` — call each, verify SQLite rows.
21. **`design_score(design_id)` self-eval.** Single judge call against 4-criterion rubric; writes `eval_score`/`eval_breakdown`. Always-on after `design_create`/`design_iterate` per decisions.md. **Acceptance:** every `design_create` response includes `_meta.eval_score`; if any criterion <6 a `warnings` field surfaces it.
22. **Tournament-judged `design_variants`.** Single-elim, ⌈log₂N⌉ judge calls, A/B order randomized. **Acceptance:** `tests/test_tournament_judge.py::test_position_bias_below_30pct` — running same pair both orders, winner flips on <30% of trials.
23. **Internal best-of-N self-rejection for `design_create`.** N=3 candidates, judge picks winner, losers persisted to `rejected_candidates`. **Acceptance:** new `rejected_candidates` row count = 2 × successful `design_create` calls.
24. **Visual eval harness.** Pillow/`odiff`-style pixel diff against golden baselines for the three flagship examples. **Acceptance:** `pytest tests/test_visual_eval.py` — any regression beyond 2% pixel-diff threshold fails the run; wired into `test.yml`.
25. **DSPy distillation loop.** `design_distill()` tool runs `BootstrapFewShot` over last-30-days kept designs; held-out validation set; only saves optimized prompt if it beats baseline on ≥60% of held-out cases. Opt-in via `CLAUDE_DESIGN_OPTIMIZED_PROMPT=on`. **Acceptance:** `tests/test_distill.py::test_optimized_prompt_gated` — fixture with 30 examples produces a `prompts/design_create.optimized.txt`; baseline-worse output rejects the write.
26. **`design_lineage(design_id)` tree query.** Walks parent/descendant chain. **Acceptance:** `tests/test_lineage.py::test_tree_walk` — 5-deep lineage chain returns full tree with depth markers.
27. **90-day rubric re-score artifact.** Write `notes/ultraplan-2026-05-10/context/rubric-snapshot-90day.md` mirroring `rubric-snapshot.md` but with new scores + evidence (commit hashes, test names, gallery file paths). **Acceptance:** file exists; every score ≥7; ORIGINAL/ALIVE/MONEY ≥8.

**Exit gate:** suite >180 tests; ruff clean; `v0.4.0` published; visual eval CI green; `design_distill` ran at least once locally and produced an opt-in optimized prompt; final rubric all ≥7, stretch goals on differentiators met.

## Risks and unknowns
- **Anthropic ships managed design Skill in <6 months.** Mitigation: Milestone 2's DESIGN.md interop layer is exactly what survives this — we become the consumer of Anthropic's output, not a competitor.
- **DESIGN.md spec churns during alpha.** Mitigation: pin `@google/design.md` to a specific version; bump deliberately; `test_design_md_roundtrip` catches breakage.
- **`uv tool install` adoption gap on Windows.** Mitigation: keep `install.ps1` working; document `pipx` fallback; README leads with uv.
- **Docker OAuth credential mount is fragile** (release-path §4.1). Accept: power-user feature; document the `~/.claude` mount workaround; primary install path is `uv tool install`.
- **Trusted Publisher misconfig on first tag push.** Mitigation: TestPyPI gate runs first; `pypi` Environment requires manual approval reviewer.
- **DSPy is a heavyweight dep.** Mitigation: feedback-loops §4b fallback — 50-line "random 8 kept designs as few-shot demos" captures 70% of value without DSPy if it bloats.
- **Judge calibration drift over 90 days.** Mitigation: rubric version stored on every judgment; calibration set re-run after any rubric edit.
- **Native Windows sandbox unsupported** (framework-docs §2.3). Accept: `tools=[]`/`permission_mode="dontAsk"` is the actual safety surface on Windows; sandbox stays opt-in via `CLAUDE_DESIGN_SANDBOX`.
- **AIDesigner or Anthropic acquihires the niche.** Accept: per positioning research §honest-verdict, that is a legitimate successful outcome; the work product is the reference implementation either way.

## Open questions
All eight open questions from `open-questions.md` have defaults locked in `decisions.md`. The two that need confirmation **before the first PyPI publish** (Milestone 1 step 7):
- **OQ-2: PyPI name + repo path.** Plan assumes `claude-design-mcp` on PyPI, repo at `github.com/evilander/claude-design-mcp`. Confirm before configuring Trusted Publisher.
- **OQ-4: License + CONTRIBUTING.** Plan keeps MIT and defers `CONTRIBUTING.md` to Milestone 2 (only add if a real external PR arrives).

Everything else (positioning=b, feedback=local, DESIGN.md=yes, sandbox=opt-in, self-eval=always-on, CSP=nonce) is locked in `decisions.md` and assumed.

## Execution notes
(left blank for the executing session)

> **Executor instructions:** write decisions to `notes/ultraplan-2026-05-10/context/decisions.md` as you make them. Answer open questions by editing `open-questions.md` and committing. Tag releases as `v0.2.0` (M1 exit), `v0.3.0` (M2 exit), `v0.4.0` (M3 exit). Re-run rubric scoring at each exit gate and commit the snapshot.
