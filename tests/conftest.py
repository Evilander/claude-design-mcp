"""Shared pytest fixtures.

Tests run against a tmp studio so they never touch the real one. We set a
sentinel ANTHROPIC_API_KEY because importing the server module is fine without
one — the Designer is constructed lazily — but a few tests instantiate it.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.setenv("CLAUDE_DESIGN_AUTO_RENDER", "0")
    # Force lazy singletons to re-init against the tmp studio.
    import claude_design.server as srv

    srv._reset_singletons()
    yield
    srv._reset_singletons()
