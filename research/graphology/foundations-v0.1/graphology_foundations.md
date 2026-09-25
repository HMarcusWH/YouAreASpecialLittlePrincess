# Graphology foundations for the question and selector database

**Research date:** 25 September 2026  
**Status:** source-anchored research and application-design draft; not an activated interpretation database.  
**Repository inspected:** `HMarcusWH/YouAreASpecialLittlePrincess`, merged roadmap commit `99380a18e3e70904304aa9329cfb21606438d05d`.  
**Deliverables:** this report; a machine-readable blueprint; a readable question catalogue; a source/access register; structural validation results.

## 1. Design conclusion

The database should represent a **graphological examination protocol**, rather than a personality quiz that happens to receive a handwriting image. Its core objects are observations of writing, their place in the whole sample, school-specific combinations and qualified interpretations. Statistical unusualness is a separate application layer.

This follows a documented practitioner structure: observe and classify first, interpret second, synthesize last. BIG describes that sequence; AHAF-approved teaching emphasizes gestalt; contemporary French teaching puts space, form, movement and stroke into relation. These are sources for a tradition's method, not experimental validation of personality predictions. [BIG26] [AHAF] [CNPG_A]

The main correction to the earlier product plan is consequently:

> Feed the model the full graphical pattern and its important ordinary features, not only the outliers. A feature can dominate a sample without being uncommon in the population.

That last sentence is our architectural deduction from keeping a within-sample hierarchy and a population reference distribution separate. They answer different questions.

## 2. What was actually researched

The source register records 15 public sources: professional-body curricula, institutional/training outlines, a historical author's translated text, a glossary, practitioner expositions and two research abstracts. Access depth is recorded individually. A course outline supports a topic's place in a curriculum; it does not supply an entire scoring method.

### British operational protocol

BIG identifies Hilliger as its syllabus basis. The 2026 syllabus gives a systematic observation stage, grades graphic importance, and demands corroborating movements before including a traditional interpretation. Its profiling stage calls for coherent treatment of contradictions. We can adapt those procedural ideas while explicitly omitting clinical, intelligence, recruitment and other consequential uses also present in the original syllabus. This is a deliberate product restriction, not a claim that the original curriculum excludes those subjects. [BIGCOURSE] [BIG26]

### Crépieux-Jamin and French teaching

The inspected historical text is the 1892 English translation, *Handwriting and Expression*, from the third French edition of *L'écriture et le caractère*. The relevant principles concern contextual meanings, combinations or resultants, and the danger of inferring an opposite quality merely because a particular sign is absent. [CJ1892]

CNPG's present curriculum verifies Jaminian genre teaching and the four large components of space, form, movement and stroke. Its next module emphasizes contextual integration, form/movement, tension and signature/text. The older translation and later French taxonomies are not silently treated as identical editions. The exact late-edition species catalogue was not established in this pass. [CNPG_A] [CNPG_B]

### Gestalt teaching

AHAF requires gestalt-based teaching for the courses it approves and explicitly distinguishes personality graphology from handwriting authentication. That makes it inappropriate to describe American graphology as uniformly a one-stroke/one-trait system, or to use personality descriptions as an authentication engine. [AHAF]

### German/Swiss concepts

The Swiss professional curriculum separates measured from assessed handwriting features and includes whole-pattern concepts associated with Klages. *Formniveau* is therefore retained as a school-specific concept awaiting its exact source method, not renamed into an invented neatness score. [SGB]

### Moretti tradition

The Moretti institute's public journal abstract verifies continued use of concepts such as triple width and *Disuguale metodico*. It does not provide the complete rating procedure. Carbonari's exposition, citing Moretti, describes sign classes, degree ratings and supporting/opposing relations; the cited founder pages were not independently read here. Contin and De Biasi provide additional practitioner-level terminology. These levels of provenance remain distinct. [MORETTI_I] [CARBONARI] [CONTIN] [DEBIASI]

### Empirical boundary

Dazzi and Pedrabissi's institutional abstract reports that its two studies did not validate graphology as a personality measure. The Neter–Ben-Shakhar abstract highlights the possible contribution of the written content to limited personnel-selection prediction. This is why the schema distinguishes traditional attribution from empirical support, and why semantic content must not masquerade as graphical insight. Full papers were not reviewed in this pass. [DAZZI2009] [NETER1989]

## 3. Source fidelity and empirical support are independent

Store two independent judgements for every interpretation:

- **Source fidelity:** Did this author or school actually make this claim, with these qualifications, in this edition?
- **Empirical support:** What evidence tests that claim, and with what result?

A historical association can have excellent source fidelity and no demonstrated predictive validity. Conversely, an accurate measurement of a line angle does not validate a personality inference attached to it.

