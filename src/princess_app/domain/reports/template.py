"""Versioned individual-report template: section order, fact grouping and
display precision. Changing it requires a new ``TEMPLATE_VERSION``."""
from __future__ import annotations

BASE_TEMPLATE_VERSION = "individual-report/1"
HIGHLIGHT_TEMPLATE_VERSION = "individual-report/2"
HIGHLIGHT_PRESENTATION_VERSION = "presentation/1"
HIGHLIGHT_POLICY_VERSION = "highlight-policy/1"
# T17 promotes new analyses only after the web client renders every server-owned first-reveal state.
TEMPLATE_VERSION = HIGHLIGHT_TEMPLATE_VERSION
SUPPORTED_TEMPLATE_VERSIONS = frozenset({BASE_TEMPLATE_VERSION, HIGHLIGHT_TEMPLATE_VERSION})

# (section_id, template, feature_ids). Every Free feature appears exactly once;
# tests check this against the engine's registered stages.
FACT_SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("section.sample", "SAMPLE_SUITABILITY", (
        "IMG_WIDTH_PX", "IMG_HEIGHT_PX", "IMG_MEGAPIXELS", "IMG_ASPECT_RATIO", "IMG_ROTATION_DEG",
        "PAGE_LINE_COUNT", "PAGE_WORD_COUNT", "PAGE_COMPONENT_COUNT", "PAGE_INK_AREA_RATIO", "PAGE_TEXT_AREA_RATIO",
    )),
    ("section.size", "METRIC_GRID", (
        "X_HEIGHT_PX", "GLYPH_HEIGHT_MEAN", "GLYPH_HEIGHT_CV", "GLYPH_WIDTH_MEAN", "GLYPH_WIDTH_CV",
        "GLYPH_ASPECT_RATIO_MEAN", "GLYPH_ASPECT_RATIO_CV",
    )),
    ("section.slant", "DISTRIBUTION", (
        "SLANT_ANGLE_MEAN", "SLANT_ANGLE_MEDIAN", "SLANT_ANGLE_STD", "SLANT_P05", "SLANT_P95",
        "SLANT_LEFT_FRACTION", "SLANT_VERTICAL_FRACTION", "SLANT_RIGHT_FRACTION", "SLANT_EXTREME_FRACTION",
        "SLANT_CONSISTENCY",
    )),
    ("section.baseline", "BASELINE_TRACE", (
        "BASELINE_ANGLE_MEAN", "BASELINE_ANGLE_MEDIAN", "BASELINE_ANGLE_STD", "BASELINE_ABS_SLOPE",
        "BASELINE_WAVINESS", "BASELINE_CURVATURE", "BASELINE_STABILITY",
    )),
    ("section.spacing", "SPACING", (
        "LINE_SPACING_PX", "LINE_SPACING_REL", "LINE_SPACING_CV", "WORD_SPACING_PX", "WORD_SPACING_REL",
        "WORD_SPACING_CV",
    )),
    ("section.layout", "PAGE_LAYOUT", (
        "MARGIN_TOP_REL", "MARGIN_BOTTOM_REL", "MARGIN_LEFT_REL", "MARGIN_RIGHT_REL", "MARGIN_LEFT_VARIABILITY",
        "MARGIN_RIGHT_VARIABILITY", "MARGIN_SYMMETRY", "TEXT_BLOCK_HORIZONTAL_CENTER",
        "TEXT_BLOCK_VERTICAL_CENTER", "PAGE_HORIZONTAL_DENSITY", "PAGE_VERTICAL_DENSITY", "LINE_LENGTH_MEAN_REL",
        "LINE_LENGTH_VARIABILITY", "LINE_START_DRIFT", "LINE_END_DRIFT",
    )),
    ("section.ink", "METRIC_GRID", (
        "INK_DARKNESS_MEAN", "INK_DARKNESS_STD", "INK_DARKNESS_CV", "STROKE_WIDTH_MEAN", "STROKE_WIDTH_MEDIAN",
        "STROKE_WIDTH_STD", "STROKE_WIDTH_CV", "STROKE_UNIFORMITY", "INK_SATURATION_FRACTION",
    )),
)

REFERENCE_SECTION = ("section.reference", "REFERENCE")
PREMIUM_SECTION = ("section.premium", "PREMIUM")

# Display precision by canonical unit; formatting keys are ``measurement.<unit>``.
PRECISION_BY_UNIT = {
    "count": 0, "px": 1, "degrees": 1, "MP": 2, "ratio": 2, "cv": 2, "normalized": 3,
    "normalized_slope": 3, "normalized_x": 3, "normalized_y": 3, "score_0_1": 2, "xheight_ratio": 2,
}
DEFAULT_PRECISION = 2


def formatting_for(unit: str | None) -> tuple[str, int | None]:
    if unit is None:
        return "measurement.unitless", DEFAULT_PRECISION
    return f"measurement.{unit}", PRECISION_BY_UNIT.get(unit, DEFAULT_PRECISION)
