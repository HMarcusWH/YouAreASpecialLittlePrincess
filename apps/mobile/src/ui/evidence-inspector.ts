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
