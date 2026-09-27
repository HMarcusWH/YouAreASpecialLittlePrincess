<!-- roadmap-v2-navigation -->
> **Roadmap v2 navigation and scope:** [index](00-index.md) · [task briefs](06-agent-backlog.md) · [machine graph](tasks.json) · [build sequence](20-end-to-end-build-sequence.md).
> This chapter's technical content is retained. Historical implementation/status examples are superseded by [tasks.json](tasks.json) and the [v2 authority amendments](00-index.md): web, iOS and Android/native payments are main-programme scope; T00, T00A and T26 are DONE; T26 remains reviewed but runtime-inactive. Earlier model aliases/prices/API examples are dated research, not approved configuration; see [current source refresh](22-research-and-source-refresh.md). Required release/owner gates are not completed by this documentation.

# 02 — Corpus acquisition, benchmarks, and continuous updates

Status: proposed statistical and collection protocol, not an acquired or calibrated corpus. See [sources](07-evidence-register.md). Counts below distinguish writers, specimens, captures and cropped characters.

## 1. What 'text samples' must mean

For visual handwriting comparison we need **images of human handwriting**, author/group identifiers sufficient to avoid double-counting, collection context, rights, and outputs of the same measurement pipeline. Plain transcriptions, generated prose, rendered handwriting fonts and LLM text embeddings cannot seed a real handwriting reference distribution.

Keep four separate collections:

1. **Synthetic fixtures:** known geometry and fault cases for algorithms and UI. Never included in human percentiles.
2. **Engineering corpus:** appropriately licensed real handwriting for accuracy, robustness and regression testing. Its representativeness is limited by its collection protocol.
3. **Product reference corpus:** explicitly authorized, quality-controlled, writer-deduplicated specimens matching the product's capture/task cohorts. This powers qualified ranks and distinctiveness.
4. **Editorial examples:** licensed or authored explanations and rule-source records. These are text content, not statistical observations.

A further writer-disjoint holdout evaluates methods and scoring choices. It must not be repeatedly tuned on or quietly promoted into the benchmark while its evaluation results are still called held-out.

## 2. Public datasets: useful candidates, not instant norms

The following decisions reflect the publisher pages inspected on 2026-09-25. Archive-level terms, privacy scope and intended commercial use still require a recorded review before download/use. A permissive code license does not clear its datasets or pretrained weights. [P04]

| Source | What the primary source establishes | Decision for this app |
|---|---|---|
| IAM | Download terms specify non-commercial research use. Forms/lines/word crops are separate representations. [S03] | Do not import into production statistics or assume derived features bypass terms. Seek written commercial permission or leave excluded. Even internal commercial R&D requires rights review. |
| CVL | 310 writers, German/English text, scanned pages; non-commercial terms. Its writing/capture protocol differs from uncontrolled phone photos. [S04] | Same permission gate. Useful potential research reference, not Swedish population norms. |
| NIST SD19 | 3,600 writers and roughly 810,000 isolated character images from forms. The page describes public-domain recognition software separately. [S05] | Candidate engineering source after exact data-license review. Do not claim the software's public-domain status automatically licenses all data. Character crops cannot calibrate page margins or natural cursive spacing. |
| DHSD v1 | 5,939 German street-name word images from 37 writers, normalized crops; CC BY 4.0 statement and an OpenStreetMap/ODbL provenance caveat. [S06] | Candidate word-level engineering evaluation after both layers are reviewed. Not 5,939 independent people; not page-layout or Swedish everyday-writing norms. |
| Historical collections | Collection and item terms differ. This round did not establish blanket commercial clearance for Bentham or a historical collection. | Do not use as a modern population baseline. A future historical-style comparison needs its own rights and cohort definition. |

No external dataset is declared cleared for product benchmarking by this document. Maintain `dataset_source` with canonical URL, release ID, archive checksum, license/attribution documents, allowed purposes (testing, benchmark statistics, display, redistribution, training), reviewer, decision date, and restrictions. Default status is `PENDING_REVIEW`, not approved because a URL is public.