A third field, **measurement feasibility**, asks whether this sample can actually supply the required graphic observation. A rule requiring elapsed time cannot become applicable merely because its words appear in a book.

This is a proposed application provenance model. No professional body cited here has endorsed our software or this design.

## 4. Four kinds of content must stay apart

### Descriptive observations

Describe the writing: distribution of space, letter bodies and extensions, slopes, connections, trace appearance, local details and whole-pattern organization. The question catalogue is centered on these.

### School-specific interpretation

Represent a named source's associations, modifiers and constraints. Do not force all schools into the existing 16 generic `TRAD_*` report headings. Those headings can be optional display projections with explicit mappings; they are not the historical theory itself.

### Reference statistics

Represent measured unusualness in a named cohort, with the existing eligibility, uncertainty and multiplicity safeguards. The source traditions do not supply a modern population percentile merely by classifying a form.

### Presentation and branding

A share-card title or an application archetype can summarize an approved result. Earlier examples such as “Architect” or “Maverick” were product labels, not verified graphological categories. Retain a brand namespace, never a false attribution to a school.

## 5. The proposed examination structure

These 16 domains are **our application organization**, assembled from source topics and explicit product extensions. They are not advertised as an original author's universal taxonomy.

| Domain | What is recorded | Main boundary |
|---|---|---|
| Context | Task, direction, writing style, frame, scale and applicability | Collect or verify metadata; do not infer demographics. |
| Global pattern | Space/form/movement relationships and coherence | Whole-pattern appraisal is not personal worth. |
| Space | Margins, gaps and distribution of writing | Crop edges are not necessarily paper edges. |
| Size | Middle zone, extensions, body proportions and changes | Physical size requires scale. |
| Direction | Letter slant, baseline direction and regional variation | Different orientations must not be conflated. |
| Connection | Joining extent and connector shape | Connectedness alone cannot name a connector form. |
| Form | Shapes, reductions, loop space and embellishments | Simplification needs a known reference and legibility context. |
| Stroke | Image-visible trace qualities, darkness and thickness | Not measured physical pen pressure. |
| Movement | Apparent flow, rhythm, tension and variation | Appearance is not elapsed time or muscle force. |
| Local detail | Crossbars, marks, openings and other local gestures | Correctly identify eligible glyphs and script first. |
| Signature | Signature characteristics relative to body writing | No authenticity or hidden-personality conclusion. |
| Hierarchy | Important, secondary and local features | Not the same as rarity or confidence. |
| Interpretation | School-specific candidates, modifiers and alternatives | No source-backed candidate means no invented reading. |
| Reference | Eligible ranks and unusual combinations | Application statistics, not a traditional school label. |
| Pair | Matched graphical similarities and differences | No relationship-outcome probability. |
| History | Comparable changes within the writer | No automatic claim that personality or health changed. |

The underlying graphic domains occur in the curricula and glossary; reference, software context checks and historical-comparison controls are our extensions. [IHAS] [CNPG_A] [CNPG_B] [LEPOUTRE]

## 6. Distinctions the selectors must preserve

### Joining extent versus shape

The glossary treats the extent of joining separately from the way letters connect. Our proposed morphology choices include arcade, garland, angular, thread, wavy-line and copybook forms. Multiple forms can occur in one sample, so a set of region-linked observations is preferable to a forced exclusive global type. [IHAS]

The related numerical `CONNECTEDNESS_RATIO` can support the degree-of-connection question. It does not establish the answer to the morphology question.

### Rhythm versus regularity

The glossary's rhythm concept concerns overall flow and variation in tension/release, not merely identical dimensions. The source material on *Disuguale metodico* likewise makes it important not to equate meaningful variation with noise. Our design therefore distinguishes uniformity, patterned variation and unpatterned variation. It does not claim that this proposed three-way descriptor implements Moretti's sign. [IHAS] [MORETTI_I]

### Trace appearance versus pressure

The glossary separately names shading, pastose/sharp appearance and pressure. Our photo pipeline can describe visible properties and report instrumental darkness/thickness proxies. It cannot derive calibrated force from appearance. The original-paper context and actual calibrated sensor context need separate observability records. [IHAS]

### Width of a body, spacing between bodies, spacing between words

Italian practitioner descriptions name distinct width concepts. A generic component bounding-box ratio is not automatically a school-specific letter-body measure; a connected cursive word is not a single letter. Preserve separate observations and require a reviewed exact mapping before activating a named Moretti score. [CONTIN]

### Frequency, strength, importance and certainty

A frequently repeated small feature, a strong isolated feature, a dominant whole-pattern feature and a reliably identified feature are different things. Store these dimensions separately. Moretti's reported degree scale must not be rendered as a probability or percentile. [CARBONARI]

### Nominal categories versus ordinal bands

