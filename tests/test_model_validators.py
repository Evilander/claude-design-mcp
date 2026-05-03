"""Tests for new Pydantic model validators (XOR fields + ID pattern)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_design.models import (
    DesignExportInput,
    DesignGetInput,
    DesignIterateInput,
    DesignVariantsInput,
)


_VALID_ID = "abc123def456"


def test_export_requires_one_field():
    with pytest.raises(ValidationError, match="design_id or system_id"):
        DesignExportInput()


def test_export_rejects_both_fields():
    with pytest.raises(ValidationError, match="not both"):
        DesignExportInput(design_id=_VALID_ID, system_id=_VALID_ID)


def test_export_accepts_design_id_only():
    DesignExportInput(design_id=_VALID_ID)


def test_export_accepts_system_id_only():
    DesignExportInput(system_id=_VALID_ID)


def test_variants_requires_id_or_brief():
    with pytest.raises(ValidationError, match="design_id .* brief"):
        DesignVariantsInput()


def test_variants_accepts_design_id_only():
    DesignVariantsInput(design_id=_VALID_ID)


def test_variants_accepts_brief_only():
    DesignVariantsInput(brief="x" * 20)


def test_design_id_pattern_rejects_traversal():
    with pytest.raises(ValidationError):
        DesignGetInput(design_id="../../etc/passwd")


def test_design_id_pattern_rejects_short():
    with pytest.raises(ValidationError):
        DesignGetInput(design_id="abc")


def test_design_id_pattern_rejects_uppercase():
    # IDs are produced lowercase via uuid4().hex; uppercase is suspicious.
    with pytest.raises(ValidationError):
        DesignGetInput(design_id="ABCDEF123456")


def test_design_id_pattern_accepts_valid():
    inp = DesignGetInput(design_id=_VALID_ID)
    assert inp.design_id == _VALID_ID


def test_iterate_id_pattern_enforced():
    with pytest.raises(ValidationError):
        DesignIterateInput(design_id="bad", instructions="do X")
