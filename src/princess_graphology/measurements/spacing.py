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


def measure_spacing(ctx):
    gaps, regions, excluded = [], [], 0
    for i, (upper, lower) in enumerate(zip(ctx.lines, ctx.lines[1:])):
        if min(upper.x2, lower.x2) <= max(upper.x, lower.x):
            continue
        gap = lower.y - upper.y2
        if gap < 0:
            excluded += 1
            continue
        gaps.append(gap)
        regions.extend((f'line_{i}', f'line_{i + 1}'))
    out = _measure('LINE', gaps, regions, ctx, excluded)
    gaps, regions, excluded = [], [], 0
    for line_index in range(len(ctx.lines)):
        members = sorted((i for i, parent in enumerate(ctx.word_lines) if parent == line_index),
                         key=lambda i: ctx.words[i].x)
        for left, right in zip(members, members[1:]):
            gap = ctx.words[right].x - ctx.words[left].x2
            if gap < 0:
                excluded += 1
                continue
            gaps.append(gap)
            regions.extend((f'word_{left}', f'word_{right}'))
    return out + _measure('WORD', gaps, regions, ctx, excluded)
