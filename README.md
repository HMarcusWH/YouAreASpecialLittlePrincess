# Inktrospect

A mobile-first, privacy-conscious handwriting-analysis product built around deterministic measurements, structured evidence and separately labelled interpretive layers. Public brand: **Inktrospect**. `YouAreASpecialLittlePrincess`, `Princess` and `princess_*` are internal repository/package names, not instructions to rename existing contracts.

**Status: active development, not publicly released.** The shared native client is implemented through T30A; real identity, purchases, push, device and store qualification remain unfinished. [Current handover snapshot](docs/handover/current-state.md) records the post-#76 baseline, the standalone Android developer handoff and the remaining limitations. [tasks.json](docs/roadmap/tasks.json) remains the task/dependency authority.

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

### Deferred operational follow-up — T17 Supabase staging Auth closeout

The selected Supabase staging identity profile is implemented and production-disabled, but its final live evidence
run is intentionally deferred. **This blocks T17 identity closeout / login activation; it does not block
continued construction of unrelated or disabled/fake-backed product work.** Revisit this checklist before claiming
the staging Auth gate complete:

- run the frozen runtime conformance witness from clean commit
  `c653a7d0cc29e0398a0cfb9e5c8113b9b2acd6b3` and retain the protected receipt plus Git-safe PASS index;
- capture the selected project's exact raw `GET /v1/projects/{ref}/config/auth` response byte-for-byte outside Git
  and generate `docs/ci/T17_SUPABASE_AUTH_SETTINGS_SNAPSHOT.json` using `supabase-auth-settings/3`;
- before destructive cleanup, run the hardened closeout checker with that same protected raw Auth-config response
  and require the only failure to be `cleanup_evidence_missing`;
- revoke all sessions and refresh state for the one disposable witness identity, verify that revocation, then delete
  that disposable Auth user; do not decommission the Princess staging project;
- generate `docs/ci/T17_SUPABASE_STAGING_CLEANUP_EVIDENCE.json` from the protected cleanup attestation and exact
  protected conformance receipt;
- require final `tools/check_supabase_staging_auth_closeout.py --auth-config-file <protected raw config>` PASS;
- keep application login and production activation disabled until their later explicit implementation/approval
  gates are satisfied.

The step-by-step operator procedure remains authoritative in
[`docs/ci/T17_SUPABASE_STAGING_AUTH_OPERATOR_RUNBOOK.md`](docs/ci/T17_SUPABASE_STAGING_AUTH_OPERATOR_RUNBOOK.md).

## Measurement engine

Deterministic handwriting-image descriptors with a schema-enforced interface.
**272 defined features ≠ 272 implemented or validated features.** The core currently
registers **64 features**; 208 remain definition-only. Unavailable implemented
features return explicit missing records, not invented numbers.

### Architecture

```text
image → preprocessing → line/word/component segmentation
      → shared MeasurementContext (including experimental x-height)
      → quality / segmentation / size / layout / baseline / spacing / slant / ink
      → AnalysisResult → runtime schema + region validation → canonical JSON
```

`GraphologyEngine` orchestrates the pipeline; extractors share immutable image
arrays and segmentation primitives. Duplicate IDs, unknown IDs, wrong units,
invalid types/ranges, non-finite values and broken region references fail loudly.
The 272-feature database is authoritative; a generated, packaged 29 KB projection
provides the runtime contract. CI checks that it has not drifted.

### Install and run

```bash
# Reviewed Linux x86_64 / Python 3.12 core environment, not a backend install.
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: --no-deps -r requirements/ci-py312.lock
python -m pip install --no-index --no-deps --no-build-isolation -e '.[dev]'
python tools/generate_feature_contract.py --check
ruff check src tests tools
pytest -q
princess-graphology path/to/handwriting.png --pretty
```

```python
from princess_graphology import GraphologyEngine

result = GraphologyEngine().analyze_file('handwriting.png')
print(result.to_json())  # Validated again; strict JSON, no NaN/Infinity.
```

The CLI accepts grayscale, BGR and BGRA uint8 images; alpha is composited on white.
Original image dimensions are separate from analysis-canvas dimensions. Result
metadata supplies both affine coordinate maps and method/frame caveats.

### A real fixture result

The following is an excerpt from the committed synthetic text fixture, not an
invented confidence example. Run `tools/example_result.py` to regenerate it.

```json
{
  "X_HEIGHT_PX": {
    "raw_value": 17.0,
    "unit": "px",
    "confidence": null,
    "n_observations": 48,
    "method_version": "component_height_mode_v1",
    "quality_flag": "EXPERIMENTAL"
  },
  "WORD_SPACING_REL": {
    "raw_value": 1.1470588235294117,
    "unit": "xheight_ratio",
    "confidence": null,
    "n_observations": 4,
    "method_version": "accepted_box_gap_rel_v1",
    "quality_flag": "EXPERIMENTAL"
  }
}
```

`confidence: null` means **uncalibrated**, not zero confidence. Missing observations
have `raw_value: null`, `quality_flag: MISSING`, and a reason. Only decoded-input
metadata calculations currently have exact conditional confidence. No detector
confidence is manufactured from a sample count or aesthetic regularity.

### Implementation and evidence status

| Status | Meaning |
|---|---|
| DEFINED | Database feature exists, but no method is registered. |
| IMPLEMENTED | Executable method is registered; contract/numerical tests exist. |
| EXPERIMENTAL | Implemented estimate/index still lacks real-data accuracy calibration. |
| VALIDATED | Reserved for documented empirical validation; synthetic tests are insufficient. |

The four input-size metadata features are exact conditional on the decoded array.
Other core estimates are experimental; none are claimed empirically validated.
See [measurement methods](docs/measurement_methods.md) for formulas, denominators,
coordinate frames, minimum observations, sign conventions and known limitations.

The deterministic measurement core itself adds no OCR, product UI, runtime
personality inference or pretrained signature weights. Those product/application
surfaces live outside `src/princess_graphology/`. The optional SigNet architecture
and independently implemented z-score/cosine/Euclidean/Mahalanobis utilities remain
separate.

### Source decisions and scientific boundary

Preprocessing adapts NitinRamchandani/ocr-preprocessing-tool; word proposals adapt
githubharald/WordDetector. Titan's legacy thresholds are historical references,
not a trained personality classifier. JJ Shay is a comparison/statistical design
reference, not the source of production comparison mathematics. The selected
optional signature architecture is **luizgh/sigver**, without pretrained weights.
See [deployment provenance](schema/implementation_sources.json),
[source notes](provenance/SOURCES.md) and `THIRD_PARTY_NOTICES.md`.

Static darkness/thickness are image proxies, **not physical pen pressure**.
Traditional graphology interpretation remains separate and must not be represented
as validated psychological assessment. Passing a schema test proves interface
consistency, not handwriting-estimation accuracy or personality validity.

Breaking bootstrap change: do not rename old JSON fields and reuse their values.
Re-analyze source images; margins, CVs, thickness sampling and frames changed.
