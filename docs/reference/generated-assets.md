# Source → generator → output

Edit the source authority, regenerate only the intended output, review the diff and run its check. An output file is not a second authority. Preserve frozen research and historical receipt bytes.

| Authority / editable input | Generator | Output / validation |
|---|---|---|
| Numerical feature database and reviewed core contract inputs | `tools/generate_feature_contract.py` | Packaged `_feature_contract.json`; `--check` detects drift |
| `contracts/product/v1` schemas plus bound feature/T26/purpose/method authorities | `tools/generate_product_contracts.py` | Product manifest, Python and TS declarations, OpenAPI components and resolved capabilities; `--check` |
| `schema/graphology_interpretation/v1` modular source | `tools/compile_premium_interpretation_db.py` | `schema/premium_interpretation_database_v1.json`; `--check` plus integrity/ontology/selector/traditional/database validators |
| `packages/design-tokens/tokens.json` | `tools/generate_design_tokens.py` | Generated platform token outputs; `--check` |
| `docs/roadmap/tasks.json` | `docs/roadmap/plan_tools.py --write` | `docs/roadmap/06-agent-backlog.md`; `--check` verifies graph and generated text |
| Literal API decorators/request models, manifests, migrations, package scripts and tracked command sources | `tools/documentation.py --write` | `docs/reference/api-routes.md`, environment/command/component inventories; `--check` |
| `requirements/ci-targets.json` and reviewed workflow policy | `tools/render_ci_workflow.py` | `.github/workflows/ci.yml`; `--check` verifies exact policy output |
| Exact interpreter/platform dependency manifest | `tools/generate_ci_lock.py` | Candidate hash lock for that reviewed host; review hashes and complete dependency tests before accepting |
| Frozen research snapshot/import manifest | `tools/check_graphology_research.py` | Integrity check; `--assemble-dir` reconstructs an original package into a new directory, not a production interpretation generator |
| Report fixture sources and generators | `tools/generate_report_fixtures.py` and owning fixture tooling | Synthetic report/evidence fixtures; see script inventory and owning tests before regenerating |
| Protected T17 evidence | Dedicated runtime/settings/cleanup builders in `tools/` | Git-safe projections only; real protected inputs and exact frozen witness required. Generation is not approval |

The tool inventory checks that registered generator paths exist. This table describes ownership; inspect each parser for its exact accepted flags. Do not assume every generator has `--write` or every validator accepts `--help`.

## Schema components versus endpoints

The product generator's `contracts/http/openapi-components.json` is an OpenAPI schema-components artifact. It is not a complete method/path/authentication inventory. The [API route table](api-routes.md) is derived from actual FastAPI decorators and request models; [API semantics](api.md) documents ownership, errors and retries. Both must remain consistent when an endpoint changes.

## Research and approval preservation

T26 and T15 structure/consumer implementation are recorded DONE, with runtime traditional activation still false. Do not rebuild T26 because an old import README describes it as future work. The immutable `research/graphology/foundations-v0.1` snapshot is verified byte-for-byte and must not be reformatted by docs tools.

No generator selects a project license, approves a policy, creates real participant evidence or qualifies a live provider. Generated documentation explicitly labels target configuration and planned tasks; it does not convert them into runtime capability.

## Maintenance checks

```bash
python tools/generate_feature_contract.py --check
python tools/generate_product_contracts.py --check
python tools/compile_premium_interpretation_db.py --check
python tools/generate_design_tokens.py --check
python tools/check_graphology_research.py
python docs/roadmap/plan_tools.py --check
python tools/documentation.py --check
```

Use the complete CI matrix for dependency policy, installed-wheel and application/native verification. If a source change makes generated output drift, review and regenerate that output; never edit a hash by hand to make a validator pass.
