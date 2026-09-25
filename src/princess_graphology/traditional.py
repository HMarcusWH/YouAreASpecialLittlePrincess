"""Traditional graphology bands preserved as historical rules, not validated personality inference.

Threshold provenance: titanh3art/ml-graphology (MIT). The old SVM personality
classifier is intentionally excluded because its labels were generated from the same
hand-coded graphology rules.
"""
def baseline_band(deg):
    if deg >= 0.2:
        return "descending"
    if deg <= -0.3:
        return "ascending"
    return "straight"

def relative_word_spacing_band(ratio):
    if ratio > 2.0:
        return "wide"
    if ratio < 1.2:
        return "narrow"
    return "medium"

def relative_line_spacing_band(ratio):
    if ratio > 3.5:
        return "wide"
    if ratio < 2.0:
        return "narrow"
    return "medium"

def letter_size_band(px):
    if px >= 18.0:
        return "big"
    if px < 13.0:
        return "small"
    return "medium"
