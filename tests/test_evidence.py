"""T05 evidence payload: observations reproduce aggregates, frames round-trip,
and the EvidenceBundle contract rejects broken links."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import cv2
import numpy as np
import pytest

from princess_app.domain.analysis import analysis_reference
from princess_app.domain.evidence import build_evidence_bundle, map_point, prepend_source_frame
from princess_graphology import GraphologyEngine, __version__
from princess_graphology import evidence as core_evidence

LINES = ['special little princess writes', 'handwriting analysis is fun',
         'deterministic measurements only', 'the quick brown fox jumps']


def page(angle=4.0, size=(600, 1400)):
    image = np.full(size, 245, np.uint8)
    for i, text in enumerate(LINES):
        cv2.putText(image, text, (40, 110 + i * 120), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 2.0, 20, 3, cv2.LINE_AA)
    if angle:
        matrix = cv2.getRotationMatrix2D((size[1] / 2, size[0] / 2), angle, 1.0)
        image = cv2.warpAffine(image, matrix, (size[1], size[0]), borderValue=245)
    return image


@pytest.fixture(scope="module")
def analyzed():
    image = page()
    original = image.copy()
    result, payload = GraphologyEngine(max_dimension=900).analyze_with_evidence(image)
    assert np.array_equal(image, original), "evidence collection must not mutate the input image"
    return image, result, payload


def accepted(payload, feature_id):
    return [o['value'] for o in payload['observations'] if o['feature_id'] == feature_id and o['accepted']]


def reference(**overrides):
    values = dict(analysis_id="analysis_1", run_id="run_1", owner_id="owner_1", input_asset_id="asset_1",
                  input_sha256="0" * 64, processed_sha256="1" * 64,
                  created_at=datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc), engine_version=__version__,
                  analysis_config_sha256="2" * 64)
    values.update(overrides)
    return analysis_reference(**values)


def test_aggregate_output_is_unchanged_by_evidence_collection(analyzed):
    image, result, _ = analyzed
    assert result.to_json() == GraphologyEngine(max_dimension=900).analyze(image).to_json()


def test_observations_reproduce_the_canonical_aggregates(analyzed):
    _, result, payload = analyzed
    m = result.measurements
    for feature_id, reducer in (('SLANT_ANGLE_MEAN', np.mean), ('BASELINE_ANGLE_MEAN', np.mean),
                                ('LINE_SPACING_PX', np.mean), ('GLYPH_HEIGHT_MEAN', np.mean),
                                ('GLYPH_WIDTH_MEAN', np.mean), ('X_HEIGHT_PX', np.median)):
        values = accepted(payload, feature_id)
        assert values, feature_id
        assert float(reducer(values)) == pytest.approx(m[feature_id].raw_value, rel=1e-12), feature_id
        assert len(values) == m[feature_id].n_observations, feature_id
    slant = accepted(payload, 'SLANT_ANGLE_MEAN')
    assert float(np.percentile(slant, 95)) == pytest.approx(m['SLANT_P95'].raw_value)
    assert float(np.mean(np.asarray(slant) > 5)) == pytest.approx(m['SLANT_RIGHT_FRACTION'].raw_value)


def test_rejected_observations_carry_reasons_and_are_excluded(analyzed):
    _, result, payload = analyzed
    rejected = [o for o in payload['observations'] if not o['accepted']]
    assert rejected and all(o['rejection_reason'] for o in rejected)
    assert {o['rejection_reason'] for o in rejected} <= {'not_elongated', 'outside_accepted_range',
                                                          'overlapping_boxes'}
    excluded = result.measurements['LINE_SPACING_PX'].method_metadata['excluded_overlapping_pairs']
    assert excluded == sum(1 for o in rejected if o['feature_id'] == 'LINE_SPACING_PX')


def test_bundle_compiles_and_is_deterministic(analyzed):
    image, _, payload = analyzed
    bundle = build_evidence_bundle(payload, reference(), "evidence_1")
    assert bundle.ok, bundle.issues[:3]
    again = GraphologyEngine(max_dimension=900).analyze_with_evidence(image)[1]
    assert build_evidence_bundle(again, reference(), "evidence_1").value.digest == bundle.value.digest
    data = bundle.value.to_dict()
    assert data['frames'][0]['frame_id'] == core_evidence.INPUT_FRAME
    assert all(o['method_version'] == '1.0.0' for o in data['observations'])
    assert core_evidence.PAGE_WARNING in data['warnings']


def test_baseline_points_round_trip_to_ink_in_the_input_image(analyzed):
    image, _, payload = analyzed
    frames = payload['frames']
    points = [r for r in payload['regions'] if r['scope'] == 'BASELINE_POINT']
    assert len(points) >= 20
    scale = frames[0]['width'] / frames[1]['width']
    radius = int(np.ceil(2 * max(scale, 1)))
    hits = 0
    for region in points:
        x, y = map_point(frames, core_evidence.ANALYSIS_FRAME, core_evidence.INPUT_FRAME,
                         region['x'], region['y'])
        xi, yi = int(round(x)), int(round(y))
        window = image[max(0, yi - radius):yi + radius + 1, max(0, xi - radius):xi + radius + 1]
        hits += int(window.size > 0 and window.min() < 128)
    assert hits / len(points) >= 0.9


def test_perspective_source_frame_composes_and_inverts(analyzed):
    _, _, payload = analyzed
    homography = [1.02, 0.03, 15.0, -0.01, 0.98, 40.0, 0.00002, 0.00001, 1.0]
    frames = prepend_source_frame(payload['frames'], frame_id='frame_upload', width=1600, height=900,
                                  root_to_new_parent=homography)
    x, y = 123.0, 77.0
    via_input = map_point(frames, core_evidence.ANALYSIS_FRAME, core_evidence.INPUT_FRAME, x, y)
    h = np.asarray(homography).reshape(3, 3)
    expected = h @ np.array([*via_input, 1.0])
    got = map_point(frames, core_evidence.ANALYSIS_FRAME, 'frame_upload', x, y)
    assert got == pytest.approx(tuple(expected[:2] / expected[2]))
    full = np.asarray(frames[2]['transform_to_parent']).reshape(3, 3)
    back = np.linalg.inv(h @ full) @ np.array([*got, 1.0])
    assert tuple(back[:2] / back[2]) == pytest.approx((x, y), abs=1e-9)
    assert build_evidence_bundle({**payload, 'frames': frames}, reference(), 'evidence_2').ok


def test_blank_image_yields_honest_empty_evidence():
    result, payload = GraphologyEngine().analyze_with_evidence(np.full((80, 120), 255, np.uint8))
    assert payload['observations'] == []
    assert any('No repeated observations' in w for w in payload['warnings'])
    assert build_evidence_bundle(payload, reference(), 'evidence_blank').ok


def test_region_budget_truncates_deterministically(monkeypatch, analyzed):
    image, _, _ = analyzed
    monkeypatch.setattr(core_evidence, 'MAX_REGIONS', 20)
    _, payload = GraphologyEngine(max_dimension=900).analyze_with_evidence(image)
    assert len(payload['regions']) == 20
    assert any(w.startswith('region budget reached') for w in payload['warnings'])
    kept = {r['region_id'] for r in payload['regions']}
    assert all(set(o['region_ids']) <= kept for o in payload['observations'])
    assert build_evidence_bundle(payload, reference(), 'evidence_small').ok


def mutated(payload, fn):
    copy = json.loads(json.dumps(payload))
    fn(copy)
    return copy


@pytest.mark.parametrize("mutation,code", [
    (lambda p: p['regions'].append({**p['regions'][1], 'region_id': 'x_frame', 'frame_id': 'frame_input'}),
     'REGION_PARENT_FRAME_MISMATCH'),
    (lambda p: p['regions'].append({**p['regions'][1], 'region_id': 'too_big', 'width': 99999}),
     'REGION_OUT_OF_BOUNDS'),
    (lambda p: p['observations'][0].update(region_ids=['nowhere']), 'UNKNOWN_OBSERVATION_REGION'),
    (lambda p: p['observations'][0].update(unit='px'), 'WRONG_UNIT'),
    (lambda p: p['observations'][0].update(accepted=False, rejection_reason=None), 'REJECTED_WITHOUT_REASON'),
    (lambda p: p['frames'].append({**p['frames'][0], 'frame_id': 'second_root'}), 'FRAME_ROOT_COUNT'),
    (lambda p: p['observations'].append(dict(p['observations'][0])), 'DUPLICATE_OBSERVATION'),
])
def test_contract_rejects_broken_evidence(analyzed, mutation, code):
    _, _, payload = analyzed
    result = build_evidence_bundle(mutated(payload, mutation), reference(), 'evidence_bad')
    assert result.value is None and code in {i.code for i in result.issues}


def test_nonfinite_values_invalid_links_and_versions_are_rejected(analyzed):
    _, _, payload = analyzed
    bad = mutated(payload, lambda p: None)
    bad['observations'][0]['value'] = float('nan')
    assert build_evidence_bundle(bad, reference(), 'e').value is None
    drift = reference()
    drift['versions']['method_manifest'] = 'f' * 64
    assert 'METHOD_MANIFEST_DRIFT' in {i.code for i in build_evidence_bundle(payload, drift, 'e').issues}
    unknown = mutated(payload, lambda p: p['observations'][0].update(method_id='learned_magic_v1'))
    assert build_evidence_bundle(unknown, reference(), 'e').issues[0].code == 'UNKNOWN_METHOD'
    old = mutated(payload, lambda p: p.update(evidence_version='evidence/0'))
    assert build_evidence_bundle(old, reference(), 'e').issues[0].code == 'EVIDENCE_PAYLOAD_VERSION'


def test_nonfinite_observation_values_are_never_emitted():
    assert core_evidence._observation('o', 'SLANT_ANGLE_MEAN', 'm', [], float('inf')) is None
    assert core_evidence._observation('o', 'SLANT_ANGLE_MEAN', 'm', [], True) is None


def test_context_arrays_are_read_only():
    from princess_graphology.context import prepare_context
    ctx = prepare_context(page(angle=0, size=(300, 700)))
    for array in (ctx.gray, ctx.mask, ctx.labels):
        with pytest.raises(ValueError):
            array[0, 0] = 1
