# Tests and what their evidence means

Use the complete checked-in workflows for exact installation and qualification. The commands below are entry points after [setup](local-setup.md), not substitutes for hash-lock, dependency-boundary or installed-wheel checks. Counts change; retain command, source SHA, environment, result and artifact rather than copying old totals.

| Layer | Entry command/source | Prerequisites and proof boundary |
|---|---|---|
| Documentation | `python tools/documentation.py --check` | Standard library + Git; links/inventories/registered targets only, no arbitrary snippet execution |
| Roadmap | `python docs/roadmap/plan_tools.py --check` | Graph, references, generated backlog and its selected links; not provider approval |
| Documentation regressions | `python -m unittest discover -s tests_docs -p 'test_*.py'` | Synthetic temporary source trees and negative controls |
| Core | `python -m pytest -q tests` | Matching reviewed core/backend environment; numerical/contracts/research unit tests, not population validation |
| App/database | `python -m pytest -q tests_app` | Real disposable PostgreSQL configured as below; RLS/transaction/application behavior |
| JS workspace | `pnpm typecheck` and `pnpm test` | Frozen workspace; browser installation for render tests |
| Native controllers | `pnpm --filter @princess/mobile test` | Node tests, not simulator UI |
| Native development-API journey | `tools/run_mobile_journey.sh` | Explicit local reset opt-in, API/workers and optional export prerequisites; actual controllers with device-I/O stand-ins |
| Web fixture UI | `pnpm --filter @princess/web e2e` | Pinned Playwright browser; browser/accessibility tests, not native accessibility |
| Web service journey | `tools/run_web_e2e.sh` | Same isolated reset precautions as native journey; no shared `princess_test` concurrent jobs |
| Native compile | [.github/workflows/native.yml](../../.github/workflows/native.yml) | Actual Android debug (dev-client, Metro-dependent) and unsigned iOS simulator compilation with native modules |
| Standalone Android packaged UI | `tools/build_android_handoff.sh`, then `tools/run_android_handoff_journey.sh <apk>`; Native foundation `android-handoff` job | The exact release-variant development APK with its embedded Hermes bundle, on one real Android emulator, through the real system Photo Picker against the local API and gated deterministic worker, with force-stop/relaunch and exact database counts ending in the saved Dossier. Not physical-device, signing or store evidence |
| Runtime/rollback/recovery | [workflow inventory](../reference/command-inventory.md), [runtime](../../infra/runtime/README.md), [runbooks](../runbooks/README.md) | Docker/PostgreSQL and synthetic state; no production provider assurance |
| iOS simulator UI / physical device / store | T30A/T30/T31/T32/T33 | Unexecuted where no recorded evidence: iOS UI driving, physical phones/tablets, signed builds and store sandboxes still need real permitted device/store tests |
| Empirical/model evaluation | T11/T06/T16 and reference tasks | Actual permitted data, account/data/spend approvals and a predeclared rubric; synthetic guards do not establish quality |

## Standalone Android packaged UI

This layer is distinct from both the Node native-controller journey (real controllers, device I/O stand-ins, no UI) and physical-device/store qualification (T30/T31, owner-gated). It answers one question: does the exact installable APK run the real Free journey without Metro?

- **Binary:** `:app:assembleRelease` of the existing `development` variant with `INKTROSPECT_BACKEND_ENV=local` and `INKTROSPECT_API_BASE=http://127.0.0.1:8000`. It is non-debuggable, embeds `assets/index.android.bundle` (Hermes) and is signed with the generated CNG debug key. `tools/verify_android_handoff.py` plus `apkanalyzer`/`apksigner` check it before any device is involved; [synthetic-ZIP unit tests](../../tests/test_verify_android_handoff.py) prove that a dev-client APK without an embedded bundle fails.
- **Device:** one explicitly provisioned `system-images;android-36;google_apis;x86_64` emulator. The job records the resolved image revision, emulator and adb versions in its log and, on `main`, in `BUILDINFO.json`.
- **Runner:** Maestro CLI **2.11.0** only, as an external CI/test tool, not an app dependency. CI downloads the GitHub release asset `maestro.zip` for tag `cli-2.11.0`, checks SHA-256 `5384593cb4e7a106489e75a821d157dd43f4e438df6bc308b72e82c685e1283a` before extracting, and requires `maestro --version` to print `2.11.0`. Maestro Cloud, API keys, unpinned actions and "latest" installers are not used. Every Maestro and ADB wait has a shell `timeout`, and the job has a `timeout-minutes` bound.
- **Journey:** flows in [apps/mobile/e2e/maestro](../../apps/mobile/e2e/maestro/) use the real Android system Photo Picker (resource IDs, not coordinates) on a synthetic page generated at runtime, which is never committed. After the run is queued with the analysis worker gated, the app is force-stopped and relaunched with its data kept. It must recover the same operation, then reach the saved Dossier once the worker is released.
- **Assertions:** exact counts in the disposable `princess_test` database: 1 capture, 1 run and 0 reports before the worker runs; 1 capture, 1 run, 1 report and 1 revision afterwards, with the report on the recorded run and the run on the one capture. Never weaken these to `>= 1`.

