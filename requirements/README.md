# CI dependency locks

T00 uses two reviewed files per supported interpreter:

- `ci-pyXYZ.txt` is the exact name/version manifest.
- `ci-pyXYZ.lock` repeats that complete manifest and records the SHA-256 of the one reviewed Linux x86_64 wheel used by CI.

CI verifies that the manifest and lock contain the same package/version set, hash-checks every downloaded wheel, installs only from the authenticated local wheelhouse, and statically validates `project.dependencies`, each selected optional-dependency group, and `build-system.requires` against the reviewed manifest. Optional markers are evaluated with the selected extra context. Direct URLs are prohibited, and upstream dependency extras such as `pkg[feature]` are rejected until their activated transitive graph is explicitly reviewed and locked. The same rules apply to every active `Requires-Dist` edge of every locked wheel (T00A), so the lock is a closed reviewed graph rather than a flat name list. The local project is then installed with `--no-deps`, and the installed distribution set must exactly equal the lock plus the local project.

## Supported build configuration

T00A makes the build configuration explicit instead of inferring it. `tools/verify_project_dependency_policy.py` rejects anything outside it before the project is installed:

| Surface | Required | Rejected because |
|---|---|---|
| `[build-system]` | Present, with an explicit `requires` list and `build-backend` | A missing table or backend makes pip fall back to an unreviewed `setuptools>=40.8.0` legacy backend. |
| `build-backend` | `setuptools.build_meta` only; its provider `setuptools` declared in `requires` | Other or legacy backends are unreviewed hook code. `backend-path` (in-tree backends) is prohibited. |
| `build-system.requires` | Exact `==` pins equal to the reviewed manifest version, with no environment markers | An isolated downstream build resolves ranges from an index without our hashes. A marker could hide a requirement, or the backend provider itself, from this runner's checks. |
| `requires-python` | Exactly the Python minors whose target-stamped `requirements/ci-py*.lock` has its `ci-py*.txt` manifest and a matching `python`/`manifest`/`lock` entry of string values in the block-style `jobs.test.strategy.matrix.include` of `.github/workflows/ci.yml` (today `>=3.10,<3.13`); text in comments, scalars, nested values or other jobs never counts, and YAML outside the strict block subset the reader interprets exactly (multi-line scalars or flow collections, anchors, aliases, tags, tabs, duplicate keys, inconsistent indentation) leaves every lock untested, written only as whole-minor `>=X.Y` and `<X.Y` bounds | A metadata-only widening would advertise interpreters with no reviewed hashes or CI job; a narrowing would drop a reviewed one. Exclusions (`!=3.11.5`), wildcards, `~=` and patch-level bounds could drop part of a reviewed minor. |
| `[project]` metadata | Fully static: no `[project].dynamic` fields, no `[tool.setuptools.dynamic]` table and no `[tool.setuptools].cmdclass` | Dynamic dependency fields let the backend generate `Requires-Dist` outside the policy. Other dynamic fields (for example `version = {attr = ...}`) and custom command classes make setuptools import project code while the build hooks run. |
| `setup.py`, `setup.cfg` | Absent | Both can supply dependency metadata and `setup_requires`, which the backend reports through `get_requires_for_build_*`. |
| Backend-reported requirements | Empty, or already exact-pinned in `build-system.requires`; checked whatever their marker says | pip never asks for them under `--no-build-isolation`, but an ordinary isolated build installs them. |

## Locked graph and backend checks

With `--lock` and `--wheelhouse`, the verifier reads `METADATA` directly from the authenticated wheels (nothing is installed, imported or downloaded) and walks every active `Requires-Dist` edge from the pyproject roots plus explicit `--root` toolchain entries (CI passes `--root pip`). It fails on active extras or direct URLs, edges leaving the lock, locked versions that do not satisfy an edge, locked entries unreachable from a root, wheelhouse/lock drift, non-wheel artifacts, duplicate wheels or `.dist-info` directories, and `METADATA` identity that disagrees with the wheel filename. Markers are evaluated for the running interpreter, which must match the lock's `# Python X.Y; System machine.` header. A marker that depends on a variable the header does not fix (`python_full_version`, `implementation_version`, `platform_release`, `platform_version`, `platform_python_implementation`, `implementation_name`) is treated as active unless the rest of the marker is false, because another interpreter the lock covers could activate it.

