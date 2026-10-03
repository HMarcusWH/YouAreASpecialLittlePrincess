#!/usr/bin/env python3
"""One-shot branch preparation. Not included in the resulting handover PR."""
from __future__ import annotations
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASE = '766125e25ccb0c9a4ada4466da5f36e708024e51'
ROOT = Path.cwd()
PAYLOAD = Path(sys.argv[1])

def run(*args):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True).stdout

def read(path):
    return (ROOT / path).read_text(encoding='utf-8')

def write(path, content):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + '\n', encoding='utf-8')

def replace(path, old, new):
    content = read(path)
    if old not in content:
        raise RuntimeError('missing reviewed replacement: ' + path + ' / ' + old[:80])
    write(path, content.replace(old, new, 1))

def prefix(path, note):
    content = read(path)
    if note not in content:
        write(path, note + '\n\n' + content)

def append(path, content):
    if (ROOT / path).is_file():
        write(path, read(path).rstrip() + '\n\n' + content)
    else:
        write(path, content)

assert run('git', 'rev-parse', 'HEAD').strip() == BASE
before_tasks = json.loads(read('docs/roadmap/tasks.json'))
for source in sorted(PAYLOAD.rglob('*')):
    if source.is_file():
        rel = source.relative_to(PAYLOAD).as_posix()
        if rel.startswith('/') or '..' in Path(rel).parts:
            raise RuntimeError('unsafe payload path')
        write(rel, source.read_text(encoding='utf-8'))

# A: entry point and state reconciliation; preserve the original numerical guide.
old_readme = read('README.md')
core = old_readme[old_readme.index('## Measurement engine'):]
deferred = old_readme[old_readme.index('### Deferred operational follow-up'):old_readme.index('## Product architecture')].strip()
deferred = deferred.replace('final live evidence\nceremony', 'final live evidence\nrun')
intro = '''# Inktrospect

A mobile-first, privacy-conscious handwriting-analysis product built around deterministic measurements, structured evidence and separately labelled interpretive layers. Public brand: **Inktrospect**. `YouAreASpecialLittlePrincess`, `Princess` and `princess_*` are internal repository/package names, not instructions to rename existing contracts.

**Status: active development, not publicly released.** The shared native client is implemented through T30A; real identity, purchases, push, device and store qualification remain unfinished. [Current handover snapshot](docs/handover/current-state.md) records the post-#72 evidence and limitations. [tasks.json](docs/roadmap/tasks.json) remains the task/dependency authority.

## Start here

| Goal | Entry |
|---|---|
| Take over development | [Receiving-maintainer guide](docs/handover/README.md) and [documentation home](docs/README.md) |
| Run the mobile development app | [Complete local setup](docs/development/local-setup.md) → [native README](apps/mobile/README.md) |
| Understand the system | [Architecture](docs/architecture/overview.md), [data/lifecycles](docs/architecture/data-and-lifecycles.md), [current API](docs/reference/api.md) |
| Make a change | [Contributing](CONTRIBUTING.md), [tests](docs/development/testing.md), [generated assets](docs/reference/generated-assets.md), [agent instructions](AGENTS.md) |
| Diagnose or operate | [Safe commands](docs/reference/commands.md), [troubleshooting](docs/development/troubleshooting.md), [runbooks](docs/runbooks/README.md) |
| Plan remaining work | [Roadmap](ROADMAP.md), [generated backlog](docs/roadmap/06-agent-backlog.md), [external access/assets](docs/handover/access-and-assets.md) |

## Current implementation, not release approval

| Area | Implemented scope / limit |
|---|---|
| Numerical Free core | 64 registered measurements against 272 definitions; zero runtime AI; most estimates remain experimental |
| Product backend | PostgreSQL/RLS, immutable captures/reports, permission events, durable jobs, ledger, exports and erasure/recovery mechanisms |
| Shared native client | Guest/development sessions, review/crop, journaled upload/analysis, saved Dossier/history, settings, feedback, authenticated exports, same-owner unsaved comparison and paid-state integration code |
| Native evidence | Controller tests, development-API journey and Android/unsigned-iOS compilation; not launched native UI, physical-device or store qualification |
| Supporting web | Implemented Free journey and regression/inspection surface; unfinished web Premium is not a native construction prerequisite |
| Premium / commerce | Provider-independent and disabled adapter/runtime machinery; real model evaluation, store proofs, commercial policy and live composition remain gated |
| Identity / operations | Narrow selected Supabase verification profile; production-style app login and complete hosting/storage/mail/push/monitoring remain open |
| Research / policy | Reviewed interpretation structure and synthetic pilot tooling; no fabricated calibration, reference population or approval of draft policy |

The accepted design is [Direction A — The Dossier](docs/design/ACCEPTED_DOSSIER_REFERENCE.md). Native clients share semantic tokens, formatting and authorized facts, not a universal web renderer. The brand is playful; numerical and privacy boundaries are not optional.

```text
private image → safe immutable capture → deterministic engine
   → evidence + saved report → current authorized projection
       ├─ native iPhone/iPad and Android phone/tablet client
       ├─ supporting web client
       └─ PDF / share rendering
optional Premium: authorized image + facts → bounded validated saved overlay
```

Clients never become a second measurement, credit or permission authority. Reopening, rendering or sharing a saved report does not call a model. Missing is not zero; image darkness/thickness are proxies, not physical pen pressure. No diagnosis, intelligence, deception, criminality, employability, authorship identification or relationship-outcome claim is permitted. Population-relative claims require a qualified reference release. Traditional associations and AI synthesis remain distinct from measured facts.

## Repository map

```text
apps/mobile/                shared native client and platform boundaries
apps/api/                   FastAPI surface and source-tree composition
apps/workers/               analysis/erasure, Premium, export and notification processes
apps/web/                   supporting Next.js Free client
apps/render/                offline PDF/share-card renderer
src/princess_graphology/    deterministic numerical core
src/princess_app/           domain, application, ports and adapters
src/princess_contracts/     authoritative product construction/validation
packages/                  shared DTOs, API transport, report semantics and design tokens
contracts/                 wire/policy sources and generated schema components
schema/                    numerical and interpretation authorities
migrations/                reviewed PostgreSQL revisions and role boundaries
infra/                     development/runtime/recovery/operations declarations
research/ provenance/      frozen source evidence and rights records
evaluation/ fixtures/      synthetic tooling and explicitly gated real evaluation
docs/                      maintainer guides, specialist specs, decisions and evidence
```

Read [component navigation](docs/reference/component-index.md) for entry pages. [Security reporting](SECURITY.md) and [third-party notices](THIRD_PARTY_NOTICES.md) explain handling and rights boundaries; this documentation does not select a project license.

```bash
python docs/roadmap/plan_tools.py --active
python docs/roadmap/plan_tools.py --ready
```

'''
write('README.md', intro + deferred + '\n\n' + core)
replace('README.md', "python -m venv .venv\nsource .venv/bin/activate\npip install -e '.[dev]'", "# Reviewed Linux x86_64 / Python 3.12 core environment, not a backend install.\npython3.12 -m venv .venv\nsource .venv/bin/activate\npython -m pip install --require-hashes --only-binary=:all: --no-deps -r requirements/ci-py312.lock\npython -m pip install --no-index --no-deps --no-build-isolation -e '.[dev]'")
prefix('AGENTS.md', '> Human maintainer entry: [docs/README.md](docs/README.md), [handover](docs/handover/README.md), [setup](docs/development/local-setup.md) and [testing](docs/development/testing.md). For documentation changes also run `python tools/documentation.py --check`. Current implementation references override historical route sketches; task/gate authorities remain unchanged.')
replace('AGENTS.md', 'This repository is moving from a deterministic Python library to a shared web/iOS/Android product.', 'This repository contains a deterministic Python core, shared product services and an implemented mobile-first native client with supporting web presentation.')
replace('AGENTS.md', 'Proposed application/domain/adapters live separately;', 'Application/domain/adapters live separately;')
replace('AGENTS.md', 'Product scope and execution order: the [current index](docs/roadmap/00-index.md), [post-PR14 reconciliation](docs/roadmap/23-post-pr14-reconciliation.md) and tasks.', 'Product scope and execution order: the [current index](docs/roadmap/00-index.md) and tasks. The [post-PR14 reconciliation](docs/roadmap/23-post-pr14-reconciliation.md) is historical evidence, not current implementation instructions.')

