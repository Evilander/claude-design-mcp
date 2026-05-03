"""Pydantic input-validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_design.models import (
    DesignCreateInput,
    DesignExportInput,
    DesignIterateInput,
    DesignVariantsInput,
    DesignMode,
    DesignTier,
    Viewport,
    VariantDimension,
)


def test_create_requires_brief():
    with pytest.raises(ValidationError):
        DesignCreateInput()  # type: ignore[call-arg]


def test_create_rejects_empty_brief_after_strip():
    with pytest.raises(ValidationError):
        DesignCreateInput(brief="   ")


def test_create_strips_brief_whitespace():
    inp = DesignCreateInput(brief="  hello world  ")
    assert inp.brief == "hello world"


def test_create_default_mode_is_auto():
    inp = DesignCreateInput(brief="design something nice")
    assert inp.mode is DesignMode.AUTO
    assert inp.tier is DesignTier.FAST
    assert inp.viewport is Viewport.DESKTOP


def test_create_rejects_unknown_field():
    with pytest.raises(ValidationError):
        DesignCreateInput(brief="x" * 20, surprise="hi")  # type: ignore[call-arg]


def test_iterate_requires_design_id_and_instructions():
    # design_id alone (no instructions) must fail; design_id is also pattern-checked.
    with pytest.raises(ValidationError):
        DesignIterateInput(design_id="abc123def456")  # type: ignore[call-arg]


def test_variants_count_bounds():
    with pytest.raises(ValidationError):
        DesignVariantsInput(brief="x" * 10, count=0)
    with pytest.raises(ValidationError):
        DesignVariantsInput(brief="x" * 10, count=99)
    DesignVariantsInput(brief="x" * 10, count=3)  # valid


def test_variants_dimension_default():
    inp = DesignVariantsInput(brief="x" * 10)
    assert inp.dimension is VariantDimension.ANY


def test_export_accepts_either_id():
    DesignExportInput(design_id="abc123def456")
    DesignExportInput(system_id="abc123def456")
    # Both empty must now raise — model_validator enforces it.
    with pytest.raises(ValidationError):
        DesignExportInput()


def test_create_truncates_references_to_five():
    with pytest.raises(ValidationError):
        DesignCreateInput(brief="x" * 10, references=["a"] * 6)