With `--backend-requirements`, and only after the static policy passes, it runs the allowlisted backend's `get_requires_for_build_wheel`, `get_requires_for_build_editable` and `get_requires_for_build_sdist` hooks, each in its own isolated-mode (`python -I`) subprocess on a temporary copy of the project, with socket egress denied and `PIP_NO_INDEX=1`. Isolated mode keeps the project directory, `PYTHONPATH` and the user site off `sys.path` from interpreter start-up, so a committed `socket.py` cannot run before the guard; the project tree is stripped from `sys.path` again before the backend is imported. Any network attempt, hook failure or unreviewed reported requirement fails CI.

Residual trust: the egress guard is an in-process, best-effort control around the hash-locked setuptools release; it is not a sandbox against a hostile backend. Downstream users building from source outside CI resolve the exact `build-system.requires` pins from their own index without these hashes. Wheels are trusted to the extent of their reviewed SHA-256 and the per-interpreter marker evaluation of the matching CI job.

## Supported interpreters

The reviewed package support range is Python 3.10–3.12, expressed as `requires-python = ">=3.10,<3.13"`. Python 3.13+ is intentionally not advertised until a later task adds its own manifest, artifact hashes and matrix coverage.

## Build toolchain

Every manifest and lock includes:

- `pip==26.2.1`
- `setuptools==84.0.0`
- `wheel==0.48.0`

The same setuptools/wheel versions are exact in `[build-system].requires`. The bootstrap pip supplied by the pinned setup-python action is used only to download the reviewed wheels with hash checking. The authenticated pip/setuptools/wheel artifacts are then installed from the local wheelhouse before project installation or tests.

Editable installation and wheel construction use `--no-build-isolation`, so no temporary PEP 517 environment can resolve unreviewed tools.

## Lock generation

`tools/generate_ci_lock.py` generates a candidate lock from an exact-version manifest for the active Python/Linux-x86_64 environment. Lock generation is maintenance work, not a CI mutation: generated hashes must be reviewed and committed.

Example, under the matching Python minor on Linux x86_64:

```bash
python tools/generate_ci_lock.py requirements/ci-py311.txt requirements/ci-py311.lock
```

## Update policy

Dependency updates are explicit review work:

1. change the exact-version manifest;
2. regenerate the matching hashed lock under the supported Python/Linux-x86_64 environment;
3. review the package/version and SHA-256 diff;
4. run the full matrix, which must:
   - hash-authenticate all wheels;
   - install only from the local wheelhouse;
   - validate `project.dependencies`, selected optional groups, and `build-system.requires`;
   - enforce the supported build configuration above (explicit backend, exact build pins, static metadata, no `setup.py`/`setup.cfg`);
   - evaluate optional dependency markers with the selected extra context;
   - reject direct URL dependencies in all reviewed dependency surfaces;
   - reject upstream dependency extras until their full activated graph is explicitly locked;
   - verify all active reviewed dependencies exist in the manifest at compatible versions;
   - walk every active `Requires-Dist` edge of the locked wheels and reject open, stale or ambiguous graphs;
   - capture backend-reported build requirements in the egress-denied sandbox;
   - install the local project with `--no-deps` so project metadata cannot trigger any download;
   - reject manifest/lock drift;
   - reject duplicate, missing, extra or version-mismatched installed distributions;
   - pass `pip check`, validators, Ruff, pytest, research regressions, wheel build and installed-wheel smoke;
5. merge only when the reviewed head is green.

The lock files are the CI artifact authority. The version-only manifests exist to make updates reviewable and are checked against the locks on every run.
