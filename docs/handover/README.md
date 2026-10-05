# Receiving-maintainer handover

This is the route for an engineer who has not read the development chats. Public product name: **Inktrospect**. `Princess`, `princess_*` and the repository name are internal namespaces; do not rename APIs/packages as an incidental cleanup.

## First reading and execution order

1. Read [current state](current-state.md). Separate code present, checks executed, capabilities enabled and approvals still pending.
2. Read [architecture](../architecture/overview.md) and [data/lifecycle boundaries](../architecture/data-and-lifecycles.md). Follow one capture from the phone to its saved report before changing a state machine.
3. To install the current standalone Android build, use the [Android APK quick start](android-apk.md). For the full environment, follow [local setup](../development/local-setup.md) on a supported host with synthetic data and run the [test layers](../development/testing.md) appropriate to your change.
4. Read the [mobile lifecycle guide](../architecture/mobile-lifecycle.md), [API reference](../reference/api.md) and [generated-source map](../reference/generated-assets.md).
5. Resolve access and custody with the outgoing owner using [access and assets](access-and-assets.md). Never collect secrets through a PR, issue or chat transcript.
6. Complete the [receiving-maintainer acceptance](acceptance.md) record. Documentation merging does not fill this record automatically.

The [documentation audit disposition](documentation-changes.md) maps all 18 findings to the implemented guides and separates remaining external/recipient acceptance.

## Useful development commands

From the repository root, after the applicable setup:

```bash
python tools/documentation.py --check
python docs/roadmap/plan_tools.py --active
python docs/roadmap/plan_tools.py --task T30A
pnpm --filter @princess/mobile typecheck
pnpm --filter @princess/mobile test
```

`--active` reports unfinished work, not release permission. The local native API journey is a separate, deliberately destructive disposable-database test; read its prerequisites before executing it.

## Before your first change

Record the actual base SHA and check other open PRs. Use the [contribution workflow](../../CONTRIBUTING.md), keep shared contracts and generated consumers together, and test both successful and interrupted/revoked behavior. Code and documentation must describe the same capability. Do not turn a disabled or fake-backed adapter into a live one merely to simplify a demonstration.

Mobile construction is the priority. The web client is still a supported regression surface, but unfinished web Premium is not a prerequisite for shared native construction. Mobile release and full multi-platform programme completion remain separate decisions.

## Handover completion boundary

The documentation can be implemented and automatically checked while recipient access, fresh-machine onboarding, device tests and external approvals remain open. Record exactly which part has been completed. No person, account access, test execution or approval is inferred from a checked template.
