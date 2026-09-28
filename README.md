<!-- roadmap-v2-navigation -->
> **Building the app:** [complete roadmap](ROADMAP.md) · [coding-agent entry](AGENTS.md) · [documentation index](docs/roadmap/00-index.md) · [detailed task briefs](docs/roadmap/06-agent-backlog.md) · [Claude Design handoff](docs/design/CLAUDE_DESIGN_HANDOFF.md).
> **Status:** active development, not publicly released. `docs/roadmap/tasks.json` is the machine authority for current task state and gates.

# Inktrospect

> Repository/internal codename: **You Are A Special Little Princess**. Existing `Princess` / `princess_*` package and service namespaces remain implementation details while the public brand is finalized through T10 design acceptance.

A privacy-conscious consumer handwriting-analysis product built around deterministic
handwriting measurements, structured evidence and clearly separated interpretive
layers. Product scope includes web, native iOS/iPad and Android phone/tablet,
PDF/share rendering, optional bounded Premium synthesis and a protected
reference/calibration programme.

The brand is playful; the evidence boundary is not. Numerical measurements remain
authoritative for measurable quantities. Traditional graphology and AI synthesis are
separately labelled and are not validated psychological assessment.

## Current implementation snapshot

| Area | Current state |
|---|---|
| Canonical numerical schema | 272 feature definitions; 64 registered core measurements |
| Deterministic Free engine | Implemented; zero runtime AI by design |
| PostgreSQL/RLS product backend | Implemented provider-independently |
| Free web journey | Implemented with saved history, evidence, settings and accessibility coverage |
| PDF/share-card rendering | Implemented from saved authorized projections |
| Premium runtime | Provider-independent packet/compiler/validator/runtime implemented; live model activation still gated |
| Commerce | Internal ledger/reservation/fulfilment machinery implemented; real Stripe/App Store/Play verification remains gated |
| Recovery/notifications | Tombstones, restore reconciliation and notification state machine implemented; production providers/topology remain incomplete |
| Pilot tooling | Synthetic-qualified, human mode fail-closed behind rights/participant gates |
| Product design | Working public brand **Inktrospect**; Direction A — The Dossier selected and app prototype in progress; owner `design_acceptance` still pending |
| Native clients | Planned; T29 unlocks after T10 design acceptance |

Current task status is intentionally not duplicated here; run:

```bash
python docs/roadmap/plan_tools.py --ready
python docs/roadmap/plan_tools.py --active
```

## Product architecture

```text
private image
    ↓
safe intake + immutable capture
    ↓
deterministic measurement engine
    ↓
EvidenceBundle + immutable ReportDocument
    ↓
server-authorized projection
    ├── web
    ├── PDF / share card
    ├── native clients (planned)
    └── optional bounded Premium synthesis
```

Free uses no runtime learned model or generative provider. Premium starts from the
same authorized image/evidence, cannot overwrite canonical measurements, and saves
a validated overlay. Reopening, exporting or sharing a saved report does not call a
model.

## Repository map

```text
src/princess_graphology/     deterministic numerical core
src/princess_app/            product domain/application/adapters
apps/api/                    FastAPI application surface
apps/web/                    Next.js Free web product
apps/render/                 PDF/share-card renderer
apps/workers/                durable background workers
packages/contracts/          generated product DTOs
packages/api-client/         typed client + runtime guards
packages/report-core/        presentation semantics/formatting
packages/report-web/         React report/print components
packages/design-tokens/      cross-platform design tokens
evaluation/collection/       gated pilot tooling
docs/                        roadmap, design, privacy, connectors and operations
```

## Scientific and product boundaries

- Missing is not zero; unavailable facts carry explicit reasons.
- Experimental is not validated; synthetic tests do not establish population accuracy.
- Static darkness/thickness are image proxies, not physical pen pressure.
- No diagnosis, intelligence, deception, criminality, employment suitability,
  authorship identification or relationship-outcome claim is permitted.
- A percentile/rank/rarity claim requires an eligible, validated reference release.
- Traditional associations remain source/school-labelled and runtime-inactive unless
  separately approved.
- Clients never become a second measurement, entitlement or credit authority.

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
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
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
