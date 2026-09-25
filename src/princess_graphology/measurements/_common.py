"""Construct canonical measurements without duplicating schema units."""
from __future__ import annotations

import numpy as np

from ..models import Measurement
from ..schema_validation import load_contract


def emit(feature_id, value, *, method, n=1, std=None, regions=(), meta=None,
         exact=False, reason=None, evidence='COMPUTATIONAL_PROXY'):
    missing = value is None
    return Measurement(
        feature_id=feature_id, raw_value=value,
        unit=load_contract()['features'][feature_id]['unit'],
        confidence=1.0 if exact and not missing else None,
        confidence_kind='EXACT_CONDITIONAL' if exact and not missing else 'UNCALIBRATED',
        n_observations=int(n), std_dev=std if not missing else None,
        method_version=method, source_regions=list(dict.fromkeys(regions)),
        evidence_status=evidence,
        quality_flag='MISSING' if missing else ('OK' if exact else 'EXPERIMENTAL'),
        missing_reason=(reason or 'insufficient_observations') if missing else None,
        method_metadata=dict(meta or {}),
    )


def mean(values):
    return float(np.mean(values)) if len(values) else None


def std(values):
    """Population descriptor; require two observations to report variability."""
    return float(np.std(values, ddof=0)) if len(values) >= 2 else None


def cv(values):
    average, spread = mean(values), std(values)
    return spread / average if spread is not None and average is not None and average > 0 else None


def relative(value, context):
    return value / context.x_height_px if value is not None and context.x_height_px is not None else None


def line_regions(context):
    return [f'line_{i}' for i in range(len(context.lines))]


def component_regions(indices):
    return [f'component_{i}' for i in indices]
