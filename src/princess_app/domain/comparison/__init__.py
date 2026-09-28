"""Calibration-independent deterministic comparisons (T18)."""
from .builder import build_comparison
from .policy import (
    COMPARISON_METHOD_VERSION,
    HISTORY_ORDERING,
    PAIR_ORDERING,
    FeatureAssessment,
    assess_feature,
    candidate_feature_ids,
    native_delta,
)

__all__ = [
    "COMPARISON_METHOD_VERSION", "HISTORY_ORDERING", "PAIR_ORDERING",
    "FeatureAssessment", "assess_feature", "build_comparison",
    "candidate_feature_ids", "native_delta",
]
