"""Runtime contract projected from the authoritative 272-feature database."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from importlib.resources import files

from .models import json_value


class SchemaContractError(ValueError):
    pass


@lru_cache(maxsize=1)
def load_contract():
    return json.loads(files('princess_graphology').joinpath('_feature_contract.json').read_text('utf-8'))


def _require(condition, message):
    if not condition:
        raise SchemaContractError(message)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_structure(m):
    _require(isinstance(m.feature_id, str) and bool(m.feature_id), 'feature_id is required')
    _require(type(m.n_observations) is int and m.n_observations >= 0, 'invalid n_observations')
    _require(m.confidence is None or (_number(m.confidence) and 0 <= m.confidence <= 1),
             'confidence must be null or in [0, 1]')
    _require(m.confidence_kind in ('UNCALIBRATED', 'EXACT_CONDITIONAL', 'CALIBRATED'),
             'invalid confidence_kind')
    _require((m.confidence is None) == (m.confidence_kind == 'UNCALIBRATED'),
             'numeric confidence requires an explicit confidence_kind')
    _require(m.std_dev is None or (_number(m.std_dev) and m.std_dev >= 0), 'invalid std_dev')
    _require(isinstance(m.method_version, str) and m.method_version not in ('', 'unspecified'),
             'method_version must name an implemented method')
    _require(isinstance(m.source_regions, list) and
             all(isinstance(x, str) and x for x in m.source_regions), 'invalid source_regions')
    _require(len(m.source_regions) == len(set(m.source_regions)), 'duplicate source_regions')
    _require(isinstance(m.notes, list) and all(isinstance(x, str) for x in m.notes), 'invalid notes')
    _require(isinstance(m.method_metadata, dict), 'method_metadata must be an object')
    _require(m.quality_flag in ('OK', 'EXPERIMENTAL', 'MISSING'), 'invalid quality_flag')
    if m.raw_value is None:
        _require(m.quality_flag == 'MISSING' and isinstance(m.missing_reason, str)
                 and bool(m.missing_reason.strip()), 'null value requires a missing reason')
        _require(m.normalized_value is None and m.std_dev is None and m.confidence is None,
                 'missing measurement cannot carry numeric estimates or confidence')
    else:
        _require(m.quality_flag != 'MISSING' and m.missing_reason is None,
                 'present value cannot be marked missing')
        _require(m.n_observations > 0, 'present value needs at least one observation')
    json_value(m.to_dict())


def _numeric_tree(value):
    if _number(value):
        return True
    if isinstance(value, list):
        return bool(value) and all(_numeric_tree(v) for v in value)
    if isinstance(value, dict):
        return bool(value) and all(isinstance(k, str) and _numeric_tree(v) for k, v in value.items())
    return False


def validate_measurement(m, feature_definition=None, *, region_ids=None):
    validate_structure(m)
    contract = load_contract()
    _require(m.feature_id in contract['features'], f'UNKNOWN FEATURE ID: {m.feature_id}')
    definition = contract['features'][m.feature_id] if feature_definition is None else feature_definition
    _require(definition.get('id', m.feature_id) == m.feature_id, 'feature definition ID mismatch')
    for field in ('unit', 'data_type', 'scope', 'input_mode'):
        _require(definition[field] == contract['features'][m.feature_id][field],
                 'feature definition disagrees with packaged canonical contract')
    _require(m.unit == definition['unit'], f'{m.feature_id}: expected unit {definition["unit"]!r}')
    _require(m.evidence_status in contract['evidence_status'], 'unknown evidence_status')
    if region_ids is not None:
        _require(set(m.source_regions) <= set(region_ids), f'{m.feature_id}: dangling source region')
    if m.raw_value is None:
        return
    value = m.raw_value
    valid = {
        'FLOAT': lambda: _number(value),
        'INT': lambda: type(value) is int,
        'BOOL': lambda: type(value) is bool,
        'ENUM': lambda: isinstance(value, str) and bool(value),
        'VECTOR': lambda: isinstance(value, list) and _numeric_tree(value),
        'DISTRIBUTION': lambda: isinstance(value, (list, dict)) and _numeric_tree(value),
    }
    _require(definition['data_type'] in valid and valid[definition['data_type']](),
             f'{m.feature_id}: incompatible data type')
    if not _number(value):
        return
    # Units alone do not imply a [0,1] range: waviness and aspect ratios can exceed 1.
    if definition['unit'] in ('px', 'MP', 'count', 'cv', 'xheight_ratio'):
        _require(value >= 0, f'{m.feature_id}: negative magnitude')
    if definition['unit'] in ('score_0_1', 'normalized_x', 'normalized_y'):
        _require(0 <= value <= 1, f'{m.feature_id}: outside [0,1]')
    bounded = {'PAGE_INK_AREA_RATIO', 'PAGE_TEXT_AREA_RATIO', 'PAGE_HORIZONTAL_DENSITY',
               'PAGE_VERTICAL_DENSITY', 'LINE_LENGTH_MEAN_REL', 'INK_DARKNESS_MEAN',
               'INK_DARKNESS_STD', 'INK_SATURATION_FRACTION'}
    if m.feature_id in bounded or m.feature_id.startswith('SLANT_') and m.feature_id.endswith('_FRACTION'):
        _require(0 <= value <= 1, f'{m.feature_id}: outside [0,1]')
    if m.feature_id in ('IMG_WIDTH_PX', 'IMG_HEIGHT_PX', 'IMG_MEGAPIXELS', 'IMG_ASPECT_RATIO', 'X_HEIGHT_PX'):
        _require(value > 0, f'{m.feature_id}: must be positive')
    if m.feature_id.endswith('_STD') or m.feature_id in ('BASELINE_ABS_SLOPE', 'BASELINE_WAVINESS', 'BASELINE_CURVATURE'):
        _require(value >= 0, f'{m.feature_id}: negative dispersion')


def validate_result(result):
    _require(type(result.width) is int and result.width > 0, 'invalid result width')
    _require(type(result.height) is int and result.height > 0, 'invalid result height')
    _require(isinstance(result.source, str), 'source must be a string')
    regions = {r.region_id: r for r in result.regions}
    _require(len(regions) == len(result.regions), 'duplicate region IDs')
    for r in result.regions:
        _require(isinstance(r.region_id, str) and bool(r.region_id), 'invalid region ID')
        _require(r.scope in ('SAMPLE', 'PAGE', 'LINE', 'WORD', 'GLYPH', 'STROKE', 'SIGNATURE', 'COMPONENT'),
                 'invalid region scope')
        _require(r.box.x2 <= result.width and r.box.y2 <= result.height, 'region outside analysis canvas')
        _require(r.confidence is None or (_number(r.confidence) and 0 <= r.confidence <= 1), 'invalid region confidence')
        seen = {r.region_id}
        current = r
        while current.parent_id is not None:
            _require(current.parent_id in regions and current.parent_id not in seen, 'invalid/cyclic region parent')
            parent = regions[current.parent_id]
            _require(parent.box.x <= current.box.x and parent.box.y <= current.box.y
                     and parent.box.x2 >= current.box.x2 and parent.box.y2 >= current.box.y2,
                     'child region lies outside parent')
            seen.add(parent.region_id)
            current = parent
    for key, measurement in result.measurements.items():
        _require(key == measurement.feature_id, 'measurement dictionary key mismatch')
        validate_measurement(measurement, region_ids=regions)
    _require(isinstance(result.metadata, dict), 'metadata must be an object')
    _require(isinstance(result.warnings, list) and all(isinstance(x, str) for x in result.warnings), 'invalid warnings')
    json_value(result.metadata)
