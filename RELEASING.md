# Releasing claude-design-mcp

This project publishes with GitHub Actions Trusted Publishing. No long-lived
PyPI token is stored in the repo. The workflow is
`.github/workflows/release.yml`.

## One-Time Setup

### PyPI

Create a pending publisher at `https://pypi.org`:

- PyPI project name: `claude-design-mcp`
- Owner: `Evilander`
- Repository name: `claude-design-mcp`
- Workflow filename: `release.yml`
- Environment name: `pypi`

### TestPyPI

Create the matching pending publisher at `https://test.pypi.org`:

- PyPI project name: `claude-design-mcp`
- Owner: `Evilander`
- Repository name: `claude-design-mcp`
- Workflow filename: `release.yml`
- Environment name: `testpypi`

### GitHub Environments

Create these repo environments:

- `testpypi`: for prerelease tags such as `v0.2.0-rc1`.
- `pypi`: for final release tags such as `v0.2.0`.

For `pypi`, require a manual reviewer so an accidental final tag cannot publish
without approval. `testpypi` can stay unreviewed for fast RC validation.

## Channels

| Tag form | Channel | Environment | Approval |
| --- | --- | --- | --- |
| `v0.2.0-rc1` | TestPyPI | `testpypi` | optional |
| `v0.2.0` | PyPI | `pypi` | required |

The workflow routes any tag with a prerelease hyphen, for example `-rc1`, to
TestPyPI. Final `v*` tags without a hyphen route to PyPI.

Manual `workflow_dispatch` runs expose an explicit `repository` input with
`testpypi` as the default.

## Release Checklist

Before tagging:

- [ ] `python -m ruff check src tests scripts` passes.
- [ ] `python -m pytest -q` passes.
- [ ] `python scripts/smoke_mcp_stdio.py` lists the expected MCP tools.
- [ ] `python -m build` produces wheel and sdist artifacts.
- [ ] `python -m twine check dist/*` reports `PASSED`.
- [ ] `claude-design-mcp --check-json` returns `ok: true` for the core server.
- [ ] Release notes or README status are current for the new version.
- [ ] `pyproject.toml` `version` matches the tag.

To tag an RC:

```bash
git tag -a v0.2.0-rc1 -m "v0.2.0-rc1"
git push origin v0.2.0-rc1
```

To tag a final release:

```bash
git tag -a v0.2.0 -m "v0.2.0"
git push origin v0.2.0
```

Watch the workflow at:

```text
https://github.com/Evilander/claude-design-mcp/actions
```

## Common Failures

| Symptom | Cause | Fix |
| --- | --- | --- |
| 403 trusted publishing rejected | Owner, repo, workflow, or environment mismatch | Edit the pending publisher on PyPI/TestPyPI. |
| Environment not found | GitHub environment missing | Create `pypi` or `testpypi` in repo settings. |
| `id-token` permission denied | Publish job lacks OIDC permission | Keep `id-token: write` on publish jobs. |
| Version already exists | Package version was uploaded before | Bump the version; PyPI does not accept reuploads. |

## Rollback

PyPI releases cannot be deleted and reuploaded. If a bad final release lands,
ship a fixed patch version and yank the broken version from the PyPI UI only if
the package would actively mislead users.
