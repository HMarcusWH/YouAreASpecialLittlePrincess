# Collection protocol v1 and pilot handoff

[Privacy drafts](README.md) · [Protocol manifest](../../content/collection/v1/manifest.json) · [Collection manifest schema](../../contracts/consent/v1/schemas/collection-manifest.schema.json) · [Pilot gate](../../contracts/consent/v1/pilot_gate.json) · [T11 brief](../roadmap/06-agent-backlog.md#t11)

Status: draft pending owner review. **No recruitment, collection or annotation may start** until `pilot_rights_consent` is `APPROVED` with every decision recorded. T11 owns the real pilot.

## Tasks and prompts

The protocol has one copied task and one free-writing task per supported language, all written originally for this project. Each prompt is pinned by SHA-256 in the manifest; editing the text without a new reviewed hash fails validation.

| Task | Kind | Language | Prompt |
|---|---|---|---|
| `copy_en` | copy a neutral passage | English | [copy-en.v1.md](../../content/collection/v1/prompts/copy-en.v1.md) |
| `copy_sv` | copy a neutral passage | Swedish | [copy-sv.v1.md](../../content/collection/v1/prompts/copy-sv.v1.md) |
| `free_en` | describe an everyday object | English | [free-en.v1.md](../../content/collection/v1/prompts/free-en.v1.md) |
| `free_sv` | describe an everyday object | Swedish | [free-sv.v1.md](../../content/collection/v1/prompts/free-sv.v1.md) |

Both copy passages span five lines and contain every letter a–z. The Swedish passage also contains å, ä and ö. Both include capitals, digits and the marks `, . : ? !`. The Swedish and English passages are parallel in content but form separate cohorts. Free-writing prompts contain no text to copy and tell writers not to include names, addresses, contact details, health information, private messages or signatures.

Participant guidance: [English](../../content/collection/v1/guidance/capture-and-author.en.md), [Swedish](../../content/collection/v1/guidance/capture-and-author.sv.md). It covers author eligibility, paper and instrument declarations, capture conditions (whole page, all four corners, even light, no filters or cropping), repeat photos and second sessions.

## Session plan

1. **Session 1, all enrolled writers:** the copy and free tasks in the writer's language, on separate pages. Selected pages are photographed again to estimate capture sensitivity.
2. **Session 2, optional subset, another day:** the same tasks again. This produces new specimens by the same writers, which estimate within-writer variation.

## Writers, specimens and captures

- A **writer** is a pseudonymous person with a self-declared adult eligibility and an enrollment ID. No name, birth date, gender or diagnosis is collected.
- A **specimen** is one physical page written by one writer for one task in one session.
- A **capture** is one photo of a specimen.

Repeat photos are captures of the same specimen. A second session creates new specimens. Neither is ever a new writer. A manifest names its `release_purpose` (normally `engineering_evaluation`) and a `release_cutoff`. Every included specimen must be `PERMITTED` for that purpose at the cutoff in the consent ledger, either directly or through its writer's pilot enrollment; otherwise it is `NO_RELEASE_PERMISSION` and excluded. The purpose must be one of the protocol's (`RELEASE_PURPOSE_NOT_IN_PROTOCOL`). Until an owner approves the purposes, no real specimen can be counted. The [collection manifest](../../contracts/consent/v1/schemas/collection-manifest.schema.json) is the T11 handoff shape. `check_collection_manifest` recomputes counts from lineage and rejects:

- byte-identical captures under another writer [`DUPLICATE_COUNTED_AS_WRITER`];
- repeated bytes [`DUPLICATE_CAPTURE_BYTES`];
- repeats filed under another page [`REPEAT_CROSSES_SPECIMEN`];
- two specimens for the same writer, task and session [`DUPLICATE_SPECIMEN_IN_SESSION`];
- a session index that is not in the protocol's session plan [`UNKNOWN_SESSION`], or a task kind that session does not schedule [`TASK_NOT_IN_SESSION`];
- a later-session specimen without the same writer's session-1 specimen for that task in the release [`SESSION_WITHOUT_BASELINE`];
- two writer rows sharing one enrollment [`DUPLICATE_ID`];
- writers not declared adult [`INELIGIBLE_WRITER`];
- context status that contradicts the declared script or language [`CONTEXT_STATUS_MISMATCH`];
- language/task mixing [`TASK_LANGUAGE_MISMATCH`];
- claimed counts that the lineage does not support [`COUNT_MISMATCH`].

Counts are reported per task, so copied and free writing, and Swedish and English, are never pooled. The check treats a manifest as a human release by default. A human release rejects synthetic manifests [`SYNTHETIC_IN_HUMAN_RELEASE`] and counts nothing unless the protocol is `APPROVED` [`PROTOCOL_NOT_APPROVED`] and the protocol's `source_id` entry in `source_rights.json` has reviewed, cleared data rights and a cleared use for the release purpose: `engineering_testing` for `engineering_evaluation`, `benchmark_statistics` for `reference_contribution` [`SOURCE_NOT_CLEARED`]. Participant consent alone never clears a use. Repository fixtures are checked in non-release mode, and their summary stays marked synthetic.

## Unsupported contexts

Pages in an unsupported script or language are recorded honestly as `UNSUPPORTED` context. They are excluded from supported cohorts and never matched to a guessed population. Protocol v1 does not collect signatures. Synthetic or rendered handwriting never enters a human collection; repository fixtures are marked `synthetic: true`.

## Eligibility and authority

Only adults who declare eligibility themselves take part; the age threshold per region is an owner decision. Participants contribute only their own handwriting. Each pilot purpose (`engineering_evaluation`, `reference_contribution`) is granted separately through the signed agreement, starts unselected, and is independent of compensation. Staff cannot grant on a participant's behalf. Withdrawal follows the [deletion lineage](retention-and-deletion.md).

## Handoff to T11 once the gate is approved

1. Record all eleven gate decisions and the approval in `pilot_gate.json`, with evidence kept outside Git. The validator requires every decision key to be present; removing one fails. Approving the protocol also requires decided prompt rights for every task. Move the pilot notice to `ACTIVE` with its effective window.
2. Implement collection tooling that writes consent events and a collection manifest in the shapes defined here. Store images and signed agreements only in protected storage.
3. Run `python tools/validate_consent_protocol.py` on every pilot release manifest before annotation or splitting. Also run `check_collection_manifest` with the protected consent ledger (via `collection_consent_context`, never in fixture mode).
4. Exercise withdrawal and deletion before the first corpus release.
