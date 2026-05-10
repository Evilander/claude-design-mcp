# Open questions — answer before executing the plan

The plan in `../ship-claude-design-mcp.md` assumes default answers for these.
If Tyler disagrees, edit this file FIRST and commit before touching code.

## STRATEGIC

1. **Positioning choice (blocks MONEY + ORIGINAL):**
   - [ ] (a) Compete head-on with claude.ai/design as a human-facing studio. Lose to first-party tooling within 12 months but capture early MCP-using devs.
   - [ ] (b) Reposition as the agent-callable design primitive. Drop "studio" framing; sell to coding agents (Claude Code, Cursor, agentic CI). **DEFAULT — assumed unless overridden.**
   - [ ] (c) Internal-only tool for Tyler's workflow. Ship the polish but never market.

2. **PyPI publishing — name + ownership:**
   - The project is `claude-design-mcp` on disk. Is that the PyPI name we want?
   - Trusted-publishing via GitHub Actions requires the repo to be under an org or your personal GitHub. Confirm: `github.com/evilander/claude-design-mcp` or another path?

3. **Docker image hosting:**
   - GHCR (`ghcr.io/evilander/claude-design-mcp`) vs Docker Hub vs both? **Default: GHCR only** (free, OIDC-integrated).

4. **License + contribution model:**
   - Currently MIT. Stay MIT? Add CONTRIBUTING.md? Open to external PRs or internal-only?

## TECHNICAL

5. **Feedback loop scope:**
   - [ ] (a) Pure local: `design_keep` / `design_discard` tools update SQLite; no phoning home. **DEFAULT.**
   - [ ] (b) Anonymized telemetry: opt-in CSV export of `(kept, discarded, iterations_until_kept)` for future training.
   - [ ] (c) Live training loop: the system regenerates worse-scoring designs automatically.

6. **DESIGN.md adoption:**
   - Adopt Google Stitch's DESIGN.md spec (Apache-2.0) as the export format for `design_extract_system`? **Default: yes** — cross-tool portability is a real differentiator.

7. **Sandbox enable:**
   - `ClaudeAgentOptions.sandbox=SandboxSettings(enabled=True, network=deny-all)` is finding #2 from the framework research. Risk: Windows hosts may fail to init the sandbox. **Default: opt-in via `CLAUDE_DESIGN_SANDBOX=on`, default off until validated on Windows.**

8. **Self-eval pass:**
   - After every `design_create` / `design_iterate`, run a second cheap LLM call ("score this design 1-10 on hierarchy, restraint, surprise, content-fit; if any score < 6, regenerate"). Cost: ~$0.02/design.
   - [ ] (a) Always on. **Default — pairs with rubric.**
   - [ ] (b) Opt-in via `tier="best+eval"`.
   - [ ] (c) Off by default; expose `design_score(design_id)` as separate tool.

9. **CSP `script-src 'unsafe-inline'` tightening (HIGH-2):**
   - The security audit wants us to drop `'unsafe-inline'` from script-src. The model emits inline JS for progressive enhancement (e.g., the v3 design's copy-button handler).
   - [ ] (a) Drop entirely; require designs to ship pure HTML/CSS. Breaks the v3 copy-button.
   - [ ] (b) Per-document nonce; system prompt instructs the model to attach `nonce` to its `<script>`. **Default.**
   - [ ] (c) Keep current; accept the residual risk.

## ASSUMPTIONS THE PLAN MAKES UNTIL ANSWERED

- Positioning = (b) agent-callable primitive.
- PyPI name = `claude-design-mcp`.
- Repo path = `github.com/evilander/claude-design-mcp` (NOT VERIFIED — confirm before first release).
- Feedback = pure local SQLite.
- DESIGN.md = adopted.
- Sandbox = opt-in.
- Self-eval = always on.
- CSP = per-document nonce.