plan = json.loads(read('docs/roadmap/tasks.json'))
plan.update(baseline_commit=BASE, reconciled_from_pr=72, reconciled_head='2a119ba55a185f4ba66f0a7df0e3e30de085ec48', reconciled_date='2026-10-04')
t30a = next(t for t in plan['tasks'] if t['id'] == 'T30A')
old_remaining = t30a['remaining_work']
t30a['remaining_work'] = [s for s in old_remaining if not s.startswith('Run the Native foundation and Application environments workflows')]
assert len(old_remaining) - len(t30a['remaining_work']) == 1
old_evidence = t30a.get('implementation_evidence', '')
t30a['implementation_evidence'] = old_evidence + ' Post-merge documentation reconciliation: PR #72 final head 2a119ba55a185f4ba66f0a7df0e3e30de085ec48 passed Roadmap 37155767212, CI 37155767215, Release compatibility 37155767231, Application environments 37155767234, Runtime topology 37155767236 and Native foundation 37155767217. These are retained PR-triggered results, not new executions on the merge SHA. Codex code/security review was quota-blocked, not approved. No native UI, physical-device, signed-build or store evidence is inferred. See docs/handover/current-state.md.'
write('docs/roadmap/tasks.json', json.dumps(plan, indent=2))
roadmap = read('ROADMAP.md')
roadmap, count = re.subn(r'(\*\*Implementation baseline reconciled through:\*\*\s*)`[^`]+`\s*\(merged PR #\d+\)', r'\g<1>`' + BASE + '` (merged PR #72)', roadmap, count=1)
assert count == 1
write('ROADMAP.md', roadmap)
prefix('ROADMAP.md', '> Taking over implementation? Start with the [maintainer handover](docs/handover/README.md). This roadmap describes scope and future work, not a substitute for the [current API](docs/reference/api.md), [setup](docs/development/local-setup.md) or [operator commands](docs/reference/commands.md).')
idx = read('docs/roadmap/00-index.md')
start = idx.index('2. [23]')
end = idx.index('\n3. ', start)
idx = idx[:start] + '2. [23](23-post-pr14-reconciliation.md) preserves the historical PR #14 snapshot. Current task state is [tasks.json](tasks.json), with a dated [post-#72 handover](../handover/current-state.md). T30A now implements the shared native client and has successful retained controller/API/compile workflow evidence; device, native UI, identity, store and provider work remain open. T30/T31 no longer depend on unfinished web Premium T20 for native construction. T17 staging evidence remains deferred and does not activate login. Never infer a task closure or approval from this summary.' + idx[end:]
write('docs/roadmap/00-index.md', idx)
prefix('docs/roadmap/00-index.md', '> Human-first navigation is now [docs/README.md](../README.md); this page retains roadmap authority and chapter navigation.')
seq = read('docs/roadmap/20-end-to-end-build-sequence.md')
seq = re.sub(r'At the current implementation baseline, `--ready` yields.*?\n', 'Use the current `--ready` and `--active` outputs; do not treat a copied list in prose as a second status authority. T30A carries the merged native client; retained #72 checks are recorded in the handover snapshot.\n', seq, count=1)
seq = re.sub(r'6\. \*\*Complete native journeys:\*\*[^\n]*', '6. **Complete native journeys:** T30A implements shared native capabilities against established services, fakes and development API contracts. T30/T31 own native UI/device/provider/store qualification. Web Premium T20 is not a construction predecessor. Persisted invitations/grants and pair Premium still require their actual T22 contracts; store, model, signing and processing approval remain separate gates. A successful Node journey or native compile is not task completion.', seq, count=1)
write('docs/roadmap/20-end-to-end-build-sequence.md', seq)

