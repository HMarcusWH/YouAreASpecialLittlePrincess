# 00 — Navigation, authority and current scope

[Home](../../ROADMAP.md) · [Agent entry](../../AGENTS.md) · [Tasks](06-agent-backlog.md) · [Machine graph](tasks.json) · [Ready work](20-end-to-end-build-sequence.md).

## Read by responsibility

| Reader/work | Required route |
|---|---|
| Any coding agent | AGENTS → this index → task JSON/brief → owning specs → tests/release gates. |
| Contract/engine | [01 Data](01-data-architecture.md), [08 T26](08-premium-question-selector-database.md), [09 Boundaries](09-connectors-and-provider-boundaries.md), [16 Tests](16-testing-evals-and-quality-gates.md). |
| Backend/platform | [05 API/operations](05-release-operations.md), [09 Ports](09-connectors-and-provider-boundaries.md), [15 Environments](15-environments-deployment-and-secrets.md), [17 Security](17-security-privacy-and-abuse.md), [18 Operations](18-observability-support-and-cost-control.md). |
| Web/render/design | [04 Reports](04-reports-design.md), [10 Web](10-web-client-and-api-integration.md), [16 Tests](16-testing-evals-and-quality-gates.md), [web release](../release/web.md). |
| Native | [11 Mobile](11-mobile-architecture.md), [12 Apple](12-apple-platform-and-app-store.md), [13 Android](13-android-and-google-play.md), [14 Commerce](14-payments-entitlements-and-commerce.md), [push](../connectors/push.md), [identity](../connectors/identity.md). |
| Data/evaluation | [02 Corpus](02-corpus-benchmarks.md), [03 Premium](03-premium-openai.md), [08 T26](08-premium-question-selector-database.md), [16 Tests](16-testing-evals-and-quality-gates.md), [17 Privacy](17-security-privacy-and-abuse.md), [T03 consent/collection drafts](../privacy/README.md). |
| Commerce | [14 Ledger](14-payments-entitlements-and-commerce.md), [payment adapters](../connectors/payments.md), [12 Apple](12-apple-platform-and-app-store.md), [13 Android](13-android-and-google-play.md). |
| Release owner | [19 Decisions](19-provider-decision-register.md), [21 Gates](21-release-readiness-checklists.md), [release index](../release/multi-platform-signoff.md). |

## Complete chapter map

01 [Data architecture](01-data-architecture.md) · 02 [Corpus/benchmarks](02-corpus-benchmarks.md) · 03 [Premium orchestration](03-premium-openai.md) · 04 [Reports/design](04-reports-design.md) · 05 [API/operations](05-release-operations.md) · 06 [Generated agent backlog](06-agent-backlog.md) · 07 [Original evidence register](07-evidence-register.md) · 08 [Reviewed interpretation handoff](08-premium-question-selector-database.md).

09 [Connectors/module ownership](09-connectors-and-provider-boundaries.md) · 10 [Web/API](10-web-client-and-api-integration.md) · 11 [Mobile architecture](11-mobile-architecture.md) · 12 [Apple suite](12-apple-platform-and-app-store.md) · 13 [Android suite](13-android-and-google-play.md) · 14 [Commerce](14-payments-entitlements-and-commerce.md) · 15 [Environments/secrets](15-environments-deployment-and-secrets.md) · 16 [Tests/evals](16-testing-evals-and-quality-gates.md) · 17 [Security/privacy](17-security-privacy-and-abuse.md) · 18 [Operations/cost](18-observability-support-and-cost-control.md) · 19 [Provider decisions](19-provider-decision-register.md) · 20 [Build sequence](20-end-to-end-build-sequence.md) · 21 [Readiness](21-release-readiness-checklists.md) · 22 [Refreshed primary sources](22-research-and-source-refresh.md).

[Connector index](../connectors/README.md) · [ADR index](../adr/README.md) · [Web release](../release/web.md) · [Apple release](../release/apple.md) · [Android release](../release/android.md) · [Multi-platform signoff](../release/multi-platform-signoff.md).

## Authority and explicit amendments to v1.1

The technical content in chapters 01–05 and original source register 07 is retained, with current-scope navigation notices. Do not silently discard its numerical, privacy or failure-handling requirements. The following explicit amendments take precedence over its historical implementation/status sentences:

1. Native iOS and Android, including their digital billing, are now required programme deliverables. Web is an early validation surface, not the entire v1 completion criterion.
2. The code baseline is `251668a…`, not the earlier PR #1 baseline. T00 and T26 are historically DONE; T00A is an outstanding follow-up. Statements that all tasks are planned or that the T26 database is empty are superseded.
3. T26 source JSON and compiler are authoritative. Use `selection_domain` and `cardinality`, not old illustrative `selection_mode` examples. Traditional runtime eligibility is still zero; reviewed database structure does not activate content.
4. Earlier model aliases, prices and API snippets are dated research/examples, not approved production configuration. [22](22-research-and-source-refresh.md) and the provider decision process govern new integration work. No particular model or price is approved by this PR.
5. JSON Schemas own product wire DTOs. Generated Python/TypeScript representations and derived OpenAPI must be drift-tested. This is separate from the 272-feature numerical schema, which is unchanged.
6. Web and print share web render components. Native screens share semantic projections, chart specifications and formatting—not an assumed universal DOM renderer.
7. Store purchase completion grants a durable credit before slow AI work. App credit reservation is not store consumable consumption. Cross-platform access and credit portability remain subject to approved product/storefront policy.
8. The dependency graph in [tasks.json](tasks.json) supersedes the old conceptual diagrams and parallel-start list. T19 does not depend on mobile clients; T32/T33 do not gate backend construction; T25 waits for platform readiness.

If another inconsistency is found, record a scoped amendment and update linked acceptance tests. Do not silently pick whichever document is easiest to satisfy.

## Status vocabulary

`status` in tasks refers to task completion, not whether a production flag is enabled. Default pending tasks are `PLANNED`; a steward may move them through `IN_PROGRESS`, `IMPLEMENTED_PENDING_REVIEW` and `DONE`, with `BLOCKED` for explicit blockers. `READY` is a computed property: all hard predecessors DONE, not a stored status. Human gates have their own evidence, decision owner, date, scope and approval. An implemented mock adapter can remain production-disabled.

Paths listed as `owned_paths` or `artifacts` are planned implementation targets unless present in the code tree. Links under `required_docs` must resolve now. Task commands distinguish currently existing checks from `TO_IMPLEMENT` suites. Do not create fake test files just to make a roadmap checkbox green.

## Maintenance

Edit task details in [tasks.json](tasks.json), run `python docs/roadmap/plan_tools.py --write`, then `--check`. The generated [backlog](06-agent-backlog.md) includes coding order, contract handoff, negative tests, gates and rollback for every task. The validator also checks local documentation links. A dedicated read-only documentation workflow runs it without production secrets.