## 3. Primary acquisition route: an owned, consented collection

Start with an adult volunteer or fairly compensated pilot recruited through several channels, not only the founder's friends or one school. Compensation must not depend on producing unusual writing, receiving a high score, or giving public-sharing permission.

**Proposed pilot:** about 100 distinct writers. Ask for one controlled copied passage and one neutral free-writing specimen, with repeat captures of selected pages and a later writing session for a subset. This is an engineering/collection pilot, not a license to advertise population rarity.

Grow toward 500 and then 2,000 eligible writers **within a sufficiently broad supported cohort**, subject to budget and recruitment feasibility. Counts are planning targets, not evidence already collected or universal sufficiency thresholds. Splitting 2,000 participants into dozens of cohorts does not leave 2,000 observations in each.

### Capture protocol v1

- Start with Latin-script Swedish and English as separate documented contexts; print, cursive and mixed styles are declared by the user/reviewer. Unsupported scripts receive an honest limitation, not a guessed population match.
- Use an original, rights-cleared neutral copied passage with a versioned `prompt_id`. Include common letter shapes and punctuation. Create Swedish and English variants; do not pool them merely because both are Latin script. Aim for several natural lines rather than a fixed claim that a certain word count guarantees validity.
- Collect a separate safe free-writing task about a neutral object or daily activity. Tell users not to include names, addresses, medical details or private messages. Copied and free text remain distinct task cohorts unless validation supports pooling.
- Provide blank-page guidance, even light, full page boundaries, no filters, and a roughly front-on camera view. Record blank/lined/grid/form paper and instrument category through optional structured controls.
- A repeat photo of the same page estimates capture sensitivity; a new writing session estimates within-writer variation. Neither is an independent new writer.
- Include realistic bad captures in the engineering set: shadows, rotation, perspective, pencil, faint ink, ruled paper, little text, cropped edges, mixed printing and cursive. Keep these for robustness tests rather than silently deleting evidence of failure.
- Do not promise physical size from pixel dimensions. Require an actual scale reference/page calibration for millimetres. Page-margin claims require visible/established page boundaries; a tight crop supplies crop margins, not paper margins.

### Consent and rights

Separate service processing, image retention, optional reference contribution, optional future model training, third-party AI processing, and public example sharing. Consent to one is not consent to all. Declining contribution must not reduce the already promised Free analysis. No prechecked donation box. Keep withdrawal accessible. [S20, S21]

Use pseudonymous writer IDs; do not collect real names, exact ages, gender, diagnoses or personality surveys merely to build visual norms. Adult eligibility can be recorded without a birth date. Pseudonymous is not anonymous. Uploaded examples must be the user's own writing in v1; partner comparison should invite each author to contribute/authorize their own sample.

The collection agreement must explicitly cover intended derived statistics, retention and deletion. Independent legal/privacy review determines the appropriate legal bases and wording. Do not assume signatures or all handwriting photographs automatically constitute special-category biometrics; purpose and processing matter, especially if unique identification is introduced later. [S22]

## 4. From upload to an eligible reference record

```text
service upload -> safe decoding -> immutable analysis
                               |
                      separate contribution grant
                               |
                    reference candidate + rights check
                               |
            writer/specimen/capture grouping + duplicate review
                               |
               per-feature quality and cohort eligibility
                               |
                   candidate quarantine/reviewer decision
                               |
                     next candidate benchmark release
```

Use cryptographic hashes for byte-identical duplicates and a perceptual duplicate detector only as a review signal. Perceptual similarity does not establish authorship. Retain provenance for transformed copies; never treat rotated or resized copies as new independent samples.

The reference membership policy chooses one primary eligible specimen per writer/task/cohort/release using a rule fixed before seeing its rarity score, such as first eligible submission within the collection window. Other specimens support validation or explicitly defined writer-level aggregates. Do not pick each writer's most unusual sample.