# B/C: preserve detailed specialist content, correct active references and add setup links.
prefix('infra/README.md', '> Complete maintainer recipes: [local setup](../docs/development/local-setup.md), [test matrix](../docs/development/testing.md), [current configuration](../docs/reference/configuration.md), [safe commands](../docs/reference/commands.md). The technical details below describe existing mechanisms and explicit pending deployment work.')
infra = read('infra/README.md')
start = infra.index('The API factory is ')
end = infra.index('\n## Intake', start)
infra = infra[:start] + 'The API factory is `princess_api.compose:app_from_environment` (`uvicorn --factory`). Local/test composition uses fake identity. The selected Supabase adapter also has an implemented, protected staging/sandbox `VERIFY_CREDENTIAL` composition for the exact qualified tuple. This is not native/web sign-in, refresh, account lifecycle or complete staging deployment. The real conformance/Auth-settings/cleanup closeout remains deferred; unrelated object/payment/abuse composition still fails closed. Production/live identity is not activated. See the [current capability snapshot](../docs/handover/current-state.md) and [provider register](../docs/roadmap/19-provider-decision-register.md).\n' + infra[end:]
write('infra/README.md', infra)
prefix('requirements/README.md', '> Choose the [supported host/setup recipe](../docs/development/local-setup.md) before installing. The core, backend and native toolchains are separate. This page owns dependency policy; [testing](../docs/development/testing.md) owns runnable suite entry points.')
api_doc = read('docs/roadmap/10-web-client-and-api-integration.md')
start = api_doc.index('## API surfaces and ownership')
end = api_doc.index('## Web session', start)
api_doc = api_doc[:start] + '''## API surfaces and ownership

The callable method/path/request inventory is now the source-generated [current API reference](../reference/api-routes.md), with [authorization/error/retry semantics](../reference/api.md). Do not implement against the historical `/v1/samples`, `/v1/jobs/{id}`, `/v1/commerce/catalog`, `/v1/devices` or generic `/v1/webhooks/{provider}` sketches: current handlers use uploads, analyses, catalog, account-bound push installations and rail-specific payment events.

The API owns identity/principal resolution, purpose decisions, immutable intake, report projections, account-backed history, ledger, export, feedback and installation state. Shared clients consume runtime-guarded responses. Product schema components are generated separately from endpoint routing.

T30A added run discovery, report-scoped deletion, authorized retained source-image delivery, exact notice catalogue delivery and unsaved same-owner comparison. Persisted invitations, partner grants and pair Premium remain T22 work; no proposed share/contribution route is callable merely because a roadmap names it.

Upload completion and analysis start are separate. Completion binds verified immutable bytes and returns a capture; `POST /v1/analyses` creates/reuses the intended run. Idempotency is operation-specific: completion is digest-bound, analysis start is capture/config-bound, permission and feedback requests carry decision IDs, and an upload reservation can consume another quota slot after a lost response. A 202 response is acceptance, not completed inference. Never blindly replay an ambiguous paid request.

''' + api_doc[end:]
write('docs/roadmap/10-web-client-and-api-integration.md', api_doc)
tests = read('docs/roadmap/16-testing-evals-and-quality-gates.md')
tests = tests.replace('The repository\'s existing Python CI is retained. This roadmap adds a documentation validator/workflow; it does not implement product suites by naming them. The baseline PR recorded 158 pytest passes per Python minor before merge. New PRs must execute their exact head and report current counts rather than copying that number.', 'Use the current [test command/evidence matrix](../development/testing.md) and source workflows. Retained post-#72 results are in the [handover snapshot](../handover/current-state.md); execute and record the actual new head rather than copying old test counts. Documentation inventory and native controller tests are distinct from device/provider evidence.')
tests = tests.replace('## Planned suite contract', '## Coverage obligations by owning task')
tests = tests.replace('The following suites are `TO_IMPLEMENT` in the owning tasks. Each task must add the exact runnable command to its README/CI and update its task record when the suite exists.', 'This table combines implemented and remaining coverage obligations, not a blanket TO_IMPLEMENT status. The current [command matrix](../development/testing.md), actual workflows and `tasks.json` validation profiles establish which checks exist. Device/provider/empirical obligations remain open where their real evidence is absent.')
write('docs/roadmap/16-testing-evals-and-quality-gates.md', tests)
for chapter in ('01-data-architecture.md', '02-corpus-benchmarks.md', '03-premium-openai.md', '04-reports-design.md', '05-release-operations.md'):
    prefix('docs/roadmap/' + chapter, '> Maintainer note: this chapter retains design requirements and dated research/examples. For what runs now use the [handover snapshot](../handover/current-state.md), [implemented architecture](../architecture/overview.md), [current API](../reference/api.md) and [safe commands](../reference/commands.md). Historical model/price/route examples are not approved current configuration.')
prefix('docs/roadmap/11-mobile-architecture.md', '> Implemented native maintenance: [mobile README](../../apps/mobile/README.md), [lifecycle/private state](../architecture/mobile-lifecycle.md), [setup](../development/local-setup.md) and [test evidence boundaries](../development/testing.md). This chapter retains architecture and completion requirements.')

