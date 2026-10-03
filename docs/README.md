# Inktrospect documentation

Start here to maintain the mobile-first product. The repository contains a working development client and substantial shared services; it is not a publicly released or fully provider-qualified application.

## Choose a reading path

| Need | Read in order |
|---|---|
| Take over the project | [Handover](handover/README.md) → [current state](handover/current-state.md) → [access and assets](handover/access-and-assets.md) → [acceptance](handover/acceptance.md) |
| Run the app | [Local setup](development/local-setup.md) → [mobile README](../apps/mobile/README.md) → [troubleshooting](development/troubleshooting.md) |
| Change native behavior | [Mobile lifecycle](architecture/mobile-lifecycle.md) → [native source](../apps/mobile/src/) → [testing](development/testing.md) |
| Change the backend | [Architecture](architecture/overview.md) → [data and lifecycles](architecture/data-and-lifecycles.md) → [API](reference/api.md) → [migrations](../migrations/README.md) |
| Diagnose an incident | [Commands and safety](reference/commands.md) → [runbooks](runbooks/README.md) → [runtime topology](../infra/runtime/README.md) |
| Change schemas, copy or tokens | [Generated assets](reference/generated-assets.md) → the linked source authority → its generator and regression tests |
| Decide what to build next | [Roadmap](../ROADMAP.md) → [task graph](roadmap/tasks.json) → generated [task briefs](roadmap/06-agent-backlog.md) |

## Reference map

[Current routes and request models](reference/api-routes.md) · [build/runtime configuration](reference/configuration.md) · [declared environment matrix](reference/environment-matrix.md) · [tool/package command inventory](reference/command-inventory.md) · [repository workflows](../.github/WORKFLOWS.md) · [component navigation](reference/component-index.md).

The original specialist documentation remains useful:

- [Measurement methods](measurement_methods.md), [numerical feature authority](../schema/graphology_feature_database_v1.json), [interpretation database](../schema/graphology_interpretation/v1/README.md), and [research](../research/graphology/README.md).
- [Accepted Dossier design](design/ACCEPTED_DOSSIER_REFERENCE.md), [connectors](connectors/README.md), and [architecture decisions](adr/README.md).
- [Privacy/consent drafts](privacy/README.md), [pilot tooling](data/pilot-tooling.md), [release requirements](roadmap/21-release-readiness-checklists.md), and [programme signoff](release/multi-platform-signoff.md).

## Which source wins?

Implementation behavior is established by source and tests, not by a proposed endpoint in a roadmap. Wire schemas, measurement definitions, interpretation source, tokens and privacy policies retain their distinct authorities. Generated artifacts are outputs, not alternate editing locations. Task state belongs to `docs/roadmap/tasks.json`; the handover snapshot is dated evidence, not a second task database. Provider, policy, signing and release approvals require their own scoped records.

Historical records and frozen research must remain historically accurate. Read current wrapper navigation before acting on an old plan. A green build does not establish empirical accuracy, physical-device behavior, a store transaction or production approval.

See [documentation maintenance](documentation-policy.md), [contributing](../CONTRIBUTING.md) and [security](../SECURITY.md).
