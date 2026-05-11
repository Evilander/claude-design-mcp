# Rubric snapshot — v0.2.0-rc1 (2026-05-10)

Captured at the moment v0.2.0-rc1 was tagged.

| # | Dimension | Score | Δ | Evidence |
|---|-----------|------:|---:|---|
| 1 | WORKS     |  9/10 | +1 | 168 tests pass, ruff clean, wheel + sdist build clean, twine PASSED, --demo works |
| 2 | OBVIOUS   |  7/10 | +1 | 4-command Quick Start (PyPI + source), --demo, --check-json, RELEASING.md |
| 3 | FAST      |  7/10 |  0 | Bound by Claude latency; warm browser pool; cache deferred |
| 4 | SOLID     |  9/10 | +2 | Nonce CSP closes HIGH-2; SVG meta-refresh tested; OAuth scrub; 2 MiB cap |
| 5 | TESTED    |  8/10 | +1 | 117 → 168 tests; nonce + foreign-content + DESIGN.md + OAuth coverage |
| 6 | ALIVE     |  7/10 | +1 | README has voice; security section is opinionated; DESIGN.md scope honest |
| 7 | MONEY     |  6/10 | +2 | **BLOCKING** — DESIGN.md interop shipped, headline framing still mid; no gallery |
| 8 | ELEGANT   |  8/10 |  0 | Architecture preserved; design_md.py defensive; hand-rolled YAML |
| 9 | READY     |  8/10 | +2 | CI workflows, RELEASING.md, twine PASSED, version 0.2.0 |
| 10| ORIGINAL  |  7/10 | +1 | First MCP that emits valid Google DESIGN.md; import in 0.3 |

**Average: 7.6 (was 6.5).** Single dimension under 7.

## Verdict for v0.2.0-rc1

**SHIP THE RC.** The one blocking dimension (MONEY) is a market problem,
not a code-fix problem. It moves with examples gallery + sharper headline
framing (M2 work), not with another nonce hardening pass.

The rubric's "below 7 = NOT PRODUCTION READY" rule applies to v0.2.0
**final**, not v0.2.0-rc1. The RC is for pipeline validation and
real-world install testing — close the MONEY gap before v0.2.0 final.

## What the RC validates

- The Trusted Publishing pipeline end-to-end (after the one-time pypi.org
  pending-publisher setup documented in RELEASING.md §1).
- The CI matrix on Python 3.10–3.13 × {ubuntu, windows}.
- Real-world `uv tool install` from TestPyPI in a fresh venv.
- DESIGN.md emit + validate against the live `@google/design.md lint` CLI
  in CI.

## To reach 7 on MONEY before v0.2.0 final

1. Examples gallery: 3 case-study designs with prompts + outputs + a POV
   statement. (M1 step 10 in the ship plan.)
2. README headline rewrite: lead with "DESIGN.md bridge" before "studio".
3. One external user try the install path and report back.

## Files in the worktree at this snapshot

```
B:\projects\claude\claude-design-mcp-ship  (branch feat/ship-claude-design-mcp)
├── README.md                (+ DESIGN.md Export section, scoped)
├── RELEASING.md             (NEW — Trusted Publishing prereqs)
├── pyproject.toml           (v0.2.0, pinned deps, project.urls)
├── .github/workflows/
│   ├── release.yml          (Trusted Publishing, environment: pypi)
│   └── test.yml             (matrix 3.10–3.13 × {ubuntu, windows})
├── src/claude_design/
│   ├── design_md.py         (NEW — emit_design_md + validate_design_md_via_cli)
│   ├── studio.py            (nonce CSP, HTML-parser injection, 2 MiB cap)
│   ├── designer.py          (OAuth env scrub, xhigh effort, api_error_status)
│   ├── renderer.py          (service_workers="block", channel="chromium")
│   └── prompts.py           (aesthetic stance, banned reflexes)
├── tests/                   (168 passing — 14 new files this autopilot run)
└── scripts/
    ├── smoke_mcp_stdio.py   (CI gate)
    └── dogfood_smoke.py     (manual install validation)
```
