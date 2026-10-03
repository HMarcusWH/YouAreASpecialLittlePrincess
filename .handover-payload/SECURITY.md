# Security reporting and sensitive material

This repository handles private handwriting, account sessions, consent, payments and generated reports. A reproducible report should use synthetic data and avoid exposing another person's material.

## Reporting

Do not post credentials, private specimens, exploitable account details or sensitive incident material in a public issue or PR. Arrange a private reporting channel with the repository owner (`HMarcusWH`) through an already established approved contact. If GitHub private vulnerability reporting is enabled for the repository, that private channel may be used; this document does not assert it is configured. No dedicated security inbox, response SLA or bounty is established by this file.

Provide the affected source SHA/build, a minimal synthetic reproduction, observed versus expected behavior, affected boundary and safe redacted error codes. Keep exploit-sensitive detail and actual account identifiers in the agreed private channel. Never test against unrelated accounts or real payment/provider data without explicit authorization.

## During investigation

Use the [safe command reference](docs/reference/commands.md) and [runbooks](docs/runbooks/README.md). Prefer bounded aggregate diagnostics. Do not log authorization headers, refresh tokens, signed image/upload URLs, raw store proofs, handwriting, model prompts/responses or database dumps. Secure-store records and app-private journals are not safe telemetry.

Changing a kill switch is not revoking all previously issued capabilities; review the affected access and deletion lifecycle. Preserve evidence and forward tombstones. Do not mark erasure events dispatched manually, issue unverified credits, repeat an ambiguous paid operation or downgrade a populated database to make a symptom disappear.

## Maintenance boundary

[Architecture boundaries](docs/architecture/overview.md), [privacy drafts](docs/privacy/README.md), [dependency policy](requirements/README.md) and [release gates](docs/roadmap/21-release-readiness-checklists.md) describe the current controls and limits. Supported platform/build evidence is in component compatibility records; a current branch or a green workflow is not a promise that every historical release is supported.

The owner must confirm incident contacts and external account custody during [handover](docs/handover/access-and-assets.md). Do not invent those approvals or rotate live credentials as a documentation-only change.