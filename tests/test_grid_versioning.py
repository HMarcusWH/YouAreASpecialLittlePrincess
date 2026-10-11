"""Integration tests for graph-paper-v1 and versioned worker fingerprints."""
import hashlib

import pytest

from grid_cases import specimen
from princess_graphology import GraphologyEngine
from princess_graphology.preprocessing.grid import GridQualityError
from princess_app.application.intake import (
    ANALYSIS_CONFIG_SHA256, analysis_config_sha256, engine_config_sha256,
    runtime_analysis_profile_and_config,
)


def test_job_fingerprint_is_versioned_and_legacy_is_bitwise_stable():
    from princess_app.domain import intake as policy
    legacy = analysis_config_sha256(grid_profile='legacy')
    original = hashlib.sha256(
        f"engine:max_dimension=2200;deskew=true;{policy.INTAKE_POLICY_VERSION}".encode()
    ).hexdigest()
    assert legacy == original
    assert analysis_config_sha256() == legacy == ANALYSIS_CONFIG_SHA256
    assert analysis_config_sha256(grid_profile='grid-v1') != legacy
    assert analysis_config_sha256() == engine_config_sha256(GraphologyEngine())
    assert legacy == engine_config_sha256(GraphologyEngine(grid_profile='legacy'))
    with pytest.raises(ValueError, match='unknown grid'):
        analysis_config_sha256(grid_profile='invalid')


def test_grid_mask_drives_line_and_word_detection():
    bgr, _ = specimen(grid='blue')
    result = GraphologyEngine(deskew_enabled=False, grid_profile='grid-v1').analyze(bgr)
    assert result.metadata['grid_preprocessing']['version'] == 'grid-v1'
    assert result.metadata['grid_preprocessing']['status'] in ('cleaned', 'detected_no_contamination')
    assert result.metadata['word_proposal_input'] == 'grid_suppressed_gray'
    assert 1 <= result.measurements['PAGE_LINE_COUNT'].raw_value <= 3
    assert result.measurements['PAGE_COMPONENT_COUNT'].raw_value < 150


def test_grid_only_and_gray_grid_are_not_valid_handwriting():
    engine = GraphologyEngine(deskew_enabled=False, grid_profile='grid-v1')
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
    result, bundle = GraphologyEngine(deskew_enabled=False, grid_profile='grid-v1').analyze_with_evidence(bgr)
    assert bundle['input_pixels_sha256'] == result.metadata['input_pixels_sha256']
    assert len(bundle['frames']) == 2
    assert all(r['frame_id'] == 'frame_analysis' for r in bundle['regions'])
    assert len(bundle['observations']) <= 20000

def test_runtime_default_and_pinned_private_evaluation_configuration():
    assert runtime_analysis_profile_and_config({}) == ('legacy', ANALYSIS_CONFIG_SHA256)
    assert runtime_analysis_profile_and_config({'PRINCESS_ENV': 'production'}) == (
        'legacy', ANALYSIS_CONFIG_SHA256)
    env = {'PRINCESS_ENV': 'test', 'PRINCESS_ANALYSIS_PROFILE': 'grid-v1',
           'PRINCESS_GRID_V1_RESEARCH_OPT_IN': '1'}
    candidate = analysis_config_sha256(grid_profile='grid-v1')
    assert runtime_analysis_profile_and_config(env) == ('grid-v1', candidate)
    assert engine_config_sha256(GraphologyEngine(grid_profile='grid-v1')) == candidate
    assert runtime_analysis_profile_and_config({
        **env, 'PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256': candidate,
    }) == ('grid-v1', candidate)
    with pytest.raises(ValueError, match='analysis_config_mismatch'):
        runtime_analysis_profile_and_config({
            **env, 'PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256': ANALYSIS_CONFIG_SHA256,
        })


@pytest.mark.parametrize('env', [
    {'PRINCESS_ANALYSIS_PROFILE': 'grid-v1',
     'PRINCESS_GRID_V1_RESEARCH_OPT_IN': '1'},
    {'PRINCESS_ENV': 'test', 'PRINCESS_ANALYSIS_PROFILE': 'grid-v1'},
    {'PRINCESS_ENV': 'staging', 'PRINCESS_ANALYSIS_PROFILE': 'grid-v1',
     'PRINCESS_GRID_V1_RESEARCH_OPT_IN': '1'},
    {'PRINCESS_ENV': 'production', 'PRINCESS_ANALYSIS_PROFILE': 'grid-v1',
     'PRINCESS_GRID_V1_RESEARCH_OPT_IN': '1'},
    {'PRINCESS_ENV': 'test', 'PRINCESS_ANALYSIS_PROFILE': 'grid-v1',
     'PRINCESS_GRID_V1_RESEARCH_OPT_IN': '1', 'PRINCESS_TEST_PUBLIC_GUEST_ONLY': '1'},
    {'PRINCESS_ENV': 'test', 'PRINCESS_ANALYSIS_PROFILE': ''},
    {'PRINCESS_ENV': 'test', 'PRINCESS_ANALYSIS_PROFILE': 'grid-v2'},
])
def test_invalid_or_public_grid_profile_fails_closed(env):
    with pytest.raises(ValueError, match='grid-v1|unknown grid'):
        runtime_analysis_profile_and_config(env)

def test_qualified_v2_fingerprint_is_separate_and_never_public_by_default():
    old = analysis_config_sha256()
    previous_grid = analysis_config_sha256(grid_profile='grid-v1')
    v2 = analysis_config_sha256(grid_profile='qualified-v2')
    assert len({old, previous_grid, v2}) == 3
    assert engine_config_sha256(GraphologyEngine(grid_profile='qualified-v2')) == v2
    research = {'PRINCESS_ENV': 'test', 'PRINCESS_ANALYSIS_PROFILE': 'qualified-v2',
                'PRINCESS_SEGMENTATION_V2_RESEARCH_OPT_IN': '1'}
    assert runtime_analysis_profile_and_config(research) == ('qualified-v2', v2)
    for forbidden in (
        {**research, 'PRINCESS_ENV': 'production'},
        {**research, 'PRINCESS_ENV': 'staging'},
        {**research, 'PRINCESS_TEST_PUBLIC_GUEST_ONLY': '1'},
        {'PRINCESS_ENV': 'test', 'PRINCESS_ANALYSIS_PROFILE': 'qualified-v2'},
        {**research, 'PRINCESS_EXPECTED_ANALYSIS_CONFIG_SHA256': old},
    ):
        with pytest.raises(ValueError):
            runtime_analysis_profile_and_config(forbidden)