Split by writer, not page or word crop. Keep all captures from the same specimen together. Cross-dataset duplicate flags and declared author linkage reduce leakage, but do not claim perfect identity deduplication without evidence.

Quality checks operate per metric. Bad x-height can make spacing ratios unavailable while image dimensions remain valid. Use validated capture/segmentation criteria, not aesthetic regularity as a confidence shortcut. Review unusual but technically valid samples; excluding them simply because they are rare would bias the reference toward conformity.

## 5. Reference definitions

A cohort specifies script/language, copied-versus-free task, paper/capture conditions where materially relevant, quality policy, feature-set version, analysis/normalization version, member selection and sampling limitations. Select a cohort **before** looking at which one flatters the user most. Log the selection rule and any fallback.

An unknown or poorly matched cohort gets descriptive measurements, not a fake reference. Pool cohorts only after measured comparability tests justify it. Smartphone and scanner samples, handwriting and signatures, or known-scale and unknown-scale images are not interchangeable by default.

Each benchmark release includes membership and artifact hashes, cutoff time, unique-writer count, feature-specific eligible counts, exclusions, source/license distribution, configuration, calibration artifacts, review decision and release notes. It is a reproducible dataset release, not a mutable SQL query over every historical upload.

## 6. Percentiles and special-trait selection

### Within-cohort rank

For an eligible feature value `x`, use a documented tie-aware empirical midrank:

`percentile = 100 * (count(reference < x) + 0.5 * count(reference == x)) / N`.

Use the same quantization/tie policy in building and querying. Exclude **all samples from the query writer** when that writer belongs to the reference. N is the eligible unique-writer count after exclusion for that feature, not the total number of files.

The display might say: 'More right-slanted than 82% of eligible samples in our English copied-text reference, version B3.' This is illustrative wording, not a computed result. A low variability value can be highlighted as relatively regular, but directionality must be defined per feature; a higher number does not universally mean better.

The rank is a description of that finite cohort conditional on measurement accuracy. It is not proof of a percentile among Swedish adults, all app users, or humanity. Selection bias is not cured by increasing N.

### Statistical uncertainty and required sample size

For an IID writer-level sample, the DKW bound supplies a distribution-free uniform CDF sampling band: `epsilon = sqrt(log(2/alpha)/(2*N))`. The primary source states the one-sample bound while studying its two-sample extension. [S07]

Our planning calculation at alpha = 0.05 gives approximately:

| Independent eligible writers | One fixed feature: CDF band half-width | Simultaneous bound over 12 predeclared features |
|---|---:|---:|
| 500 | 6.07 percentage points | 7.86 percentage points |
| 2,000 | 3.04 percentage points | 3.93 percentage points |
| 10,000 | 1.36 percentage points | 1.76 percentage points |

The last column is our union-bound calculation using `log(2*m/alpha)`, with m = 12; it does not assume those features are independent. These are conservative sampling bounds under the stated assumptions, not confidence in measurement accuracy or population representativeness. Clustered recruitment and repeated writers violate a naive IID interpretation.

For a sampling half-width of at most five percentage points across those 12 features, this calculation requires at least 1,235 independent observations per feature. That still does not justify a precise one-percent-tail or '1 in 100 people' claim. Tail-specific intervals, capture uncertainty, cohort bias and selection effects require their own evaluation.

Do not turn these numbers into a universal N-only release rule. Store the actual estimand, interval procedure, writer-level N, eligible feature count and measurement stability. Publish coarse ranks before precise tail claims. When uncertainty crosses a badge threshold, omit or weaken the badge.

### The multiple-feature trap

With hundreds of searched features, an apparently unusual maximum is easy to find. For v1, predeclare at most 12 eligible headline descriptors across independent conceptual families; do not count means, medians and related transforms as separate evidence of uniqueness.

Use 'what stands out in this sample' before sufficient calibration exists. To label a selected result rare, calibrate the **selection procedure itself**, for example against a writer-disjoint holdout distribution of the maximum family-standardized deviation. A claim about the maximum of 272 dimensions is not justified by one unadjusted tail probability.

