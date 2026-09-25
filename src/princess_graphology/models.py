from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass(frozen=True)
class Box:
    x: int
    y: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    def crop(self, image):
        return image[self.y:self.y2, self.x:self.x2]

    def as_tuple(self):
        return (self.x, self.y, self.width, self.height)

@dataclass
class Measurement:
    feature_id: str
    raw_value: Any
    unit: str | None = None
    normalized_value: Any = None
    confidence: float = 1.0
    n_observations: int = 1
    std_dev: float | None = None
    method_version: str = "bootstrap_v1"
    source_regions: list[str] = field(default_factory=list)
    evidence_status: str = "MEASURED_VISUAL_FEATURE"
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

@dataclass
class Region:
    region_id: str
    scope: str
    box: Box
    parent_id: str | None = None
    confidence: float = 1.0

    def to_dict(self):
        d = asdict(self)
        d["box"] = self.box.as_tuple()
        return d

@dataclass
class AnalysisResult:
    source: str
    width: int
    height: int
    measurements: dict[str, Measurement] = field(default_factory=dict)
    regions: list[Region] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add(self, m: Measurement):
        self.measurements[m.feature_id] = m

    def to_dict(self):
        return {
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "measurements": {k: v.to_dict() for k, v in self.measurements.items()},
            "regions": [r.to_dict() for r in self.regions],
            "warnings": self.warnings,
            "metadata": self.metadata,
        }
