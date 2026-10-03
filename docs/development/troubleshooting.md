# Development troubleshooting

Start with the exact source SHA, environment, component and safe error code. Do not paste tokens, signed URLs, journal contents, store proofs or specimen images into a public report. [Commands](../reference/commands.md) distinguishes read-only diagnosis from state changes.

| Symptom | Check | Safe next step |
|---|---|---|
| API import fails | App dependencies and `PYTHONPATH` include `src` and `apps/api` | Follow the backend setup; installing the Free wheel alone does not install the source-tree application |
| `notice_registry_unreadable` at startup | The image contains `contracts/consent/v1/notices.json`; source checkout and image match | Rebuild the reviewed image. Do not disable notice validation or invent approved copy |
| Container says healthy but HTTP fails | Database probe versus `/health/live` versus `/health/ready`; API process logs | Inspect process startup and packaged inputs. A separate DB probe does not prove the API is serving |
| Native configuration error | `config:public`, variant, backend environment and API origin | Correct build-time values and rebuild where required; do not make release config accept development identity |
| Phone can call API but upload fails | The ticket's origin is device-reachable and allowlisted; API `PRINCESS_PUBLIC_API_BASE` matches reality | Correct the issuing origin/allowlist. Never attach the API bearer token to a storage PUT |
| Emulator works, physical phone fails | Loopback/LAN address, API bind, firewall and trusted network | Test reachability from the actual device; `localhost` on a phone is not the development computer |
| Image rejected | MIME after conversion, byte/pixel/side limits, orientation and checksum of the uploaded derivative | Retake or reviewed re-encode/crop; don't relabel HEIC bytes as JPEG |
| Analysis stays queued | Worker process, correct database/environment and shared storage | Start the analysis worker. Do not create another analysis merely because the route reopened |
| Lost completion/start response | Journal phase, stable capture/run references and server run discovery | Resume the existing workflow; an unknown outcome is not a definite failure |
| Lost upload reservation response | The workflow records a consumed slot but may not know its ID | Follow bounded recovery/quota behavior; do not claim a reservation is perfectly deduplicated |
| Original image unavailable | Retention permission and current live projection | Expected when not retained or withdrawn. Never recover erased bytes from an old URL/cache |
| History missing after switch | Current principal, transfer outcome and server authorization | Re-fetch for the current principal; never reuse previous-account results |
| Token expired/offline launch | Secure credential record, verified state and `/v1/me` | Preserve only allowed offline state; current development session support is not provider refresh |
| PDF request accepted but no file | Export worker and renderer/browser prerequisites, export state | Poll the existing export. A 202 is not completed output; use authenticated download, not external URL opening |
| Purchase appears pending | Store state, verified server grant and completion ownership | Reconcile the same transaction. No local Premium flag or manual unverified credit |
| `completed: 0` from operations | Completed count versus actual outstanding completion state | Zero successes is not proof the backlog is empty; see the corrected payment runbook |
| Premium disabled/unavailable | Manifest switches, approved model/data/spend and image/credit eligibility | Use fakes for development; do not enable live use as a debugging shortcut |
| Comparison not saved/shared | Baseline implementation is same-owner and unsaved | Persistence/partner permissions belong to T22; a comparison response is not an invitation grant |
| Test suite passes but native UI unknown | Which layer actually executed | Run app-driving/device acceptance; Node controllers and native compilation do not prove UI behavior |
| Generated reference drift | Source change and owning generator | Regenerate intended outputs, review the diff and rerun `--check`; do not edit the generated table |

## Incident versus local debugging

The [runbooks](../runbooks/README.md) contain deployed-operation prerequisites and pending provider decisions. Database restore, provider cleanup, account revocation, refunds and signing changes are not routine troubleshooting steps. Preserve forward tombstones and immutable financial history. Do not downgrade a populated database or replay an ambiguous paid request to make a local test green.

The T17 closeout checker intentionally fails until real protected evidence exists. `cleanup_evidence_missing` is useful only at the documented pre-cleanup checkpoint after the other evidence has validated; it is not a global success condition. Follow the [specific runbook](../ci/T17_SUPABASE_STAGING_AUTH_OPERATOR_RUNBOOK.md), not a generic retry loop.