# D/E: safe operator interpretation and actual local-data descriptions.
runbook = read('docs/runbooks/README.md')
runbook = runbook.replace('- `$API_ENV` is the API component\'s environment (`PRINCESS_ENV`, `PRINCESS_COMPONENT=api`, `PRINCESS_DATABASE_URL`, …).', '- Commands below are operator templates after the correct component environment and reviewed role have been prepared. Follow [command safety and outputs](../reference/commands.md); an undefined `$API_ENV` expansion is not a setup command.')
runbook = runbook.replace('- SQL runs as a migration or operator role, never as an owner.', '- SQL requires the approved diagnostic/operator role and verified environment. Ordinary API principals must never receive owner/BYPASSRLS privileges for troubleshooting. Cross-owner completion needs the actual authorized worker/operator scope.')
runbook = runbook.replace('$API_ENV python', 'python').replace('$NOTIFY_ENV python', 'python').replace('$PREMIUM_ENV python', 'python')
runbook = runbook.replace('(`$NOTIFY_ENV` = the `notification_worker` component\'s environment.)', '(Prepare the `notification_worker` component environment and approved role before these mutating commands.)')
runbook = runbook.replace('- **Verify:** `complete-pending` reports `0`, and the provider shows the refund.', '- **Verify:** `completed` reports successful completions in that invocation, not remaining work. Zero can also mean provider completion failed. Inspect remaining completion state using the repository\'s actual pending-completion predicate under approved operator scope, reconcile it with authoritative provider state, and separately verify any requested refund. Do not close an incident on `completed == 0` or CLI exit 0 alone. A new bounded pending-state CLI, if needed, is separate T24 implementation work.')
runbook = runbook.replace('The customer is charged only on publication.', 'The application spends a reserved credit on publication; the store purchase may already have charged the customer earlier. Releasing an eligible reservation is not a store refund. Refund-after-spend/access behavior requires the approved commercial policy.')
write('docs/runbooks/README.md', runbook)
prefix('docs/runbooks/README.md', '> [Operator command safety/output semantics](../reference/commands.md) · [troubleshooting](../development/troubleshooting.md) · [access/custody](../handover/access-and-assets.md). These are implementation runbooks with explicit deployment gaps, not authorization to operate live providers.')
replace('src/princess_app/application/reports.py', '``InMemoryReportStore`` is the fixture-backed seam used until the T02\nPostgreSQL repository exists; both honour ``check_revision``.', '``InMemoryReportStore`` is the fixture/test implementation; runtime composition\nuses the PostgreSQL repository. Both honour ``check_revision``.')
replace('apps/mobile/src/work/journal.ts', '// operation instead of starting another. It holds identifiers, a private file\n// reference and a digest only: never image bytes, report bodies, purchase\n// proofs or credentials. It lives in app-private storage, not preferences.', '// operation instead of starting another. It holds identifiers, private file\n// metadata/digests, consent and retry state, and the upload slot URL/expiry. A\n// signed upload URL is a scoped capability: never log this journal. It stores\n// no image bytes, report bodies, store proofs or account credentials and lives\n// in app-private storage, not preferences. See docs/architecture/mobile-lifecycle.md.')

# F: current wrapper navigation only; frozen payloads and decisions are untouched.
research = read('research/graphology/README.md')
research = research.replace('3. [Database construction handoff](DATABASE_HANDOFF.md): requirements for the separate post-merge T26 implementation.', '3. [Historical database construction handoff](DATABASE_HANDOFF.md): original T26 requirements; current implementation is the [reviewed interpretation source](../../schema/graphology_interpretation/v1/README.md). Do not rebuild completed T26 work.')
start = research.index('The supporting-materials PR must be merged')
end = research.index('\n\nThe preserved draft', start)
research = research[:start] + 'The original supporting-materials import preceded T26 construction. That is historical provenance, not present implementation status: T26 and its T15 consumer are now recorded DONE, the database is populated/reviewed, runtime activation remains false and traditional runtime eligibility remains zero. The frozen research JSON stays under `research/`; it does not independently authorize interpretation. Read the current schema handoff before acting on historical construction instructions.' + research[end:]
write('research/graphology/README.md', research)
prefix('research/graphology/DATABASE_HANDOFF.md', '> Historical construction handoff, retained as provenance. T26 and its T15 consumer have since been implemented. Current source/status: [interpretation database](../../schema/graphology_interpretation/v1/README.md). Do not alter frozen foundations or treat this record as authorization to activate content.')
replace('contracts/consent/README.md', 'These are versioned draft contracts. T01 owns the final product wire DTOs and code generation. It maps these schemas into `contracts/product/v1` and generated Python/TypeScript. Until then, the IDs, enums and semantics here are the source, and any change must keep the validator and fixtures green.', 'These are versioned draft policy contracts. T01 now binds their authority into `contracts/product/v1` and generated Python/TypeScript; product generation does not approve the draft policy. These IDs, enums and semantics retain their distinct authority, and changes must keep the policy validators, fixtures and bound product outputs consistent.')
replace('THIRD_PARTY_NOTICES.md', 'This bootstrap contains or adapts code under permissive open-source licenses. Original license texts are preserved separately in the provenance commit.', 'This repository contains or adapts the source work listed below. Follow [provenance/SOURCES.md](provenance/SOURCES.md) and the [retained license-text inventory](docs/reference/component-index.md#retained-license-text-candidates) to retrieve the actual records. This notice is not a newly selected license for the whole project; the owner must confirm project distribution/contribution terms during handover.')
append('THIRD_PARTY_NOTICES.md', '## Separate rights categories\n\nCode, datasets, pretrained weights, fonts, prototype assets and user specimens need separate rights decisions. A permissive code dependency does not clear its dataset or weights. No project-wide LICENSE is created by this documentation change. See [access and assets](docs/handover/access-and-assets.md) and [source-rights policy](docs/privacy/source-rights.md).')
append('docs/design/ACCEPTED_DOSSIER_REFERENCE.md', '## Maintainer artifact retrieval\n\nThe acceptance record above is unchanged. [Access and assets](../handover/access-and-assets.md) records the exact archive digest and the outstanding durable delivery/recipient verification action. A clone contains the accepted token/reference records, not the external prototype ZIP or approval to redistribute fonts.')
prefix('docs/adr/README.md', '> Current implemented/composed/qualified limits are summarized in the [handover snapshot](../handover/current-state.md) and [configuration reference](../reference/configuration.md). Engineering defaults below are not blanket production approvals.')
provider = read('docs/roadmap/19-provider-decision-register.md')
provider = provider.replace('native bridge selection; catalog/', 'native bridge sandbox/device qualification (the expo-iap implementation is present); catalog/')
write('docs/roadmap/19-provider-decision-register.md', provider)

