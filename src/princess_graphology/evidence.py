"""Versioned evidence payload emitted beside the aggregate measurements.

The payload records the individual observations behind selected aggregates
(per-component slant, per-line baseline fits, accepted and rejected spacing
gaps, component size distributions) with their regions and the coordinate
frames needed to draw them on the input image. It never changes an aggregate:
the measurement stages and this module read the same observation functions.

Frames: ``frame_input`` is the image handed to the engine (root); the analysis
canvas ``frame_analysis`` is its child, and ``transform_to_parent`` maps
analysis coordinates to input coordinates (row-major 3x3, pixel centres).
Regions are half-open pixel boxes in the analysis frame. ``page_0`` is the
image canvas, not a detected paper edge.

Product identifiers (bundle, run, owner) and method versions are added by the
application layer; this module stays free of product contracts.
"""
from __future__ import annotations

import math

import numpy as np

from .measurements.baseline import baseline_fits
from .measurements.slant import slant_candidates
from .measurements.spacing import line_gaps, word_gaps
from .schema_validation import load_contract

EVIDENCE_VERSION = 'evidence/1'
INPUT_FRAME = 'frame_input'
ANALYSIS_FRAME = 'frame_analysis'
MAX_REGIONS = 4096
MAX_OBSERVATIONS = 20000
BASELINE_POINTS_PER_LINE = 12
PAGE_WARNING = 'page_0 is the analysis canvas, not a detected paper edge; margins are canvas-relative.'


def _unit(feature_id):
    return load_contract()['features'][feature_id]['unit']


def _observation(observation_id, feature_id, method_id, region_ids, value, *, reason=None):
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) not in (int, float) or not math.isfinite(value):
        return None  # non-finite or non-numeric observations are never emitted
    return {'observation_id': observation_id, 'feature_id': feature_id, 'method_id': method_id,
            'region_ids': list(dict.fromkeys(region_ids)), 'value': float(value), 'unit': _unit(feature_id),
            'accepted': reason is None, 'rejection_reason': reason}


def _even_sample(count, limit):
    if count <= limit:
        return list(range(count))
    return sorted({round(i * (count - 1) / (limit - 1)) for i in range(limit)})


def _frames(ctx):
    transform = ctx.metadata.get('analysis_to_original')
    flat = [float(v) for row in transform for v in row] if transform is not None else None
    if flat is None or len(flat) != 9 or not all(math.isfinite(v) for v in flat):
        raise ValueError('analysis context lacks a finite analysis_to_original transform')
    return [
        {'frame_id': INPUT_FRAME, 'width': int(ctx.original_width), 'height': int(ctx.original_height),
         'unit': 'px', 'parent_frame_id': None, 'transform_to_parent': None},
        {'frame_id': ANALYSIS_FRAME, 'width': ctx.width, 'height': ctx.height, 'unit': 'px',
         'parent_frame_id': INPUT_FRAME, 'transform_to_parent': flat},
    ]


def _region(region_id, scope, box, parent):
    x, y, w, h = box
    return {'region_id': region_id, 'frame_id': ANALYSIS_FRAME, 'scope': scope, 'x': int(x), 'y': int(y),
            'width': int(w), 'height': int(h), 'parent_region_id': parent}


def _baseline_point_regions(ctx, fits):
    regions = []
    for fit in fits:
        line = ctx.lines[fit.line_index]
        for k in _even_sample(len(fit.xs), BASELINE_POINTS_PER_LINE):
            x = line.x + int(fit.xs[k])
            y = min(line.y + int(round(fit.ys[k])), line.y2 - 1)
            regions.append(_region(f'baseline_{fit.line_index}_{k}', 'BASELINE_POINT', (x, y, 1, 1),
                                   f'line_{fit.line_index}'))
    return regions


def collect_evidence(ctx, result):
    """Build the evidence payload for one analysis from its shared context."""
    warnings = [PAGE_WARNING]
    fits = baseline_fits(ctx)
    groups = [
        [_region(r.region_id, r.scope, r.box.as_tuple(), r.parent_id) for r in result.regions
         if r.scope in ('PAGE', 'LINE')],
        _baseline_point_regions(ctx, fits),
        [_region(r.region_id, r.scope, r.box.as_tuple(), r.parent_id) for r in result.regions if r.scope == 'WORD'],
        [_region(r.region_id, r.scope, r.box.as_tuple(), r.parent_id) for r in result.regions
         if r.scope == 'COMPONENT'],
    ]
    regions, dropped = [], {}
    for group in groups:
        for region in group:
            if len(regions) < MAX_REGIONS:
                regions.append(region)
            else:
                dropped[region['scope']] = dropped.get(region['scope'], 0) + 1
    if dropped:
        warnings.append('region budget reached; omitted ' + ', '.join(
            f'{count} {scope.lower()}' for scope, count in sorted(dropped.items())))
    kept = {r['region_id'] for r in regions}

    observations = []

    def add(obs):
        if obs is not None:
            obs['region_ids'] = [rid for rid in obs['region_ids'] if rid in kept]
            observations.append(obs)

    for i, angle, reason in slant_candidates(ctx):
        add(_observation(f'obs:slant:component_{i}', 'SLANT_ANGLE_MEAN', 'oriented_component_axis_v1',
                         [f'component_{i}'], angle, reason=reason))
    for fit in fits:
        points = [f'baseline_{fit.line_index}_{k}' for k in _even_sample(len(fit.xs), BASELINE_POINTS_PER_LINE)]
        add(_observation(f'obs:baseline:line_{fit.line_index}', 'BASELINE_ANGLE_MEAN', 'bottom_quantile_angle_v1',
                         [f'line_{fit.line_index}', *points], fit.angle))
    for first, second, gap, reason in line_gaps(ctx):
        add(_observation(f'obs:line_gap:{first}', 'LINE_SPACING_PX', 'accepted_box_gap_px_v1', [first, second],
                         gap, reason=reason))
    for first, second, gap, reason in word_gaps(ctx):
        add(_observation(f'obs:word_gap:{first}', 'WORD_SPACING_PX', 'accepted_box_gap_px_v1', [first, second],
                         gap, reason=reason))
    for i in ctx.glyph_indices:
        box = ctx.components[i]
        add(_observation(f'obs:glyph_height:component_{i}', 'GLYPH_HEIGHT_MEAN', 'component_box_size_v1',
                         [f'component_{i}'], box.height))
        add(_observation(f'obs:glyph_width:component_{i}', 'GLYPH_WIDTH_MEAN', 'component_box_size_v1',
                         [f'component_{i}'], box.width))
    for i in ctx.x_height_indices:
        add(_observation(f'obs:x_height:component_{i}', 'X_HEIGHT_PX', 'component_height_mode_v1',
                         [f'component_{i}'], ctx.components[i].height))
    if len(observations) > MAX_OBSERVATIONS:
        warnings.append(f'observation budget reached; omitted {len(observations) - MAX_OBSERVATIONS}')
        observations = observations[:MAX_OBSERVATIONS]
    if not observations:
        warnings.append('No repeated observations were available for this image.')
    return {
        'evidence_version': EVIDENCE_VERSION,
        'frames': _frames(ctx),
        'regions': regions,
        'observations': observations,
        'warnings': warnings,
    }


def map_to_input(transform, x, y):
    """Map an analysis-frame point to the input frame with a flat 3x3 transform."""
    matrix = np.asarray(transform, dtype=float).reshape(3, 3)
    px, py, pw = matrix @ np.array([x, y, 1.0])
    return float(px / pw), float(py / pw)
