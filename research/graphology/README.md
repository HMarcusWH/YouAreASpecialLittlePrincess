# Graphology research supporting the application

This directory holds **research snapshots and database-design evidence**, not an enabled interpretation database. The source material was supplied in `Graphology_Foundations_and_Selector_Blueprint_v0_1.zip`.

## Reading order

1. [Foundations v0.1](foundations-v0.1/README.md): research report, source register, question domains and provenance.
2. [Question catalogue navigation](foundations-v0.1/catalogue_index.md): the 89 proposed questions, grouped into 16 examination domains, with links to their complete records and legal draft values.
3. [Historical database construction handoff](DATABASE_HANDOFF.md): original T26 requirements; current implementation is the [reviewed interpretation source](../../schema/graphology_interpretation/v1/README.md). Do not rebuild completed T26 work.
4. [Existing product roadmap](../../ROADMAP.md) and [selector architecture](../../docs/roadmap/08-premium-question-selector-database.md): application context, not authority to activate draft associations.

## Review boundary

The original supporting-materials import preceded T26 construction. That is historical provenance, not present implementation status: T26 and its T15 consumer are now recorded DONE, the database is populated/reviewed, runtime activation remains false and traditional runtime eligibility remains zero. The frozen research JSON stays under `research/`; it does not independently authorize interpretation. Read the current schema handoff before acting on historical construction instructions.

The preserved draft distinguishes source fidelity, empirical support and observation feasibility. Original terminology, access-depth limits, pending rubrics and research-only associations remain intact. Any later correction or new research must be documented as a new revision, not silently edited into this snapshot.

## Verification

From the repository root, using Python 3.10 or newer:

```bash
python tools/check_graphology_research.py
python tools/check_graphology_research.py --assemble-dir /tmp/graphology-foundations-v0.1
```

The first command checks integrity and draft structure without writing files or making network/model calls. The second writes the original research-package files into a **new** directory only after the checks pass. It reconstructs the original monolithic blueprint and readable catalogue byte-for-byte from the partitioned records. It is not a production database generator.

[Import validation receipt](foundations-v0.1/provenance/import_validation.json) records this import's executed checks. [Original validation](foundations-v0.1/provenance/original_validation_report.json) is the historical research-stage receipt; neither establishes graphological or model accuracy.
