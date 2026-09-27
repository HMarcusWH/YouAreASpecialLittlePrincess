"""Clear box gaps, never baseline-to-baseline distance or clamped overlaps."""
from ._common import cv, emit, mean, relative, std

FEATURE_IDS = ('LINE_SPACING_PX', 'LINE_SPACING_REL', 'LINE_SPACING_CV',
               'WORD_SPACING_PX', 'WORD_SPACING_REL', 'WORD_SPACING_CV')


def _measure(prefix, gaps, regions, ctx, excluded):
    average, spread = mean(gaps), std(gaps)
    meta = {'observation_unit': 'non-overlapping adjacent box gap', 'ddof': 0,
            'excluded_overlapping_pairs': excluded}
    out = []
    for suffix, value, deviation in (
        ('PX', average, spread), ('REL', relative(average, ctx), relative(spread, ctx)),
        ('CV', cv(gaps), None),
    ):
        reason = ('cv_requires_two_observations_and_positive_mean' if suffix == 'CV'
                  else 'no_valid_gaps_or_xheight_unavailable')
        out.append(emit(prefix + '_SPACING_' + suffix, value,
                        method='accepted_box_gap_' + suffix.lower() + '_v1',
                        n=len(gaps), std=deviation, regions=regions, meta=meta, reason=reason))
    return out


def line_gaps(ctx):
    """(upper_region, lower_region, gap, rejection_reason) for horizontally overlapping line pairs."""
    out = []
    for i, (upper, lower) in enumerate(zip(ctx.lines, ctx.lines[1:])):
        if min(upper.x2, lower.x2) <= max(upper.x, lower.x):
            continue
        gap = lower.y - upper.y2
        out.append((f'line_{i}', f'line_{i + 1}', gap, 'overlapping_boxes' if gap < 0 else None))
    return out


def word_gaps(ctx):
    """(left_region, right_region, gap, rejection_reason) for adjacent words within a line."""
    out = []
    for line_index in range(len(ctx.lines)):
        members = sorted((i for i, parent in enumerate(ctx.word_lines) if parent == line_index),
                         key=lambda i: ctx.words[i].x)
        for left, right in zip(members, members[1:]):
            gap = ctx.words[right].x - ctx.words[left].x2
            out.append((f'word_{left}', f'word_{right}', gap, 'overlapping_boxes' if gap < 0 else None))
    return out


def _accepted(pairs):
    gaps, regions = [], []
    for first, second, gap, reason in pairs:
        if reason is None:
            gaps.append(gap)
            regions.extend((first, second))
    return gaps, regions, sum(reason is not None for *_, reason in pairs)


def measure_spacing(ctx):
    line_values, line_regions, line_excluded = _accepted(line_gaps(ctx))
    word_values, word_regions, word_excluded = _accepted(word_gaps(ctx))
    return (_measure('LINE', line_values, line_regions, ctx, line_excluded)
            + _measure('WORD', word_values, word_regions, ctx, word_excluded))
