# Feedback-loop patterns for LLM design tools — and what claude-design-mcp should adopt

> Scope: adversarial review scored HUMAN DEPENDENCY 1/10 because claude-design-mcp has zero mechanism to learn which designs the user kept vs discarded vs iterated. This note surveys five families of feedback patterns from production LLM-design tools, then proposes 3 high-leverage implementations that fit a local MCP server in the next 30 days.
>
> Audience: builder of claude-design-mcp (Tyler). Scope is local-first, no telemetry leaves the box.

---

## 0. Local repo baseline (where signal already exists, untapped)

Before adopting external patterns, note what claude-design-mcp already has and is throwing away:

- `notes/ultraplan-2026-05-10/research/designs.db` — SQLite store already on disk (73 KB).
- MCP tools (`src/claude_design/server.py`): `design_create`, `design_iterate`, `design_variants`, `design_render`, `design_get`, `design_list`, `design_extract_system`, `design_apply_system`, `design_export`, `design_preview`.
- `Designer.designs/` already persists design records — but the *act* of iterating, exporting, or applying a system is not labelled as a preference signal.
- No `docs/solutions/` directory exists in this repo, so prior-art lookup is purely external.

The shortest path to a signal mechanism is: **label the verbs you already expose.** `design_iterate` against an ID is implicit "kept and refined." `design_export` is "kept as final." A discarded record is just a `design_id` from `design_list` that never gets iterated, exported, or rendered again after N days. This is the cheapest training signal in the building.

---

## 1. Vercel v0 — forking as implicit preference

### What it looks like in practice
v0 records **lineage metadata** on every fork: `"X was forked from Y"`. A fork spawns a new chat session tied to the forked block, and v0 surfaces the parent-child relationship in UI. There is no explicit thumbs-up; the *act of forking* is the signal that this state was worth preserving.

Behaviors that v0 treats as fork-equivalent signals:
- **"Known good" preservation** — users fork before risky changes, branching from a state they want to keep.
- **Context refresh** — users fork when the chat gets slow or drifts, anchoring on a preferred snapshot.
- **Branch-off from regression** — when v0 goes off the rails, users fork backward to a healthier ancestor.

### What's exposed via API/MCP
The v0 **Platform API (beta)** exposes `POST /v1/chats`, `POST /v1/chats/{chatId}/messages`, plus chat-management ops including **fork, rename, delete**. The API does not document a dedicated "preference event" endpoint — fork events are inferred from chat lineage records returned on `GET /chats/{id}` or list calls. So forks are not fed back into v0's model in any publicly visible way; they're *structural metadata* for the user's history, and an aggregate signal Vercel almost certainly mines server-side for ranking.

### Minimum implementation for an MCP server
Already trivial in claude-design-mcp because `design_iterate` is essentially a fork:
- Add `parent_id`, `forked_at`, `fork_reason` columns to the design record.
- When `design_iterate` is called, populate `parent_id` automatically.
- Add a `design_fork(design_id, reason?)` tool that copies the record without modifying it (snapshot-preserve).
- Expose `design_lineage(design_id)` to walk the tree.

Cost: ~150 lines of Python + a migration. The signal lands automatically because every iterate call is already a fork.

**Works locally?** Yes — pure SQLite, no network.

---

## 2. Open CoDesign — `data-codesign-id` + region-scoped comments

### What it looks like in practice
Open CoDesign (MIT, OpenCoworkAI) attaches a **stable `data-codesign-id` attribute** to every interactive element in generated HTML. These IDs survive regenerations. The user clicks any element in the live preview, drops a pin, types a note, and the model rewrites *only that region* using a `str_replace` operation keyed off the `data-codesign-id`.

Concretely:
1. Renderer injects `data-codesign-id="btn-primary-7f3a"` (stable hash) on every element during HTML emission.
2. Browser preview pane listens for clicks, captures `{id, comment, bbox, screenshot_crop}`.
3. Comment is appended to a per-design comment graph in SQLite.
4. Next iteration call sends only the targeted element's HTML subtree plus the comment, and the model returns a `str_replace` patch.

