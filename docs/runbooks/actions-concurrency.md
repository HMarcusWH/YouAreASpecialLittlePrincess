# GitHub Actions PR concurrency and main-branch preservation

**Status:** Implemented scheduling policy; no runtime, deployment, release, or handwriting-algorithm change. The authoritative source is the seven workflow files and `tools/render_ci_workflow.py` for generated `ci.yml`.

## Approved workflow-level policy

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

The same root-level policy applies to `ci.yml`, `app.yml`, `native.yml`, `runtime.yml`, `release-compat.yml`, `documentation.yml` and `roadmap.yml`. Preserve their triggers, path filters, permissions and jobs.

- `github.workflow` isolates workflow families. Concurrency groups are case-insensitive, so workflow names must also be unique ignoring case.
- `github.event_name` separates PR and push events.
- `github.event.pull_request.number` selects the PR's group across eligible commits.
- `github.run_id` gives different non-PR runs unique fallback groups.
- `cancel-in-progress` cancels only competing PR runs.

The separate `railway-guest-apk.yml` workflow is `workflow_dispatch` only, exact-SHA-pinned and dependent on verified Railway backend provenance; it must not inherit PR cancellation. Publishing, signing and deploying similarly require their own approval before any scheduling change.

GitHub normally allows one running and one pending execution per group. A newer pending run can replace another pending run **even when** `cancel-in-progress` is false. Distinct `main` pushes therefore need distinct groups, not merely disabled in-progress cancellation. GitHub does not guarantee execution order within a concurrency group.

See [GitHub Actions concurrency documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

## Interpretation and safety limits

A newer **eligible** execution of the same PR and workflow supersedes older work. If no workflow starts because of existing path filters, no supersession occurs. Path-filtered workflows may also cause pending required checks; diagnose this separately from concurrency.

For `pull_request` events, the PR branch head (`github.event.pull_request.head.sha`) differs from the synthetic merge SHA commonly reported as `github.sha`. Check the current PR head, tested merge revision and merge-readiness requirements rather than treating a historical canceled SHA as a passing result.

GitHub does **not** guarantee that the newest commit wins a race against an intentionally rerun older PR execution. If an old rerun displaces current verification, rerun the current revision and re-evaluate before merging.

The `CI` workflow also retains its historical `feat/schema-contract-core-metrics` push branch. Each distinct push execution remains independently grouped; it does not cancel with PR executions. Reruns of the **same** push keep their existing run ID and are not distinct main pushes.

## Inspecting workflow runs

1. Open the PR **Checks** tab or the repository **Actions** tab. Select a workflow family and inspect the run's event type, PR number, workflow name, run ID, attempt and source revision.
2. Distinguish `cancelled` historical runs from actual `failure` results. Confirm the latest eligible PR revision has full verification, including CI's Python 3.10/3.11/3.12 matrix and Native's `static` → Android/iOS dependencies.
3. Do not interpret absent path-filtered workflows as passed checks. Confirm existing required-check and branch-protection configuration independently.
4. Inspect any unexpected cancellation by comparing workflow identity, event, PR number and run ID. Distinct PRs, workflow families and distinct main pushes should not cross-cancel.
5. Never infer empirical segmentation accuracy, deployment authorization or physical-device qualification from green scheduling tests.

## Evidence and operational metrics

For a PR with naturally overlapping eligible commits, record the earlier/newer source SHAs, run IDs, workflow names, statuses and cancellation conclusions. If no overlap happens, record `not observed`; a local policy test alone cannot demonstrate actual scheduler behavior.

Where evidence permits, compare the number of runs per PR, superseded runs canceled, obsolete jobs actually started, and time until current-head checks finish. These are observational metrics; no particular savings are guaranteed. No poller, custom cancellation API, new token or scheduler is authorized.

## Verify and roll back

From the repository root in the reviewed Python environment:

```sh
python tools/render_ci_workflow.py --check
python -m pytest -q tests/test_workflow_concurrency.py tests/test_ci_workflow_contract.py
python tools/documentation.py --check
python docs/roadmap/plan_tools.py --check
```

The GitHub exact-revision CI remains authoritative for integration and platform builds. Before merging, inspect the current PR head and applicable check runs; after merging, verify the merge commit's independent `main` workflows.

Rollback: revert the workflow, generator, test and runbook changes, check regenerated CI integrity, and re-run verification for the appropriate SHA. The change does not require a database migration, Railway rollout or application rollback. Historical canceled executions cannot be uncanceled.
