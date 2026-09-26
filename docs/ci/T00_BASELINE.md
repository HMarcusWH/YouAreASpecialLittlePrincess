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
- Supply-chain integrity: hash-checked wheel download, offline wheelhouse installation, marker-aware runtime/dev/build-system policy verification, direct-URL and upstream-extra rejection, local project installation with `--no-deps`, duplicate-aware exact installed-graph verification, and `python -m pip check`
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

A second review identified two deeper supply-chain gaps: exact versions did not authenticate artifact bytes, and constraint files did not reject dependencies absent from the reviewed snapshot. T00 therefore moved to per-Python SHA-256 wheel locks, authenticated wheelhouse installation, manifest-lock equality checks, and exact installed-environment verification.

A third review identified two bypasses: a PEP 508 direct URL could still be fetched during editable dependency resolution, and duplicate installed distribution metadata could be silently collapsed by the verifier. That repair added `--no-deps`, direct-URL checks, reviewed runtime/dev dependency checks, and duplicate rejection.

A fourth review found three remaining policy-coverage gaps: selected optional-group markers were evaluated without the selected `extra` context, upstream dependency extras such as `pkg[feature]` could activate unreviewed transitives, and `build-system.requires` was outside the static policy check. The final policy carries selected-extra marker context, rejects upstream dependency extras until their complete graph is explicitly locked, and validates build-system requirements against the same reviewed manifest.

## Closeout rule

T00 remains marked `DONE` only if the current PR head satisfies the complete reviewed policy. The final head must pass SHA-256 artifact authentication, marker-aware project/optional/build-system dependency-policy verification, direct-URL and upstream-extra rejection, no-dependency local project installation, manifest/lock equality, duplicate-aware exact installed-environment verification, build-tool verification, `pip check`, generation/validator checks, Ruff, pytest, research checks, offline wheel construction and installed-wheel smoke on Python 3.10 / 3.11 / 3.12. The exact final commit and Actions run are recorded in the PR conversation.

## T00A post-merge follow-up

Status: `IMPLEMENTED_PENDING_REVIEW`. This section is appended; the T00 history above is unchanged.

The final Codex review of PR #10 at `90e88e5c73a081182974575925561ac948dbc0e1` ([review 5324261655](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/10#pullrequestreview-5324261655)) was submitted after the merge decision and left four P2 findings. T00 stays `DONE` as a historical record; T00A owns these repairs.

### Reproduction on the pre-T00A head

Base: `main` at `c7f511945d6a9f37938e0cd1a050ab194e7d2d52`. Environment: CPython 3.11.15, Linux x86_64, with `requirements/ci-py311.lock` downloaded with `--require-hashes` and installed offline (pip 26.2.1, setuptools 84.0.0, wheel 0.48.0, packaging 26.3). Each scenario used a temporary project; `verify_project_dependency_policy.py` exited 0 in all four:

| # | Finding | Observed behaviour before T00A |
|---|---|---|
| 1 | Locked distributions' `Requires-Dist` edges were never inspected | A locked `parentpkg` declaring `childpkg[feature]>=1` passed; an ordinary `pip install --dry-run parentpkg` resolved `childpkg`, `grandchild`, `parentpkg`, with `grandchild` outside the lock. |
| 2 | Dynamic dependency metadata bypassed the static check | With `dynamic = ["dependencies"]` and `[tool.setuptools.dynamic]`, setuptools' `prepare_metadata_for_build_wheel` emitted `Requires-Dist: evilpkg @ https://example.invalid/…`. |
| 3 | Backend-reported build requirements were never validated | With `setup.cfg` `setup_requires`, setuptools' `get_requires_for_build_{wheel,editable,sdist}` each returned `unreviewed-build-helper @ https://example.invalid/helper.whl`. pip 26.2.1 calls those hooks only when build isolation is on, so CI never saw them. |
| 4 | A missing `[build-system]` table was accepted | pip's `load_pyproject_toml` supplied `requires=['setuptools>=40.8.0']`, `backend='setuptools.build_meta:__legacy__'`. |

### Disposition

