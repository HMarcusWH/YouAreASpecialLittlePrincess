# AbuseChallengeProvider — quotas plus risk signals

[Index](README.md) · [T04](../roadmap/06-agent-backlog.md#t04) · [Abuse ADR](../adr/ADR-009-abuse-protection.md) · [Security](../roadmap/17-security-privacy-and-abuse.md).

The port verifies a scoped challenge/attestation and returns `accepted`, `rejected` or `unavailable` with minimal reason codes. It receives expected app/site identity, operation/challenge binding, expiry/nonce and deadline. A successful challenge does not authorize an account, purchase or report.

For web, Turnstile is a candidate: verify tokens server-side, expected hostname/action, expiry and replay behavior. For native, evaluate App Attest/DeviceCheck and Play Integrity with server-generated request-bound challenges and tested fallback behavior. Do not promise identical trust semantics across providers or treat unavailable attestation as proof of malicious intent.

Independently enforce account/guest quotas, concurrent jobs, decoded image limits, storage/exports, payment verification throttles and model spend caps. Risk signals are applied before expensive admission, then authoritative permission is checked again in the use case. A provider outage triggers controlled fallback/limits rather than unbounded free compute or universal denial.

This connector belongs to admission/security, not the zero-AI handwriting inference graph. Keep network/learned provider dependencies absent from the deterministic worker itself. Privacy records include challenge/device telemetry and retention; avoid collecting stable unnecessary identifiers.

Fakes exercise expired/replayed/wrong-action/wrong-app tokens, outage, throttle and risk uncertainty. Integration tests prove expected-action binding, no grant on challenge alone, bounded fallback load and normal authorized-user recovery. Sources E26/E31 and pending Apple capability verification are tracked in [22](../roadmap/22-research-and-source-refresh.md).
