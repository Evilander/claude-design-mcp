# Rubric snapshot — 2026-05-10

Captured at the moment ultraplan was invoked. The 5 blocking dimensions are the
target of the 30/60/90 cadence.

| # | Dimension | Score | Status |
|---|-----------|------:|--------|
| 1 | WORKS     |  8/10 | ok |
| 2 | OBVIOUS   |  6/10 | **BLOCKING** — multi-step setup; no `--demo` |
| 3 | FAST      |  7/10 | ok |
| 4 | SOLID     |  7/10 | ok (5 HIGH addressed, MEDIUMs deferred) |
| 5 | TESTED    |  7/10 | ok (no visual eval, no lifespan tests) |
| 6 | ALIVE     |  6/10 | **BLOCKING** — no examples gallery, no demo video, no POV |
| 7 | MONEY     |  4/10 | **BLOCKING** — competes with claude.ai/design |
| 8 | ELEGANT   |  8/10 | ok |
| 9 | READY     |  6/10 | **BLOCKING** — no PyPI, no CI, no Docker |
| 10| ORIGINAL  |  6/10 | **BLOCKING** — niche is narrow, time-limited |

**Goal:** every dimension >= 7. Stretch: 8+ on the differentiators (ALIVE, MONEY, ORIGINAL).

## Adversary's load-bearing criticisms (must close)

1. **No aesthetic stance** — addressed in prompts.py rewrite (post-adversary). Verified output: operator-console-v3 has personality. Keep iterating the prompt.
2. **No feedback loop** — every iterate call is a labeled "this was wrong" signal we throw away. Critical missing system.
3. **The 1930 redesigns were AI-good not good** — v2 had numbered quadrants + 8 identical cards. v3 fixed it after prompt rewrite. But the project needs a way to *detect* when output regresses to AI-good without Tyler eyeballing every render.
4. **No visual eval** — design quality is not measured by anything. The TESTED score of 7 hides this gap.
5. **Competes with claude.ai/design** — first-party tool with the same OAuth and same model. Must reposition.

## Files at risk if we don't act

- `src/claude_design/prompts.py` — the soul of the product. Any regression here ships generic AI output.
- `src/claude_design/designer.py` — _build_oauth_safe_env / _oauth_only_environ; if the SDK changes env handling, our scrub silently fails.
- `src/claude_design/studio.py` — inject_csp HTMLParser-based; locked by tests/test_csp_injection_bypass.py.

## Test count baseline

136 tests passing, ruff clean (2026-05-10). New work must preserve both gates.
