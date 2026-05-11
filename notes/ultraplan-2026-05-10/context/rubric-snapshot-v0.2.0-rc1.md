# Rubric snapshot - v0.2.0-rc1 post-review (2026-05-10)

This note supersedes the first RC snapshot after the adversarial review found
two CSP placement blockers and one release-channel mismatch.

## Verified locally after fixes

- `python -m ruff check src tests scripts`: passed.
- `python -m pytest -q`: 172 passed.
- `python scripts/smoke_mcp_stdio.py`: passed, 11 MCP tools listed.
- `python -m build`: passed, wheel and sdist built.
- `python -m twine check dist/*`: both artifacts passed.

## Scores

| # | Dimension | Score | Evidence |
| --- | --- | ---: | --- |
| 1 | WORKS | 9/10 | Ruff, 172 tests, MCP smoke, build, and twine checks pass. |
| 2 | OBVIOUS | 8/10 | README has PyPI/source quick starts, render notes, demo, and check-json flow. |
| 3 | FAST | 7/10 | Bound by Claude latency; warm renderer pool and readiness cache remain. |
| 4 | SOLID | 9/10 | Pre-head CSP bypasses, template decoy heads, nonce handling, OAuth scrub, and 2 MiB cap covered. |
| 5 | TESTED | 9/10 | CSP adversarial coverage now includes pre-policy script/img/base/event payloads and real template decoys. |
| 6 | ALIVE | 7/10 | README presents a clear product stance and honest beta status. |
| 7 | MONEY | 6/10 | Still needs examples gallery and sharper customer proof before final release. |
| 8 | ELEGANT | 8/10 | Existing architecture preserved; hardening stayed inside the persistence boundary. |
| 9 | READY | 8/10 | Release workflow now routes prerelease tags to TestPyPI and final tags to PyPI. |
| 10 | ORIGINAL | 7/10 | DESIGN.md bridge plus persistent local design lineage remains the differentiated angle. |

Average: 7.8. One product-market dimension remains below 7 for the final
release bar, but the RC is suitable for install and pipeline validation.

## Review findings closed

- P0: Pre-head executable/resource content could run before the injected CSP.
  Fixed by sanitizing the prefix before the real head.
- P0: Real `<template><head>fake</head></template>` could catch CSP insertion.
  Fixed by ignoring template contents while locating the document head.
- P1: RC docs claimed TestPyPI routing while the workflow published every
  `v*` tag to PyPI. Fixed with separate TestPyPI and PyPI publish jobs.
- P2: README exposed `playwright install chromium` without ensuring the
  Playwright executable is installed by `uv tool install`. Fixed with
  `--with-executables-from playwright`.
- P2: Evidence note was stale. Updated to the final local verification above.

## Remaining before v0.2.0 final

1. Build an examples gallery with 3 case-study designs, prompts, outputs, and
   a concise point of view.
2. Have one external user run the PyPI or TestPyPI install path from scratch.
3. Keep the `pypi` environment approval gate enabled for final tags.
