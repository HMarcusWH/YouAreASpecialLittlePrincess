# PremiumModelProvider — bounded evidence-bound inference

[Connector index](README.md) · [T15](../roadmap/06-agent-backlog.md#t15) · [Premium orchestration](../roadmap/03-premium-openai.md) · [T26 handoff](../roadmap/08-premium-question-selector-database.md) · [Commerce](../roadmap/14-payments-entitlements-and-commerce.md).

## Port contract

`generate(packet, approved_policy, attempt_id, deadline) -> ProviderGenerationResult` accepts an immutable `PremiumRequestPacket`, applicable T26/question-pack versions, allowed candidate/evidence IDs, one authorized image derivative and a compiled strict output schema. The result contains parsed candidate output or refusal/incomplete/error, actual provider request/model identifiers and usage metadata. It is not a published `PremiumAnalysis` until application validation succeeds. Provider attempts use a deterministic application `attempt_id` derived from the durable job and bounded attempt number; the application journals that ID and the packet digest before transmission.

The application owns authorization, credit reservation, budget, question selection, candidate generation, reference statistics, canonical facts and the sanitized attempt journal. The adapter owns provider wire format, image encoding/authorized transfer, SDK/HTTP mapping, explicit timeout and safe error normalization. It cannot discover extra facts, browse, execute tools or change model policy after a failure. An adapter may additionally advertise `attempt_lookup`; when present, `lookup_attempt(request, deadline)` must authoritatively return the prior normalized result, `None` for a proven-absent attempt, or a typed ambiguous failure. Lookup must never generate new model work.

## OpenAI implementation default

Use a currently supported vision-capable Responses API model and strict Structured Outputs after account/model/SDK compatibility tests. No specific model alias, snapshot, price, reasoning option or temperature setting is approved by this roadmap. Disable hidden SDK retries; the business attempt policy owns the entire call/cost budget. Normal application persistence currently uses `store=false`, but consent/privacy copy must reflect actual provider retention controls and exceptions. The present OpenAI adapter therefore does **not** advertise `attempt_lookup`; its lookup method fails closed without a network request. Live restored-Premium reconciliation stays disabled until the approved provider configuration demonstrates authoritative lookup or an equivalent reviewed idempotency mechanism compatible with the data-control policy.

Construct the request from a bounded applicable packet, not the entire database, owner profile or OCR transcript. Treat every word in the image as untrusted data. Image-only observations stay outside canonical measurement namespaces. Exact numerical values render from saved facts, not model-retyped numbers. Unknown/ineligible reference or traditional candidates use their defined fallback states.

## State and failure handling

The worker writes the sanitized provider-attempt row before transmission; if that write fails, no provider request is sent. A timeout after transmission may have an unknown remote outcome, so record `AMBIGUOUS` and return `AmbiguousOutcome` rather than claiming no execution. The journal stores attempt/job identity, packet digest, policy/model/request identifiers, state, usage and timestamps only—never the image, packet, prompt or model output. Limit retries and reserve worst-case permitted cost. Authentication/schema failures are not endlessly retried; refusal is not a reason to switch to a permissive prompt.

Application validation checks schema, known IDs/cardinality, evidence ownership/version, text bounds, no new numerical claims, prohibited consequential inferences and safe rendering. Recheck current consent, grant/deletion epoch and lease fencing before publishing. On failure release/compensate credit per the approved policy and preserve Free. Reopen/export/share routes never import or call this connector.

## Tests and production gates

Fakes cover valid sparse output, impossible candidate, extra properties, hallucinated number, foreign evidence ID, refusal, truncated response, 429/retry-after, wrong model capabilities, bad image input, timeout after acceptance, deterministic attempt lookup after a lost response, proven-absent lookup and lookup/request mismatch. T16 supplies human/adversarial semantic evaluation; syntactic validity alone is not enough.

Live use requires approved API account, data/region/retention configuration, model/SDK support, evaluation result, customer processing notice and spend caps. Do not log image URLs, prompts or raw responses by default. Source E15–E17 in [22](../roadmap/22-research-and-source-refresh.md) governs the research baseline; recheck at activation.