### Is the comment graph mined for training signal?
The Open CoDesign CHANGELOG and quickstart describe it as **product UX**, not as a training pipeline. But the data shape is already ideal for distillation: every comment is `(element_id, before_html, after_html, user_note)` — that's a labelled edit-pair, which is exactly what DPO / preference fine-tuning consumes. No published evidence that OpenCoworkAI mines this, but the design enables it.

### Minimum implementation for an MCP server
This is the highest-leverage pattern on the list because it captures **what was wrong**, not just *that something was wrong*.

- In `renderer.py`, hash each significant element (`button`, `a`, `h1-h6`, semantic containers) into `data-cd-id="<8-char-hash>"`. Hash from path + text content so it's stable across iterations.
- Add `design_comment(design_id, element_id, note, action?)` MCP tool. Actions: `keep | rewrite | remove | iterate`.
- Add `design_iterate_region(design_id, element_id, instruction)` — runs `str_replace`-style narrow patches against the cached HTML.
- Store comments in `comments` table: `(design_id, element_id, note, action, created_at, applied_at, resolved_in_design_id)`.

**Crucially:** every comment is a tiny labelled example. After 50 comments you have a small private dataset of `(context_snippet, instruction, before, after)` quadruples. That's the entry point to pattern 4.

**Works locally?** Yes — the renderer is already local; this just adds attribute injection and a tool.

---

## 3. Google Stitch DESIGN.md — portable spec, NOT a feedback loop

### What it looks like in practice
`DESIGN.md` (Apache-2.0, alpha) is a **portable design-system format**, not a feedback channel. The spec has 9 ordered sections:

1. YAML front matter (tokens: colors, typography, rounded, spacing)
2. `## Overview`
3. `## Colors`
4. `## Typography`
5. `## Layout`
6. `## Elevation & Depth`
7. `## Components` (with `backgroundColor`, `textColor`, `typography`, `rounded`, `padding`, `size`, `height`, `width`)
8. Variants as separate component entries with related key names (hover, active, pressed)
9. (Optional) extension sections

CLI: `npx @google/design.md` ships:
- `lint` — structural validation, includes **WCAG contrast ratios automatically** (`textColor (#ffffff) on backgroundColor (#1A1C1E) has contrast ratio 15.42:1 — passes WCAG AA`).
- `diff` — token-level regression detection (exit 1 if "after" has more errors/warnings than "before").
- `export --format tailwind` — drops straight into Tailwind theme configs; also W3C DTCG tokens.
- `spec` — outputs the full format spec for prompt injection.

**Windows note:** invoke as `designmd` (not `design.md`) from package.json scripts — the `.md` suffix collides with the Markdown file association on Windows.

### Is this a feedback loop?
No. It's a **substrate** that makes feedback loops portable. The loop value is indirect: if claude-design-mcp emits DESIGN.md after `design_extract_system`, the user can hand-edit it, and `lint` + `diff` against it become an automated gate for whether subsequent designs respect the system. That *is* a feedback loop — it's just one where the user's edits to DESIGN.md are the labels and the linter is the judge.

### Minimum implementation for an MCP server
- `design_extract_system` already exists; add `format="design-md"` option that emits a valid `DESIGN.md` file.
- Shell out to `npx @google/design.md lint` (or `designmd lint` on Windows) on every render and surface results in the MCP response.
- Run `designmd diff prev.md cur.md` after every `design_iterate` and label the iteration as `regressed | improved | neutral` based on exit code and warning delta.

This buys: free WCAG audit, portable design tokens across tools, and a labelled iteration outcome — all from a CLI someone else maintains.

**Works locally?** Yes — pure Node CLI, runs offline once installed.

---

## 4. RapidFire patterns — judge-based selection and labelled-example distillation

This family is what actually closes the loop: turn signals into model-visible improvement without a backend.

### 4a. LLM-as-judge + tournament-style `design_variants`