Connector forms are nominal categories. A documented width band is ordinal. A numerical gap is a measurement. A candidate ID refers to an entire eligible explanation. Do not turn all of these into VERY_LOW/LOW/MODERATE/HIGH/VERY_HIGH just because that produces an easy radar chart.

## 7. From observations to interpretations

Use the following conceptual chain:

```text
sample context and graphic observations
               |
     within-sample importance
               |
     selected school / edition
               |
 source-backed candidate associations
               |
 required evidence + modifiers + counterevidence
               |
 eligible, qualified or withheld interpretation
               |
 bounded explanation and optional brand presentation
```

Reference statistics run alongside this chain. They can identify which descriptive features are unusual, but they do not prove a traditional meaning.

### Corroboration

BIG's curriculum requires an interpretation to be supported by two other movements. Our conservative software adaptation would use at least three distinct supporting observation groups in that school profile. Slant mean, slant median and the percentage of rightward strokes are related summaries, not three independent supporting movements. This grouping policy is our implementation proposal, not an experimental proof of the rule. [BIG26]

### Absence and alternative explanations

Crépieux-Jamin explicitly warns against a missing sign being treated as proof of an opposite quality. Thus the software must distinguish an identified sign that is absent, an unobservable sign, and a question with no applicable object. [CJ1892]

For example, no identifiable `t` makes a crossbar question inapplicable; it is not evidence of missing crossbars or low ambition. A static photograph without timing cannot answer actual writing speed. The same caution applies to any traditional inference that needs unavailable evidence.

### Contradictory observations

Do not force every report to sound perfectly consistent. Record whether the conflict is between sources, regional styles, observations and a measurement, or competing interpretations. A contradictory result may require a qualification or withholding rather than a more elaborate story.

The engine's canonical record remains immutable, but that does not make the algorithm infallible. Image/measurement disagreement creates a review flag and can suppress dependent interpretation. A numerical correction requires a new validated analysis revision, not a model rewriting the original record.

## 8. A source assertion is not yet an executable rule

The machine-readable blueprint records two narrow historical association examples from Crépieux-Jamin's prose: examples concerning animation and firmness. They are **research-only**, with no automatic activation or invented thresholds. Their purpose is to show how alternative premises and contextual meanings should be stored. [CJ1892]

Each future executable association must identify:

`school + author/edition + exact location + observed concept + premise logic + supporting signs + modifiers + counter-signs + exclusions + applicable script/task + interpretation + source fidelity + empirical status + release status`.

An original passage listing alternative indicators needs `any_of`; it must not be transformed into an `all_of` requirement. A modern editorial paraphrase must retain qualifications and not silently replace an author's concept with Big Five, diagnosis or a flattering archetype.

Do not import discriminatory historical hierarchies, medical diagnoses, sexuality claims, intelligence rankings, deception claims or personnel-selection prescriptions into active output. Preserve their existence in a source review when relevant, while marking the deliberate exclusion. This is not rewriting history; it is separating historical documentation from product behavior.

## 9. Letter detail and language-specific adaptation

Letter-level graphology warrants several separate questions rather than a single “details” score. Crossbar height, length, lateral balance and terminal shape require different observations. Mark shape and its offset need different selectors. Oval closure and the location of an opening are separate. Initial and terminal graphic forms are not a directly observed temporal stroke sequence.

BIG lists diacritics and the personal pronoun I among its detailed topics. Our applicability rules must prevent an English-language PPI interpretation from being applied indiscriminately to Swedish writing or to every capital I. [BIG26]

Swedish å/ä/ö variants are explicitly **application extensions** in this draft. Dots, a stroke substitute, or dots combined with a stroke can be documented visually. No inspected source establishes a particular personality meaning for the combined form. A unique-looking mark only becomes statistically unusual if its properly defined descriptor is evaluated against an appropriate reference set.

## 10. What the Premium call should answer

The full question catalogue is not one compulsory giant prompt. A compiler selects applicable, versioned questions and supplies precomputed answers as read-only context.

This draft assigns questions to five owners:

| Owner | Count | Role |
|---|---:|---|
| User or reviewer | 4 | Context that should not be guessed. |
| Deterministic services | 24 | Measurements, documented bands, eligibility and comparisons. |
| School rule engine | 3 | Precomputed relation/support states from a reviewed pack. |
| Premium visual assessment | 28 | Qualified image-visible descriptions with source regions. |
| Premium editorial selection | 30 | Choose among supplied eligible candidates and explain their relationships. |

The model receives the image, ordinary and dominant graphic evidence, eligible reference outliers, school information and allowed answers. It does not receive permission to infer missing statistics or to fill inactive associations from memory.

