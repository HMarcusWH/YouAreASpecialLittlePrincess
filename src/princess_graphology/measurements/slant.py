"""Elongated-component axis slant. Sign is invariant to fitLine's axis direction."""
import cv2
import numpy as np

from ._common import emit, mean, std

FEATURE_IDS = ('SLANT_ANGLE_MEAN', 'SLANT_ANGLE_MEDIAN', 'SLANT_ANGLE_STD', 'SLANT_P05', 'SLANT_P95',
               'SLANT_LEFT_FRACTION', 'SLANT_VERTICAL_FRACTION', 'SLANT_RIGHT_FRACTION',
               'SLANT_EXTREME_FRACTION', 'SLANT_CONSISTENCY')


def axis_slant(vx, vy):
    if vy > 0:
        vx, vy = -vx, -vy
    return float(np.degrees(np.arctan2(vx, -vy)))


def measure_slant(ctx):
    angles, regions = [], []
    for i, box in enumerate(ctx.components):
        if box.height < 8:
            continue
        mask = (box.crop(ctx.labels) == i + 1).astype(np.uint8)
        contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
        if not contours:
            continue
        contour = max(contours, key=len)
        if len(contour) < 12:
            continue
        points = contour[:, 0, :].astype(float)
        eigenvalues = np.linalg.eigvalsh(np.cov(points.T, bias=True))
        if eigenvalues[-1] <= 0 or eigenvalues[-1] < 2 * max(eigenvalues[0], 1e-12):
            continue
        vx, vy, _, _ = cv2.fitLine(contour, cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        angle = axis_slant(float(vx), float(vy))
        if abs(angle) <= 60:
            angles.append(angle)
            regions.append(f'component_{i}')
    a = np.asarray(angles)
    spread = std(angles)
    values = (mean(angles), float(np.median(a)) if a.size else None, spread,
              float(np.percentile(a, 5)) if a.size else None,
              float(np.percentile(a, 95)) if a.size else None,
              float(np.mean(a < -5)) if a.size else None,
              float(np.mean(np.abs(a) <= 5)) if a.size else None,
              float(np.mean(a > 5)) if a.size else None,
              float(np.mean(np.abs(a) >= 30)) if a.size else None,
              max(0.0, 1 - spread / 60) if spread is not None else None)
    meta = {'positive': 'top leans right relative to vertical', 'vertical_band_deg': [-5, 5],
            'extreme_abs_deg': 30, 'accepted_abs_deg_max': 60, 'minimum_axis_eigenvalue_ratio': 2,
            'observation_unit': 'elongated connected-component contour axis',
            'consistency_formula': 'max(0, 1-population_std_degrees/60)'}
    return [emit(key, value, method='oriented_component_axis_v1', n=len(a), regions=regions,
                 std=spread if key == 'SLANT_ANGLE_MEAN' else None, meta=meta)
            for key, value in zip(FEATURE_IDS, values)]
