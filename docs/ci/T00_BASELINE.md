# T00 — Green baseline evidence

Status: `DONE`

## Assigned baseline-run diagnosis

T00 originally assigned GitHub Actions run `36168879709` at commit `8f2ec7b07f23f7b3613ccc71576714f3c245e7a0`.

Retained GitHub evidence:

- run created and started: 2026-09-25 17:43:14 UTC;
- run completed: failure, updated 2026-09-25 17:43:19 UTC;
- matrix jobs: Python 3.10, 3.11 and 3.12;
- all three jobs completed with `failure`;
- all three jobs expose zero workflow steps through the GitHub Actions job API;
- workflow-job step lookup returns an empty step list for each job;
- job-log retrieval is unavailable for those jobs, so there is no retained command output to attribute the failure to checkout, Python setup, dependency installation, lint or tests.

Diagnosis: the assigned run failed before any executable workflow step was recorded. That rules out a demonstrated repository command/test failure for this run. The retained API evidence does **not** distinguish among runner dispatch, account/billing, permissions or another pre-step GitHub Actions condition, so T00 records the exact subcause as unrecoverable rather than guessing.

A later run with usable step logs was therefore required to identify the repository-level baseline defect.

## Reproducible broken baseline

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
- Package metadata: `requires-python = ">=3.10,<3.13"`
- CI runner: Ubuntu 24.04
- CI dependencies: exact per-Python manifests plus SHA-256-authenticated wheel locks in `requirements/ci-py*`
- Build toolchain: `pip==26.2.1`, `setuptools==84.0.0`, `wheel==0.48.0`, included in every hash lock
- Build isolation: disabled after authenticated build-tool installation; setuptools/wheel are also exact in `[build-system].requires`
- Supply-chain integrity: hash-checked wheel download, offline wheelhouse installation, offline `.[dev]` resolution, exact installed-graph verification, and `python -m pip check`
- Ruff baseline: 0.16.9
- GitHub checkout action: v7.0.1 pinned to commit `3d3c42e5aac5ba805825da76410c181273ba90b1`
- GitHub setup-python action: v7.0.0 pinned to commit `5fda3b95a4ea91299a34e894583c3862153e4b97`
- Future web-app Node baseline: Node.js 24.21.0 LTS (Krypton), recorded in `.node-version`

Node selection source checked on 2026-09-26: https://nodejs.org/en/download/archive/v24.21.0

## Policy-locked baseline

Commit `11a6657c1b1360ca41936c00c576698d06596a95` passed the complete first-generation constraint-driven matrix in GitHub Actions run `36205683287`:

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

Codex review first identified three policy gaps: the build toolchain was not included in the snapshot, Python metadata advertised versions outside the matrix, and the assigned run `36168879709` had not been explicitly diagnosed. Those were repaired on `4b07e54337852a5a5943901de4d8bd15dbcbdb33`, which passed run `36206449686`.

A second review identified two deeper supply-chain gaps: exact versions did not authenticate artifact bytes, and constraint files did not reject dependencies absent from the reviewed snapshot. T00 therefore moved to per-Python SHA-256 wheel locks, offline wheelhouse installation/resolution, manifest-lock equality checks, and exact installed-environment verification. The final hash-locked head must pass the full matrix before PR #10 is merge-ready.

## Closeout rule

T00 remains marked `DONE` only if the current PR head satisfies the complete reviewed policy. The final head must pass SHA-256 artifact authentication, offline dependency resolution, manifest/lock equality, exact installed-environment verification, build-tool verification, `pip check`, generation/validator checks, Ruff, pytest, research checks, offline wheel construction and installed-wheel smoke on Python 3.10 / 3.11 / 3.12. The exact final commit and Actions run are recorded in the PR conversation.
