# T11 pilot metadata tooling

Status: **synthetic qualification only; human pilot disabled.**

This slice implements the first engineering part of T11 under `evaluation/collection/`. It does **not** approve participant recruitment, collection, annotation, calibration or a corpus release. The canonical `pilot_rights_consent` gate and collection protocol are still pending owner review.

## Commands

```sh
python evaluation/collection/pilot_tool.py gate-status

python evaluation/collection/pilot_tool.py build-manifest \
  --mode synthetic \
  --input evaluation/collection/fixtures/source.synthetic.json \
  --capture-root evaluation/collection/fixtures \
  --consent-log evaluation/collection/fixtures/consent.synthetic.json \
  --output /tmp/pilot-manifest.json

python evaluation/collection/pilot_tool.py split-synthetic \
  --manifest /tmp/pilot-manifest.json \
  --consent-log evaluation/collection/fixtures/consent.synthetic.json \
  --output /tmp/pilot-splits.json
```

The synthetic split uses deterministic writer ranking and the engineering allocation weights `development=60`, `validation=20`, `holdout=20`. When at least three writers are present, every configured split receives at least one writer. These are partition mechanics, **not** evidence that a split is large enough for calibration or publication.

## Hard boundaries

- `build-manifest --mode human` refuses unless the real pilot gate, all required gate decisions, the protocol, participant notice and protocol purposes are genuinely approved. There is no `--force` escape hatch.
- Synthetic mode refuses a manifest marked human, and human mode refuses a synthetic manifest.
- Source capture paths are accepted only to hash local regular files beneath an explicit capture root. Paths and bytes never enter the emitted manifest.
- Input metadata is closed-shape and rejects obvious PII/path fields such as names, email, phone, address, birth date and signed-agreement content.
- IDs are opaque; the production generator takes no participant attributes. Deterministic IDs are available only for synthetic fixtures.
- Synthetic manifests are passed through the existing `collection_consent_context(..., fixture_mode=True)` and `check_fixture_collection_manifest` semantics. This tool does not create a second eligibility policy.
- Writer-disjoint plans inherit a writer's split across every eligible specimen, session and capture. The worklist contains opaque IDs and a protected/synthetic asset reference only—never an image path.
- Human release authority remains `compile_release_policy -> collection_consent_context -> check_collection_manifest` with protected ledger/evidence. This PR does not implement or bypass that boundary.

## Public fixture safety

The checked-in T11 fixtures are tiny text files labelled synthetic. They are only byte sources for hashing and provenance tests; they contain no handwriting, participant data or signed consent material. Real pilot pages, agreements, identities and annotation evidence must remain in protected storage and must never be committed or uploaded as CI artifacts.

## Next T11 work

After owner/legal/privacy approval, humans still need to recruit actual eligible writers, collect rights-cleared controlled/free specimens and repeats, run protected annotation with disagreement review, freeze real writer-disjoint evaluation evidence, exercise withdrawal/deletion, and record real recruitment-bias and count evidence. None of those facts can be inferred from this synthetic tooling.
