"""Counts and digital areas conditional on the accepted segmentation."""
import numpy as np

from ._common import emit

FEATURE_IDS = ('PAGE_LINE_COUNT', 'PAGE_WORD_COUNT', 'PAGE_COMPONENT_COUNT',
               'PAGE_INK_AREA_RATIO', 'PAGE_TEXT_AREA_RATIO')


def measure_segmentation(ctx):
    bounds = ctx.text_bounds
    values = (len(ctx.lines), len(ctx.words), len(ctx.components),
              float(np.count_nonzero(ctx.mask) / ctx.mask.size),
              bounds.area / ctx.mask.size if bounds is not None else 0.0)
    return [emit(key, value, method='accepted_segmentation_census_v1', regions=['page_0'],
                 meta={'text_area': 'enclosing detected-line bounding rectangle; not summed boxes',
                       'confidence': 'detector accuracy is uncalibrated',
                       'observation_unit': 'one page'})
            for key, value in zip(FEATURE_IDS, values)]
