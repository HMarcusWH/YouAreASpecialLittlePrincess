"""T10 design tokens: WCAG contrast for every declared pair, theme parity and generated drift."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import generate_design_tokens as generator

TOKENS = json.loads((Path(__file__).resolve().parents[1] / "packages/design-tokens/tokens.json").read_text())


def luminance(hex_color: str) -> float:
    channels = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def pairs():
    rules = TOKENS["contrast"]
    for theme in ("light", "dark"):
        for kind in ("text", "ui"):
            for role in rules[kind]["roles"]:
                for background in rules[kind]["on"]:
                    yield theme, role, background, rules[kind]["minimum"]
        for pair in rules["pairs"]:
            yield theme, pair["fg"], pair["bg"], pair["minimum"]


@pytest.mark.parametrize("theme,role,background,minimum", list(pairs()))
def test_declared_pairs_meet_wcag_contrast(theme, role, background, minimum):
    palette = TOKENS["color"][theme]
    ratio = contrast(palette[role], palette[background])
    assert ratio >= minimum, f"{theme}: {role} on {background} is {ratio:.2f}, needs {minimum}"


def test_contrast_formula_matches_known_values():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)


def test_themes_define_the_same_roles_and_every_evidence_class_is_themed():
    assert TOKENS["color"]["light"].keys() == TOKENS["color"]["dark"].keys()
    for cls in ("measured", "proxy", "reference", "authored", "traditional", "ai"):
        assert f"evidence-{cls}" in TOKENS["color"]["light"]


def test_reduced_motion_zeroes_every_duration_and_generated_files_are_current():
    css = generator.outputs()[generator.OUT / "tokens.css"]
    for name in TOKENS["motion"]["duration"]:
        assert f"--motion-duration-{name}: 0ms;" in css
    assert generator.main(["--check"]) == 0
