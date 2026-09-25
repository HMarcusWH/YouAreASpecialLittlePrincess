"""Registered deterministic measurement stages and their exact feature sets."""
from . import baseline, ink, layout, quality, segmentation, size, slant, spacing

_MODULES = (quality, segmentation, size, layout, baseline, spacing, slant, ink)
MEASUREMENT_STAGES = tuple(getattr(module, 'measure_' + module.__name__.rsplit('.', 1)[-1])
                           for module in _MODULES)
STAGE_FEATURE_IDS = tuple(module.FEATURE_IDS for module in _MODULES)
IMPLEMENTED_FEATURE_IDS = tuple(key for keys in STAGE_FEATURE_IDS for key in keys)
if len(set(IMPLEMENTED_FEATURE_IDS)) != len(IMPLEMENTED_FEATURE_IDS):
    raise RuntimeError('duplicate feature registration')
