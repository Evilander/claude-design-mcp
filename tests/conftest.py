"""Shared pytest fixtures.

Tests run against a tmp studio so they never touch the real one. No API key
is needed because the designer routes through the local `claude` CLI's
OAuth session — but actually exercising the network path is out of scope
for unit tests, which only construct ``Designer`` to verify wiring.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_DESIGN_STUDIO_DIR", str(tmp_path / "studio"))
    monkeypatch.setenv("CLAUDE_DESIGN_AUTO_RENDER", "0")
    # Force lazy singletons to re-init against the tmp studio.
    import claude_design.server as srv

    srv._reset_singletons()
    yield
    srv._reset_singletons()
