import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from princess_graphology import AnalysisResult, Box, GraphologyEngine, Measurement, Region
from princess_graphology.measurements import IMPLEMENTED_FEATURE_IDS
from princess_graphology.models import DuplicateMeasurementError
from princess_graphology.schema_validation import SchemaContractError, load_contract, validate_measurement

ROOT = Path(__file__).resolve().parents[1]


def measurement(key='PAGE_LINE_COUNT', value=3, unit='count', **kwargs):
    return Measurement(key, value, unit, method_version='test_v1', **kwargs)


def test_full_database_contract_and_emission(page):
    raw = (ROOT / 'schema/graphology_feature_database_v1.json').read_bytes()
    database = json.loads(raw)
    features = {f['id']: f for f in database['features']}
    assert len(features) == len(database['features']) == 272
    assert load_contract()['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert set(load_contract()['features']) == set(features)
    result = GraphologyEngine().analyze(page)
    assert len(result.measurements) == len(IMPLEMENTED_FEATURE_IDS) == 64
    assert set(result.measurements) == set(IMPLEMENTED_FEATURE_IDS)
    for m in result.measurements.values():
        assert m.unit == features[m.feature_id]['unit']
        validate_measurement(m, features[m.feature_id], region_ids={r.region_id for r in result.regions})
    assert not {'LINE_COUNT', 'WORD_COUNT', 'IMAGE_WIDTH_PX', 'PAGE_MARGIN_LEFT'} & result.measurements.keys()


def test_generated_contract_is_fresh_and_generator_rejects_duplicates():
    path = ROOT / 'tools/generate_feature_contract.py'
    spec = importlib.util.spec_from_file_location('contract_generator', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.OUTPUT.read_text() == module.render()
    database = json.loads(module.SOURCE.read_text())
    database['features'].append(database['features'][0])
    with pytest.raises(ValueError, match='duplicate'):
        module.project_database(database)


def test_duplicate_cannot_overwrite():
    result = AnalysisResult('test', 10, 10)
    result.add(measurement())
    with pytest.raises(DuplicateMeasurementError):
        result.add(measurement(value=99))
    assert result.measurements['PAGE_LINE_COUNT'].raw_value == 3


@pytest.mark.parametrize('key,value,unit', [
    ('FOO_BAR_SCORE', 0.4, 'score_0_1'), ('BASELINE_WAVINESS', 17.4, 'pixels'),
    ('PAGE_LINE_COUNT', True, 'count'), ('PAGE_LINE_COUNT', 3.0, 'count'),
    ('PAGE_LINE_COUNT', -1, 'count'), ('INK_DARKNESS_MEAN', 1.1, 'normalized'),
    ('MARGIN_LEFT_REL', -1, 'xheight_ratio'), ('IMG_WIDTH_PX', 0, 'px'),
    ('GLYPH_WIDTH_MEAN', '3', 'px'), ('SLANT_RIGHT_FRACTION', 1.01, 'ratio'),
])
def test_wrong_id_unit_type_or_range_rejected(key, value, unit):
    with pytest.raises(SchemaContractError):
        AnalysisResult('test', 10, 10).add(measurement(key, value, unit))


@pytest.mark.parametrize('kwargs', [
    {'confidence': -0.1}, {'confidence': 1.1}, {'confidence': True},
    {'confidence': 0.5}, {'confidence_kind': 'CALIBRATED'},
    {'n_observations': -1}, {'n_observations': True}, {'n_observations': 0},
    {'std_dev': -1}, {'source_regions': ['a', 'a']}, {'quality_flag': 'FAKE'},
])
def test_bad_structure_rejected(kwargs):
    with pytest.raises(ValueError):
        measurement(**kwargs)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf'), np.float64('nan')])
def test_nonfinite_rejected(value):
    with pytest.raises(ValueError):
        measurement('BASELINE_WAVINESS', value, 'normalized')
    with pytest.raises(ValueError):
        measurement(method_metadata={'nested': [value]})


def test_unknown_confidence_missing_and_numpy_json():
    m = measurement(value=np.int64(2))
    assert m.confidence is None
    assert type(m.raw_value) is int
    missing = measurement(value=None, quality_flag='MISSING', missing_reason='not_detected', n_observations=0)
    validate_measurement(missing)
    with pytest.raises(ValueError):
        measurement(value=None)
    with pytest.raises(ValueError):
        replace(missing, std_dev=0)


def test_units_do_not_all_mean_zero_to_one():
    for key, value, unit in [('BASELINE_WAVINESS', 17.4, 'normalized'),
                             ('GLYPH_ASPECT_RATIO_MEAN', 2.1, 'ratio'),
                             ('WORD_SPACING_CV', 2.0, 'cv')]:
        validate_measurement(measurement(key, value, unit))


def test_full_definition_cannot_override_runtime_unit():
    definition = dict(load_contract()['features']['PAGE_LINE_COUNT'], unit='wrong')
    with pytest.raises(ValueError):
        validate_measurement(measurement(unit='wrong'), definition)


def test_vector_json_and_nonfinite_nested():
    m = measurement('HU_MOMENTS_7', np.arange(7, dtype=float), 'vector_7')
    validate_measurement(m)
    assert isinstance(m.raw_value, list)
    with pytest.raises(ValueError):
        measurement('HU_MOMENTS_7', [0, float('nan')], 'vector_7')


def test_evidence_and_region_integrity():
    with pytest.raises(ValueError):
        validate_measurement(measurement(evidence_status='MADE_UP'))
    r = AnalysisResult('test', 10, 10)
    r.add(measurement(source_regions=['absent']))
    with pytest.raises(ValueError, match='dangling'):
        r.to_json()
    r.regions.append(Region('absent', 'PAGE', Box(0, 0, 10, 10)))
    assert json.loads(r.to_json())['measurements']['PAGE_LINE_COUNT']['raw_value'] == 3
    r.regions.append(r.regions[0])
    with pytest.raises(ValueError, match='duplicate region'):
        r.to_dict()


@pytest.mark.parametrize('regions', [
    [Region('a', 'PAGE', Box(0, 0, 11, 10))],
    [Region('a', 'WORD', Box(0, 0, 2, 2), 'no_parent')],
    [Region('a', 'PAGE', Box(0, 0, 10, 10), 'b'), Region('b', 'PAGE', Box(0, 0, 10, 10), 'a')],
    [Region('a', 'LINE', Box(1, 1, 2, 2)), Region('b', 'WORD', Box(0, 0, 1, 1), 'a')],
    [Region('a', 'PAGE', Box(0, 0, 10, 10), confidence=float('nan'))],
])
def test_bad_regions_rejected(regions):
    with pytest.raises(ValueError):
        AnalysisResult('test', 10, 10, regions=regions).to_dict()


def test_serialization_revalidates_mutations():
    r = AnalysisResult('test', 10, 10)
    r.measurements['wrong_key'] = measurement()
    with pytest.raises(ValueError, match='key mismatch'):
        r.to_dict()
    r.measurements.clear()
    r.metadata['bad'] = float('nan')
    with pytest.raises(ValueError):
        r.to_dict()
