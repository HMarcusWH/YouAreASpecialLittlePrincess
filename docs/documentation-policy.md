# Documentation maintenance policy

Documentation describes the implementation and its evidence without changing approval. Start at [docs/README.md](README.md). The [task graph](roadmap/tasks.json), schemas, provider decisions and frozen research keep their existing authority.

## Maintain one editable source

Use [generated assets](reference/generated-assets.md) to find the source, generator and check. Do not manually edit generated API route/request tables, environment/command inventories or the backlog. Historical receipts stay historical; update current wrapper navigation instead of changing frozen SHA values or approvals.

New maintained documents must have a purpose, a discoverable incoming link, real source references and explicit status where a procedure is only planned. Prefer one current implementation reference over repeated status tables. Keep historical path/anchor compatibility when reorganizing.

## Automated scope

```bash
python tools/documentation.py --write
python tools/documentation.py --check
python -m unittest discover -s tests_docs -p 'test_*.py'
```

The generator uses Python AST and JSON/package metadata, not runtime application imports, external network calls or provider credentials. The checker scans repository Markdown recursively while ignoring build/cache directories. It excludes the exact immutable `research/graphology/foundations-v0.1/` tree from rewriting/link normalization; that tree retains its own byte-integrity checks. Links *to* frozen material must still resolve. Any inherited historical-link exception is recorded explicitly with its reason rather than silently ignored.

The checked outputs cover literal decorated API routes, source request-model fields, environment declarations, package scripts, Python tool inventory, migrations and component entry pages. AST-derived route presence is not proof of runtime composition, authorization correctness or release approval. Environment manifests can describe unimplemented target modes; the runtime preflight is stricter.

The checker validates an explicit inventory of critical source/script paths and selected package-script names. It does not pretend that every inline code fragment is a runnable command. It never runs arbitrary Markdown fences. Shell syntax and reset-refusal controls are separately allowlisted in the read-only workflow.

## Evidence and command labeling

State the working directory, prerequisites, role/environment, destructive or billable effects, expected output and cleanup for executable recipes. Use complete commands for supported local recipes. Place placeholders only in explicitly labelled operator templates; never present `$API_ENV command` as if an undefined shell expansion were a portable setup.

Keep these distinctions visible: source reviewed, syntax checked, unit tested, integration tested, app UI exercised, physical-device tested, provider-qualified, approved and released. An independent recipient record remains pending until that recipient executes it. Do not auto-fill names, accounts, effective policy dates, model IDs, prices, provider approvals or test outcomes.

## Review checklist

Every behavior change updates its owning docs, generated route/config references when affected, and tests. Documentation-only work must preserve frozen research, policy/approval data, dependency locks, migration contents and executable runtime behavior. New runtime defects discovered while checking recipes get separate fixes. Current external provider/store research is refreshed by its owning task, not by silently changing dates in old source registers.
