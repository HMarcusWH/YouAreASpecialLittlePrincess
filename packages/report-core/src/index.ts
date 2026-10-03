export { FORMAT_VERSION, formatFact } from "./format.ts";
export type { FormattedFact } from "./format.ts";
export { baselineTraces, histogram, mapToAncestor, spacingBrackets } from "./charts.ts";
export type { BaselineTrace, Histogram, HistogramBin, SpacingBracket } from "./charts.ts";

export { HIGHLIGHT_POLICY_VERSION, PRESENTATION_VERSION, featureLabel, presentationContent, presentationDisplayDomain } from "./presentation.ts";
export type { PresentationDisplayDomain, PresentationLocale } from "./presentation.ts";
export { contentText, featureName, sectionTitle, t } from "./messages.ts";
export type { Locale } from "./messages.ts";
export { EVIDENCE_ICON, buildDossier, displayLocale, presentFact } from "./dossier.ts";
export type { DossierModel, DossierSection, DossierSectionKind, FactPresentation } from "./dossier.ts";
