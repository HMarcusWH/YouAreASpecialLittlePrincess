// Pure inspection of already-saved, owner-authorized fact-to-region references.
// This module maps evidence coordinates into the *actual* retained source frame.
// No client-side detection, region guessing, feature inference or new measurement.
import type { EvidenceBundle, ReportViewModel } from "@princess/contracts";
import { mapToAncestor } from "./charts.ts";

export const MAX_SOURCE_FOCUS_REGIONS = 32;

export interface FocusedSourceRegion {
  readonly regionId: string;
  readonly scope: string;
  /** Closed polygon in pixels of the exact original source image. */
  readonly points: readonly (readonly [number, number])[];
}

export interface SourceEvidenceFocus {
  readonly status: "READY" | "IMAGE_UNAVAILABLE" | "EVIDENCE_UNAVAILABLE" | "FRAME_MISMATCH" | "NO_SUPPORTED_REGIONS";
  readonly regions: readonly FocusedSourceRegion[];
  /** Count of distinct valid saved regions; the UI explicitly names the 32-region display cap. */
  readonly total: number;
}

/** Source rights are only an initial client hint. The image endpoint MUST reauthorize each GET. */
export function sourceImageEligible(view: ReportViewModel): boolean {
  return (view.projection === "OWNER" || view.projection === "FREE")
    && view.authorized_asset_ids.length > 0
    && !view.notices.some((n) => n.localization_key === "notice.source_image_omitted");
}

export function focusSourceEvidence(
  view: ReportViewModel,
  bundle: EvidenceBundle | null,
  sectionId: string,
  imageWidth: number,
  imageHeight: number,
  maxRegions = MAX_SOURCE_FOCUS_REGIONS,
): SourceEvidenceFocus {
  const unavailable = (status: SourceEvidenceFocus["status"]): SourceEvidenceFocus =>
    ({ status, regions: [], total: 0 });
  if (!Number.isInteger(maxRegions) || maxRegions < 1 || maxRegions > 64) {
    throw new RangeError("source evidence focus cap must be between 1 and 64");
  }
  if (!sourceImageEligible(view)) return unavailable("IMAGE_UNAVAILABLE");
  if (bundle === null || !view.authorized_asset_ids.includes(bundle.analysis.input_asset_id)) {
    return unavailable("EVIDENCE_UNAVAILABLE");
  }
  const roots = bundle.frames.filter((f) => f.parent_frame_id === null && f.unit === "px");
  if (roots.length !== 1 || !Number.isInteger(imageWidth) || !Number.isInteger(imageHeight)
      || roots[0]!.width !== imageWidth || roots[0]!.height !== imageHeight
      || imageWidth <= 0 || imageHeight <= 0) {
    return unavailable("FRAME_MISMATCH");
  }
  const root = roots[0]!;
  const section = view.sections.find((s) => s.section_id === sectionId);
  if (!section) return unavailable("NO_SUPPORTED_REGIONS");
  const facts = new Map(view.facts.map((f) => [f.fact_id, f] as const));
  const regions = new Map(bundle.regions.map((region) => [region.region_id, region] as const));
  const frames = new Map(bundle.frames.map((frame) => [frame.frame_id, frame] as const));
  const seen = new Set<string>();
  const mapped: FocusedSourceRegion[] = [];
  let total = 0;
  for (const factId of section.fact_ids) {
    const fact = facts.get(factId);
    // Missing/ineligible facts and authored/AI text cannot act as geometric evidence.
    if (!fact || !["READY", "UNCALIBRATED"].includes(fact.availability)
        || !["MEASURED", "COMPUTATIONAL_PROXY"].includes(fact.evidence_class)) continue;
    for (const id of fact.source_region_ids) {
      if (seen.has(id)) continue;
      seen.add(id);
      const region = regions.get(id);
      if (!region) continue;
      const frame = frames.get(region.frame_id);
      if (!frame || frame.unit !== "px"
          || ![region.x, region.y, region.width, region.height].every(Number.isFinite)
          || region.x < 0 || region.y < 0 || region.width <= 0 || region.height <= 0
          || region.x + region.width > frame.width + 1e-6
          || region.y + region.height > frame.height + 1e-6) continue;
      const corners: readonly (readonly [number, number])[] = [
        [region.x, region.y], [region.x + region.width, region.y],
        [region.x + region.width, region.y + region.height],
        [region.x, region.y + region.height],
      ];
      let points: readonly (readonly [number, number])[];
      try {
        points = corners.map(([x, y]) => mapToAncestor(bundle.frames, frame.frame_id, root.frame_id, x, y));
      } catch {
        continue; // Missing ancestor transform: no approximate or invented polygon.
      }
      if (!points.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y)
          && x >= -1e-6 && x <= imageWidth + 1e-6
          && y >= -1e-6 && y <= imageHeight + 1e-6)) continue;
      const twiceArea = points.reduce((sum, [x, y], i) => {
        const [nx, ny] = points[(i + 1) % points.length]!;
        return sum + x * ny - nx * y;
      }, 0);
      if (!Number.isFinite(twiceArea) || Math.abs(twiceArea) < 1e-6) continue;
      total += 1;
      if (mapped.length < maxRegions) {
        mapped.push({ regionId: region.region_id, scope: region.scope, points: [...points, points[0]!] });
      }
    }
  }
  return mapped.length > 0
    ? { status: "READY", regions: mapped, total }
    : unavailable("NO_SUPPORTED_REGIONS");
}
