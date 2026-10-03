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
| Native compile | [.github/workflows/native.yml](../../.github/workflows/native.yml) | Actual Android debug and unsigned iOS simulator compilation with native modules |
| Runtime/rollback/recovery | [workflow inventory](../reference/command-inventory.md), [runtime](../../infra/runtime/README.md), [runbooks](../runbooks/README.md) | Docker/PostgreSQL and synthetic state; no production provider assurance |
| Simulator UI / physical device / store | T30A/T30/T31/T32/T33 | Unexecuted where no recorded evidence; add a pinned app-driving runner and real permitted device/store tests |
| Empirical/model evaluation | T11/T06/T16 and reference tasks | Actual permitted data, account/data/spend approvals and a predeclared rubric; synthetic guards do not establish quality |

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
```

A controlled negative test supplies a loopback placeholder URL with `PRINCESS_E2E_ALLOW_RESET=0` and asserts the runner exits before contacting PostgreSQL. It is not a successful end-to-end journey.

## Evidence recording

Distinguish a PR head, GitHub's candidate merge ref and a merged `main` SHA. Preserve each workflow's source binding. A historical run linked in a handover record is not a new test. Attach only safe synthetic outputs and bounded redacted results; CI artifact retention is finite.

Do not count a skipped check, unavailable reviewer, pending native build or empty finding list as PASS. Neither a signed binary nor a validated policy draft is public-release approval. Required provider/device/empirical evidence remains with its owning task.