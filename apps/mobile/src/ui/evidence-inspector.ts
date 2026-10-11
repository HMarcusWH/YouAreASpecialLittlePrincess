import type { EvidenceBundle } from "@princess/contracts";
import { mapToAncestor } from "@princess/report-core";

// Pure state transition for the native evidence step inspector. The inspector
// selects already-stored evidence only; it never computes, ranks or alters a measurement.
export type InspectorDirection = "PREVIOUS" | "NEXT";

export function stepEvidenceIndex(index: number, direction: InspectorDirection, count: number): number {
  if (!Number.isInteger(count) || count <= 0) return 0;
  const current = Number.isInteger(index) ? Math.min(Math.max(index, 0), count - 1) : 0;
  return direction === "PREVIOUS" ? Math.max(0, current - 1) : Math.min(count - 1, current + 1);
}

export function evidencePosition(index: number, count: number): string {
  if (!Number.isInteger(count) || count <= 0) return "0 / 0";
  const current = Number.isInteger(index) ? Math.min(Math.max(index, 0), count - 1) : 0;
  return `${current + 1} / ${count}`;
}


/** Bound native evidence rendering: all original rows stay accessible through pages. */
export const EVIDENCE_PAGE_SIZE = 20;

export function evidencePage<T>(rows: readonly T[], requestedPage: number, size = EVIDENCE_PAGE_SIZE): {
  readonly page: number;
  readonly pageCount: number;
  readonly start: number;
  readonly end: number;
  readonly rows: readonly T[];
} {
  if (!Number.isInteger(size) || size < 1) throw new RangeError("evidence page size must be positive");
  const pageCount = Math.ceil(rows.length / size);
  const page = pageCount === 0 ? 0 : Math.min(
    Math.max(Number.isInteger(requestedPage) ? requestedPage : 0, 0), pageCount - 1,
  );
  const start = page * size;
  const end = Math.min(start + size, rows.length);
  return { page, pageCount, start, end, rows: rows.slice(start, end) };
}


export type EvidenceOutline = {
  regionId: string;
  scope: "LINE" | "WORD";
  points: readonly (readonly [number, number])[];
};

/** Finite, evidence-only line/word outlines; preserve slots for both scopes. */
export function evidenceOutlines(bundle: EvidenceBundle, rootFrame: string, scale: number,
                                 maxLines = 24, maxWords = 48): EvidenceOutline[] {
  if (!Number.isFinite(scale) || scale <= 0) return [];
  if (![maxLines, maxWords].every((n) => Number.isInteger(n) && n >= 0 && n <= 72)) {
    throw new RangeError("invalid bounded evidence outline limits");
  }
  const regions = [
    ...bundle.regions.filter((r) => r.scope === "LINE").slice(0, maxLines),
    ...bundle.regions.filter((r) => r.scope === "WORD").slice(0, maxWords),
  ];
  return regions.flatMap((r): EvidenceOutline[] => {
    if (![r.x, r.y, r.width, r.height].every(Number.isFinite) || r.width <= 0 || r.height <= 0) return [];
    const source = [
      [r.x, r.y], [r.x + r.width, r.y],
      [r.x + r.width, r.y + r.height], [r.x, r.y + r.height],
      [r.x, r.y],
    ] as const;
    try {
      const points = source.map(([x, y]) => {
        const [rx, ry] = mapToAncestor(bundle.frames, r.frame_id, rootFrame, x, y);
        return [rx * scale, ry * scale] as const;
      });
      if (!points.every(([x, y]) => Number.isFinite(x) && Number.isFinite(y))) return [];
      return [{ regionId: r.region_id, scope: r.scope as "LINE" | "WORD", points }];
    } catch {
      return []; // Refuse mismatched or malformed coordinate lineage.
    }
  });
}
