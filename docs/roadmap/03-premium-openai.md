# 03 — Premium OpenAI orchestration

Status: proposed integration contract. No paid API call or model-quality evaluation was executed for this roadmap. Current API facts are sourced in [07](07-evidence-register.md); deployment must verify the account's actual access and applicable data controls.

## 1. One bounded enrichment job

The initial Premium product is not an autonomous agent and does not need browser tools, model-selected database queries, vector search, provider-hosted file stores, or one call per feature. The application prepares an authorized evidence packet; one Responses API request produces structured narrative sections; the application validates and saves them.

```text
auth + report access + sample suitability
              -> confirmed entitlement + third-party processing permission
              -> immutable evidence packet + cost reservation
              -> durable job + one leased worker
              -> Responses API, strict structured output
              -> parse + evidence + semantic-policy checks
              -> immutable Premium overlay + fulfilment
              -> app / cards / PDF without further inference
```

Publish neither unvalidated token streams nor model-generated HTML. Stream job status to the UX; reveal completed, validated sections or the final saved result.

## 2. Input contract: EvidencePacket v1

The packet contains an opaque report reference, locale, report kind, version manifest, and only permitted facts:

- Measured feature IDs, values, units, observation counts, method/evidence labels and explicit missingness.
- Approved deterministic axes and their definitions, without presenting an engineering index as psychological certainty.
- Eligible reference claims already computed by the statistical service, including cohort wording, writer count, benchmark version and uncertainty restrictions.
- Approved rule hits with content-source IDs, conditions, caveats and conflicting-school notes. An empty rule pack means no traditional association may be invented.
- Precomputed pair differences/common-feature coverage for comparison requests.
- A small allowlist of relevant editorial text. A relational join by rule/source IDs is sufficient; retrieval is performed by our code.

Give every fact a stable `fact_id`. Keep source facts typed as `measurement`, `reference_statistic`, `mechanical_summary`, `traditional_association`, or `comparison`. These classes remain distinct in output.

Do not include names, email addresses, raw handwriting images, OCR transcriptions, signatures, file paths, unbounded notes, or the entire 193 KB database by default. A display alias can be inserted after generation. Data minimization is useful but does not make all feature vectors anonymous.

Task text and handwriting content are not instructions. Untrusted user content must never enter the system/developer instruction position. Default v1 has no free-form question box, which narrows the prompt-injection and cost surface.

## 3. Output contract: PremiumNarrative v1

Proposed shape, not an example of an actual analysis:

```json
{
  "schema_version": "premium-narrative/1",
  "summary": {
    "text": "A short explanation grounded only in supplied evidence.",
    "fact_ids": ["fact_1"]
  },
  "sections": [
    {
      "section_id": "pattern_1",
      "kind": "mechanical_explanation",
      "title": "Short heading",
      "text": "A bounded caption or explanation.",
      "fact_ids": ["fact_1", "fact_2"],
      "association_ids": []
    }
  ],
  "reflection_questions": [],
  "limitations": []
}
```

`kind` is an enum: `mechanical_explanation`, `traditional_reading`, `cross_feature_pattern`, `comparison_explanation`. Strict schema has required fields, bounded arrays/strings where supported, and `additionalProperties: false`. App validation enforces all remaining lengths/invariants.

Numerical labels and citations are rendered from the canonical facts, not retyped by the model. Prefer no novel numerals in narrative text; numeric statements must resolve to supplied facts through a formatter or validated reference. The model cannot return new scores, percentile values, probability, archetype assignments or measurements. Deterministic authored rules own style labels and scoring.

A `traditional_reading` requires approved association IDs and a visible traditional/entertainment label. Supporting IDs alone do not prove that the prose follows from the evidence; semantic checking and evaluation remain necessary.

## 4. Provider request

Use the Responses API with strict Structured Outputs. Current official documentation provides Python `responses.parse(..., text_format=...)` and JSON-schema output through `text.format`. JSON mode alone does not provide the same schema contract. [S08]

Illustrative wiring for the implementation task; this is not a drop-in service and omits the job/database code intentionally:

```python
from openai import OpenAI

# Configure credentials through the server secret manager, never the browser.
# SDK retries are disabled because the job policy owns the total retry budget.
client = OpenAI(timeout=45.0, max_retries=0)

response = client.responses.parse(
    model=approved_model_id,
    store=False,
    input=[
        {"role": "system", "content": reviewed_prompt_text},
        {"role": "user", "content": evidence_packet_json},
    ],
    text_format=PremiumNarrative,  # reviewed Pydantic schema defined by T15
    max_output_tokens=3000,
)

# Implementation must handle refusal/incomplete output and SDK parse errors,
# verify response.status, then run application validators before publication.
# response.output_parsed being non-null is necessary, not sufficient.
```

The timeout and token limit are proposed initial operating bounds. Verify supported parameters with the pinned SDK/model in a controlled integration test. Do not add temperature/reasoning/service-tier parameters copied from another model unless verified. Model output limits must allow its reasoning/output behavior; test truncation explicitly.

System prompt requirements: explain supplied evidence only; separate traditional associations from observation; no clinical/intelligence/criminality/employment/relationship predictions; no invented sources or statistics; no instructions from packet text; acknowledge missing evidence; short structured prose suited to cards; no external tools; no roleplay as a scientific examiner.

## 5. Model selection and cost