Already half-built. `design_variants` emits N candidates. Add a judge stage:

- After generating variants, dispatch a separate **judge call** that takes pairs and picks winners. Use **single-elimination tournament** (Arena-Lite style): N variants → ⌈log₂N⌉ rounds → Bradley-Terry rating per variant.
- **Mitigate position bias** by evaluating both `(A,B)` and `(B,A)` orderings, or randomizing per round.
- Judge prompt grounds on a rubric: "Score for (1) hierarchy clarity, (2) contrast/WCAG, (3) coherent token usage, (4) absence of generic AI aesthetics." Return per-criterion + overall.
- Store: `(variant_id, criterion, score, judge_model, rubric_version, timestamp)`.

When the user accepts/exports variant X, you now have `(judge_rank, user_choice)` pairs — that's a calibration set for the judge itself. After ~30 sessions, you can spot when the judge disagrees with the user and either re-prompt or fall back to user-only ranking.

References: Arena-Lite (arxiv 2411.01281), JuStRank (arxiv 2412.09569), "Tuning LLM Judge Design Decisions" (arxiv 2501.17178).

### 4b. DSPy-style optimization from kept/discarded labels

DSPy doesn't learn from preference pairs directly; it learns from **metric functions over labelled examples**. The trick is: once you've labelled designs as `kept` (iterated > 0 times AND/OR exported) vs `discarded` (no follow-up activity in 14 days), you have a binary metric.

- Wrap your design-generation prompt as a `dspy.Signature`.
- Build `dspy.Example` objects from kept designs (input = original user request, output = final HTML).
- Choose an optimizer based on dataset size:
  - **< 10 examples** → `LabeledFewShot` (just retrieve relevant kept designs as few-shot).
  - **10–50 examples** → `BootstrapFewShot` (your kept designs become the demos; the metric filters bad ones).
  - **50–200+ examples** → `MIPROv2` (joint instruction + example optimization via Bayesian search).
- Metric function: composite of `(was_kept, judge_score, designmd_lint_passed, wcag_contrast_passed)`.

This is the loop close: kept-vs-discarded → metric → optimizer → improved prompt for the *next* `design_create`. No model fine-tune required.

### 4c. Self-refinement / self-rejection within a single generation

Cheap version, no labels needed: every `design_create` runs `N=3` candidates internally, judges them with a rubric, returns only the winner, and stashes the losers in a `rejected_candidates` table. Those rejected candidates are negative examples for later DPO-style work, and the user never sees the misses.

References: Lee et al. 2024 (JSFT + self-rejection by tournament), Yuan et al. 2024 (self-rewarding LLMs).

**Works locally?** Yes — judge calls hit the same Anthropic/OAuth endpoint you already use. DSPy runs locally, only LM calls leave the box, and even those can target a local Ollama.

---

## 5. Local signal capture without phoning home — Apple, Copilot, and the gap

### Apple (Xcode Predictive Code Completion)
Runs **entirely on-device** (Apple Silicon, 8 GB RAM, 2 GB disk). Trained for Swift + Apple SDKs. Accept = Tab. Apple does *not* train on user code. Publicly **silent on whether anonymized accept-rate telemetry is collected**; the privacy framing emphasizes only that code stays local. The model is shipped pre-optimized; there's no continuous learning loop user-visible.

Takeaway: Apple's pattern is "ship a tuned model, no online learning, no signal exfil." For a local MCP server this is the safest default but it forfeits the compounding advantage. The alternative — local on-disk signal capture + local optimization — gives you the compounding without ever sending data out.

### GitHub Copilot
Captures `total_suggestions_count` and `total_acceptances_count` **in the IDE extension**, sends them to GitHub over the network. Acceptance rate = `accepts / shown * 100`, industry average **27–30%**. Requires telemetry on; offline mode produces no signal. ~88% of accepted Copilot code remains in final commits — that's how they validate the signal post hoc.