**Destructive: drops and recreates `princess_test`.** On a Linux host with a booted emulator/device, Maestro 2.11.0 and the locked backend:

```bash
INKTROSPECT_APP_VARIANT=development INKTROSPECT_BACKEND_ENV=local INKTROSPECT_API_BASE=http://127.0.0.1:8000 \
  PYTHON=.venv/bin/python tools/build_android_handoff.sh
PYTHON=.venv/bin/python \
  PRINCESS_E2E_ADMIN_URL='postgresql://princess_admin:local-only-admin@127.0.0.1:5432/postgres' \
  PRINCESS_E2E_ALLOW_RESET=1 \
  tools/run_android_handoff_journey.sh apps/mobile/android/app/build/outputs/apk/release/app-release.apk
```

The runner refuses when host port 8000 or 8081 is already serving, when the device locale is not English, or when the Maestro version differs. It starts no Metro, Premium worker, payment, push or model provider. Its qualification server uses `PRINCESS_ENV=test`, because the `local` environment manifest is bound to the developer's `princess_local` database.

## Core and generation checks

```bash
python tools/generate_feature_contract.py --check
python tools/generate_product_contracts.py --check
python tools/compile_premium_interpretation_db.py --check
python tools/generate_design_tokens.py --check
python tools/check_graphology_research.py
python tools/validate_consent_protocol.py
python docs/roadmap/plan_tools.py --check
python tools/documentation.py --check
python -m unittest discover -s tests_docs -p 'test_*.py'
```

See [generated assets](../reference/generated-assets.md) and the exact CI workflow. `--write`/generation is maintenance, not a passing drift check. Default `pytest` uses `testpaths = ["tests"]`; it does **not** include `tests_app` implicitly.

## PostgreSQL application tests

Create `princess_test` on the disposable local cluster if it does not exist (the native/web E2E runners also create it, but destroy its existing contents). Do not reuse a populated development database as a disposable test target.

```bash
psql 'postgresql://princess_admin:local-only-admin@127.0.0.1:5432/postgres' -v ON_ERROR_STOP=1 -c 'CREATE DATABASE princess_test'
PRINCESS_TEST_DATABASE_URL='postgresql://princess_admin:local-only-admin@127.0.0.1:5432/princess_test' \
  .venv/bin/python -m pytest -q tests_app
```

The first command is only for a missing database; an already-existing error is not permission to drop an unknown database. Fixtures establish non-owner runtime-role coverage. SQLite is not evidence for the PostgreSQL/RLS semantics.

## Safe refusal and shell checks

The documentation workflow checks shell syntax and a narrowly selected refusal path, never all code fences:

```bash
bash -n tools/run_mobile_journey.sh
bash -n tools/run_web_e2e.sh
bash -n tools/run_android_handoff_journey.sh
bash -n tools/build_android_handoff.sh
```

A controlled negative test supplies a loopback placeholder URL with `PRINCESS_E2E_ALLOW_RESET=0` and asserts each journey runner exits before contacting PostgreSQL; another asserts the handoff build refuses staging/store/production/public-API configuration before running any tool. These are not successful end-to-end journeys.

## Evidence recording

Distinguish a PR head, GitHub's candidate merge ref and a merged `main` SHA. Preserve each workflow's source binding. A historical run linked in a handover record is not a new test. Attach only safe synthetic outputs and bounded redacted results; CI artifact retention is finite.

Do not count a skipped check, unavailable reviewer, pending native build or empty finding list as PASS. Neither a signed binary nor a validated policy draft is public-release approval. Required provider/device/empirical evidence remains with its owning task.
