// Chart specifications derived only from saved evidence observations.
// No smoothing, no fitted curves, no rescaling per person.
import type { CoordinateFrame, EvidenceBundle, Observation, RegionEvidence } from "@princess/contracts";

export interface HistogramBin {
  readonly start: number;
  readonly end: number;
  readonly count: number;
}

export interface Histogram {
  readonly featureId: string;
  readonly unit: string | null;
  readonly bins: readonly HistogramBin[];
  readonly accepted: number;
  readonly rejected: number;
  readonly outOfDomain: number;
}

export function histogram(bundle: EvidenceBundle, featureId: string, domain: readonly [number, number],
                          binWidth: number): Histogram {
  const [min, max] = domain;
  if (!(binWidth > 0) || !(max > min)) {
    throw new RangeError("histogram needs a positive bin width and a non-empty domain");
  }
  const count = Math.ceil((max - min) / binWidth);
  const counts = new Array<number>(count).fill(0);
  let accepted = 0;
  let rejected = 0;
  let outOfDomain = 0;
  let unit: string | null = null;
  for (const obs of bundle.observations) {
    if (obs.feature_id !== featureId) continue;
    unit = obs.unit;
    if (!obs.accepted) {
      rejected += 1;
      continue;
    }
    accepted += 1;
    const value = obs.value;
    if (typeof value !== "number" || value < min || value > max) {
      outOfDomain += 1;
      continue;
    }
    const index = Math.min(count - 1, Math.floor((value - min) / binWidth));
    counts[index] = (counts[index] ?? 0) + 1;
  }
  const bins = counts.map((c, i) => ({ start: min + i * binWidth, end: Math.min(max, min + (i + 1) * binWidth), count: c }));
  return { featureId, unit, bins, accepted, rejected, outOfDomain };
}

export interface BaselineTrace {
  readonly lineRegionId: string;
  readonly frameId: string;
  readonly points: readonly (readonly [number, number])[];
  readonly angleDegrees: number | null;
}

export function baselineTraces(bundle: EvidenceBundle): BaselineTrace[] {
  const byLine = new Map<string, RegionEvidence[]>();
  for (const region of bundle.regions) {
    if (region.scope !== "BASELINE_POINT" || region.parent_region_id === null) continue;
    const list = byLine.get(region.parent_region_id) ?? [];
    list.push(region);
    byLine.set(region.parent_region_id, list);
  }
  const angles = new Map<string, number>();
  for (const obs of bundle.observations) {
    if (obs.feature_id === "BASELINE_ANGLE_MEAN" && obs.accepted && typeof obs.value === "number") {
      const line = obs.region_ids[0];
      if (line !== undefined) angles.set(line, obs.value);
    }
  }
  return [...byLine.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "en", { numeric: true }))
    .map(([line, points]) => ({
      lineRegionId: line,
      frameId: points[0]?.frame_id ?? "",
      points: points
        .slice()
        .sort((p, q) => p.x - q.x)
        .map((p) => [p.x + 0.5, p.y + 0.5] as const),
      angleDegrees: angles.get(line) ?? null,
    }));
}

export interface SpacingBracket {
  readonly from: RegionEvidence;
  readonly to: RegionEvidence;
  readonly gap: number;
  readonly accepted: boolean;
  readonly rejectionReason: string | null;
}

export function spacingBrackets(bundle: EvidenceBundle, featureId: "LINE_SPACING_PX" | "WORD_SPACING_PX"): SpacingBracket[] {
  const regions = new Map(bundle.regions.map((r) => [r.region_id, r] as const));
  const out: SpacingBracket[] = [];
  for (const obs of bundle.observations as readonly Observation[]) {
    if (obs.feature_id !== featureId || typeof obs.value !== "number") continue;
    const [first, second] = obs.region_ids;
    const from = first === undefined ? undefined : regions.get(first);
    const to = second === undefined ? undefined : regions.get(second);
    if (from === undefined || to === undefined) continue;
    out.push({ from, to, gap: obs.value, accepted: obs.accepted, rejectionReason: obs.rejection_reason });
  }
  return out;
}

type Matrix = readonly number[];

function multiply(a: Matrix, b: Matrix): number[] {
  const out: number[] = [];
  for (let r = 0; r < 3; r += 1) {
    for (let c = 0; c < 3; c += 1) {
      let sum = 0;
      for (let k = 0; k < 3; k += 1) sum += (a[3 * r + k] ?? 0) * (b[3 * k + c] ?? 0);
      out.push(sum);
    }
  }
  return out;
}

/** Map a point from ``fromFrameId`` up to its ancestor ``toFrameId`` (same algorithm as the Python domain). */
export function mapToAncestor(frames: readonly CoordinateFrame[], fromFrameId: string, toFrameId: string,
                              x: number, y: number): readonly [number, number] {
  const byId = new Map(frames.map((f) => [f.frame_id, f] as const));
  let matrix: number[] = [1, 0, 0, 0, 1, 0, 0, 0, 1];
  let current = fromFrameId;
  const seen = new Set<string>();
  while (current !== toFrameId) {
    const frame = byId.get(current);
    if (frame === undefined || frame.parent_frame_id === null || frame.transform_to_parent === null || seen.has(current)) {
      throw new RangeError(`${toFrameId} is not an ancestor of ${fromFrameId}`);
    }
    seen.add(current);
    matrix = multiply(frame.transform_to_parent, matrix);
    current = frame.parent_frame_id;
  }
  const [m0 = 0, m1 = 0, m2 = 0, m3 = 0, m4 = 0, m5 = 0, m6 = 0, m7 = 0, m8 = 1] = matrix;
  const w = m6 * x + m7 * y + m8;
  if (w === 0) throw new RangeError("point maps to infinity");
  return [(m0 * x + m1 * y + m2) / w, (m3 * x + m4 * y + m5) / w];
}
