# Question catalogue navigation

**New navigation for the preserved research draft; not an activated question pack.**

Complete question records are split by examination domain below. Every record retains its original wording, answer owner, source references, applicability, evidence class and guardrails. Fixed choices and display labels are in [value_sets.json](blueprint/value_sets.json). Dynamic choices are defined in [metadata.json](blueprint/metadata.json).

The original 59,005-byte readable `question_catalogue.md` is reconstructed without content changes by `python tools/check_graphology_research.py --assemble-dir /tmp/graphology-foundations-v0.1` from the repository root. Its original SHA-256 is checked before export. The JSON records are the single reviewable source here; no manually edited second catalogue can drift.

| Domain | Questions | Complete records |
|---|---:|---|
| Sample context and applicability | 6 | [CONTEXT](blueprint/questions/01-context.json) |
| Whole-pattern appraisal | 4 | [GLOBAL](blueprint/questions/02-global.json) |
| Page organization and spacing | 6 | [SPACE](blueprint/questions/03-space.json) |
| Size, proportion and zones | 5 | [SIZE](blueprint/questions/04-size.json) |
| Slant, baseline and directional tendencies | 4 | [DIRECTION](blueprint/questions/05-direction.json) |
| Degree and form of joining | 4 | [CONNECTION](blueprint/questions/06-connection.json) |
| Letterform and simplification | 6 | [FORM](blueprint/questions/07-form.json) |
| Stroke appearance and pressure boundary | 5 | [STROKE](blueprint/questions/08-stroke.json) |
| Apparent movement, rhythm and variation | 6 | [MOVEMENT](blueprint/questions/09-movement.json) |
| Local gestures, diacritics and letter detail | 12 | [DETAIL](blueprint/questions/10-detail.json) |
| Signature and body-text relationship | 6 | [SIGNATURE](blueprint/questions/11-signature.json) |
| Dominants, modifiers and whole-sample coherence | 7 | [HIERARCHY](blueprint/questions/12-hierarchy.json) |
| School-specific interpretation and synthesis | 6 | [INTERPRETATION](blueprint/questions/13-interpretation.json) |
| Database-relative distinctiveness | 4 | [REFERENCE](blueprint/questions/14-reference.json) |
| Two-sample comparison | 4 | [PAIR](blueprint/questions/15-pair.json) |
| Within-writer comparison over time | 4 | [HISTORY](blueprint/questions/16-history.json) |

**Inventory:** 89 questions/selectors; 44 fixed sets / 156 entries; 33 dynamic candidate kinds; eight bounded text fields; five question packs. The six school records comprise five tradition profiles plus the APPLICATION namespace.

Source links establish only their documented scope. All questions/values remain draft; traditional and reference packs retain their stated activation gates.

[Research report](graphology_foundations.md) · [Sources and access limits](sources.json) · [Post-merge database handoff](../DATABASE_HANDOFF.md)