A permitted candidate ID establishes its place in the approved vocabulary, not that the sample proves it. A candidate requiring image-only observations remains provisional until post-validation checks those prerequisites and the permitted evidence type. Do not describe such candidates as preverified. Ordering visual questions first in a single request also does not create a blinded assessment: the model still receives the full input, so salience and content effects need evaluation.

An empty traditional candidate list permits a descriptive report but not an improvised traditional personality reading. A question may end in a properly recorded abstention; optional omissions have reasons, not invented content.

Text visible in the handwriting is untrusted input. Beyond prompt-injection defense, evaluate the content confound: the words' meaning must not be presented as insight derived from letter shapes. Matched neutral-passage evaluations and content-aware review are appropriate proposed controls. [NETER1989]

## 11. Blueprint and database changes

The draft contains 89 question/selector definitions across 16 application domains, 44 fixed value sets with 156 entries, 33 dynamic candidate kinds, eight bounded text fields and five graphological tradition profiles plus an application namespace.

Add a source assertion and school-concept layer **before** the existing `selector_definition` tables. The resulting model is:

```text
source / edition / passage
       -> school concept / descriptive sense
       -> observation definition and capability
       -> school association / context relationship
       -> eligible candidate
       -> selector / prepared question / soft field
       -> report projection
```

The same-looking word can carry different technical senses. For example, a connector described as thread-like should not automatically inherit the meaning of an Italian trace-quality sign by translation alone. Record `sense_id` and mapping type: exact, broader, narrower, related or not mapped. [IHAS] [CONTIN]

Also split candidate origin from cardinality. `FIXED` versus `DYNAMIC` and `SINGLE` versus `MULTIPLE` are independent properties; the current scaffold's `MULTI_SELECT` should not be an alternative to “fixed enum” in the same conceptual axis.

A future sign observation record should retain presence/state, region and scope, values, frequency, degree/intensity, within-sample prominence, assessment method and version, confidence type, and referenced source assertions. Population ranks live elsewhere.

## 12. What is ready and what is not

**Ready as a research draft:** source register with access limits, the domain organization, question wording, typed selector candidates, owner routing, source-supported methodological constraints, and a clear separation of observed signs from school interpretations.

**Not claimed:** a complete historical dictionary, founder-verified numerical tables for all schools, empirical personality validity, an activated rule pack, localization completion, calibrated visual classification, or production runtime implementation.

The specific next research/authoring work is to obtain and inspect the exact texts for named Moretti/Klages/Pulver methods; complete edition-specific sign definitions; add licensed/consented visual exemplars; define thresholds only where justified; and review each proposed association, contraindication and translation. The BIG term “currency,” for instance, was verified as present but not given a guessed operational definition.

All fixed bands remain unusable until their versioned rubric exists. The historical association examples remain research-only. No source title, curriculum mention or API schema supplies the missing evidence automatically.

## 13. Verification performed

The local build performed 21 structural checks. They cover unique IDs, resolvable sources/value sets/pack references, absence of orphan fixed sets, valid canonical feature references against the actual 272-definition file, explicit draft status, inactive historical association examples, ownership separation, bounded-text policy and JSON/control-character integrity.

These are structural checks, not handwriting-accuracy or model-selection tests. No paid API call, real-person assessment or empirical corpus study was run. The production repository scaffold has not been overwritten by this research package.

## Sources

Full access-depth, attribution and limitation records are in `sources.json`.

[BIG26]: https://members.britishgraphology.org/wp-content/uploads/2025/10/BIG-SYLLABUS-OVERVIEW-2026.pdf
[BIGCOURSE]: https://www.britishgraphology.org/courses/
[AHAF]: https://ahafhandwriting.org/Handwriting_Analysis_Courses
[IHAS]: https://handwritingfoundation.org/graphology-terms/
[CNPG_A]: https://www.cnpg-formation.com/formation/CCG-1A.php
[CNPG_B]: https://www.cnpg-formation.com/formation/CCG-1B.php
[SGB]: https://sgb-graphologie.ch/cms/lehrplan.php
[CJ1892]: https://archive.org/stream/handwritingexpre00crpi/handwritingexpre00crpi_djvu.txt
[MORETTI_I]: https://istitutomoretti.it/manu-scribere-festival-della-scrittura-a-mano/
[CARBONARI]: https://www.psicologiacarbonari.it/2011/09/07/il-metodo-morettiano/
[CONTIN]: https://www.dottorcontin.com/consulenza-grafologica.html
[DEBIASI]: https://www.peritografologo.eu/teoria-e-tecnica/grafologia-morettiana/
[LEPOUTRE]: https://coursdegraphologie.com/cours-de-graphologie/
[DAZZI2009]: https://www.research.unipd.it/handle/11577/2377610
[NETER1989]: https://cris.openu.ac.il/en/publications/the-predictive-validity-of-graphological-inferences-a-meta-analyt-2/