# Concise component entry pages; append navigation rather than discard existing guides.
components = {
'apps/api/README.md': ('FastAPI application', 'Factory: `princess_api.compose:app_from_environment`. Routing is `princess_api/app.py`; operator commands are `princess_api/ops.py`. Run with the separately locked Python backend and source paths. HTTP authenticates the principal and invokes application services; it is not an entitlement engine of its own. The notice registry is a required packaged input.\n\nRead [setup](../../docs/development/local-setup.md), [API semantics/routes](../../docs/reference/api.md), [configuration](../../docs/reference/configuration.md) and [operator output semantics](../../docs/reference/commands.md). Tests: `python -m pytest -q tests_app` with disposable PostgreSQL; default core pytest alone is not this suite. Narrow staging identity verification is not production login; non-fake storage/payment composition remains separately gated.'),
'apps/workers/README.md': ('Durable application workers', 'Entry processes: `analysis/run_worker.py` (deterministic analysis and erasure), `premium/run_worker.py` (bounded attempts and restored-attempt reconciliation), `export/run_worker.py` (authorized projection to bounded renderer output), `notifications/run_worker.py` (generic permitted mail/push delivery). Use each process\'s reviewed component manifest, worker role and required private storage.\n\nSee [lifecycles](../../docs/architecture/data-and-lifecycles.md), [local setup](../../docs/development/local-setup.md), [runtime images](../../infra/runtime/README.md) and [runbooks](../../docs/runbooks/README.md). Leases and fences reject stale publication. A worker restart is not permission to repeat ambiguous provider execution. Erasure events are dispatched only after required deletion verification. No production provider, notification channel or paid model is activated by starting a local fake-backed process.'),
'apps/render/README.md': ('Offline report renderer', 'This Node/Chromium child receives an authorized saved projection through stdin under the export-worker boundary; it owns layout, not authorization, private SQL, storage credentials or inference. Use `pnpm --filter @princess/render run build`; install the workspace\'s pinned Chromium for source-tree tests or use the qualified export-runtime image. `pnpm --filter @princess/render inspect:artifacts` generates synthetic review outputs, not a public user export.\n\nRead [setup](../../docs/development/local-setup.md), [testing](../../docs/development/testing.md), [runtime packaging](../../infra/runtime/README.md) and [accepted design](../../docs/design/ACCEPTED_DOSSIER_REFERENCE.md). A PDF/export must use the same authorized saved facts; changing a template does not authorize missing Premium or partner scope. Downloads need authenticated transport, and externally saved copies cannot be recalled.'),
'apps/web/README.md': ('Supporting web client', 'Next.js provides the existing Free journey and browser regression/inspection surface. Mobile is the current construction priority; unfinished web Premium is not a prerequisite for native client work. Preserve cookie/proxy and server authorization boundaries when changing shared packages.\n\nUse [setup](../../docs/development/local-setup.md), the package scripts in [command inventory](../../docs/reference/command-inventory.md), `pnpm --filter @princess/web build` and `pnpm --filter @princess/web e2e`. The disposable real-service journey is `tools/run_web_e2e.sh`; read its reset warnings before running. Web/print components share report semantics; native clients do not import the web DOM renderer.'),
'packages/api-client/README.md': ('Shared API transport and runtime guards', 'Source exports are in `src/index.ts`; transport and native operations live in `src/client.ts` and `src/operations.ts`. Credentials can be resolved per request so long-lived native clients do not keep stale bearers. Runtime guards validate returned objects; a TypeScript cast is not validation.\n\n`TransportError` separates timeout/network/abort from an API response. Honor bounded Retry-After and operation-specific idempotency. Uploads go only to approved origins without the API credential; protected image/export downloads stay authenticated API operations. Portable hashing and strict URI parsing are shared, not alternate authorization logic. Read [API semantics](../../docs/reference/api.md), [native lifecycle](../../docs/architecture/mobile-lifecycle.md) and [package scripts](../../docs/reference/command-inventory.md).'),
'packages/contracts/README.md': ('Generated product TypeScript contracts', 'Generated declarations are outputs of `tools/generate_product_contracts.py` and the source authorities under `contracts/product/v1`. Do not hand-edit generated types or use a cast as a trust-boundary validator. Field names, versions and missingness must remain identical across Python/TypeScript consumers.\n\nRead [product authority](../../contracts/product/v1/README.md), [generated assets](../../docs/reference/generated-assets.md) and [API semantics](../../docs/reference/api.md). Regenerate and run the owning drift/positive/negative tests after source changes; small endpoint DTOs also need their explicit client guards.'),
'packages/report-core/README.md': ('Shared report semantics', 'Platform-neutral formatting, chart specifications, reviewed presentation domains, EN/SV report copy and `buildDossier()` live here. The Dossier reading model partitions the server-authorized projection in server order; it does not remeasure handwriting, compute rarity, choose new highlights or synthesize paid text.\n\nNative, web and print reuse semantics while owning their platform layout. Missing values stay missing, zero stays a value and evidence classes stay distinct. Read [architecture](../../docs/architecture/overview.md), [generated assets](../../docs/reference/generated-assets.md) and the package test scripts in [command inventory](../../docs/reference/command-inventory.md).'),
'packages/report-web/README.md': ('Web and print report components', 'React DOM presentation consumes shared report-core semantics and authorized projections. It is used by the web/print path, not as a universal native renderer. The report copy source is now report-core; preserve compatibility re-exports rather than forking translations.\n\nRead [accepted design](../../docs/design/ACCEPTED_DOSSIER_REFERENCE.md), [renderer](../../apps/render/README.md), [testing](../../docs/development/testing.md) and [generated assets](../../docs/reference/generated-assets.md). Never reconstruct an evidence histogram from aggregate mean/std, invent missing values or expose locked Premium fields in a Free view.'),
'packages/design-tokens/README.md': ('Canonical design tokens', 'Edit `tokens.json`; `tools/generate_design_tokens.py` produces the platform outputs. Run its `--check` after intentional regeneration. Tokens encode the accepted Dossier system, not permission to retrieve remote fonts or redistribute design assets.\n\nSee [accepted design](../../docs/design/ACCEPTED_DOSSIER_REFERENCE.md), [generated-source map](../../docs/reference/generated-assets.md) and [asset custody](../../docs/handover/access-and-assets.md). Native fallback typography is an explicit current limitation. Test light/dark, large text and evidence labels; color alone is not classification.'),
'migrations/README.md': ('PostgreSQL migration and role guide', 'The ordered source revisions are under `versions/`; the [generated migration inventory](../docs/reference/command-inventory.md#migration-inventory) lists their declared IDs and predecessors. Run upgrades through `python -m princess_app.adapters.postgres.migrate upgrade` with `PRINCESS_MIGRATION_DATABASE_URL`, not by executing individual revision files.\n\nFresh local role setup is in [local setup](../docs/development/local-setup.md). Runtime logins use reviewed application/worker group roles and must not own tables or have superuser/BYPASSRLS. The migration/admin connection is separate. Composite ownership and immutable report/evidence semantics are not optional client-side filters.\n\nBack up and qualify real provider migrations under their owner scope. Application rollback keeps the database forward and promotes a separately built previous application artifact; do not downgrade a populated schema as an incident shortcut. Follow [rollback/restore runbooks](../docs/runbooks/README.md). This documentation update adds no migration.'),
'src/princess_app/README.md': ('Source-tree product application', '`domain` and `application` own product semantics; `ports` define typed boundaries; `adapters` provide persistence/provider implementations. This code is intentionally outside the Free distribution and runs with the backend lock.\n\nRead [architecture](../../docs/architecture/overview.md), [lifecycles](../../docs/architecture/data-and-lifecycles.md), [connectors](../../docs/connectors/README.md) and [tests](../../docs/development/testing.md). In-memory/fake implementations remain fixtures, not a fallback for failed live configuration. Preserve RLS, leases, permission epochs, immutable publication, ledger uniqueness and forward deletion tombstones.'),
'src/princess_graphology/README.md': ('Deterministic numerical core', 'The root [measurement guide](../../README.md#measurement-engine) and [measurement methods](../../docs/measurement_methods.md) explain canonical IDs, units, estimands, frames, observation counts and missingness. There are 272 definitions but 64 registered methods at the handover baseline; synthetic tests do not establish empirical calibration.\n\nThe core has no product authentication, SQL or provider responsibility. Free adds no runtime learned model/OCR/provider call. The optional signature module stays isolated from Free. Preserve `_feature_contract.json` generation and installed-wheel tests; use the reviewed core lock for the matching interpreter/architecture.'),
'src/princess_contracts/README.md': ('Authoritative product construction', '`runtime.compile_document()` creates immutable validated product values; generated declarations alone are not validation. Cross-document projection and Premium-output checks preserve current authority and support confinement.\n\nEdit the reviewed source in [contracts/product/v1](../../contracts/product/v1/README.md), then follow [generation](../../docs/reference/generated-assets.md). Numerical definitions, interpretation source and policy/permission authority remain separate inputs. No contract generator activates a provider, a traditional association or a public reference claim.'),
'contracts/README.md': ('Product, HTTP and policy authorities', '[Product v1](product/v1/README.md) owns product wire schemas and generation. [Consent](consent/README.md) owns separately versioned draft policy/permission semantics. `http/openapi-components.json` is generated schema components, not a complete callable route reference.\n\nUse [current routes](../docs/reference/api.md) for actual handlers and [generated assets](../docs/reference/generated-assets.md) for edits. Approval, runtime activation and schema validity are different states. Do not alter consent decisions or source digests during documentation work.'),
'schema/README.md': ('Numerical and interpretation schema navigation', '`graphology_feature_database_v1.json` defines canonical numerical features. [Interpretation v1](graphology_interpretation/v1/README.md) is reviewed modular T26 source consumed by T15; it is not an active traditional inference system. `premium_interpretation_database_v1.json` is compiled output. Method capability source/resolution describes learned/provider dependency boundaries.\n\nRead [generated assets](../docs/reference/generated-assets.md), [measurement methods](../docs/measurement_methods.md) and the owning tests before edits. Do not equate a populated selector database with validated psychology or an approved model configuration.'),
'research/README.md': ('Research and historical evidence', '[Graphology research](graphology/README.md) navigates the immutable foundations import, historical construction handoff and current interpretation source. Research source fidelity is not empirical validation, runtime feasibility, population rarity or product approval.\n\nDo not bulk-format the frozen snapshot or change its hashes. The wrapper may explain later implementation without rewriting what the original research said. See [generated assets](../docs/reference/generated-assets.md) and [source rights](../docs/privacy/source-rights.md).'),
'provenance/README.md': ('Provenance and rights records', '[SOURCES.md](SOURCES.md) records origin and reuse decisions. The [license-text inventory](../docs/reference/component-index.md#retained-license-text-candidates) discovers retained records; inspect actual text and upstream/commit context before relying on it. [Third-party notices](../THIRD_PARTY_NOTICES.md) do not select a project-wide license.\n\nKeep code, data, weights, fonts and user-material rights separate. Do not rewrite source fidelity as commercial clearance or use a documentation patch to assign ownership.'),
'evaluation/README.md': ('Evaluation and protected data boundaries', '[Pilot tooling](../docs/data/pilot-tooling.md) explains synthetic metadata/partition mechanics and the human gate. `premium/README.md` distinguishes synthetic validator adversarial cases from actual live model evaluation. Real handwriting/participant agreements/provider responses stay in protected approved storage, not this repository.\n\nThe [test matrix](../docs/development/testing.md) and [reference/calibration roadmap](../docs/roadmap/02-corpus-benchmarks.md) describe missing empirical work. Do not count repeated captures as independent writers or synthetic fixtures as population evidence.'),
'fixtures/README.md': ('Synthetic and contract fixtures', 'Fixtures exercise interface, numerical, privacy and failure cases. They are not real participant counts or model-quality evidence. The owning generator/test determines how each family is updated; use [generation](../docs/reference/generated-assets.md) and [testing](../docs/development/testing.md).\n\nDo not overwrite immutable expected facts to hide a regression. No private handwriting, raw prompts, signed URLs, credentials or store proofs belong in public fixtures. Keep measured, proxy, reference, authored, traditional and AI evidence classes distinct.'),
'content/README.md': ('Authored content and collection prompts', 'Collection prompt/policy material under `collection` is separate from user specimens and from measured report facts. Read [privacy/collection](../docs/privacy/README.md) and the owning versioned manifests before changes.\n\nDraft copy and validated synthetic scenarios do not authorize participant recruitment or public processing. Product display copy/tokens have their own generation path in [generated assets](../docs/reference/generated-assets.md); never silently replace saved report meaning with new authored text.'),
'supabase/README.md': ('Supabase integration boundary', 'This directory is not proof that the entire Princess application backend is deployed on Supabase. The selected identity adapter lives under `src/princess_app/adapters/supabase`; application PostgreSQL migrations remain under `migrations`.\n\nRead the [provider decision](../docs/roadmap/19-provider-decision-register.md), [current handover](../docs/handover/current-state.md) and [T17 operator runbook](../docs/ci/T17_SUPABASE_STAGING_AUTH_OPERATOR_RUNBOOK.md). Only the protected selected staging verification profile is implemented/composed as recorded. Application login, provider lifecycle, full staging and production activation remain separate. No raw project references, credentials or protected receipts are added here.'),
'tools/README.md': ('Tools, generators and operator safety', 'The [generated command inventory](../docs/reference/command-inventory.md) lists tool paths and source descriptions; [command safety](../docs/reference/commands.md) distinguishes read-only, generating, mutating, destructive and protected operations. A script inventory is not permission to run every entry.\n\nUse [generated assets](../docs/reference/generated-assets.md) to find editable sources. Web/native journey scripts reset a loopback disposable database only with explicit opt-in. Provider evidence scripts require protected inputs and their own runbook. Documentation checks never execute arbitrary Markdown code fences.'),
'tests/README.md': ('Core and contract test suite', 'Default pytest discovery targets this directory through `pyproject.toml`. Use the reviewed interpreter/architecture lock and `python -m pytest -q tests`. These checks cover their implemented numerical/contracts/policy/research boundaries, not actual participant or native-device evidence.\n\nPostgreSQL integration lives separately in [tests_app](../tests_app/README.md). Documentation regressions use [tests_docs](../tests_docs/README.md); JavaScript tests use workspace scripts. Read the complete [test matrix](../docs/development/testing.md) and preserve adversarial cases rather than only testing happy paths.'),
'tests_app/README.md': ('PostgreSQL application tests', 'Run `python -m pytest -q tests_app` with `PRINCESS_TEST_DATABASE_URL` targeting a disposable real PostgreSQL database and the reviewed backend dependencies. These tests are not included by default `pytest` discovery.\n\nFollow [setup/testing](../docs/development/testing.md) for isolated roles/database. Do not run concurrently with destructive web/native E2E scripts against the same `princess_test`. RLS/transaction/fencing evidence must come from PostgreSQL, not an SQLite substitute. Real provider/store/device qualification is separate.'),
'tests_docs/README.md': ('Documentation checker tests', 'Run `python -m unittest discover -s tests_docs -p \'test_*.py\'`. These standard-library tests cover source-derived route inventories, broken links/anchors, missing paths/scripts, narrow frozen exclusions and reset refusal before external commands.\n\nThey do not import the application, execute arbitrary Markdown snippets, connect to a database, sign an app or call providers. The [documentation policy](../docs/documentation-policy.md) and read-only workflow describe exact scope.'),
'.github/README.md': ('Repository workflows', 'Current workflows are indexed in [command inventory](../docs/reference/command-inventory.md#workflows). Core CI is generated by `tools/render_ci_workflow.py`; do not edit its output independently. Application, runtime, release and native workflows prove distinct scopes.\n\nThe Documentation handover workflow is read-only and runs standard-library source/link/inventory checks plus explicitly safe tests. It never executes every code fence. Record exact candidate/head and review limitations. Workflow configuration does not prove branch protection or external account authorization; confirm those in [access handover](../docs/handover/access-and-assets.md).'),
}
for path, (title, body) in components.items():
    if (ROOT / path).exists():
        append(path, '## Maintainer navigation\n\n' + body)
    else:
        write(path, '# ' + title + '\n\n' + body)
