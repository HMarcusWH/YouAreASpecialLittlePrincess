// Read-only T08A presentation helpers. No salience selection exists in the client.
import { PRESENTATION } from "./presentation.generated.ts";
import { READING_CONTENT } from "./reading.generated.ts";

export type PresentationLocale = "en" | "sv";
export type PresentationDisplayDomain = Readonly<Record<string, string | number>>;

const LABELS = PRESENTATION.feature_labels as Readonly<
  Record<string, Readonly<Record<PresentationLocale, string>>>
>;
const CONTENT = PRESENTATION.content as Readonly<
  Record<string, Readonly<Record<PresentationLocale, string>>>
>;
const DOMAINS = PRESENTATION.display_domains as Readonly<Record<string, PresentationDisplayDomain>>;
const V2_LABELS = READING_CONTENT.feature_labels as Readonly<
  Record<string, Readonly<Record<PresentationLocale, string>>>
>;
const V2_CONTENT = READING_CONTENT.content as Readonly<
  Record<string, Readonly<Record<PresentationLocale, string>>>
>;

export const PRESENTATION_VERSION = PRESENTATION.version;
export const HIGHLIGHT_POLICY_VERSION = PRESENTATION.policy_version;

function language(locale: string): PresentationLocale {
  return locale.toLowerCase().startsWith("sv") ? "sv" : "en";
}

export function featureLabel(featureId: string, locale: string,
                             version: "presentation/1" | "presentation/2" = "presentation/1"): string | undefined {
  return (version === "presentation/2" ? V2_LABELS : LABELS)[featureId]?.[language(locale)];
}

export function presentationContent(contentId: string, locale: string): string | undefined {
  // Exact saved content ID lookup. Never reinterpret unknown v2 IDs as v1.
  return (CONTENT[contentId] ?? V2_CONTENT[contentId])?.[language(locale)];
}

/** A v2 title applies only when a saved section references that chapter's actual copy ID. */
export function readingChapterTitle(sectionId: string, contentIds: readonly string[],
                                    locale: string): string | undefined {
  const chapter = READING_CONTENT.chapters.find((row) => row.section_id === sectionId);
  if (!chapter || (!contentIds.includes(chapter.neutral_content_id)
                   && !contentIds.includes(chapter.unavailable_content_id))) return undefined;
  return chapter.title[language(locale)];
}

export function presentationDisplayDomain(featureId: string): PresentationDisplayDomain | undefined {
  const domain = DOMAINS[featureId];
  return domain === undefined ? undefined : { ...domain };
}
