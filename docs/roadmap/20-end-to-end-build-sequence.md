# 20 — End-to-end coding sequence and PR handoffs

[Index](00-index.md) · [Generated detailed briefs](06-agent-backlog.md) · [Machine graph](tasks.json) · [Readiness gates](21-release-readiness-checklists.md).

## The machine graph wins

Task IDs T00–T26 are preserved. T00A records the post-merge hardening follow-up. T27–T33 add connector/environment/mobile/store work. T25 is now multi-platform signoff; T19 is shared backend commerce. Hard dependencies are stored only in tasks.json, not a separately maintained READY list.

```bash
python docs/roadmap/plan_tools.py --ready
python docs/roadmap/plan_tools.py --active
python docs/roadmap/plan_tools.py --task T11
```

At the current implementation baseline, `--ready` yields no newly startable planned task. `--active` yields **T11, T17, T19, T21, T24 and T29**. T10 and T18 are DONE. T29's provider-independent native foundation is implemented/qualified across Android and iOS simulator builds; signed-device/IAP and live processor evidence remain separately gated.

## Current handoff

The [post-PR14 reconciliation](23-post-pr14-reconciliation.md) is retained as historical evidence. Current status comes from [tasks.json](tasks.json) and the generated backlog.

- **READY planned work:** none at this graph state while T29 is actively claimed.
- **Active incomplete work:** T11 (human pilot gates/real evidence), T17 (production identity plus accepted-design integration), T19 (real payment rails/sandbox evidence and product policy), T24 (deployment/recovery/live providers) and T29 (signed-device/IAP plus live-processor evidence).
- **Implemented pending review:** T21 (final accepted-design integration/render review).
- **Completed since PR #14:** T10 accepted Inktrospect/Dossier design handoff, T15 provider-independent Premium adapter/runtime work, T08A calibration-independent presentation/first-reveal policy and T18 deterministic pair/history comparison are DONE; live model activation/evaluation and population calibration remain separately gated.
- **Native foundation:** T29 is IN_PROGRESS after establishing the shared Expo/RN scaffold, native ports, exact dependency matrix and cross-platform compile qualification.
- **Optional enhancement:** T07 remains non-blocking if omitted from the approved marketed scope.

Do not collapse this into a single percentage. `--ready` answers what new planned task may start; `--active` answers what already-started tasks still need work.

## Phases and parallel lanes

1. **Close the foundation:** T00A fixes the four recorded review gaps. T03 drafts purpose/retention/collection contracts independently. T01 then freezes product schemas and Free isolation. T26 remains reviewed/inactive and is consumed, not rebuilt.
2. **Expose stable seams:** T27 defines application-owned connector ports/fakes; T28 establishes isolated reproducible environments and build matrices. T05 produces actual evidence while T10 develops contract-driven visual/native design. T02 adds persistence/identity/authorization using the ports and environment.
3. **Make a usable Free slice:** T04 implements safe uploads and durable jobs. T09 assembles report snapshots from T01/T05 without requiring a real reference release or model. T08A adds reviewed presentation labels/non-population display domains and the server-owned first reveal without waiting for empirical calibration. T17 integrates the web journey. T29 builds the mobile shell/platform seam and compatibility spike; it need not wait for every paid journey to exist.
4. **Run empirical and Premium lanes:** T11 collects approved pilot evidence after safe intake; T06 calibrates; T08 consumes T06 plus T08A to add calibrated normalization and calibration-sensitive content; T12/T13/T14 build the reference/release pipeline. T15 implements the evidence-bound model adapter against T09/T26 with mocks; T16 performs approved evals. These lanes meet before production claims are enabled.
5. **Integrate commerce and presentation:** after T15 establishes the Premium attempt/result contract, T19 implements the shared ledger and Stripe/Apple/Google server adapters without waiting for native UI completion. T18 adds deterministic comparisons; T21 lands shared exports; T24 establishes notification/support operations and the redacted feedback backend; T20 then closes the web paid journey against those real exports, paid-state semantics and feedback API; T22 adds scoped sharing/invitations.
6. **Complete native journeys:** after T20 publishes the shared paid-state fixtures/semantics and T24 provides server-side push operations, T30/T31 integrate capture, account-backed reports/history, native purchases, Premium, comparison, export, links, push and deletion against the established services. A native shell is not task completion. Use internal PR slices for each feature; the task stays open until its full integrated acceptance passes.
7. **Qualify and release:** T23 runs full multi-platform QA/security/privacy/recovery evidence. T32/T33 assemble App Store/Play readiness and actual review/testing evidence. T25 checks owner gates and publishes the approved scope in staged releases. No circular dependency from store approval back to building the API.

The sequence deliberately avoids making mobile clients prerequisites of the shared ledger. It also avoids making partner-grant API implementation depend on an already released mobile app. Mock-based sub-PRs must state which real integration remains outstanding.

## PR-sized work within a task

A task may contain several cohesive PRs: contract/fake; pure use case; adapter/persistence; integrated UX; adversarial/operational acceptance. Do not combine database redesign, model selection, payment rollout and native UI into one giant implementation commit. An adapter cannot silently change a DTO shared with another lane.

Before implementation include: task ID, base commit, predecessor evidence, selected ADR status, owned paths, contract/schema versions, planned migrations, test data rights, exact acceptance cases, required secrets (names only), owner gates and rollback. During the PR report actual commands and failures. At handoff include exported fixtures/schema digest, API operation IDs, migration compatibility, fake behavior, sample-safe logs and remaining blocked capabilities.

## Completion protocol

`DONE` requires all implementation acceptance, actual exact-head tests and review disposition recorded. `IN_PROGRESS` and `IMPLEMENTED_PENDING_REVIEW` record `implementation_evidence` where available and explicit `remaining_work`; a merge never erases residuals. Human-only deliverables need real evidence. For an implementation that is deliberately disabled pending a human gate, record the disabled state and outstanding gate separately. A new review finding creates a linked follow-up task or reopens the affected task; it is not erased by a merge.

When a task changes schemas, update JSON source, generated DTOs, fixtures, codegen drift checks, consumers and migration notes in the same scoped series. When it changes data/claims, version engine/content/reference/model policy independently. When it changes mobile/native dependencies, rebuild and retest the native binary rather than relying on an OTA-only update.

## Final system integration trace

An authorized client reserves an upload asset → T04 verifies immutable input and schedules extraction → core produces canonical measurements → T05 packages actual evidence → T09 publishes an authorized report revision → T17/T30/T31 render the same facts → T19 verifies a purchase and grants a credit → T15 reserves/executes/validates a bounded Premium job → the saved overlay becomes available through the same report projection → T21 renders export bytes → T22 controls disclosure → T24 operates deletion/recovery/alerts → T23/T32/T33 supply release evidence → T25 approves publication.

At each arrow there is a typed contract, version reference, owner/grant check and failure case. No client has a second measurement engine or credit counter. No provider callback bypasses the application ledger. No render path generates new AI content.