append('apps/mobile/README.md', '## Maintainer handover\n\nUse the [complete host-specific setup](../../docs/development/local-setup.md) rather than assembling the abbreviated launch examples above. [Native lifecycle/private data](../../docs/architecture/mobile-lifecycle.md) documents session epochs, workflow recovery, signed upload URLs and cleanup. [Testing](../../docs/development/testing.md) distinguishes Node/controller integration from native UI/device/store qualification. [Current state](../../docs/handover/current-state.md) records #72 workflow evidence without inventing a Codex review. [Configuration](../../docs/reference/configuration.md) explains build-time values and runtime/provider limits.')
# Replace the original abbreviated mobile run examples with the complete recipe link.
mobile = read('apps/mobile/README.md')
start = mobile.index('```bash\n# API (see infra/README.md)')
end = mobile.index('```', start + 3) + 3
mobile = mobile[:start] + 'Follow [local setup](../../docs/development/local-setup.md) for complete locked backend/role/worker preparation and Android/macOS launch commands. The API and issued upload URLs must use the same device-reachable origin; do not paste a placeholder command as a shell recipe.' + mobile[end:]
# Keep actual test command pointer rather than a credential ellipsis.
mobile = re.sub(r'PYTHON=\.venv/bin/python PRINCESS_E2E_ADMIN_URL=postgresql://.*?tools/run_mobile_journey.sh[^\n]*', '# The destructive native API journey has a complete isolated recipe in docs/development/local-setup.md.', mobile, flags=re.DOTALL, count=1) if 'PYTHON=.venv/bin/python PRINCESS_E2E_ADMIN_URL=postgresql://' in mobile else mobile
write('apps/mobile/README.md', mobile)

