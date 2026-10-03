// Pure bounds for the uploaded derivative, mirroring the server intake policy
// (intake-policy/1): 32..12000 px per side and at most 24 MP decoded. Bounding
// happens before upload so the phone never sends what the server must refuse.
// Coordinates in reports always refer to the uploaded derivative's frame; a
// crop edge is never presented as a page boundary.
import type { CropRect } from "../platform/contracts.ts";

export const MIN_DIMENSION = 32;
export const MAX_DIMENSION = 12_000;
export const MAX_PIXELS = 24_000_000;

export type DerivativePlan =
  | { readonly ok: true; readonly crop: CropRect | null;
      readonly resize: { readonly width: number; readonly height: number } | null }
  | { readonly ok: false; readonly code: "image_too_small" | "image_unreadable" };

export function clampCrop(width: number, height: number, crop: CropRect): CropRect {
  const x = Math.max(0, Math.min(width - 1, Math.round(crop.x)));
  const y = Math.max(0, Math.min(height - 1, Math.round(crop.y)));
  return { x, y, width: Math.max(1, Math.min(width - x, Math.round(crop.width))),
           height: Math.max(1, Math.min(height - y, Math.round(crop.height))) };
}

export function planDerivative(width: number, height: number, crop: CropRect | null): DerivativePlan {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return { ok: false, code: "image_unreadable" };
  }
  const bounded = crop === null ? null : clampCrop(width, height, crop);
  const isFull = bounded !== null && bounded.x === 0 && bounded.y === 0 && bounded.width === width
    && bounded.height === height;
  const effective = isFull ? null : bounded;
  const w = effective?.width ?? width;
  const h = effective?.height ?? height;
  if (w < MIN_DIMENSION || h < MIN_DIMENSION) return { ok: false, code: "image_too_small" };
  const scale = Math.min(1, Math.sqrt(MAX_PIXELS / (w * h)), MAX_DIMENSION / Math.max(w, h));
  if (scale >= 1) return { ok: true, crop: effective, resize: null };
  const resize = { width: Math.max(MIN_DIMENSION, Math.floor(w * scale)),
                   height: Math.max(MIN_DIMENSION, Math.floor(h * scale)) };
  if (resize.width * resize.height > MAX_PIXELS) {
    return { ok: true, crop: effective, resize: { width: resize.width - 1, height: resize.height - 1 } };
  }
  return { ok: true, crop: effective, resize };
}

/** Map a crop drawn on a fitted preview (display points) to working-image pixels. */
export function previewCropToPixels(crop: CropRect, preview: { width: number; height: number },
                                    image: { width: number; height: number }): CropRect {
  const sx = image.width / preview.width;
  const sy = image.height / preview.height;
  return clampCrop(image.width, image.height, { x: crop.x * sx, y: crop.y * sy, width: crop.width * sx,
                                                height: crop.height * sy });
}
