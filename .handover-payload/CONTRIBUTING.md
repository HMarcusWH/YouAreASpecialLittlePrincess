# Contributing to Inktrospect

Start with the [documentation home](docs/README.md), [current handover](docs/handover/current-state.md) and [local setup](docs/development/local-setup.md). For automation-specific boundaries also read [AGENTS.md](AGENTS.md).

## Before changing code

Read current `main`, open PRs and the owning task. Record the base commit and proposed scope. Use `python docs/roadmap/plan_tools.py --active` and `--task ID`; the graph's status is not production permission. Mobile construction is prioritized under T30A and T30/T31. Web remains a regression surface, not a prerequisite for writing the native product.

Use one branch per cohesive change, state owned paths and share DTO/migration/worker changes with other maintainers. An unmerged PR is not a dependency. Fakes may unblock explicitly fake-backed construction, not claimed live integration.

## Development and tests

Use reviewed runtime versions and locked installations. The core wheel intentionally excludes `princess_app`; application code runs from the source tree with its separate backend lock. The [test guide](docs/development/testing.md) lists real commands and prerequisites. Default `pytest` covers `tests`, not the separately invoked PostgreSQL `tests_app` suite.

For schemas, tokens, interpreted content and generated docs, follow [source → generator → output](docs/reference/generated-assets.md). Never hand-edit generated artifacts or regenerate a lock merely to hide a failure. Use synthetic or explicitly authorized engineering fixtures; no real participant writing in Git.

## PR record

Include task ID, baseline, scope and non-goals; changed contracts and compatibility; actual commands/results; fixture/source rights; security/privacy failure cases; review disposition; rollback and explicit remaining work. A green job is evidence only of what that job executes. Distinguish controller tests, app UI, compilation, devices, provider sandbox and empirical evidence. If a reviewer was quota-blocked, record that instead of claiming approval.

Keep documentation changes with the behavior they describe. Read-only documentation checks must pass; new API routes and configuration changes regenerate the relevant reference inventories. Do not merge failures or weaken checks to bypass them.

## Review priorities

Preserve canonical measurements, missingness and coordinate lineage; server ownership and credit authority; purpose-specific permission; account-switch and deletion fencing; idempotent business outcomes under duplicated/reordered events; and separate store completion from slow Premium work. Free remains zero runtime AI. A timeout does not prove no external effect occurred.

Never put credentials, private writing, signed upload URLs, store proofs, prompts/responses, protected receipts or production dumps in code, logs or PRs. Report sensitive findings using [SECURITY.md](SECURITY.md).

## Rights and approval boundary

This guide does not select a project license, transfer ownership, authorize publication or clear third-party assets. The repository has no owner-selected project license at this handover baseline; ask the product/technical owner for the applicable distribution and contribution terms. Preserve [third-party notices](THIRD_PARTY_NOTICES.md), frozen research and separate code/data/weights/font rights.

Provider accounts, spending, prices, privacy policies, participants, signing and release remain explicit owner decisions. Do not modify their approval fields as part of documentation maintenance.