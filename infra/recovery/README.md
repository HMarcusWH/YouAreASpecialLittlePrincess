# T24 synthetic backup/restore rehearsal

This directory proves the provider-neutral recovery choreography against a real
PostgreSQL custom-format backup. It is deliberately **not** a production backup
system and does not approve an RPO, RTO, database host or object-storage
provider.

The drill uses only synthetic identities and a generated handwriting-like PNG.
It snapshots PostgreSQL, makes destructive post-backup changes through the
ordinary API/application code, leaves the local object/tombstone plane at the
newer point in time, restores the old PostgreSQL backup, proves that private
database state was genuinely resurrected, then runs the existing
`princess_api.ops replay-tombstones` mechanism and ordinary erasure worker to
remove the resurrection again.

Safety fences:

- `PRINCESS_RECOVERY_ALLOW_RESET=1` is mandatory.
- only the `test` manifest and database `princess_test` are used;
- the backend image must be tagged with the exact 40-character Git SHA;
- PostgreSQL 16.13 is digest-pinned;
- backup/restore commands are fixed argv arrays, never shell fragments;
- the recovery receipt contains counts/digests/timings only—no principal IDs,
  object keys, report text, handwriting bytes or credentials.

`restore_elapsed_ms` and `recovery_elapsed_ms` are observations from CI, not
production RTOs. Production RPO/RTO remain owner/provider decisions after the
actual managed PostgreSQL and object/tombstone stores are selected and tested.

Run from the repository root only against a disposable environment:

```sh
PRINCESS_RECOVERY_ALLOW_RESET=1 \
PRINCESS_BACKEND_IMAGE=princess-backend:<exact-40-char-sha> \
PRINCESS_RECOVERY_WORKDIR=/tmp/princess-recovery-local \
python3 infra/recovery/run_restore_drill.py
```

The output receipt is written to
`$PRINCESS_RECOVERY_WORKDIR/recovery-receipt.json` and validated by
`receipt.py`.
