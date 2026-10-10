"""Integration tests for graph-paper-v1 and versioned worker fingerprints."""
import hashlib

import numpy as np
import pytest

from grid_cases import specimen
from princess_graphology import GraphologyEngine
from princess_graphology.preprocessing.grid import GridQualityError
from princess_app.application.intake import analysis_config_sha256, engine_config_sha256


def test_job_fingerprint_is_versioned_and_legacy_is_bitwise_stable():
    from princess_app.domain import intake as policy
    legacy = analysis_config_sha256(grid_profile='legacy')
    original = hashlib.sha256(
        f"engine:max_dimension=2200;deskew=true;{policy.INTAKE_POLICY_VERSION}".encode()
    ).hexdigest()
    assert legacy == original
    assert analysis_config_sha256() != legacy
    assert analysis_config_sha256() == engine_config_sha256(GraphologyEngine())
    assert legacy == engine_config_sha256(GraphologyEngine(grid_profile='legacy'))
    with pytest.raises(ValueError, match='unknown grid'):
        analysis_config_sha256(grid_profile='invalid')


def test_grid_mask_drives_line_and_word_detection():
    bgr, _ = specimen(grid='blue')
    result = GraphologyEngine(deskew_enabled=False).analyze(bgr)
    assert result.metadata['grid_preprocessing']['version'] == 'grid-v1'
    assert result.metadata['grid_preprocessing']['status'] == 'cleaned'
    assert result.metadata['word_proposal_input'] == 'grid_suppressed_gray'
    assert 1 <= result.measurements['PAGE_LINE_COUNT'].raw_value <= 3
    assert result.measurements['PAGE_COMPONENT_COUNT'].raw_value < 150


def test_grid_only_and_gray_grid_are_not_valid_handwriting():
    engine = GraphologyEngine(deskew_enabled=False)
    for color, has_ink, expected in (
        ('blue', False, 'no_handwriting_after_grid_removal'),
        ('gray', True, 'grid_ink_separation_ambiguous'),
    ):
        bgr, _ = specimen(grid=color, text=has_ink)
        with pytest.raises(GridQualityError, match=expected):
            engine.analyze(bgr)


def test_plain_input_matches_legacy_measurements():
    bgr, _ = specimen(grid='none')
    default = GraphologyEngine(deskew_enabled=False).analyze(bgr)
    legacy = GraphologyEngine(deskew_enabled=False, grid_profile='legacy').analyze(bgr)
    assert set(default.measurements) == set(legacy.measurements)
    for key in default.measurements:
        assert default.measurements[key].raw_value == legacy.measurements[key].raw_value
    assert default.metadata['input_pixels_sha256'] == legacy.metadata['input_pixels_sha256']


def test_grid_evidence_has_valid_input_lineage():
    bgr, _ = specimen(grid='blue')
    result, bundle = GraphologyEngine(deskew_enabled=False).analyze_with_evidence(bgr)
    assert bundle['input_pixels_sha256'] == result.metadata['input_pixels_sha256']
    assert len(bundle['frames']) == 2
    assert all(r['frame_id'] == 'frame_analysis' for r in bundle['regions'])
    assert len(bundle['observations']) <= 20000
