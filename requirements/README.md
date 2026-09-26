# CI dependency constraints

T00 uses exact per-interpreter constraint snapshots under this directory to make the reviewed CI baseline reproducible while `pyproject.toml` continues to describe supported compatibility ranges.

## Current snapshots

The Python 3.10, 3.11 and 3.12 files were frozen from successful GitHub Actions run `36205458224` on 2026-09-26. That run passed 149 pytest tests, the graphology research checks, wheel build and installed-wheel smoke on all three interpreters.

## Update policy

Dependency updates are explicit review work:

1. change the relevant constraint file(s) in a dedicated PR;
2. record the newly resolved versions in the PR;
3. run `pip check`, all validators, Ruff, pytest, research regressions, wheel build and installed-wheel smoke across all supported Python minors;
4. merge only when the reviewed commit is green.

Do not silently regenerate these files on every CI run. They are a reviewed compatibility snapshot, not a claim that these are the only package versions supported by the library.