Takeaway: Copilot's pattern is the *opposite* of what a local MCP should do — but the **metric** is the right one. `accept_rate` mapped to design-MCP terms = `(designs iterated or exported) / (designs created)`. That single number is the north-star metric the adversarial reviewer wanted to see.

### The gap claude-design-mcp can fill
Apple ships a tuned model with no learning. Copilot learns but requires telemetry. A **local MCP server can do both**: capture signal in local SQLite, run optimization locally (DSPy or just prompt-cache the winning patterns), never phone home. This is genuinely novel as a packaged offering. Sell it as "your design system gets sharper the more you use it, and nothing leaves your machine."

---

## Concrete 30-day implementation plan for claude-design-mcp

Three implementations, ranked by leverage-per-day-of-work. Costs assume Opus 4.7 baseline pricing (~$15/M input, $75/M output) for judge calls; all storage is local SQLite (free).

### Implementation A — Lineage + accept-rate metric (3 days)

**What ships:**
- Add `parent_id`, `forked_at`, `accepted_at`, `discarded_at`, `accept_signal` columns to `designs` table.
- `design_iterate` auto-sets `parent_id` and marks parent `accepted_at=now()`.
- `design_export` and `design_apply_system` mark `accepted_at=now()` and `accept_signal='exported'` / `'applied'`.
- `design_render` + user opening the rendered file (track via mtime on the rendered PNG) marks `accept_signal='rendered'`.
- New tool `design_stats()` returns: total designs, accept rate, top-5 kept design IDs by lineage depth, designs in `stale` state (created > 14d ago, no descendants, no exports).
- New tool `design_lineage(design_id)` returns parent chain + descendants as a tree.

**Why it matters:** lights up the HUMAN DEPENDENCY axis immediately. Adversarial reviewer can re-score because the system now has a measurable answer to "which designs were kept?"

**Cost:** ~1 day SQLite migration + tool wiring, ~1 day mtime watcher for the rendered/ dir, ~1 day stats + lineage tooling and tests. **Zero recurring LLM cost.**

**Risks:** mtime-as-signal is noisy if Tyler previews then ignores; mitigated by requiring two signals (rendered + iterated, OR exported alone) before counting as "kept."

### Implementation B — `data-cd-id` + region-scoped comment loop (5 days)

**What ships:**
- Renderer injects stable `data-cd-id="<8-char-hash>"` on every semantic element. Hash = first 8 chars of `sha256(element_path + normalized_text)`.
- New tool `design_comment(design_id, element_id, note, action)` where `action ∈ {keep, rewrite, remove, iterate}`.
- New tool `design_iterate_region(design_id, element_id, instruction)` that runs a narrow `str_replace` patch against cached HTML and re-renders.
- `comments` table stores every annotation; each comment becomes a labelled `(before_html_snippet, instruction, after_html_snippet)` triple after the patch lands.
- `design_get` returns recent comments alongside the design.

**Why it matters:** captures *what was wrong*, not just that something was wrong. Builds the dataset that powers Implementation C. Also makes the tool dramatically more useful for iterative work — surgical edits instead of full regenerations.

**Cost:** ~1 day attribute injection in `renderer.py`, ~1 day comment tools + table, ~2 days `design_iterate_region` with `str_replace` patch logic, ~1 day tests + preview-pane click handler (if applicable). **LLM cost per region edit: 5–20× cheaper than a full regen** because the prompt only includes the targeted subtree. Net cost reduction over time.

**Risks:** stable hashing breaks when text changes; mitigated by falling back to path-only hash for elements without stable text (icons, dividers). Also: comments on elements that get removed by a parent-level iterate are orphaned — surface them as "resolved by parent edit" instead of erroring.

### Implementation C — Tournament-judged `design_variants` + DSPy-style prompt distillation (10–14 days)

**What ships:**
- Modify `design_variants` to:
  1. Generate N candidates (default 4).
  2. Run a single-elimination tournament: ⌈log₂N⌉ judge calls, each scoring a pair on a 4-criterion rubric (hierarchy, contrast/WCAG, token coherence, non-generic aesthetics).
  3. Randomize A/B order per pair to mitigate position bias.
  4. Return ranked variants with per-criterion scores stored in `variant_judgments` table.