| # | Repair | Regression cases (`tests/test_ci_lock.py`) |
|---|---|---|
| 1 | `--lock/--wheelhouse/--root`: read `METADATA` from the hash-authenticated wheels without installing or importing them, then walk every active `Requires-Dist` edge from the reviewed roots. Reject active extras or direct URLs, edges leaving the lock, unsatisfied versions, unreachable lock entries, wheelhouse/lock drift, duplicate wheels or `.dist-info` directories, identity mismatches, and a lock target header that differs from the running interpreter. | `test_locked_requires_dist_*`, `test_inactive_locked_markers_are_not_edges`, `test_unreachable_locked_distribution_is_rejected`, `test_duplicate_wheels_*`, `test_wheel_*`, `test_wheelhouse_must_equal_lock`, `test_lock_*` |
| 2 | Reject `project.dynamic` entries for `dependencies` / `optional-dependencies`, the matching `[tool.setuptools.dynamic]` tables, and a missing `[project]` table. The alternative generated-metadata policy was not adopted. | `test_dynamic_dependency_metadata_is_rejected[*]`, `test_missing_project_table_is_rejected` |
| 3 | Static prohibition of `setup.py`, `setup.cfg`, `backend-path` and non-allowlisted backends. Then `--backend-requirements` runs the three hooks of the allowlisted, hash-locked backend, each in its own subprocess on a temporary copy of the project, with socket egress denied and the project tree removed from `sys.path`. Reported requirements must already be exact-pinned in `build-system.requires`. The hooks never run if the static policy fails. | `test_legacy_setuptools_configuration_is_rejected[*]`, `test_unreviewed_build_backend_is_rejected[*]`, `test_in_tree_*`, `test_backend_*`, `test_repository_backend_reports_no_unreviewed_build_requirements` |
| 4 | Require an explicit `[build-system]` with a `requires` list and `build-backend` (`setuptools.build_meta` only, with its provider declared), and exact `==` pins to the reviewed manifest. | `test_missing_build_*`, `test_build_backend_provider_must_be_declared`, `test_build_requirement_must_be_an_exact_reviewed_pin[*]` |

Failing-before/passing-after: the final `tests/test_ci_lock.py` (56 cases) run against the pre-T00A tools gives 43 failed and 13 passed. The 13 are the nine original T00 regressions plus four positive controls. The same file gives 56 passed with the repaired tools on Python 3.10, 3.11 and 3.12. Re-running the four end-to-end scenarios through the repaired CLI now exits 1 for each, with the errors shown in the PR description.

The existing protections are unchanged: SHA-256 wheelhouse download, offline `--no-deps` installation, manifest/lock equality, duplicate-aware exact installed-environment verification, `pip check`, direct-URL and upstream-extra rejection in pyproject surfaces, and selected-extra marker context.

### Locally executed results on the T00A head

The same wheel locks were hash-downloaded and installed into per-interpreter virtual environments, and the CI steps were run in order:

- `verify_project_dependency_policy.py … --lock … --wheelhouse … --root pip`: PASS. Closed graphs: py310 has 25 distributions and 27 active edges; py311 and py312 each have 23 and 25.
- `verify_project_dependency_policy.py … --backend-requirements`: PASS. setuptools 84.0.0 reports `wheel=[]`, `editable=[]` and `sdist=[]` on each interpreter.

These are local results. Exact-head GitHub Actions evidence for the PR head is recorded in the PR conversation. T00A moves to `DONE` only after that run and review.

### PR #12 review follow-up

The Codex review of the T00A head found that an inactive environment marker on a `build-system.requires` entry skipped the manifest and exact-pin checks, while the entry's raw name still counted as declaring the backend provider. Build requirements must now be marker-free, and the provider must be declared unconditionally. Backend-reported requirements are validated whatever their marker says. Regressions: `test_build_requirements_must_be_unconditional[*]` and the updated `test_backend_reported_requirement_must_be_a_declared_reviewed_build_requirement`.

### Supported build configuration and residual trust

The supported configuration is a pyproject-only setuptools project with an explicit `setuptools.build_meta` backend, exact reviewed build pins, and static dependency metadata. See the [requirements README](../../requirements/README.md#supported-build-configuration). Residual trust remains in three places:

- the hash-locked setuptools/pip/wheel releases themselves;
- the in-process egress guard, which is best effort and not a sandbox against a hostile backend;
- downstream source builds outside CI, which resolve the exact `build-system.requires` pins from their own index without these hashes.

New ecosystems (T28) must extend these checks deliberately.
