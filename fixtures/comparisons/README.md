# T18 synthetic comparison fixtures

These fixtures are generated from the repository's programmatically drawn handwriting sample.
They contain no participant data and are not calibration/reference evidence.

- `pair-ab.json`: request-ordered A → B native-unit differences.
- `pair-ba.json`: swapped pair used for reversal invariants.
- `pair-equal.json`: distinct synthetic report lineages with equal comparable values.
- `history.json`: three reports supplied out of order and emitted by report-created chronology.
- `no-overlap.json`: every approved comparison candidate is explicitly unavailable in one input.

Generate with `python tools/generate_comparison_fixtures.py`; `--check` fails on drift.
No fixture contains an aggregate similarity percentage, cosine, Mahalanobis score, percentile,
authorship claim, relationship claim, or inferred writing date.
