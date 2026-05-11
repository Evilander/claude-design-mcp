# Releasing claude-design-mcp

This project ships to PyPI via GitHub Actions Trusted Publishing (OIDC, no
long-lived tokens). The workflow at `.github/workflows/release.yml` triggers
on any `v*` tag push.

## One-time prerequisites (must be done before the first release)

These steps are not in CI. They are configured manually on pypi.org and
GitHub.com.

### 1. Reserve the PyPI project name

If `claude-design-mcp` is brand-new on PyPI (which it is for v0.2.0):

- Log in to https://pypi.org as the project owner.
- Go to **Your projects → Publishing → Add a new pending publisher**.
- Fill in:
  - **PyPI project name:** `claude-design-mcp`
  - **Owner:** `Evilander`
  - **Repository name:** `claude-design-mcp`
  - **Workflow filename:** `release.yml`
  - **Environment name:** `pypi`
- Save. PyPI now waits for the first matching `v*` tag push to claim the
  name.

For the test channel, repeat at https://test.pypi.org with the same fields
except environment name `testpypi`.

### 2. Create GitHub Environments

On the repo settings page (`github.com/Evilander/claude-design-mcp/settings/environments`):

- Create environment **`pypi`**.
  - Add a required reviewer (yourself) so accidental tag pushes can't
    auto-publish.
  - Optional: restrict deployment to the `master` branch and to tag
    pushes (`Deployment branches and tags → Selected branches and tags`).
- Create environment **`testpypi`** with no required reviewer (so RCs
  publish automatically).

### 3. Confirm Trusted Publisher settings match the workflow

In `release.yml` the `environment:` field is `pypi`. Mismatched
environment names cause a 403 from PyPI at publish time. The fix is to
edit the pending-publisher entry on pypi.org, not the workflow.

## Release cadence

| Tag form     | Channel  | Environment | Manual approval |
|--------------|----------|-------------|-----------------|
| `v0.2.0-rc1` | TestPyPI | `testpypi`  | no              |
| `v0.2.0`     | PyPI     | `pypi`      | yes (required)  |

The `release.yml` workflow ships to PyPI on any `v*` tag. The convention
for RCs is to publish to TestPyPI only. If we ship RCs to PyPI directly,
the manual-approval gate on the `pypi` environment is the safety net.

## Release checklist

Before tagging:

- [ ] `pytest -q` passes (target: ≥ 164 tests, ruff clean).
- [ ] `python -m build` produces wheel + sdist.
- [ ] `python -m twine check dist/*` reports PASSED on both artifacts.
- [ ] `scripts/smoke_mcp_stdio.py` lists ≥ 11 tools from a fresh package
      install.
- [ ] `claude-design-mcp --check-json | python -m json.tool` returns
      `ok: true`.
- [ ] CHANGELOG.md updated for the new version.
- [ ] `pyproject.toml` `version` reflects the tag (or trusted to hatch-vcs
      when we move).

To tag and ship:

```bash
git tag -a v0.2.0 -m "v0.2.0 — DESIGN.md export, nonce CSP, PyPI release"
git push origin v0.2.0
```

Watch the workflow at
`github.com/Evilander/claude-design-mcp/actions`. For `pypi` environment
pushes, you'll receive a "review required" prompt; approve to publish.

## What can fail at the PyPI step

| Symptom | Cause | Fix |
|---|---|---|
| 403 "Trusted publishing rejected" | Owner / repo / workflow / environment mismatch on pypi.org | Edit the pending publisher on pypi.org. |
| "Environment 'pypi' not found" | GH environment not created | Create it in repo settings → environments. |
| `id-token` permission denied | `permissions:` block missing from workflow | Already present in `release.yml`; do not remove. |
| 400 "version already exists" | Tag matches an existing PyPI version | Bump the version. PyPI never accepts re-uploads of the same version. |

## Rollback

Once a version is on PyPI, it cannot be deleted (only yanked). The safe
path is to ship a new version with the fix; yank the broken one only if
it would actively mislead users.

```
# Yank from the PyPI UI: Your projects → claude-design-mcp →
# Manage → Releases → "Yank release"
```
