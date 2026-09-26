# ObjectStore — private immutable analysis inputs and revocable artifacts

[Connector index](README.md) · [T04](../roadmap/06-agent-backlog.md#t04) · [Storage ADR](../adr/ADR-004-object-storage.md) · [Security](../roadmap/17-security-privacy-and-abuse.md).

## Port contract

Use internal `AssetRef` identifiers. Proposed operations: `issue_upload_ticket(asset_ref, upload_policy)`, `inspect_upload(asset_ref)`, `promote_verified_input(upload_ref, verified_digest)`, `read_authorized(asset_ref, scope)`, `issue_download_ticket(asset_ref, scope)`, `write_derivative(...)`, `delete_asset_versions(...)` and `verify_deletion(...)`. Provider bucket/key/version/ETag details remain in adapter metadata, not public IDs.

An upload policy declares allowed media, byte/pixel expectations, deadline, checksum behavior and write conditions. A capability profile states which constraints the provider enforces before upload and which the completion worker must verify. Do not promise a maximum-size PUT policy that the selected provider does not implement. Short-lived tickets are bearer capabilities, not one-use tokens unless enforcement actually exists.

## Upload completion algorithm

1. API authorizes principal/quota and creates a private upload slot with unpredictable server-selected key and expiry.
2. Client uploads only to the issued operation; storage remains private.
3. Completion endpoint verifies owner, expiry, expected object and available checksum/size/version metadata. Decode/sanitize in a resource-limited worker; do not trust MIME/extension.
4. Bind processing to immutable verified bytes. Use a tested immutable version reference or copy/promote to an internal non-upload-writable key. Reusing a still-mutable presigned PUT key for analysis is prohibited.
5. Record content hash, source/derivative relationship, transform lineage and retention/deletion scope. An ETag is not treated as a SHA-256 digest by default.
6. Enqueue only after the verified asset reference and job/outbox are durably linked. Retry completion returns the same accepted result or a clear conflict for changed bytes.

## Reads, exports and deletion

Issue asset access only after current owner/grant/entitlement/deletion checks. Bound ticket lifetime and avoid placing signed URLs in analytics, logs or notifications. Render/Premium workers get scope-limited internal access, not arbitrary storage credentials or user-provided URLs.

Deletion covers originals, normalized crops, thumbnails, rendered exports, object versions and applicable caches. A deletion marker in a versioned store is not proof old bytes are gone. Document retention/lifecycle/backup behavior and reconcile against tombstones. Immutable storage must still support the approved erasure lifecycle; do not enable retention locks casually for personal handwriting.

## Fakes and verification

The fake simulates overwrite between HEAD/read, checksum mismatch, expired URL, partial upload, missing version, copy failure, duplicate completion, stale read, permission revocation and delayed delete. Contract tests must run against the chosen S3/R2 profile before claiming compatibility. Private bucket policy, CORS origins, signing method and least-privilege credentials require an approved configuration record.

Source E21 in [22](../roadmap/22-research-and-source-refresh.md) supports the presigned-URL design; exact provider capabilities are tested, not inferred from an S3-compatible label.
