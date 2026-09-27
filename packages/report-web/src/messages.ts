// Display strings only. Fact IDs, units and values are never localized here.
// Feature names fall back to a readable form of the ID until reviewed content (T08) exists.
export type Locale = "en" | "sv";

const EN: Record<string, string> = {
  "availability.READY": "Measured",
  "availability.UNCALIBRATED": "Not calibrated",
  "availability.MISSING": "Not measured in this sample",
  "availability.NOT_IMPLEMENTED": "Not available yet",
  "availability.INELIGIBLE": "Not applicable to this sample",
  "availability.LOCKED": "Available with Premium",
  "availability.PENDING": "In progress",
  "availability.FAILED": "Could not be produced",
  "availability.REVOKED": "No longer available",
  "evidence.MEASURED": "Measured",
  "evidence.COMPUTATIONAL_PROXY": "Computed proxy",
  "evidence.REFERENCE_STATISTIC": "Reference statistic",
  "evidence.AUTHORED_CONTENT": "Authored",
  "evidence.TRADITIONAL_ASSOCIATION": "Traditional graphology",
  "evidence.AI_SYNTHESIS": "AI-assisted",
  "notice.measured": "Measured values come directly from your handwriting image.",
  "notice.proxy_uncalibrated": "Computed proxies are engineering indices. They are not calibrated and are not percentiles.",
  "notice.reference_unavailable": "No reference group is available yet, so nothing here is ranked against other writers.",
  "notice.reference_named_cohort": "Comparisons use the named reference group shown next to each rank.",
  "notice.traditional_not_included": "Traditional graphology interpretations are not included.",
  "notice.ai_synthesis": "AI-assisted sections explain measured facts; they do not change them.",
  "notice.private_report": "This report is private to your account.",
  "notice.source_image_omitted": "Source image omitted.",
  "action.COMPARE": "Compare",
  "action.EXPORT": "Export PDF",
  "action.SHARE": "Share",
  "action.SAVE": "Save",
  "action.DELETE": "Delete",
  "action.PURCHASE": "Get Premium",
  "reason.commerce_disabled": "Purchases are not available yet.",
  "reason.sharing_disabled": "Sharing is not available yet.",
  "reason.comparison_not_available": "Comparison is not available yet.",
  "projection.FREE": "Free report",
  "projection.OWNER": "Your report",
  "projection.PREMIUM": "Premium report",
  "projection.SHARE": "Shared report",
  "projection.EXPORT": "Export preview",
  "report.revision": "Revision",
  "report.facts": "Measurements",
  "report.premium_saved": "The AI-assisted section is saved with this revision.",
  "report.image_omitted": "Source image omitted.",
  "quality.observations": "observations",
};

const SV: Record<string, string> = {
  "availability.READY": "Uppmätt",
  "availability.UNCALIBRATED": "Inte kalibrerad",
  "availability.MISSING": "Inte uppmätt i detta prov",
  "availability.NOT_IMPLEMENTED": "Inte tillgänglig ännu",
  "availability.INELIGIBLE": "Gäller inte detta prov",
  "availability.LOCKED": "Ingår i Premium",
  "availability.PENDING": "Pågår",
  "availability.FAILED": "Kunde inte tas fram",
  "availability.REVOKED": "Inte längre tillgänglig",
  "evidence.MEASURED": "Uppmätt",
  "evidence.COMPUTATIONAL_PROXY": "Beräknat närmevärde",
  "evidence.REFERENCE_STATISTIC": "Referensstatistik",
  "evidence.AUTHORED_CONTENT": "Redaktionellt",
  "evidence.TRADITIONAL_ASSOCIATION": "Traditionell grafologi",
  "evidence.AI_SYNTHESIS": "AI-stött",
  "notice.measured": "Uppmätta värden kommer direkt från bilden av din handstil.",
  "notice.proxy_uncalibrated": "Beräknade närmevärden är tekniska index. De är inte kalibrerade och är inte percentiler.",
  "notice.reference_unavailable": "Det finns ännu ingen referensgrupp, så inget här rangordnas mot andra skribenter.",
  "notice.reference_named_cohort": "Jämförelser använder den namngivna referensgruppen som visas vid varje rang.",
  "notice.traditional_not_included": "Traditionella grafologiska tolkningar ingår inte.",
  "notice.ai_synthesis": "AI-stödda avsnitt förklarar uppmätta fakta; de ändrar dem inte.",
  "notice.private_report": "Den här rapporten är privat för ditt konto.",
  "notice.source_image_omitted": "Källbilden är utelämnad.",
  "action.COMPARE": "Jämför",
  "action.EXPORT": "Exportera PDF",
  "action.SHARE": "Dela",
  "action.SAVE": "Spara",
  "action.DELETE": "Radera",
  "action.PURCHASE": "Skaffa Premium",
  "reason.commerce_disabled": "Köp är inte tillgängliga ännu.",
  "reason.sharing_disabled": "Delning är inte tillgänglig ännu.",
  "reason.comparison_not_available": "Jämförelse är inte tillgänglig ännu.",
  "projection.FREE": "Gratisrapport",
  "projection.OWNER": "Din rapport",
  "projection.PREMIUM": "Premiumrapport",
  "projection.SHARE": "Delad rapport",
  "projection.EXPORT": "Förhandsgranskning av export",
  "report.revision": "Version",
  "report.facts": "Mätvärden",
  "report.premium_saved": "Det AI-stödda avsnittet är sparat med denna version.",
  "report.image_omitted": "Källbilden är utelämnad.",
  "quality.observations": "observationer",
};

const CATALOGS: Record<Locale, Record<string, string>> = { en: EN, sv: SV };

export function t(locale: Locale, key: string): string {
  return CATALOGS[locale][key] ?? CATALOGS.en[key] ?? key;
}

export function featureName(featureId: string): string {
  const words = featureId.toLowerCase().split("_");
  return words.map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w)).join(" ");
}

export function sectionTitle(template: string): string {
  const name = template.replace(/^section\./i, "").replace(/[._-]+/g, " ").toLowerCase().trim();
  return name.charAt(0).toUpperCase() + name.slice(1);
}
