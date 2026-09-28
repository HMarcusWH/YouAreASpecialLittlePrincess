// Read-only T08A presentation helpers. No salience selection exists in the client.
import { PRESENTATION } from "./presentation.generated.ts";

export type PresentationLocale = "en" | "sv";
export type PresentationDisplayDomain = Readonly<Record<string, string | number>>;

const LABELS = PRESENTATION.feature_labels as Readonly<
  Record<string, Readonly<Record<PresentationLocale, string>>>
>;
const CONTENT = PRESENTATION.content as Readonly<
  Record<string, Readonly<Record<PresentationLocale, string>>>
>;
const DOMAINS = PRESENTATION.display_domains as Readonly<Record<string, PresentationDisplayDomain>>;

export const PRESENTATION_VERSION = PRESENTATION.version;
export const HIGHLIGHT_POLICY_VERSION = PRESENTATION.policy_version;

function language(locale: string): PresentationLocale {
  return locale.toLowerCase().startsWith("sv") ? "sv" : "en";
}

export function featureLabel(featureId: string, locale: string): string | undefined {
  return LABELS[featureId]?.[language(locale)];
}

export function presentationContent(contentId: string, locale: string): string | undefined {
  return CONTENT[contentId]?.[language(locale)];
}

export function presentationDisplayDomain(featureId: string): PresentationDisplayDomain | undefined {
  const domain = DOMAINS[featureId];
  return domain === undefined ? undefined : { ...domain };
}
