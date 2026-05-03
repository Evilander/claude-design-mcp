"""Cover the repr fallback in _clamp_metadata for non-JSON-able types."""

from __future__ import annotations

from claude_design.designer import _clamp_metadata


def test_clamp_set_falls_back_to_repr():
    out = _clamp_metadata({1, 2, 3})
    assert isinstance(out, str)
    # A set's repr starts with '{' and contains the elements.
    assert "{" in out


def test_clamp_custom_object_falls_back_to_repr():
    class Weird:
        def __repr__(self) -> str:
            return "Weird()"

    assert _clamp_metadata(Weird()) == "Weird()"


def test_clamp_repr_truncated():
    class Huge:
        def __repr__(self) -> str:
            return "x" * 100_000

    out = _clamp_metadata(Huge())
    assert len(out) <= 8 * 1024