Combination rarity must use an actual joint reference procedure. Never multiply marginal frequencies as though slant, spacing, size and regularity were independent. Start with predeclared two-feature bins or a low-dimensional neighborhood measure and calibrate on held-out writers; defer broad 'rare profile' claims until this exists. [P02]

## 7. Pair comparison and Me-v-Me

The initial useful pair report can show native-unit differences, common features, standardized family differences and source evidence without publishing an overall percentage.

For a versioned distance, robustly scale predeclared features using the same reference release, compute differences over a common valid mask, average within families, then combine fixed family weights. Record eligible coverage and prohibit comparison below a declared coverage threshold. Missing is not zero. Constant reference features have no valid scale; omit or explicitly handle them rather than divide by an epsilon and manufacture huge z-scores.

Related features must not dominate through repetition. Include simple invariants: swapping A/B preserves distance, self-comparison has zero distance, equivalent unit conversions preserve normalized distance, and degraded coverage never improves a score through silent imputation.

The existing utility returns cosine in its mathematical range and returns zero on a zero-norm input; its canonical schema calls the result `score_0_1`. Resolve that semantic conflict before wiring it. Do not clip negative cosines and call them probabilities. Similarly, a pseudoinverse does not make an ill-conditioned covariance estimate scientifically adequate. [R03]

A 0–100 style-similarity **index** is optional and must disclose its mapping. It is not a probability of same authorship or relationship compatibility. A reference-pair percentile requires a documented pair-sampling design and writer-cluster-aware uncertainty; all N*(N-1)/2 pairs are not independent.

For Me-v-Me, distinguish capture variation, writing-task differences and method changes from a true change in writing. Never interpret these as improvement in mental health or personality. Reprocess retained inputs under the same method where authorized, otherwise restrict to comparable features and disclose the limitation.

## 8. Continuous update and deletion policy

Ingest candidates continuously, but publish reference snapshots deliberately. Initial operational cadence: build a candidate weekly when enough new eligible writers exist; a maintainer approves promotion. This is a proposed app operation, not an automation created in this conversation.

A release job freezes its cutoff, checks active rights/consents, resolves duplicates, constructs writer-disjoint splits, computes summaries, compares acquisition mix and feature drift, runs regression/privacy checks and produces an audit manifest. Compare changes against expected measurement noise and cohort composition; do not rely on one arbitrary drift-score threshold. Canary the candidate, then atomically change the active release pointer. Keep a rollback pointer to the last still-authorized release.

New uploads do not silently rewrite saved or purchased reports. New analysis uses the active eligible release; an explicit re-benchmark creates a new revision. Capture software changes require re-extracting a compatible reference set or withholding affected statistics. Never pool incompatible engine outputs without a validated bridge.

Withdrawal immediately prevents new contribution use and revokes relevant public disclosures. Locate contributions through membership lineage, delete restricted rows/assets, and retire or rebuild affected benchmark artifacts as required by the approved policy. Retention of anonymized aggregates is a legal/privacy assessment, not an automatic exemption. A deletion tombstone prevents restored backups from reactivating erased data.

Private report snapshots can be retained only under their valid service/retention basis; version immutability is not a right to keep personal data forever. Downloaded PDFs and images cannot be recalled from recipients; disclose this before sharing. Any publicly reachable derivative is revocable on our systems.

## 9. Acceptance evidence

Before public reference claims: recorded source rights and writer consent; writer-disjoint evaluation; per-feature ground-truth/repeatability results; frozen eligibility/selection plan; reproducible release hashes; leave-writer-out tests; tied/constant/missing-feature tests; multiplicity and cold-start tests; cohort-bias documentation; deletion/rebuild/rollback rehearsal.

Proposed metric-calibration targets must be written before final evaluation and reviewed for the supported input cohort. Use annotated slant/baseline/spacing/page-boundary evidence and inter-annotator disagreement, not an LLM's personality judgement as ground truth. No reference corpus, human annotation study or population calibration was executed by this roadmap PR.
