# CI dependency constraints

T00 uses exact per-interpreter constraint snapshots under this directory to make the reviewed CI baseline reproducible while `pyproject.toml` describes the supported compatibility range.

## Supported interpreters

The reviewed package support range is Python 3.10–3.12, expressed as `requires-python = ">=3.10,<3.13"`. Python 3.13+ is intentionally not advertised until a later task adds constraint-backed matrix coverage.

## Build toolchain

Every CI snapshot pins the build toolchain as well as runtime/test dependencies:

- `pip==26.2.1`
- `setuptools==84.0.0`
- `wheel==0.48.0`

The same setuptools/wheel versions are pinned in `[build-system].requires`. CI installs the pinned build toolchain explicitly and uses `--no-build-isolation` for editable installation and wheel construction, preventing a temporary PEP 517 build environment from resolving unreviewed tool versions.

## Current snapshots

The Python 3.10, 3.11 and 3.12 runtime/test graphs were frozen from successful GitHub Actions run `36205458224` on 2026-09-26. That run passed 149 pytest tests, the graphology research checks, wheel build and installed-wheel smoke on all three interpreters.

The build-tool pins above were added during review remediation and must pass the same full matrix before merge.

## Update policy

Dependency updates are explicit review work:

1. change the relevant constraint file(s) and, for build-tool changes, `[build-system].requires`;
2. record the newly reviewed versions in the PR;
3. run build-tool verification, `pip check`, all validators, Ruff, pytest, research regressions, wheel build and installed-wheel smoke across all supported Python minors;
4. merge only when the reviewed commit is green.

Do not silently regenerate these files on every CI run. They are a reviewed compatibility snapshot, not a claim that these are the only package versions supported by the library.
