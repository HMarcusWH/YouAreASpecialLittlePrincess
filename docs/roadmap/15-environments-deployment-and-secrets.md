# 15 — Environments, builds, secrets and deployment topology

[Index](00-index.md) · [Module boundaries](09-connectors-and-provider-boundaries.md) · [Operations](18-observability-support-and-cost-control.md) · [Decisions](19-provider-decision-register.md) · [Release gates](21-release-readiness-checklists.md).

## Environment contract

T28 creates local/test/preview/staging/production configurations and validates required settings at startup. Fake mode must be explicit and impossible to select accidentally in production; production must refuse test payment credentials, unapproved model policies and missing capability gates. Each environment has separate database, bucket namespace, identity audience, callback domains, push environment, purchase environment and secret scope. A preview deployment never receives production handwriting or production payment proofs.

Local development uses synthetic fixtures, a local PostgreSQL instance, a fake object-store port or tested local S3 profile, fake identity/purchases/model/notifications and a local mail sink. External-provider tests are opt-in sandbox jobs with explicit credentials and budgets. Default CI needs no live paid calls, real participant files, signing keys or store accounts.

Native variants have distinct bundle/package identifiers, deep-link domains and notification environments. A production app cannot be silently pointed at a developer's preview API. Record build-time versus runtime configuration; an OTA configuration change cannot smuggle in new native capabilities or bypass store review.

## Deployment topology

API and background workers share application contracts but have separate processes, credentials, quotas and network rules. CPU extraction runs in a constrained worker with no model credentials and no model-provider egress. Premium has only the image/report grants it needs plus the approved model credential. Render runs a sandboxed browser against trusted internal templates and authorized assets, without an arbitrary Internet browser API. Reference jobs use a privileged but separate data role and cannot expose member vectors to client endpoints.

Use managed PostgreSQL/private object storage selected through ADRs; no Kubernetes requirement for v1. Containerize where it improves reproducibility and limits. T28 pins base images by digest and establishes a supported local workflow; T24 adds production rollout, health, resource and recovery configuration. PostgreSQL migrations use a short-lived migration role, not the API runtime owner.

## Secret and egress matrix

| Component | Allowed credentials/data | Explicitly absent |
|---|---|---|
| Web/browser/native JS | Public API URL, publishable identity configuration, public store SKU IDs | Database, provider secret, signing private keys, service roles |
| Web server/session boundary | Approved identity/session secret and application API transport | Raw report database ownership, model/payment server credentials |
| API | Narrow DB role, identity verification configuration, scoped upload signing, approved webhook validation keys | Unrestricted corpus role, model execution key where not required |
| Analysis worker | Job/read-input/write-result capabilities and narrow storage access | Model SDK credentials, commerce administration, public network fetch |
| Premium worker | Leased job scope, approved derivative, model key, result publication capability | Arbitrary tenant reads, canonical measurement mutation |
| Render worker | Authorized projection and scoped asset tickets, export writer | Model key, arbitrary DB access, arbitrary URL browsing |
| Reference worker | Approved corpus/release roles and bounded storage | User-facing public endpoints, payment keys |
| Notification worker | Opaque event payload, mail/APNs/FCM credentials | Handwriting content, full model prompt, ledger mutation |
| CI/store build | Least-privilege read/release identities, explicitly protected signing when needed | Production database dumps and user samples |

Use short-lived workload credentials where supported. Store secrets in a managed secret system, rotate them, log access without values and maintain emergency revocation procedures. Never put secret examples containing realistic values in `.env.example`. Browser/native build artifacts must be scanned for server secrets.

Evidence-bound provider profile values that are unsafe to commit but are not credentials (for example the qualified Supabase staging issuer containing the project reference) remain protected runtime configuration. They are accepted only by an explicitly reviewed environment/component/provider tuple and must be validated against Git-safe evidence hashes. Do not add them to a checked-in manifest when doing so would invalidate an existing qualification receipt's manifest binding; do not read arbitrary process variables directly inside an adapter to bypass T28 startup validation.

## Reproducible build policy

Retain T00's exact Python manifests, hash locks, no-dependency local installation and toolchain verification. T00A closes the post-merge dependency-policy gaps before new application packages are integrated. New runtime environments get their own complete locks and tests; do not force OpenAI, native build tools or unused ML packages into the Free distribution.

T28 verifies the inherited Node version, selects compatible exact pnpm/TypeScript/Next/Expo/native module versions, records the matrix and commits a frozen lockfile. Do not run `latest` scaffold commands in reproducible CI. Pin native SDK/JDK/Gradle/Xcode/build image versions to approved supported combinations, then refresh deliberately as store requirements change. T29 documents which native files are generated versus maintained by humans.

CI should separate documentation, core, contract generation, backend/PostgreSQL integration, web, native, security/locks and release jobs. Untrusted fork PRs get no signing, production or paid-provider secrets. Store submission is a protected manual promotion of a tested artifact digest, not a side effect of every push to main.

## Schema and client rollout

Mobile clients cannot all upgrade atomically. T01 owns versioned product DTOs, while T24 now qualifies a narrower provider-neutral application rollback property: migrate the database forward first, deploy the new application, and keep the forward database if application code must roll back. The immediately previous runtime must therefore tolerate the candidate schema. Application rollback never runs a database downgrade.

The repository does **not** yet implement client-build/API-version negotiation. Product `contract_version = 1.0.0`, FastAPI `0.1.0` and the native scaffold `0.1.0` are different authorities and none means "clients older than X are unsupported." A real minimum installed-client support window and deprecation mechanism remain release/native work; T24 must not invent one. Until then, removal of a public method+route used by an installed client fails rollback qualification, and a candidate-only endpoint must not become mandatory during the rollback window without separate evidence.

Deploy API/worker versions against explicit schema compatibility, stop affected admission and drain or fence candidate-only queued work before rollback, canary resource limits and keep rollback artifacts. A rollback may restore code/template/model pointers only to still-authorized data/benchmark versions. Database state stays forward so deletion tombstones, financial history, newer rows, provider-attempt journals and revocations are not undone.

## Required evidence

Document setup/teardown, bootstrap data labels, migration upgrade/compatibility tests, offline/fake operation, secret scans, allowed egress tests, backup restoration, kill-switch behavior and clean-environment builds. T28 is environment scaffolding; T24 is operational acceptance; neither alone is public release approval.