# Explicitly ignore local-only tombstones introduced in the runnable recipe.
ignore = read('.gitignore')
if '.local-tombstones/' not in ignore:
    write('.gitignore', ignore.rstrip() + '\n# Local development tombstone evidence is private, never repository content.\n.local-tombstones/')

# Regenerate maintained outputs, then enforce documentation-only scope.
run('python3', 'docs/roadmap/plan_tools.py', '--write')
run('python3', 'tools/documentation.py', '--write')
after_tasks = json.loads(read('docs/roadmap/tasks.json'))
assert before_tasks['gate_registry'] == after_tasks['gate_registry']
assert before_tasks['validation_profiles'] == after_tasks['validation_profiles']
for before, after in zip(before_tasks['tasks'], after_tasks['tasks']):
    for key in ('id', 'status', 'depends_on', 'production_gates'):
        assert before[key] == after[key], (before['id'], key)

# Assert runtime Python semantic AST unchanged after stripping only docstrings.
def executable_ast(source):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body.pop(0)
    return ast.dump(tree, include_attributes=False)
assert executable_ast(run('git', 'show', BASE + ':src/princess_app/application/reports.py')) == executable_ast(read('src/princess_app/application/reports.py'))
before_js = run('git', 'show', BASE + ':apps/mobile/src/work/journal.ts')
strip_comments = lambda source: '\n'.join(line for line in source.splitlines() if not line.lstrip().startswith('//'))
assert strip_comments(before_js) == strip_comments(read('apps/mobile/src/work/journal.ts'))
for protected in ('research/graphology/foundations-v0.1', 'schema', 'contracts', 'migrations/versions', 'requirements', 'infra/environments'):
    changed = run('git', 'diff', '--name-only', BASE, '--', protected).splitlines()
    assert all(path.endswith('.md') for path in changed), ('protected data changed', changed)
