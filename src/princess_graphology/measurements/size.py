"""Connected-component size descriptors and an experimental x-height proxy."""
from ._common import component_regions, cv, emit, mean, std

FEATURE_IDS = ('X_HEIGHT_PX', 'GLYPH_HEIGHT_MEAN', 'GLYPH_HEIGHT_CV',
               'GLYPH_WIDTH_MEAN', 'GLYPH_WIDTH_CV', 'GLYPH_ASPECT_RATIO_MEAN', 'GLYPH_ASPECT_RATIO_CV')


def measure_size(ctx):
    out = [emit('X_HEIGHT_PX', ctx.x_height_px, method='component_height_mode_v1',
                n=len(ctx.x_height_indices), regions=component_regions(ctx.x_height_indices),
                reason=ctx.x_height_missing_reason,
                meta={'minimum_inliers': 6, 'relative_height_tolerance': 0.15,
                      'limitation': 'not recognized lowercase; all-capital and cursive text can mislead'})]
    boxes = [ctx.components[i] for i in ctx.glyph_indices]
    regions = component_regions(ctx.glyph_indices)
    vectors = ([b.height for b in boxes], [b.width for b in boxes],
               [b.width / b.height for b in boxes])
    for prefix, values in zip(('GLYPH_HEIGHT', 'GLYPH_WIDTH', 'GLYPH_ASPECT_RATIO'), vectors):
        meta = {'observation_unit': 'filtered connected component, not recognized glyph', 'ddof': 0}
        out.append(emit(prefix + '_MEAN', mean(values), method='component_box_size_v1',
                        n=len(values), std=std(values), regions=regions, meta=meta))
        out.append(emit(prefix + '_CV', cv(values), method='component_box_size_v1',
                        n=len(values), regions=regions, meta=meta,
                        reason='cv_requires_two_observations_and_positive_mean'))
    return out