- Add `design_judge(design_id_a, design_id_b)` standalone tool for pairwise comparison of any two designs.
- Add a nightly (or on-demand `design_distill()` tool) job that:
  1. Pulls last 30 days of `kept` designs (Implementation A signal).
  2. Builds `dspy.Example` objects: `(user_request, kept_html)`.
  3. Runs `BootstrapFewShot` against the current `design_create` signature.
  4. Saves the optimized prompt to `prompts/design_create.optimized.txt`.
  5. Next `design_create` call uses the optimized prompt if it exists and outperforms the baseline on a small held-out validation set (also stored locally).

**Why it matters:** this is the actual learning loop the adversarial reviewer wanted. Closes from signal → metric → optimizer → improved future generation, all on the local box. Compounds with every session.

**Cost:**
- LLM judge calls: ~4 variant gen + 3 judge calls per `design_variants` invocation. At Opus 4.7 with ~3K token rubric prompts, ~$0.05–0.15 per variants call. Negligible vs the human time it saves.
- DSPy optimization run: `BootstrapFewShot` over 30 examples ≈ 60–120 LM calls. Run weekly = ~$2–5/week. Use Haiku 4.7 or local Ollama for the bootstrap stage to drop this near zero.
- Engineering: ~3 days tournament logic, ~2 days judge prompt + rubric calibration, ~3 days DSPy wiring + storage, ~2 days held-out validation harness, ~2–4 days hardening (Windows path quirks, OAuth env reuse, retries).

**Risks:**
- Judge calibration drift — mitigated by storing rubric version with every judgment and re-running calibration set after rubric edits.
- Catastrophic prompt regression after distillation — mitigated by held-out validation set with hard floor (new prompt must beat baseline on ≥ 60% of held-out cases) and `prompts/design_create.optimized.txt` is opt-in via env var until proven.
- DSPy is a heavyweight dep; if it's too much, the equivalent hand-rolled version is a `select random 8 kept designs, inject as few-shot demos in the prompt` loop. That's ~50 lines and captures 70% of the value.

### Optional Implementation D — DESIGN.md emission + lint gate (2 days)

**What ships:**
- `design_extract_system(format="design-md")` emits a valid Stitch DESIGN.md.
- Every `design_render` shells out to `designmd lint` and surfaces WCAG + structural results in the MCP response.
- Every `design_iterate` runs `designmd diff prev.md cur.md` and labels the iteration `regressed/improved/neutral` based on exit code.

**Why it matters:** free WCAG audit + portable design tokens + automatic labelled iteration outcomes, all from a CLI someone else maintains.

**Cost:** ~2 days including the Windows `designmd` vs `design.md` alias handling. **LLM cost: zero.**

**Risks:** DESIGN.md is alpha — spec changes are expected. Pin to a specific `@google/design.md` version and update deliberately.

### Optional Implementation E — Internal best-of-N self-rejection (1 day)

**What ships:**
- `design_create` internally generates 3 candidates, runs a 1-shot judge to pick the winner, returns only the winner. Losers stashed in `rejected_candidates` for future DPO data.

**Why it matters:** instant quality bump on every single-design generation. No user-facing change beyond "designs got noticeably better."

**Cost:** 3× LLM cost per `design_create` (offset by 1 judge call). At ~$0.02–0.05 baseline → ~$0.06–0.15 per call. ~1 day of code.

---

## Recommended 30-day sequence

