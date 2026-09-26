# T00 — Green baseline evidence

Status: `DONE`

## Broken baseline

- Main commit: `7a767754c8190e42f3d9f98f9cc0f95da9375713`
- GitHub Actions run: `36203571871`
- Python matrix: 3.10 / 3.11 / 3.12
- Pre-Ruff generation, graphology validators and `compileall`: PASS
- Ruff: FAIL with 277 errors across 12 T26 support files
- Pytest / research checks / wheel / installed-wheel smoke: not executed because Ruff stopped the jobs

The 277 lint failures were 127 E702, 123 E701, 12 E401, 9 E402 and 6 F401.

## Repaired behavioral baseline

Commit `83d133c91cf70f7a310cbf918ac9305060552ce3` established the first fully executed green matrix in run `36205458224`:

- Ruff: PASS
- pytest: 149 passed on each of Python 3.10, 3.11 and 3.12
- graphology research import check: PASS
- graphology research regression tests: PASS
- wheel build: PASS
- installed-wheel smoke: PASS

The repair did not weaken Ruff. It normalized the T26 support code, removed module-level `sys.path` bootstrap hacks, made `tools/` an explicit pytest import path, and repaired two tests whose assumptions were exposed once lint stopped masking pytest.

## Dependency and platform policy

- Python support baseline: 3.10 / 3.11 / 3.12
- CI runner: Ubuntu 24.04
- CI dependencies: exact per-Python constraints in `requirements/ci-py*.txt`
- Dependency integrity: `python -m pip check`
- Ruff baseline: 0.16.9
- GitHub checkout action: v7.0.1 pinned to commit `3d3c42e5aac5ba805825da76410c181273ba90b1`
- GitHub setup-python action: v7.0.0 pinned to commit `5fda3b95a4ea91299a34e894583c3862153e4b97`
- Future web-app Node baseline: Node.js 24.21.0 LTS (Krypton), recorded in `.node-version`

Node selection source checked on 2026-09-26: https://nodejs.org/en/download/archive/v24.21.0

## Policy-locked baseline

Commit `11a6657c1b1360ca41936c00c576698d06596a95` passed the complete pinned/constraint-driven matrix in GitHub Actions run `36205683287`:

- `pip check`: PASS on Python 3.10 / 3.11 / 3.12
- resolved-dependency logging: PASS
- feature and Premium compiler freshness: PASS
- all graphology validators: PASS
- `compileall`: PASS
- Ruff: PASS
- pytest: 149 passed on each interpreter
- graphology research import/regression checks: PASS
- wheel build: PASS
- installed-wheel smoke: PASS

## Closeout rule

T00 is promoted to `DONE` by the closing status commit that contains this document and the task-state update. That exact closing commit must pass the same matrix before the PR is considered merge-ready. Its final GitHub Actions run is recorded on the pull request conversation as the self-referential evidence record.
