# Graphology foundations — supporting research v0.1

**Frozen research snapshot dated 25 September 2026. Not a production database or approved inference pack.**

## Contents

| Material | File | Role |
|---|---|---|
| Research report | [graphology_foundations.md](graphology_foundations.md) | Original report, unchanged. |
| Question catalogue | [catalogue_index.md](catalogue_index.md) | Domain navigation; original full Markdown catalogue is reproducible. |
| Source register | [sources.json](sources.json) | 15 original source/access/limitation records, unchanged. |
| School concepts and protocol | [blueprint/metadata.json](blueprint/metadata.json) | Original blueprint metadata, assertions, answer states, soft fields and packs. |
| Allowed draft values | [blueprint/value_sets.json](blueprint/value_sets.json) | 44 original sets containing 156 value entries. |
| Questions | [blueprint/questions](blueprint/questions) | 89 original records across 16 ordered domain files. |
| Import provenance | [import_manifest.json](provenance/import_manifest.json) | File hashes, source archive hash, ordering and reconstruction mapping. |
| Original provenance | [README](provenance/original_README.md), [checksums](provenance/original_SHA256SUMS.json), [validation](provenance/original_validation_report.json) | Historical package files preserved unchanged; paths in the old README describe the original archive layout. |
| New verification | [import_validation.json](provenance/import_validation.json) | Current import integrity/structure results, not empirical validation. |

No third-party books, syllabus PDFs, handwriting images, private participant data, model calls or credentials are included. Source URLs and the original research's access/reuse limitations are preserved; this import does not establish reproduction rights or re-verify all external sources.

## Lossless organization

The original monolithic JSON is partitioned by examination domain for review. Keys, values and order are preserved in the manifest. The offline checker reconstructs it with the original serialization and verifies its SHA-256. It also reconstructs the original complete readable question catalogue from the same records and original preamble; that output must match its original checksum exactly.

```bash
# Run from the repository root; default is read-only.
python tools/check_graphology_research.py
# Optional: recreate all seven original archive files in a NEW directory.
python tools/check_graphology_research.py --assemble-dir /tmp/graphology-foundations-v0.1
```

This is a research export only. The checker neither writes the production schema nor activates the draft values. The ZIP container itself is not committed; its checksum is retained and its seven content files are preserved or exactly reconstructable.

## Next stage

Follow the [database handoff](../DATABASE_HANDOFF.md) **after this supporting-materials PR is merged**. T26 remains planned. New database records require explicit source/rubric review and traceability to these draft IDs; do not treat copying this directory into `schema/` as database construction.
