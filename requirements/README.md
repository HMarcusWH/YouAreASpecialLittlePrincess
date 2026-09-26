# CI dependency locks

T00 uses two reviewed files per supported interpreter:

- `ci-pyXYZ.txt` is the exact name/version manifest.
- `ci-pyXYZ.lock` repeats that complete manifest and records the SHA-256 of the one reviewed Linux x86_64 wheel used by CI.

CI verifies that the manifest and lock contain the same package/version set, hash-checks every downloaded wheel, installs only from the authenticated local wheelhouse, and statically validates `project.dependencies`, each selected optional-dependency group, and `build-system.requires` against the reviewed manifest. Optional markers are evaluated with the selected extra context. Direct URLs are prohibited, and upstream dependency extras such as `pkg[feature]` are rejected until their activated transitive graph is explicitly reviewed and locked. The local project is then installed with `--no-deps`, and the installed distribution set must exactly equal the lock plus the local project.

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
   - evaluate optional dependency markers with the selected extra context;
   - reject direct URL dependencies in all reviewed dependency surfaces;
   - reject upstream dependency extras until their full activated graph is explicitly locked;
   - verify all active reviewed dependencies exist in the manifest at compatible versions;
   - install the local project with `--no-deps` so project metadata cannot trigger any download;
   - reject manifest/lock drift;
   - reject duplicate, missing, extra or version-mismatched installed distributions;
   - pass `pip check`, validators, Ruff, pytest, research regressions, wheel build and installed-wheel smoke;
5. merge only when the reviewed head is green.

The lock files are the CI artifact authority. The version-only manifests exist to make updates reviewable and are checked against the locks on every run.
