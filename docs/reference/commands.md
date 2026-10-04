# Command safety and output reference

Use [local setup](../development/local-setup.md) for complete development environment preparation. Commands below are **operator templates** unless stated otherwise: execute them only inside the approved environment for the named component, from the repository root with its reviewed dependencies and source paths. `$API_ENV` is not a defined executable shell command; do not paste an unexplained environment placeholder.

The [generated command inventory](command-inventory.md) lists real scripts/package commands. An inventory entry is not permission to execute it, and not every Python tool implements `--help`.

## Safety classes

| Class | Examples | Required care |
|---|---|---|
| Read-only validation | Documentation/contract checks, manifest validation | Read source/files; no activation or data-collection claim |
| Local generation | Backlog, DTO/token/reference generators, candidate locks | Writes reviewed files; inspect diff; never regenerate all locks blindly |
| Read-only operational | Snapshot, alert check, verify-disabled | Correct environment/role; even read-only diagnostics can expose data if broadened |
| Mutating operational | Reconcile, complete-pending, expiry, tombstone replay, notification suppression | Correct role/scope and owner authorization; can affect external/account state |
| Destructive test | Web/native E2E and restore fixtures | Disposable local target, explicit reset opt-in, no shared concurrent test database |
| Protected provider operation | T17 conformance/settings/cleanup, real store/model work | Dedicated runbook, protected inputs, approved scope/spend, no secrets in Git |

## `princess_api.ops`

Source: [ops.py](../../apps/api/princess_api/ops.py). Start with the actual parser when implementing new diagnostics. Commands print bounded JSON on success; composition/validation failures may exit nonzero before a business result exists.

| Invocation after component environment is prepared | Effect | Output and exit interpretation |
|---|---|---|
| `python -m princess_api.ops snapshot` | Read-only database/manifest/tombstone posture | `operational-snapshot/1`; no live provider call; contains bounded aggregates |
| `python -m princess_api.ops check --policy /approved/alert-policy.json` | Read-only policy evaluation | `PASS`, exit 0, or `ALERT`, exit 2. This is an alert-policy result, not release approval |
| `python -m princess_api.ops verify-disabled --switch commerce --switch premium_generation` | Read-only switch check | Exit 0 only if requested switches are off; 2 if any are on. Never changes a switch |
| `python -m princess_api.ops emit-telemetry` | Exports bounded observations | Read-only database operation but telemetry output side effect; current exporter composition is fake-only. Record export result, not provider approval |
| `python -m princess_api.ops reconcile --rail google_play --since-hours 48` | Authoritative provider reconciliation and ledger effects | Outcome counts. May recover grants/refunds; not a dry run. Use the actual selected rail (`stripe`, `apple_app_store`, `google_play`) |
| `python -m princess_api.ops complete-pending` | Retry server-owned consume/acknowledge | `completed` is the **number completed in this invocation**, not pending count. Exit 0 or zero successes does not prove no unresolved work |
| `python -m princess_api.ops expire-feedback` | Erases expired feedback | `expired` count, not proof of all privacy obligations completed |
| `python -m princess_api.ops replay-tombstones` | Reapplies forward deletion/withdrawal/revocation after restore | `reapplied`, `already`, `unknown`, `unreadable`. Investigate unreadable evidence before traffic resumes; preserve the external log |

Cross-owner completion/diagnostic queries require the actual authorized worker/operator role. An ordinary API principal context must not be broadened or given BYPASSRLS for convenience. Some commands compose providers; incident posture commands deliberately avoid that dependency. Current sandbox/live composition restrictions still apply even when a parser accepts the command.

### Payment-incident closure

Do not close an incident because `{"completed":0}` appeared. The service sums successful completions; provider failures can also produce zero. Check remaining completion state using the repository's pending-completion predicate under the approved operator scope and reconcile with the provider's authoritative state. Separate Apple client finish from server-owned completion. A broader safe pending-completion diagnostic, if needed, is a T24 implementation follow-up, not an invented interpretation of this existing counter.

A store purchase/charge, credit grant, credit reservation, credit spend, reservation release and provider refund are different events. Failure to publish Premium can release a credit without reversing a prior store charge. Refund-after-spend behavior is an explicit product-policy decision.

## Worker commands

Use the relevant component environment, runtime role and shared storage. The [worker entry page](../../apps/workers/README.md) maps process paths. Notification CLI supports `once`, `suppress --recipient <principal_id> --reason COMPLAINT` and `unsuppress --recipient <principal_id>` as operator actions; these are not anonymous API calls. Restored Premium reconciliation uses `apps/workers/premium/run_worker.py --reconcile-restored` before normal workers resume. It must fail closed on unsupported/uncertain authoritative attempt lookup.

## T17 protected closeout

The ordinary final checker requires the same protected raw Auth response used for snapshot generation:

```bash
python tools/check_supabase_staging_auth_closeout.py --auth-config-file /protected/princess-staging-auth-config.json
```

This is a template, not a file committed here. Follow the [full operator runbook](../ci/T17_SUPABASE_STAGING_AUTH_OPERATOR_RUNBOOK.md), including frozen runtime source, exact-byte preservation, pre-cleanup validation and authorized disposable-user cleanup. `cleanup_evidence_missing` is expected only at the explicitly documented intermediate checkpoint. Never fabricate provider evidence or use a rehashed public envelope as a provenance signature.

## Test and generation commands

[Testing](../development/testing.md) and [generated assets](generated-assets.md) own the executable developer recipes. `tools/run_mobile_journey.sh`, `tools/run_web_e2e.sh` and `tools/run_android_handoff_journey.sh` reset `princess_test`; they are not installation scripts for an existing user's database. The Android handoff runner also installs the given APK on the attached device, replacing any installed `se.inktrospect.development` and its app data. `tools/build_android_handoff.sh` regenerates only the uncommitted `apps/mobile/android/` CNG project. `tools/verify_android_handoff.py` reads an APK and writes only the summary/BUILDINFO paths it is given. The docs workflow runs only syntax/refusal controls in addition to read-only inventories. It does not execute all examples automatically.
