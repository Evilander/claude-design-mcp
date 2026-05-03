"""Pydantic input models for claude-design-mcp tools."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class DesignMode(str, Enum):
    """High-level design intent — drives the system prompt's stylistic posture."""

    LANDING = "landing"          # marketing landing page
    APP_UI = "app_ui"            # product/app surface
    DASHBOARD = "dashboard"      # data-dense dashboard
    EDITORIAL = "editorial"      # long-form magazine layout
    COMPONENT = "component"      # single component / hero / card
    EMAIL = "email"              # HTML email
    AUTO = "auto"                # let Claude pick


class DesignTier(str, Enum):
    """Which Claude tier to use. ``fast`` = Sonnet, ``best`` = Opus."""

    FAST = "fast"
    BEST = "best"


class Viewport(str, Enum):
    MOBILE = "mobile"      # 390x844
    TABLET = "tablet"      # 834x1112
    DESKTOP = "desktop"    # 1440x900
    WIDE = "wide"          # 1920x1080
    HD = "hd"              # 2560x1440


class VariantDimension(str, Enum):
    """Axis to explore when generating variants."""

    COLOR = "color"              # different palettes, same structure
    LAYOUT = "layout"            # different compositions
    TYPOGRAPHY = "typography"    # different type systems
    MOOD = "mood"                # serious vs playful vs editorial vs brutalist
    DENSITY = "density"          # spacious vs compact
    ANY = "any"                  # let Claude vary across whichever axes it wants


# Design IDs are 12-char hex strings (uuid4().hex[:12]); reject anything that
# couldn't possibly be one. Same pattern for system_id.
_ID_PATTERN = r"^[a-f0-9]{6,32}$"
_ID_RE = re.compile(_ID_PATTERN)

_AUTO_RENDER_DESC = (
    "Override the global auto-render setting for this call. None = use env."
)


# ---- Tool inputs ----------------------------------------------------------


class DesignCreateInput(BaseModel):
    """Generate a brand-new design from a natural-language brief."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    brief: str = Field(
        ...,
        description=(
            "A vivid description of the design. Include audience, emotional tone, "
            "key content, brand keywords, and any constraints. "
            "Example: 'Hero section for a privacy-focused note app — dark mode, "
            "glassmorphism, primary CTA \"Start writing\", mention end-to-end encryption.'"
        ),
        min_length=8,
        max_length=4000,
    )
    mode: DesignMode = Field(default=DesignMode.AUTO, description="Design surface type.")
    tier: DesignTier = Field(
        default=DesignTier.FAST,
        description="`fast` (Sonnet, ~5-15s) or `best` (Opus, slower but more ambitious).",
    )
    viewport: Viewport = Field(default=Viewport.DESKTOP, description="Primary viewport for the screenshot.")
    name: str | None = Field(
        default=None,
        description="Optional short name to remember this design by (kebab-case recommended).",
        max_length=64,
    )
    references: list[str] = Field(
        default_factory=list,
        description="Optional list of design IDs whose style/tokens should inform this one.",
        max_length=5,
    )
    auto_render: bool | None = Field(default=None, description=_AUTO_RENDER_DESC)

    # str_strip_whitespace=True + min_length=8 already reject empty/whitespace
    # briefs, so no separate validator is needed for `brief`.

    @field_validator("references")
    @classmethod
    def _validate_refs(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if not _ID_RE.fullmatch(r)]
        if bad:
            raise ValueError(
                f"reference IDs must be hex-only and 6-32 chars; got {bad}"
            )
        return v


class DesignIterateInput(BaseModel):
    """Refine an existing design with new instructions, creating a child version."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    design_id: str = Field(
        ...,
        description="ID of the parent design to refine.",
        pattern=_ID_PATTERN,
    )
    instructions: str = Field(
        ...,
        description=(
            "What to change. Be specific about what to keep and what to alter. "
            "Example: 'Keep the layout, but make the CTA gradient more vivid and "
            "add a subtle typewriter effect on the headline.'"
        ),
        min_length=4,
        max_length=2000,
    )
    tier: DesignTier = Field(default=DesignTier.FAST)
    auto_render: bool | None = Field(default=None, description=_AUTO_RENDER_DESC)