1. **Days 1–3:** Implementation A (lineage + accept-rate). Lights up HUMAN DEPENDENCY axis with near-zero risk.
2. **Days 4–5:** Implementation D (DESIGN.md + lint gate). Cheap, externally maintained, audit-grade WCAG.
3. **Days 6–10:** Implementation B (region-scoped comments). Builds the dataset that powers C.
4. **Days 11–14:** Implementation E (best-of-N self-rejection). Quality bump while C is being built.
5. **Days 15–28:** Implementation C (tournament judge + DSPy distillation). The actual learning loop. Ship optimized prompt opt-in behind env flag.
6. **Days 29–30:** Re-run the adversarial review. HUMAN DEPENDENCY should now score ≥ 7/10 with measurable evidence: lineage trees, accept rates, region-edit history, judge calibration logs, weekly distillation runs.

## Final note on the "local-only" positioning

The most defensible angle for claude-design-mcp is: **"every other AI design tool either ships a static model (Apple) or requires telemetry to learn (Copilot, v0). This one learns from your usage, locally, and never sends a byte off your machine."** Implementations A + B + C together earn that claim. Implementations D and E are quality multipliers. None of them require a network beyond the LLM calls already happening.

---

## Sources

- [Improve v0 quality with strategic forking — Vercel Community](https://community.vercel.com/t/improve-v0-quality-with-strategic-forking/16487)
- [v0 Platform API now in beta — Vercel](https://vercel.com/changelog/v0-platform-api-now-in-beta)
- [Build your own AI app builder with the v0 Platform API — Vercel](https://vercel.com/blog/build-your-own-ai-app-builder-with-the-v0-platform-api)
- [v0 Platform API Demo template — Vercel](https://vercel.com/templates/ai/v0-platform-api-demo)
- [Open CoDesign repo (CHANGELOG with data-codesign-id mechanic)](https://github.com/OpenCoworkAI/open-codesign/blob/main/CHANGELOG.md)
- [Open CoDesign quickstart](https://opencoworkai.github.io/open-codesign/quickstart)
- [google-labs-code/design.md (Apache-2.0 spec)](https://github.com/google-labs-code/design.md)
- [Stitch's DESIGN.md format announcement — Google](https://blog.google/innovation-and-ai/models-and-research/google-labs/stitch-design-md/)
- [google-labs-code/stitch-skills (design-md skill pipeline)](https://github.com/google-labs-code/stitch-skills)
- [DESIGN.md Specification overview](https://www.dsebastien.net/design-md-specification/)
- [LangSmith human-in-the-loop feedback and annotation](https://apxml.com/courses/langchain-production-llm/chapter-5-evaluation-monitoring-observability/human-feedback-annotation)
- [How to Use LangSmith with DSPy](https://ishanbhagawati.medium.com/how-to-use-langsmith-with-dspy-debugging-and-evaluating-llm-pipelines-made-easy-d175eb94e9c4)
- [DSPy Optimizers overview](https://dspy.ai/learn/optimization/optimizers/)
- [DSPy BootstrapFewShot API](https://dspy.ai/api/optimizers/BootstrapFewShot/)
- [DSPy MIPROv2 API](https://dspy.ai/api/optimizers/MIPROv2/)
- [Arena-Lite: Tournament-Based Direct Comparisons (arxiv 2411.01281)](https://arxiv.org/html/2411.01281v4)
- [From Generation to Judgment: LLM-as-a-judge survey (arxiv 2411.16594)](https://arxiv.org/html/2411.16594v3)
- [JuStRank: Benchmarking LLM Judges for System Ranking (arxiv 2412.09569)](https://arxiv.org/html/2412.09569v1)
- [Tuning LLM Judge Design Decisions for 1/1000 of the Cost (arxiv 2501.17178)](https://arxiv.org/html/2501.17178v2)
- [LLM-as-a-judge complete guide — Evidently AI](https://www.evidentlyai.com/llm-guide/llm-as-a-judge)
- [GitHub Copilot usage metrics — GitHub Docs](https://docs.github.com/en/copilot/concepts/copilot-usage-metrics/copilot-metrics)
- [Predictive Code Completion in Xcode — Lickability](https://lickability.com/blog/xcode-predictive-code-completion/)
- [Xcode 16 Predictive Code Completion (InfoQ)](https://www.infoq.com/news/2024/06/xcode-16-predictive-code-complet/)
