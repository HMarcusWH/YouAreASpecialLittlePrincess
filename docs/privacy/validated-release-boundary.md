# Validated consent and collection-release boundary

Status: **implemented reference tooling, pending exact-head review and owner decisions**.
Scope: T00A/T03 of PR #12. No measurement engine, numerical feature contract,
participant recruitment, real approval, source clearance or pilot activation is
created by this change. Revert the structural-repair commit to restore the prior
reference API; never use rollback to rewrite protected consent history.

## Why the entry point changed

The repeated review failure was not merely a missing conditional. A standalone
checker could reject a registry while a separately callable release function
rebuilt a dictionary, selected one duplicate definition or omitted that checker.
Adding an issue and setting `releasable=False` were separate operations.

The replacement has a single production release path:

```
raw policy documents
  -> policy_document_issues (all schemas, uniqueness, full semantic checks)
  -> compile_release_policy (additional approval/readiness checks)
  -> immutable ReleasePolicy
  -> collection_consent_context (exact manifest and authoritative ledger)
  -> AuthoritativeConsentContext
  -> check_collection_manifest (current assets, attestation, per-row permissions)
  -> ValidationResult[ApprovedCollection] OR issues with no value
```

The repository draft validator uses the same `policy_document_issues` pipeline.
Valid pending drafts can pass that structural validator but **cannot** compile
as human-release policy. Missing dependencies and invalid definitions are not
silently repaired, rebound, auto-approved or selected by array order.

## API migration

The old `check_collection_manifest(manifest, protocol, consent, sources=...,
retention=..., gate=..., human_release=...)` API is removed. Raw policy dictionaries
and caller-assembled contexts are not publication authority. The input sources
must be the complete source-rights registry, not a dictionary that may already
have collapsed duplicate source IDs.

```python
from validate_consent_protocol import (
    compile_release_policy, collection_consent_context, check_collection_manifest,
)

def assess_release(documents, manifest, ledger, publication_evidence, publish_at):
    compiled = compile_release_policy(
        registry=documents["purposes"], notices=documents["notices"],
        protocol=documents["protocol"], retention=documents["retention"],
        lineage=documents["lineage"], sources=documents["sources"],
        gate=documents["gate"],
    )
    if compiled.value is None:
        return compiled
    context = collection_consent_context(compiled.value, manifest, ledger)
    return check_collection_manifest(
        manifest, compiled.value, context,
        publish_at=publish_at, release_evidence=publication_evidence,
    )
```

This function assesses supplied protected snapshots; it does not load an
identity provider, implement storage deletion or publish an artifact. The caller
must implement the runtime obligations below. A failed result always has
`value=None`. A successful value includes exact membership IDs, per-task counts,
source attribution, input digests and the publication instant. A downstream
consumer must use those membership IDs, not assume every supplied row was accepted.

`check_fixture_collection_manifest` is a different, synthetic-only API. It may
produce a diagnostic preview alongside row errors, always labelled synthetic.
There is no flag that promotes this output to a human release. The old test-only
adapter returns empty diagnostic summaries on failed human checks to preserve
historical assertions; that adapter is not a production entry point.

## Enforcement invariants

### Unique identities before any authoritative indexing

`unique_index` returns no value when duplicate keys exist. Policy compilation
checks purpose/version, notice/version, retention class, artifact kind, source,
gate-decision key, task, session and guidance identities, including purpose gate
decisions. Human manifests check writer, enrollment, specimen and capture IDs
before constructing an authoritative context. Ambiguity cannot select a winner
because one array row happened to be last. Session ordering follows its logical
index, not its position in an array.

### Decisions and history

Approvals retain the reviewed content-digest layout, with one shared metadata
predicate for nonempty decision identity, actor role and UTC decision time.
Content and decision metadata are bound together. Purpose retirement and notice
endings retain separate, predecessor-bound transition digests. Notice activation
now has bound actor/time metadata too. Chronology is enforced inside the predicates
used by evaluation, not only by standalone diagnostic code. Recomputing a hash
cannot make an internally inconsistent or backdated transition pass semantic checks.

A new material definition still needs a new version and genuine decision in the
protected history. The compiler does not create those decisions or rewrite old
events. Reordering signed arrays changes their digest and needs a newly recorded
decision; with fresh test decisions, permutation must not change authorization or
membership. Tests distinguish this from silently reusing the old digest.

### Authority and restrictive events

`build_context` validates account-link intervals before constructing its authority
index. Overlapping, incoherent or reversed intervals disable the writer's authority
and permission evaluation. Valid historical authority remains bound to event time.

Grants cannot become effective before recording; among events already effective,
recording order wins, with restrictive choices winning timestamp ties. An older
scheduled grant cannot override a later recorded withdrawal. An authorized but
malformed restriction blocks the context rather than disappearing and reviving an
older grant. Account, pilot, verified support and system withdrawals share the
same actor-authority predicate. Duplicate event IDs block the ledger too.

### Protocol assets and provenance

The compiler runs full prompt/guidance checks, including actual bytes. The release
entry re-reads every referenced asset and rejects a stale compiled policy if bytes
changed. Relative paths cannot escape the collection root; component-wise
`O_NOFOLLOW` file-descriptor traversal rejects symlink substitutions, and assets
must be regular files of at most 1 MiB. This filesystem reader fails closed where
the required POSIX facilities are unavailable.