class DesignVariantsInput(BaseModel):
    """Generate N parallel variants of a design exploring a single dimension."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    design_id: str | None = Field(
        default=None,
        description="If set, variants branch from this design. If omitted, `brief` is required.",
        pattern=_ID_PATTERN,
    )
    brief: str | None = Field(
        default=None,
        description="If `design_id` is omitted, generate variants directly from this brief.",
        max_length=4000,
    )
    dimension: VariantDimension = Field(
        default=VariantDimension.ANY,
        description="Which axis the variants should explore.",
    )
    count: int = Field(
        default=3,
        description="Number of variants to generate in parallel (1-6).",
        ge=1,
        le=6,
    )
    tier: DesignTier = Field(default=DesignTier.FAST)
    auto_render: bool | None = Field(default=None, description=_AUTO_RENDER_DESC)

    @model_validator(mode="after")
    def _require_one(self) -> "DesignVariantsInput":
        if not self.design_id and not self.brief:
            raise ValueError("Provide either design_id (to branch) or brief (to start fresh).")
        return self


class DesignRenderInput(BaseModel):
    """Render (or re-render) a design's HTML to a screenshot at a chosen viewport."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    design_id: str = Field(..., description="ID of the design to render.", pattern=_ID_PATTERN)
    viewport: Viewport = Field(default=Viewport.DESKTOP)
    full_page: bool = Field(
        default=True,
        description="Capture the full scrollable page, not just the viewport.",
    )


class DesignGetInput(BaseModel):
    """Retrieve a design's full record, optionally including raw HTML."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    design_id: str = Field(..., description="ID of the design to retrieve.", pattern=_ID_PATTERN)
    include_html: bool = Field(
        default=False,
        description="If true, include the full HTML in the response (can be large).",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class DesignListInput(BaseModel):
    """List recent designs in the studio, with optional filtering."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    name_contains: str | None = Field(
        default=None,
        description="Filter by substring in the design's name.",
        max_length=128,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class DesignExtractSystemInput(BaseModel):
    """Extract a coherent design system (tokens) from one or more designs."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    design_ids: list[str] = Field(
        ...,
        description="One or more design IDs to analyze for shared tokens.",
        min_length=1,
        max_length=10,
    )
    name: str | None = Field(
        default=None,
        description="Optional name for the extracted system.",
        max_length=64,
    )
    tier: DesignTier = Field(default=DesignTier.FAST)

    @field_validator("design_ids")
    @classmethod
    def _validate_ids(cls, v: list[str]) -> list[str]:
        bad = [r for r in v if not _ID_RE.fullmatch(r)]
        if bad:
            raise ValueError(f"design_ids must be hex-only 6-32 chars; got {bad}")
        return v


class DesignApplySystemInput(BaseModel):
    """Apply a previously extracted design system's tokens to a new brief."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    system_id: str = Field(
        ..., description="ID of the design system to apply.", pattern=_ID_PATTERN
    )
    brief: str = Field(
        ...,
        description="Brief for the new design that should follow the system.",
        min_length=8,
        max_length=4000,
    )
    mode: DesignMode = Field(default=DesignMode.AUTO)
    tier: DesignTier = Field(default=DesignTier.FAST)
    auto_render: bool | None = Field(default=None, description=_AUTO_RENDER_DESC)


class DesignExportInput(BaseModel):
    """Export a design (or design system) as portable files."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    design_id: str | None = Field(
        default=None, description="Design to export.", pattern=_ID_PATTERN
    )
    system_id: str | None = Field(
        default=None, description="Design system to export.", pattern=_ID_PATTERN
    )
    target_dir: str | None = Field(
        default=None,
        description=(
            "Absolute path of directory to write into. Must not be a system "
            "directory. Defaults to studio/exports/."
        ),
        max_length=1024,
    )

    @model_validator(mode="after")
    def _require_one(self) -> "DesignExportInput":
        if not self.design_id and not self.system_id:
            raise ValueError("Provide design_id or system_id.")
        if self.design_id and self.system_id:
            raise ValueError("Provide design_id or system_id, not both.")
        return self


class DesignPreviewInput(BaseModel):
    """Get file:// URLs for previewing designs in a browser."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    design_id: str | None = Field(
        default=None,
        description="Specific design to preview. If omitted, returns a contact-sheet of recent designs.",
        pattern=_ID_PATTERN,
    )
    rebuild_index: bool = Field(
        default=True,
        description="Regenerate the contact-sheet index page before returning its URL.",
    )
