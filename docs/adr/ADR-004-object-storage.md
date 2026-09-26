# ADR-004 — Private object storage with explicit capability profiles

[Index](README.md) · [ObjectStore](../connectors/object-storage.md) · [Security](../roadmap/17-security-privacy-and-abuse.md).

Status: IMPLEMENTATION_DEFAULT for a private S3-shaped port; provider choice pending T04/T27.

Keep originals, derivatives and exports outside PostgreSQL. Use opaque application asset IDs and scoped temporary operations. Compare AWS S3 and Cloudflare R2 or an approved equivalent for region/jurisdiction, signed methods, checksum/version/copy behavior, lifecycle/deletion, CORS, latency and actual egress/storage costs. Do not assume perfect interchangeability from the term S3-compatible.

Analysis inputs must bind immutable verified bytes, not a mutable upload key while its presigned URL remains valid. ETag is provider metadata, not a universal content hash. A private derivative remains personal content and follows consent/grant/deletion lineage.

Acceptance: overwrite-race, checksum/size/format failure, duplicate completion, expired access and all-version deletion tests against the selected profile. Production gate: private bucket/least privilege, region/retention approval and deletion verification. Provider replacement preserves application asset IDs and digest lineage.
