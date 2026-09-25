"""Image darkness and medial-axis thickness proxies. No physical pen pressure."""
import inspect

import numpy as np
from skimage.morphology import medial_axis

from ._common import cv, emit, mean, std

FEATURE_IDS = ('INK_DARKNESS_MEAN', 'INK_DARKNESS_STD', 'INK_DARKNESS_CV',
               'STROKE_WIDTH_MEAN', 'STROKE_WIDTH_MEDIAN', 'STROKE_WIDTH_STD', 'STROKE_WIDTH_CV',
               'STROKE_UNIFORMITY', 'INK_SATURATION_FRACTION')


def stroke_width_samples(mask):
    if not np.any(mask):
        return np.empty(0, dtype=float)
    # Seed tie-breaking for deterministic output across repeated analyses.
    # scikit-image 0.22 used random_state; newer supported releases use rng.
    seed_name = 'rng' if 'rng' in inspect.signature(medial_axis).parameters else 'random_state'
    padded = np.pad(mask > 0, 1)
    axis, distance = medial_axis(padded, return_distance=True, **{seed_name: 0})
    return 2 * distance[axis]


def measure_ink(ctx):
    ink = ctx.mask > 0
    darkness = 1 - ctx.gray[ink].astype(float) / 255
    widths = stroke_width_samples(ctx.mask)
    width_cv = cv(widths)
    values = (mean(darkness), std(darkness), cv(darkness), mean(widths),
              float(np.median(widths)) if len(widths) else None, std(widths), width_cv,
              1 / (1 + width_cv) if width_cv is not None else None,
              float(np.mean(ctx.gray[ink] <= 5)) if np.any(ink) else None)
    out = []
    for key, value in zip(FEATURE_IDS, values):
        stroke = key.startswith('STROKE_')
        n = len(widths) if stroke else len(darkness)
        deviation = std(widths) if key == 'STROKE_WIDTH_MEAN' else (
            std(darkness) if key == 'INK_DARKNESS_MEAN' else None)
        out.append(emit(key, value, method='medial_axis_diameter_v1' if stroke else 'grayscale_darkness_v1',
                        n=n, std=deviation, regions=['page_0'],
                        reason='insufficient_ink_samples_or_zero_mean',
                        meta={'observation_unit': 'medial-axis pixels' if stroke else 'foreground pixels',
                              'ddof': 0, 'saturation_grayscale_max': 5,
                              'darkness_formula': '1-gray/255', 'uniformity_formula': '1/(1+width_cv)',
                              'limitation': 'image proxy, not physical pressure; widths have pixel-grid bias'}))
    return out
