"""Historical rules, not validated personality inference.

Threshold provenance: titanh3art/ml-graphology (MIT). Its self-labelled SVM is
excluded. Baseline angles here follow the canonical convention: positive rises
right. The historical thresholds used the opposite sign and are converted.
"""


def baseline_band(deg):
    if deg <= -0.2:
        return 'descending'
    if deg >= 0.3:
        return 'ascending'
    return 'straight'


def relative_word_spacing_band(ratio):
    if ratio > 2.0:
        return 'wide'
    if ratio < 1.2:
        return 'narrow'
    return 'medium'


def relative_line_spacing_band(ratio):
    if ratio > 3.5:
        return 'wide'
    if ratio < 2.0:
        return 'narrow'
    return 'medium'


def letter_size_band(px):
    """Historical pixel thresholds; not resolution-independent and not calibrated."""
    if px >= 18.0:
        return 'big'
    if px < 13.0:
        return 'small'
    return 'medium'