Repeat ancestry is iterative and memoized. Cycles, missing parents, forward or
cross-page links, excluded ancestors, duplicate positions and rejected bytes cannot
contribute valid descendants. Byte de-duplication retains the prior explicit rule:
for one page the lowest capture index is the representative; bytes shared across
pages support none of them. This rule is based on capture identity/index, never
array order. Every accepted capture stays in its page's task cohort. Tests include
10,000 repeat captures through the complete public human-release path, not just a
small helper. Ancestry itself is O(V+E); the entire validator also performs schema,
permission and sorting work and is not claimed to be globally linear.

### No success alongside errors

`ValidationResult` forbids both a successful value and issues, or neither.
`ReleasePolicy`, `AuthoritativeConsentContext` and `ApprovedCollection` are
factory-only, recursively immutable in-process snapshots. Changing the caller's
original dictionary cannot mutate an already compiled object. Human release checks
that context, manifest and policy match before evaluating the cohort. Schema,
malformed JSON-value, node/depth/text-budget and expected I/O failures return
rejections, not authorization or an uncaught recursive ancestry exception.

These types prevent accidental construction/mutation by normal callers. Python
code executing inside the process can deliberately bypass language conventions;
the types are **not** a security sandbox or cryptographic capabilities.

## Deletion evidence and runtime obligations

An approved deletion-lineage policy is mandatory. The full artifact/action/edge
plan is validated, not just its top-level status. A release additionally requires
`release-evidence/v1`, whose attestation binds:

- the compiled policy digest, exact manifest and consent-event snapshot;
- the exact UTC publication-check instant;
- PASS evidence references/hashes for withdrawal reconciliation, deletion
  propagation and restore-tombstone reconciliation;
- the actor, decision reference and decision time of the attestation.

Missing, pending, failed, stale, differently scoped or content-mismatched evidence
returns no release. There are no committed real approval/attestation examples.
Test helpers create clearly labelled in-memory fakes only.

**An unkeyed SHA-256 does not authenticate an approver or prove physical deletion.**
This reference tool verifies contract completeness and consistency. T02/T11/T24
must resolve actor identities, opaque evidence/decision references and their hashes
against authenticated, append-only protected storage. A caller-supplied `SYSTEM`
label or `PASS` string is not authenticated evidence at a public ingress.

Before actual publication, the runtime must obtain a fresh coherent policy,
consent, withdrawal and tombstone snapshot; execute/verify the applicable real
deletion, processor and restore checks; and atomically fence publication against
those snapshot revisions. Any intervening withdrawal, retirement, policy change,
asset change or deletion request cancels or restarts publication. The returned
reference result is not a reusable publish token and does not prove that no unseen
ledger event exists. Timestamp equality alone cannot close that concurrency gap.
This PR intentionally leaves the real pilot and owner gates pending.

## Review-13 traceability and broader controls

All ten comments reviewed `1667d72`. The existing 436 tests remain; migration changes
only the expected API/earlier failure diagnostics or formerly partial human counts.
The original numerical/research tests are unchanged.

| Comment ID | Invariant and executable regression |
|---|---|
| 4112627118 | `test_even_rebound_activation_cannot_predate_its_decision`; missing activation metadata tests |
| 4112627120 | `test_duplicate_canonical_keys_are_fatal_before_indexing[notices...]` |
| 4112627123 | Same family for retention classes; full semantic retention checks before release |
| 4112627128 | Same family for session indexes; session permutation control |
| 4112627130 | Mandatory lineage document/approval; `test_no_deletion_attestation_means_no_release` and all three check-status mutations |
| 4112627131 | `test_overlapping_links_block_the_writer_in_the_reference_evaluator_too` |
| 4112627137 | Duplicate-purpose family before indexing; no uncompiled context can release |
| 4112627139 | `test_ten_thousand_repeat_captures_through_the_whole_public_release`; 10,000-node cycle/excluded-ancestor tests |
| 4112627144 | `test_assets_are_checked_before_compilation_and_again_at_release` for prompts and guidance |
| 4112627146 | `test_optional_skipped_masked_or_wrong_interpreter_jobs_never_count` and the full generated-workflow contract |

Additional controls cover all seven missing dependencies, malformed inputs,
rebound-but-invalid policies, original-input mutation, exact membership, manifest
and event permutations, authenticated-source restriction variants, target-file
symlinks, and a separately expressed finite event-order model. The model tests
648 trace/order/query combinations, including delayed grants.

`python tools/test_contract_faults.py` removes nine enforcement predicates, one at
a time in isolated subprocesses. Detection requires an actual assertion failure
and a nonzero invocation count; an import failure or timeout is not a pass. These
are named fault-injection controls, not a claim that every possible mutation or
future bug is covered. CI runs both the full suite and these controls on every
reviewed Python target. Future findings should add an invariant-level regression
at the shared boundary rather than another independent release predicate.

## CI and review trust

The custom YAML coverage parser is removed. Strict `ci-targets.json` plus the exact
complete workflow rendered by `tools/render_ci_workflow.py` define mandatory jobs.
No job/step error allowance, condition, missing check or alternate runtime binding
can silently count as reviewed coverage. Exact successful CI results are still
required; a configuration file is not a completed test run. The verifier and
renderer remain reviewed code, protected by repository review/required-check
settings outside their own control. No repository administration settings are
changed by this PR.
