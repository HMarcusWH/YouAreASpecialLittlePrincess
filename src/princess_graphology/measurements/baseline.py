"""Lower-ink-envelope regression. Experimental baseline, not recognized letter feet."""
from dataclasses import dataclass

import numpy as np

from ._common import emit, mean, relative, std

FEATURE_IDS = ('BASELINE_ANGLE_MEAN', 'BASELINE_ANGLE_MEDIAN', 'BASELINE_ANGLE_STD',
               'BASELINE_ABS_SLOPE', 'BASELINE_WAVINESS', 'BASELINE_CURVATURE', 'BASELINE_STABILITY')


@dataclass(frozen=True)
class BaselineFit:
    """One line's lower-envelope fit; sample coordinates are line-crop relative."""
    line_index: int
    xs: tuple
    ys: tuple
    angle: float
    residual: float
    sag: float


def baseline_fits(ctx):
    """Per-line fits shared by the aggregates and the evidence payload."""
    fits = []
    for index, line in enumerate(ctx.lines):
        crop = line.crop(ctx.mask)
        xs, ys = [], []
        for x in range(0, line.width, max(1, line.width // 50)):
            ink = np.flatnonzero(crop[:, x])
            if ink.size:
                xs.append(x)
                ys.append(float(np.percentile(ink, 82)))
        if len(xs) < 6 or max(xs) == min(xs):
            continue
        x, y = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        t = (x - (x.max() + x.min()) / 2) / np.ptp(x)
        quadratic = np.polyfit(t, y, 2)[0]
        fits.append(BaselineFit(index, tuple(xs), tuple(ys), float(-np.degrees(np.arctan(slope))),
                                float(np.std(y - (slope * x + intercept))), float(abs(quadratic) / 4)))
    return fits


def measure_baseline(ctx):
    fits = baseline_fits(ctx)
    angles = [fit.angle for fit in fits]
    residuals = [fit.residual for fit in fits]
    sags = [fit.sag for fit in fits]
    regions = [f'line_{fit.line_index}' for fit in fits]
    waviness = relative(mean(residuals), ctx)
    values = (mean(angles), float(np.median(angles)) if angles else None, std(angles),
              mean([abs(angle) for angle in angles]), waviness, relative(mean(sags), ctx),
              1 / (1 + waviness) if waviness is not None else None)
    methods = ('bottom_quantile_angle_v1',) * 4 + ('baseline_residual_xheight_v1',
               'baseline_quadratic_sag_xheight_v1', 'baseline_inverse_waviness_index_v1')
    meta = {'positive_angle': 'baseline rises to the right', 'bottom_quantile': 82,
            'curvature_formula': 'abs(quadratic coefficient)/4/xheight; x scaled to [-0.5,0.5]',
            'stability_formula': '1/(1+waviness); engineering index, not confidence', 'ddof': 0}
    return [emit(key, value, method=method, n=len(angles), regions=regions, meta=meta,
                 std=std(angles) if key == 'BASELINE_ANGLE_MEAN' else None,
                 reason='insufficient_baseline_observations_or_xheight')
            for key, value, method in zip(FEATURE_IDS, values, methods)]
