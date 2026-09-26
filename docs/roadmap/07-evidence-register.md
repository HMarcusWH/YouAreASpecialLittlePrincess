<!-- roadmap-v2-navigation -->
> **Roadmap v2 navigation and scope:** [index](00-index.md) · [task briefs](06-agent-backlog.md) · [machine graph](tasks.json) · [build sequence](20-end-to-end-build-sequence.md).
> This chapter's technical content is retained. Its historical status/scope examples are superseded where explicitly listed in [v2 authority amendments](00-index.md): web, iOS and Android/native payments are main-programme scope; T00 and T26 are historically DONE; T00A is pending follow-up. T26 is reviewed but inactive, not an empty scaffold. Earlier model aliases/prices/API examples are dated research, not approved configuration; see [current source refresh](22-research-and-source-refresh.md). Required release/owner gates are not completed by this documentation.

# 07 — Evidence register, research corrections and open decisions

Research reviewed on **2026-09-25**. Links identify the official/primary sources used; they are not permission grants or warranties that a future API deployment will work. Recheck live provider terms, model availability, prices and store requirements at implementation/release.

## Repository evidence

- **R01:** [README at the inspected main commit](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/blob/8f2ec7b07f23f7b3613ccc71576714f3c245e7a0/README.md), [merged PR #1](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/pull/1). Establishes 64 registered/272 defined features, experimental status and the earlier local test record. Not a fresh accuracy study.
- **R02:** [models.py](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/blob/8f2ec7b07f23f7b3613ccc71576714f3c245e7a0/src/princess_graphology/models.py). Establishes aggregate dictionary shape, strict Measurement fields and region model.
- **R03:** [comparison.py](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/blob/8f2ec7b07f23f7b3613ccc71576714f3c245e7a0/src/princess_graphology/comparison.py), [method documentation](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/blob/8f2ec7b07f23f7b3613ccc71576714f3c245e7a0/docs/measurement_methods.md). Comparison utilities are not a calibrated public similarity product; zero-variance/cosine/covariance behavior requires product-level handling.
- **R04:** [main CI run 36168879709](https://github.com/HMarcusWH/YouAreASpecialLittlePrincess/actions/runs/36168879709). Inspected result was failure. Cause was not diagnosed in this roadmap task.

## Supplied project research

These are user-provided project documents, not newly verified empirical studies or a claim that their mock interfaces already exist. The roadmap is self-contained; agents do not need private chat access to follow its decisions.

| ID | File and relevant material | SHA-256 of inspected attachment |
|---|---|---|
| P01 | `deep-research-report (1).md`: results-first flow, share cards, invites, comparison, export and analytics concepts. | `e4ccb8b14b67dcdab4f60d8757c5f11ca464c96746e78ac216cd13d791c402bc` |
| P02 | `the-ego-buttons-and-designs.md`: measured/interpretive/relative score separation; rarity methodology; shared privacy-safe cards; comparison and Me-v-Me; avoid fabricated rankings. | `56dfba02e7e638b6766dff35400d78e656148932521d3ccde5f1a21d4d1601a4` |
| P03 | `graphology_feature_database_v1.json`: canonical definitions, compute classes, evidence and future interpretation dimensions. Exact bytes match the repository schema blob. | `5c21dfc9f594bbb1c2e9dad77e3b0664a0f53b33b33697311539f7b6ca52b607` |
| P04 | `graphology_github_repo_inventory.md`: candidate source inventory; code/data/weight rights must be reviewed separately. | `47800529b9bbe928ea83737272ab7c19e188bc64a7d63c231a3fb8303c1af567` |

## Primary/official sources

| ID | Source | What it supports; important limit |
|---|---|---|
| S01 | [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) | Role/policy enforcement and owner/bypass caveats; RLS needs correct roles and tests. |
| S02 | [PostgreSQL JSON types](https://www.postgresql.org/docs/current/datatype-json.html) | JSON/JSONB storage and query capabilities; not a substitute for application schema validation. |
| S03 | [IAM download terms](https://fki.tic.heia-fr.ch/databases/download-the-iam-handwriting-database) | Non-commercial research restriction. No production or derived-statistics clearance inferred. |
| S04 | [TU Wien CVL database](https://cvl.tuwien.ac.at/research/cvl-databases/an-off-line-database-for-writer-retrieval-writer-identification-and-word-spotting/) | 310 writers, text/capture protocol and non-commercial restrictions. |
| S05 | [NIST Special Database 19](https://www.nist.gov/srd/nist-special-database-19) | Writer/character counts and dataset description; public-domain software wording is not blanket data-license verification. |
| S06 | [DHSD v1, Zenodo record 18743313](https://zenodo.org/records/18743313) | 37 writers/5,939 word crops, normalized format and declared licensing/provenance. Review CC BY and OSM/ODbL aspects separately. |
| S07 | [Wei and Dudley, DKW inequalities](https://arxiv.org/abs/1107.5356) | Primary mathematical statement of the one-sample DKW/Massart bound in a paper about the two-sample extension. Roadmap numerical examples and the finite-feature union bound are our calculations under explicit assumptions. |
| S08 | [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) | Responses structured output and SDK parsing, supported schema behavior, refusals/limitations. Schema adherence is not factual accuracy. |
| S09 | [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) | API training defaults, storage/abuse-monitoring distinctions and regional eligibility. `store=false` is not universal zero retention. |
| S10 | [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) | Dated Standard short-context token rates and regional processing uplift. The roadmap's arithmetic excludes other possible cost categories explicitly. |
| S11 | [GPT-6 Luna model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna) | Listed capabilities and model identifier as of review. No claim of this account's access or a dated pinned snapshot. |
| S12 | [GPT-6 Sol model documentation](https://developers.openai.com/api/docs/models/gpt-6-sol) | Candidate model documentation; quality must be evaluated on this product. |
| S13 | [OpenAI images and vision](https://developers.openai.com/api/docs/guides/images-vision) | Input/vision behavior and limitations relevant to precision geometry/counting. |
| S14 | [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices) | Evaluation design and ongoing regression practice, not a product-specific accuracy guarantee. |
| S15 | [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits) | Rate-limit and backoff considerations; retries still need an application cost/fulfilment policy. |
| S16 | [Claude Design announcement](https://www.anthropic.com/news/claude-design-anthropic-labs), [current product page](https://claude.com/product/design) | Codebase/design inputs, interactive prototypes and implementation handoff. Prototype output still requires engineering review. |
| S17 | [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Accessibility standard used as a design/release target. No conformance is claimed before testing. |
| S18 | [Playwright Page API](https://playwright.dev/docs/api/class-page) | Print-CSS PDF generation and rendering options. Tagged output alone is not proof of accessible reading order. |
| S19 | [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) | Layered file validation, size/storage and execution-risk controls. |
| S20 | [EDPB lawful processing guidance](https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_en) | Lawful basis/consent considerations; product contribution purposes need review. |
| S21 | [EU business data protection guidance](https://europa.eu/youreurope/business/dealing-with-customers/data-protection/data-protection-gdpr/index_en.htm) | Transparency, individual rights, retention and controller obligations. |
| S22 | [European Commission sensitive personal data guidance](https://commission.europa.eu/law/law-topic/data-protection/rules-business-and-organisations/legal-grounds-processing-data/sensitive-data/what-personal-data-considered-sensitive_en) | Special-category treatment includes biometric data for unique identification. Handwriting handling requires purpose-specific analysis, not a universal classification. |
| S23 | [Stripe webhooks](https://docs.stripe.com/webhooks) | Signature verification, duplicate/out-of-order delivery and fulfilment design. |
| S24 | [Stripe idempotent requests](https://docs.stripe.com/api/idempotent_requests) | Stripe request semantics; this does not establish OpenAI exactly-once execution. |
| S25 | [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/) | Starting point for current native billing/privacy/third-party-AI disclosure review. Google and jurisdiction-specific rules must be checked when native release is scoped. |
| S26 | [PostgreSQL SELECT/locking](https://www.postgresql.org/docs/current/sql-select.html) | Locking and `SKIP LOCKED` queue-like consumers; not a complete job-system implementation. |
| S28 | [Neter and Ben-Shakhar, 1989](https://doi.org/10.1016/0191-8869(89)90120-7) | Meta-analysis of graphology in personnel selection and script-content confounding. Supports caution; it does not validate our personality scores or supply their ground truth. |

## Corrections that agents must preserve

1. **Free is zero AI, not merely zero API billing.** The historical schema includes OCR and small-ML features as free-compute; the runtime capability policy is stricter.
2. **A definition is not an implemented or calibrated feature.** Counts of 272/217/189 are inventory counts, not guaranteed report lengths.
3. **The UX research is a concept/strategy input, not a verified audit of existing screens.** Its assumed Figma/assets and illustrative score examples are not facts about this repo. Do not ship unsupported copy such as a weekday causing slant changes, 'handwriting reveals the truth about you', or invented Big Five/rarity scores.
4. **The PDF is an export, not the primary product.** Complete entitled content is available in-app; share cards are separate selective disclosures.
5. **External datasets are not automatically product norms.** Writer count, collection context, rights and population representativeness matter. Font-generated images and repeated crops never inflate the human sample size.
6. **A prompt example is not a rule source.** Reserved traditional dimensions and arbitrary example weights are not a reviewed association database.
7. **Structured Outputs validates shape, not truth.** Evidence linking, semantic checks and evaluation are separate tasks.
8. **`store=false` does not promise zero provider retention.** Regional configuration, account approval, contracts and abuse-monitoring behavior must be verified.
9. **A model alias is not an invented dated snapshot.** Record actual identifiers; re-evaluate changes.
10. **Merged is not green CI.** The inspected main run failed; the cause and supported matrix still require T00 evidence.
11. **A zero-AI computation is not free infrastructure.** Model-token arithmetic does not include data acquisition, CPU, exports, payment costs or support.

## Open owner decisions

Actual hosting/auth/payment providers and contracts; approved data locations/retention; participant agreement and acquisition budget; supported initial cohorts; numeric accuracy/coverage targets; editorial rule pack; production model/account access and spend; retail price/refund terms; approved Claude Design brand/UI; native release timing.

Until decided, use explicit disabled capabilities and synthetic test fixtures. The roadmap intentionally does not insert fabricated approvals, population data, model-evaluation scores, UX screenshots, or revenue projections.
