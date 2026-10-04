# Handover snapshot — post-#76

Snapshot date: **2026-10-04**. Implementation baseline: `13ca478eca256c04ec2b22ee2ac91841dc8d0109`, the merge of [PR #76](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/76). Final PR head: `26d09564e42d61577f04e1ef03973cbee22f9a06`. GitHub recorded the merge at `2026-10-04T18:36:03Z`.

This page is a dated handover summary. For subsequent task changes use [tasks.json](../roadmap/tasks.json) and the generated [backlog](../roadmap/06-agent-backlog.md). It is not a release certificate.

## Merged since the post-#72 snapshot

| PR | Merge | What it changed |
|---|---|---|
| [#73](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/73) | `f406de0` | Mobile-first maintainer handover documentation, local setup and testing guides |
| [#74](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/74) | `3099bcf` | Root README precedence; workflow guide moved to `.github/WORKFLOWS.md` |
| [#75](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/75) | `137f0cfd51f3e8ea67ffd06c2f2ee373a8ae976b` | Dossier v3 native implementation: editorial report sections, stored-evidence plates, page-region map, slant range and the accessible step-through evidence inspector, without changing fact/salience authority ([implementation sync](../design/IMPLEMENTATION_SYNC_V3.md), [native matrix](../design/NATIVE_IMPLEMENTATION_MATRIX_V3.md)) |
| [#76](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/76) | `13ca478eca256c04ec2b22ee2ac91841dc8d0109` | The exact v3 UX archive retained as an immutable, checksum-pinned reference under [docs/design/artifacts/2026-10-04-v3/](../design/artifacts/2026-10-04-v3/README.md) |

The v3 archive is a composition reference. Compare it against current source; never extract it over the checkout. Current contracts, permissions, saved-report truth and tests take precedence.

## What the receiving engineer gets

| Area | Implemented at this baseline | Not established by that implementation |
|---|---|---|
| Numerical engine | 64 registered measurements against 272 definitions; deterministic Free path and evidence contracts | Real-data calibration or all 272 features implemented |
| Shared backend | PostgreSQL/RLS, immutable captures/reports, jobs, permission events, erasure, ledger, export and notification services | A complete approved production deployment |
| Native client | Guest/development-account bootstrap, capture/review/crop, journaled upload/analysis recovery, v3 editorial Dossier with stored-evidence inspector, history/settings, feedback, authenticated PDF sharing, same-owner comparison, paid-state/store/push/link integration code | Provider sign-in/refresh, real store proofs, delivered push, physical-device/tablet qualification or public availability |
| Android handoff binary | Candidate capability (see below): a standalone, non-debuggable, debug-key-signed development APK with an embedded bundle, qualified by a real emulator Free journey | Play signing, store distribution, physical-device qualification or T31 |
| Web | Working Free client and regression/inspection surface | Finished web Premium; web is not mobile priority one |
| Premium | Packet/compiler/validator, bounded attempt and saved-overlay services, native presentation | Approved live model, semantic evaluation, paid-pair deliverable or production inference |
| Commerce | Internal account/credit ledger and disabled Stripe/Apple/Google server adapters; native orchestration | Approved prices/refunds/portability, real sandbox transactions, enabled non-fake composition |
| Sharing/comparison | Same-owner unsaved comparison and authorized export mechanics | Persisted comparisons, invitation/grant lifecycle, partner comparison or pair Premium |
| Identity | Selected Supabase profile and narrowly protected staging verification composition | Completed staging evidence closeout, app login lifecycle or live identity approval |
| Recovery/operations | Runtime images, synthetic topology and PostgreSQL restore/rollback qualification, tombstones, reconciliation and aggregate telemetry | Qualified production host/storage/PITR, deployed alert routing or approved RPO/RTO |
| Research/policy | Reviewed interpretation structure, synthetic pilot tooling and policy contracts | Active traditional associations, approved participant collection, real reference statistics or approved draft notices |

The native development flow is an implemented client, not a scaffold. It is also not a store-ready app. Source entry: [mobile README](../../apps/mobile/README.md). Important current limits include development-only account sign-in, unsaved same-owner comparisons, platform fallback fonts and no byte-range resumable upload.

## Retained automated evidence

These PR-triggered and push-triggered run identities were verified for this snapshot. Each workflow run owns its exact candidate/merge-ref attribution; they are not fresh executions on a later commit.

| Change | Workflow | Retained run | Result |
|---|---|---|---|
| #76 final head `26d0956` | Roadmap integrity | [37222562997](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37222562997) | success |
| #76 final head `26d0956` | CI | [37222563002](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37222563002) | success |
| #76 final head `26d0956` | Application environments | [37222563021](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37222563021) | success |
| #76 final head `26d0956` | Documentation handover | [37222563013](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37222563013) | success |
| #75 final head `dd877ed` | Native foundation | [37212432185](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37212432185) | success |
| #75 merge `137f0cf` (push to `main`) | Native foundation | [37218431306](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37218431306) | success |

#76 changed documentation and a design-artifact test only, so Native foundation did not run for it. The latest native compile evidence is #75's. Its `main` push retained a 14-day artifact named `inktrospect-android-development-<sha>`, which is a **dev-client debug APK**: it needs Metro and embeds no application bundle or API origin. Do not hand that binary to a developer as a runnable app.

Earlier #72 final-head results (`2a119ba`) remain retained history: Roadmap [37155767212](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37155767212), CI [37155767215](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37155767215), Release compatibility [37155767231](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37155767231), Application environments [37155767234](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37155767234), Runtime topology [37155767236](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37155767236) and Native foundation [37155767217](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/37155767217). Codex code/security review did not run for #72 because the payer reached its quota; [that discussion](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/72#issuecomment-5973602291) is not an approval. Zero review findings is not evidence of a review that never executed.

Render-inspection uploads use finite CI retention. Preserve approved synthetic evidence in an owner-controlled archive when a durable handover needs it; do not assume artifact download links last forever.

## Standalone Android developer handoff (current candidate)

The change that introduces this section adds a second Android build to Native foundation, beside the unchanged dev-client compile job:

- `tools/build_android_handoff.sh` builds the existing `development` variant with `INKTROSPECT_BACKEND_ENV=local` and `INKTROSPECT_API_BASE=http://127.0.0.1:8000` as a Gradle **release** APK. The APK is non-debuggable, embeds the Hermes bundle, and is signed with the generated debug key; Android cleartext is enabled only for the development variant.
- `tools/verify_android_handoff.py`, `apkanalyzer` and `apksigner` verify the bundle, embedded configuration, manifest, permissions and signing class before any device is used.
- `tools/run_android_handoff_journey.sh` installs that exact APK on an API-36 emulator and drives the real Free journey with pinned Maestro 2.11.0. The path runs through the system Photo Picker, consent, a queued run with the worker gated, force-stop/relaunch and same-run recovery to the saved Dossier, with exact database counts and no Metro.

Pull requests only qualify. After merge, the `main` push repeats the whole job and alone publishes `inktrospect-android-handoff-<main-sha>` with the APK, its `.sha256`, `BUILDINFO.json` and `HANDOFF.md` for 30 days. `BUILDINFO.json` names the exact `main` source commit it was built from, so no later documentation commit is needed to identify the binary. To hand it over: open the successful `main` Native foundation run, download the artifact, verify the checksum, read `BUILDINFO.json`, and send that exact artifact. The recipient procedure is [local setup section 8](../development/local-setup.md#8-standalone-android-handoff-apk); the evidence model is in [COMPATIBILITY.md](../../apps/mobile/COMPATIBILITY.md#packaged-standalone-android-evidence-model).

It is not Play signing, a Play production candidate, production identity, live Premium/model or payment evidence, production push, physical-device qualification or T31 completion.

## Work still open, grouped by kind

| Kind | Remaining work and existing owner |
|---|---|
| Missing implementation/integration | Native provider sign-in/refresh/recovery and linking (T17/T30A/T30/T31); T22 invitations/grants/persisted comparisons/pair Premium; production storage/mail/push/telemetry composition (T24) |
| Missing executable/device evidence | Physical phone/tablet acceptance, iOS simulator UI driving, and device-level native store recovery and secure-store cases (T29/T30A/T30/T31). One Android API-36 emulator journey of the standalone handoff APK exists; it is not a device matrix |
| Provider/account qualification | Deferred T17 runtime/settings/cleanup evidence; Apple and Google sandbox/store evidence; deployed recovery/monitoring (T17/T19/T24) |
| Owner decisions | Prices/refund-after-spend/portability, processor/retention choices, notices/rights, signing and distribution custody |
| Empirical evidence | Actual permitted writers, calibration, reference release and live Premium quality (T11/T06/T08/T12–T14/T16) |
| Deliberate prioritization | Expanded web Premium is not a construction predecessor for native clients; overall programme scope is not silently reduced |

Do not remove physical-device/provider residuals when reconciling successful CI. T30A stays `IN_PROGRESS`; T30/T31 and store tasks retain their recorded status until their own acceptance is met. No gate or task status is changed by this handover snapshot.

## Frozen identities are not stale baselines

The T17 runtime witness remains `c653a7d0cc29e0398a0cfb9e5c8113b9b2acd6b3`; do not replace it with this snapshot SHA. Follow the [operator runbook](../ci/T17_SUPABASE_STAGING_AUTH_OPERATOR_RUNBOOK.md). Frozen research, protected evidence digests and historical rollback witnesses retain their original identities. Only the current task/handover reconciliation baseline advances.