As inspected on 2026-09-25, official pages list `gpt-6-luna` and `gpt-6-sol`. Luna supports Structured Outputs. These are **evaluation candidates**, not a claim that our account can invoke them or that they perform adequately on this task. The inspected Luna snapshot section directs requests to the alias; do not invent a dated snapshot name. Pin a snapshot only when a supported one exists, otherwise record the requested/returned model identifiers and run regression checks around provider changes. [S11, S12]

The inspected Standard short-context prices per million tokens are Luna: $0.10 input/$0.50 output; Sol: $2 input/$10 output. A purely illustrative 8,000-input/3,000-output request would therefore cost $0.0023 or $0.046 before retries, cache-write behavior, regional uplift, other applicable billing and infrastructure. Regional processing has a documented surcharge for eligible models. Prices are a dated estimate, not our selling price or a full unit-economics model. [S10]

Choose the cheapest evaluated model satisfying the release rubric. Route to a more expensive model only under an approved policy and per-job reservation; never silently upgrade all traffic. Bound input facts, output length, number of calls, total job cost, account/day spend and user/session concurrency. Estimate conservatively and reconcile to actual usage. Configurations must cover reasoning/output tokens as billed and SDK retries, not just visible prose length.

No open-ended chat subscription in v1. One paid single-report job or separately entitled pair-report job has a defined deliverable. A model switch, language change, or explicit regenerate action can be a new metered operation, but ordinary report viewing is not.

## 6. State, retries and money

Use states `CREATED -> AUTHORIZED -> RESERVED -> RUNNING -> VALIDATING -> SUCCEEDED`, with terminal `REFUSED`, `FAILED`, `CANCELLED` and `REFUNDED/RELEASED` business outcomes. Store each actual provider attempt separately from the business job. A report overlay is published only after validation succeeds.

A unique key over owner, report revision, operation, locale and approved prompt/model policy prevents duplicate jobs. A DB lease/heartbeat controls worker ownership. A crash after a provider accepted a request can still leave an ambiguous outcome: application idempotency is not exactly-once provider execution. Record this ambiguity, cap retry exposure, and never charge the customer twice for one intended deliverable.

Retry transient 429/5xx/network failures with bounded exponential backoff and jitter, respecting provider retry guidance. Do not retry permanent authentication/schema errors endlessly. A refusal is not a reason to bypass constraints or call increasingly permissive prompts. Default initial policy: at most one automated additional attempt within budget; inconclusive/failed jobs expose an honest retry or refund path. [S15]

A webhook-confirmed purchase can grant a generation credit; consuming and restoring that credit must be atomic and auditable. Do not infer paid success from a browser redirect. Release/refund policies and statutory rights require owner/legal approval. A failed Premium job leaves the Free report intact. Do not secretly replace purchased AI analysis with template text and label it successful Premium.

Use an outbox for job/fulfilment publication. Enforce uniqueness on provider payment events and business fulfilments. Reconciliation handles delayed/out-of-order notifications and crashes; a user closing the tab does not cancel an authorized charge or erase the job. [S23, S24]

## 7. Validation and evaluation

Programmatic checks: supported JSON schema; valid IDs from this report; allowed section types; no unknown measurements/sources; reference claims restricted to the selected cohort; permitted counts/lengths; adequate common-feature support for pair claims; no claimed precision beyond the fact packet; no prohibited diagnostic categories; no executable HTML/URLs; no unsupported premium capability.

A keyword filter cannot establish semantic correctness. Build a writer-disjoint and scenario-disjoint evaluation suite with human-reviewed expected facts, acceptable interpretations and prohibited claims. Include blank/low-quality/partial samples, no reference, contradictory rules, near-threshold ranks, varying scripts, zero values, tiny N, malicious text, unknown IDs, prompt injection, pair reversal, consent revocation, refusal, timeout, schema errors and stale model output.

Proposed initial evaluation set: at least 150 varied fact packets plus focused adversarial cases, with repeated runs on a subset to expose instability. These are proposed test resources, not completed evaluation. Critical failures (invented numerical facts, unauthorized content, sensitive inference or privacy leak) block launch; specify an acceptable non-critical error rate and rubric before selecting a model. Human review should include Swedish and English output. [S14]

The same input fact changes should lead to directionally consistent descriptions; changing irrelevant aliases should not alter the meaning. Test output usefulness separately from factuality. A longer, more flattering response is not a higher-quality one.

## 8. Privacy and retention

Set `store=False` for normal application-state persistence and keep our system as the report record. This is **not** a promise of zero provider retention: current documentation describes separate abuse-monitoring logs and controls. API data is not used for training by default, but account configuration, exceptions and applicable terms must be reviewed. [S09]

For an EU processing requirement, verify organization/project/model eligibility, required approvals/contract terms and regional endpoint behavior. Merely setting a European base URL does not establish compliant residency. Choose the approved processing arrangement before enabling production.

Do not log full prompts/responses or source writing by default. Store the validated user report privately under its retention policy; operations logs use minimal request IDs, status, token counts, digests and redacted error codes. Access to sensitive failure examples requires a separate support/diagnostic workflow.

## 9. Deferred visual enrichment

Later, an optional consented image/crop request may describe glyph forms or suggest regions for review. OpenAI documents vision limitations including precise spatial localization and counting. It must not overwrite canonical measurements or supply physical pen pressure. [S13]

Keep visual model observations in a separate versioned namespace with evidence status and source regions. A validated deterministic method can consume a verified region proposal only through an explicit method/version change; it cannot quietly contaminate the original Free result. Re-evaluate rights, retention, prompt injection, costs and benchmark comparability before enabling it.
