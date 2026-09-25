"""Single-column layout in analysis-canvas coordinates; not physical paper edges."""
import numpy as np

from ._common import cv, emit, line_regions, mean, relative, std

FEATURE_IDS = ('MARGIN_TOP_REL', 'MARGIN_BOTTOM_REL', 'MARGIN_LEFT_REL', 'MARGIN_RIGHT_REL',
               'MARGIN_LEFT_VARIABILITY', 'MARGIN_RIGHT_VARIABILITY', 'MARGIN_SYMMETRY',
               'TEXT_BLOCK_HORIZONTAL_CENTER', 'TEXT_BLOCK_VERTICAL_CENTER',
               'PAGE_HORIZONTAL_DENSITY', 'PAGE_VERTICAL_DENSITY', 'LINE_LENGTH_MEAN_REL',
               'LINE_LENGTH_VARIABILITY', 'LINE_START_DRIFT', 'LINE_END_DRIFT')


def measure_layout(ctx):
    regions = line_regions(ctx)
    bounds = ctx.text_bounds
    n = len(ctx.lines)
    margins = (bounds.y, ctx.height - bounds.y2, bounds.x, ctx.width - bounds.x2) if bounds else (None,) * 4
    out = [emit(key, relative(value, ctx), method='text_bounds_xheight_v1', n=n, regions=regions,
                reason='text_bounds_or_xheight_unavailable',
                meta={'coordinate_frame': 'analysis_canvas', 'normalizer': 'X_HEIGHT_PX'})
           for key, value in zip(FEATURE_IDS[:4], margins)]
    starts = [b.x for b in ctx.lines]
    ends = [b.x2 for b in ctx.lines]
    lengths = [b.width for b in ctx.lines]
    right = [ctx.width - x for x in ends]
    for key, vector in (('MARGIN_LEFT_VARIABILITY', starts), ('MARGIN_RIGHT_VARIABILITY', right),
                        ('LINE_LENGTH_VARIABILITY', lengths)):
        out.append(emit(key, cv(vector), method='line_edge_population_cv_v1', n=n, regions=regions,
                        reason='cv_requires_two_observations_and_positive_mean', meta={'ddof': 0}))
    symmetry = None
    if bounds and margins[2] + margins[3] > 0:
        symmetry = 1 - abs(margins[2] - margins[3]) / (margins[2] + margins[3])
    out.append(emit('MARGIN_SYMMETRY', symmetry, method='margin_balance_index_v1', n=n,
                    regions=regions, reason='missing_text_or_zero_total_horizontal_margin',
                    meta={'formula': '1 - abs(left-right)/(left+right)'}))
    for key, value in (
        ('TEXT_BLOCK_HORIZONTAL_CENTER', (bounds.x + bounds.width / 2) / ctx.width if bounds else None),
        ('TEXT_BLOCK_VERTICAL_CENTER', (bounds.y + bounds.height / 2) / ctx.height if bounds else None),
        ('PAGE_HORIZONTAL_DENSITY', bounds.width / ctx.width if bounds else None),
        ('PAGE_VERTICAL_DENSITY', bounds.height / ctx.height if bounds else None),
    ):
        out.append(emit(key, value, method='text_bounds_canvas_ratio_v1', n=n, regions=regions))
    fractions = [length / ctx.width for length in lengths]
    out.append(emit('LINE_LENGTH_MEAN_REL', mean(fractions), method='line_width_page_ratio_v1',
                    n=n, std=std(fractions), regions=regions,
                    meta={'normalizer': 'analysis_canvas_width; NOT x-height'}))
    y = np.array([(b.y + b.height / 2) / ctx.height for b in ctx.lines])
    for key, vector in (('LINE_START_DRIFT', starts), ('LINE_END_DRIFT', ends)):
        drift = None
        if n >= 2 and np.ptp(y) > 0:
            drift = float(np.polyfit(y, np.asarray(vector) / ctx.width, 1)[0])
        out.append(emit(key, drift, method='normalized_edge_vs_vertical_position_v1', n=n,
                        regions=regions, meta={'formula': 'slope(x_edge/canvas_width ~ y_center/canvas_height)'}))
    return out
