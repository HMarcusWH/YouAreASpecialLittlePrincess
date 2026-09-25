"""Input acquisition metadata, not dimensions of the resized analysis canvas."""
from ._common import emit

FEATURE_IDS = ('IMG_WIDTH_PX', 'IMG_HEIGHT_PX', 'IMG_MEGAPIXELS', 'IMG_ASPECT_RATIO', 'IMG_ROTATION_DEG')


def measure_quality(ctx):
    values = (ctx.original_width, ctx.original_height,
              ctx.original_width * ctx.original_height / 1e6,
              ctx.original_width / ctx.original_height)
    out = [emit(key, value, method='input_dimensions_v1', exact=True,
                regions=['page_0'], meta={'coordinate_frame': 'original_image'},
                evidence='MEASURED_VISUAL_FEATURE')
           for key, value in zip(FEATURE_IDS[:4], values)]
    out.append(emit('IMG_ROTATION_DEG', ctx.rotation_deg, method='text_skew_ccw_v1',
                    regions=['page_0'], reason='rotation_not_estimated',
                    meta={'positive': 'counterclockwise input text rotation',
                          'correction_deg': ctx.metadata.get('deskew_applied_deg'),
                          'limitation': 'text tilt is not independently identified paper rotation'}))
    return out
