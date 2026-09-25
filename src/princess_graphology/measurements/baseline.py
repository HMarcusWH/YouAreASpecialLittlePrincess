"""Lower-ink-envelope regression. Experimental baseline, not recognized letter feet."""
import numpy as np

from ._common import emit, mean, relative, std

FEATURE_IDS = ('BASELINE_ANGLE_MEAN', 'BASELINE_ANGLE_MEDIAN', 'BASELINE_ANGLE_STD',
               'BASELINE_ABS_SLOPE', 'BASELINE_WAVINESS', 'BASELINE_CURVATURE', 'BASELINE_STABILITY')


def measure_baseline(ctx):
    angles, residuals, sags, regions = [], [], [], []
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
        angles.append(float(-np.degrees(np.arctan(slope))))
        residuals.append(float(np.std(y - (slope * x + intercept))))
        t = (x - (x.max() + x.min()) / 2) / np.ptp(x)
        quadratic = np.polyfit(t, y, 2)[0]
        sags.append(float(abs(quadratic) / 4))
        regions.append(f'line_{index}')
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