for command in (
    ('python3', 'tools/documentation.py', '--check'),
    ('python3', 'docs/roadmap/plan_tools.py', '--check'),
    ('python3', '-m', 'unittest', 'discover', '-s', 'tests_docs', '-p', 'test_*.py'),
    ('python3', '-m', 'unittest', 'discover', '-s', 'docs/roadmap', '-p', 'test_plan_tools.py'),
    ('python3', 'tools/check_graphology_research.py'),
    ('bash', '-n', 'tools/run_mobile_journey.sh'),
    ('bash', '-n', 'tools/run_web_e2e.sh'),
):
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    print('$ ' + ' '.join(command), flush=True)
    print(result.stdout, flush=True)
    print(result.stderr, flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)

# Commit in reviewable groups, never the temporary payload/preparation workflow.
groups = [
 ('docs: reconcile post-72 scope and maintainer entry points', ['README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'AGENTS.md', 'ROADMAP.md', 'docs/README.md', 'docs/handover', 'docs/roadmap/tasks.json', 'docs/roadmap/06-agent-backlog.md', 'docs/roadmap/00-index.md', 'docs/roadmap/20-end-to-end-build-sequence.md']),
 ('docs: add reproducible setup testing and component navigation', ['.gitignore', 'docs/development', 'apps', 'packages', 'migrations/README.md', 'tests/README.md', 'tests_app/README.md', 'infra/README.md', 'requirements/README.md']),
 ('docs: document API architecture configuration and generated sources', ['docs/architecture', 'docs/reference', 'src', 'docs/roadmap/10-web-client-and-api-integration.md', 'docs/roadmap/11-mobile-architecture.md', 'docs/roadmap/16-testing-evals-and-quality-gates.md']),
 ('docs: correct operational interpretation and preserve research provenance', ['docs/runbooks', 'research', 'provenance', 'schema/README.md', 'contracts/README.md', 'contracts/consent/README.md', 'content/README.md', 'fixtures/README.md', 'evaluation/README.md', 'supabase/README.md', 'THIRD_PARTY_NOTICES.md', 'docs/design/ACCEPTED_DOSSIER_REFERENCE.md', 'docs/adr/README.md', 'docs/roadmap/19-provider-decision-register.md', 'docs/roadmap/01-data-architecture.md', 'docs/roadmap/02-corpus-benchmarks.md', 'docs/roadmap/03-premium-openai.md', 'docs/roadmap/04-reports-design.md', 'docs/roadmap/05-release-operations.md']),
 ('test(docs): check recursive links and source-derived references read-only', ['tools', 'tests_docs', 'docs/documentation-policy.md', '.github']),
]
for message, paths in groups:
    existing = [path for path in paths if (ROOT / path).exists()]
    run('git', 'add', '--', *existing)
    if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode:
        print(run('git', 'commit', '-m', message), flush=True)
assert not run('git', 'status', '--porcelain').strip(), 'unstaged files remain'
print('FINAL_DOCS_HEAD=' + run('git', 'rev-parse', 'HEAD').strip(), flush=True)
print(run('git', 'diff', '--stat', BASE), flush=True)
