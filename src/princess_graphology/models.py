"""Strict, JSON-safe public result models. Unknown confidence is not certainty."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


class DuplicateMeasurementError(ValueError):
    pass


def json_value(value: Any) -> Any:
    """Convert NumPy containers/scalars; reject non-finite or non-JSON values."""
    if isinstance(value, np.ndarray):
        return json_value(value.tolist())
    if isinstance(value, np.generic):
        return json_value(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('NaN and Infinity are not valid measurement JSON')
        return value
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {k: json_value(v) for k, v in value.items()}
    raise TypeError(f'Not a JSON value: {type(value).__name__}')


@dataclass(frozen=True)
class Box:
    """Half-open pixel rectangle in the analysis-canvas coordinate frame."""
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self):
        for name in ('x', 'y', 'width', 'height'):
            value = json_value(getattr(self, name))
            if type(value) is not int or value < (1 if name in ('width', 'height') else 0):
                raise ValueError(f'Invalid box {name}: {value!r}')
            object.__setattr__(self, name, value)

    @property
    def x2(self):
        return self.x + self.width

    @property
    def y2(self):
        return self.y + self.height

    @property
    def area(self):
        return self.width * self.height

    def crop(self, image):
        return image[self.y:self.y2, self.x:self.x2]

    def as_tuple(self):
        return self.x, self.y, self.width, self.height


@dataclass(frozen=True)
class Measurement:
    feature_id: str
    raw_value: Any
    unit: str | None = None
    normalized_value: Any = None
    confidence: float | None = None
    n_observations: int = 1
    std_dev: float | None = None
    method_version: str = 'unspecified'
    source_regions: list[str] = field(default_factory=list)
    evidence_status: str = 'MEASURED_VISUAL_FEATURE'
    notes: list[str] = field(default_factory=list)
    quality_flag: str = 'OK'
    missing_reason: str | None = None
    confidence_kind: str = 'UNCALIBRATED'
    method_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for name in ('raw_value', 'normalized_value', 'confidence', 'n_observations',
                     'std_dev', 'source_regions', 'notes', 'method_metadata'):
            object.__setattr__(self, name, json_value(getattr(self, name)))
        # Structural checks at construction; feature/region checks at insertion/export.
        from .schema_validation import validate_structure
        validate_structure(self)

    def to_dict(self):
        return json_value(asdict(self))


@dataclass(frozen=True)
class Region:
    region_id: str
    scope: str
    box: Box
    parent_id: str | None = None
    confidence: float | None = None

    def to_dict(self):
        data = asdict(self)
        data['box'] = self.box.as_tuple()
        return json_value(data)


@dataclass
class AnalysisResult:
    source: str
    width: int
    height: int
    measurements: dict[str, Measurement] = field(default_factory=dict)
    regions: list[Region] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, measurement: Measurement):
        from .schema_validation import validate_measurement
        if measurement.feature_id in self.measurements:
            raise DuplicateMeasurementError(measurement.feature_id)
        validate_measurement(measurement)
        self.measurements[measurement.feature_id] = measurement

    def to_dict(self):
        from .schema_validation import validate_result
        validate_result(self)
        return json_value({
            'source': self.source, 'width': self.width, 'height': self.height,
            'measurements': {k: v.to_dict() for k, v in self.measurements.items()},
            'regions': [r.to_dict() for r in self.regions],
            'warnings': self.warnings, 'metadata': self.metadata,
        })

    def to_json(self, *, indent: int | None = 2):
        return json.dumps(self.to_dict(), allow_nan=False, sort_keys=True, indent=indent)
