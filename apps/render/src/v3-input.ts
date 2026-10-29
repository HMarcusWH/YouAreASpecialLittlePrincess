// Strict offline renderer boundary for the reviewed v3 Free RenderEnvelope.
// This is not an authorization service. It only accepts server-compiled,
// source-bound data and never looks up URLs, files, identities or model output.
import { createHash } from "node:crypto";

import type { RenderEnvelope, RenderEnvelopeSourceImage } from "@princess/contracts";
import { parseEvidenceBundle, parseReportView } from "@princess/api-client";

export const MAX_V3_INPUT_BYTES = 8 * 1024 * 1024;
export const MAX_CLEAN_IMAGE_BYTES = 2 * 1024 * 1024;
const MAX_CHUNKS = 43;
const MAX_CHUNK_CHARS = 65_536;
const MAX_BASE64_CHARS = 2_796_204;
const SHA = /^[a-f0-9]{64}$/;
const B64 = /^[A-Za-z0-9+/]+={0,2}$/;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;
const LAYOUTS = new Set(["A4", "LETTER", "CARD_SQUARE", "CARD_STORY"]);
const ROOT_KEYS = [
  "contract_version", "renderer_version", "view", "premium", "evidence",
  "source_image", "layout", "detail", "locale", "generated_at",
  "presentation_version", "render_policy_version",
] as const;

export interface CheckedV3Envelope {
  readonly envelope: RenderEnvelope;
  // Only this decoder may produce a trusted raster data URI. Never accept a
  // caller-provided URL or arbitrary data URI through the render contract.
  readonly imageDataUri: string | null;
}

function fail(code: string): never { throw new Error(code); }

function object(raw: unknown, keys: readonly string[], code: string): Record<string, unknown> {
  if (raw === null || Array.isArray(raw) || typeof raw !== "object") fail(code);
  const data = raw as Record<string, unknown>;
  if (Object.keys(data).length !== keys.length ||
      keys.some((name) => !Object.prototype.hasOwnProperty.call(data, name)) ||
      Object.keys(data).some((name) => !keys.includes(name))) fail(code);
  return data;
}

function positiveDimension(raw: unknown): number {
  if (!Number.isInteger(raw) || (raw as number) < 1 || (raw as number) > 1600) {
    fail("render_v3_image_dimensions_invalid");
  }
  return raw as number;
}

function jpegSize(bytes: Buffer): readonly [number, number] {
  if (bytes.length < 12 || bytes[0] !== 0xff || bytes[1] !== 0xd8) {
    fail("render_v3_image_bytes_invalid");
  }
  let pos = 2;
  while (pos < bytes.length) {
    if (bytes[pos] !== 0xff) fail("render_v3_image_bytes_invalid");
    while (bytes[pos] === 0xff) pos++;
    const marker = bytes[pos++];
    if (marker === undefined || marker === 0xd9 || marker === 0xda) break;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    if (pos + 2 > bytes.length) break;
    const length = bytes.readUInt16BE(pos);
    if (length < 2 || pos + length > bytes.length) break;
    if (marker === 0xe1 || marker === 0xfe) fail("render_v3_image_metadata_forbidden");
    const isSof = marker >= 0xc0 && marker <= 0xcf &&
      ![0xc4, 0xc8, 0xcc].includes(marker);
    if (isSof) {
      if (length < 7) break;
      return [bytes.readUInt16BE(pos + 5), bytes.readUInt16BE(pos + 3)];
    }
    pos += length;
  }
  fail("render_v3_image_bytes_invalid");
}

function rasterDataUri(raw: unknown): { readonly uri: string; readonly width: number; readonly height: number } {
  const v = object(raw, ["media_type", "sha256", "width", "height", "data_base64_chunks"],
                   "render_v3_image_shape_invalid") as Record<string, unknown>;
  const mime = v.media_type;
  if (mime !== "image/png" && mime !== "image/jpeg") fail("render_v3_image_media_invalid");
  if (typeof v.sha256 !== "string" || !SHA.test(v.sha256)) fail("render_v3_image_sha_invalid");
  const width = positiveDimension(v.width);
  const height = positiveDimension(v.height);
  if (!Array.isArray(v.data_base64_chunks) ||
      v.data_base64_chunks.length < 1 || v.data_base64_chunks.length > MAX_CHUNKS) {
    fail("render_v3_image_chunks_invalid");
  }
  let encoded = "";
  for (const [index, chunk] of v.data_base64_chunks.entries()) {
    if (typeof chunk !== "string" || !chunk.length || chunk.length > MAX_CHUNK_CHARS ||
        !B64.test(chunk) || (index < v.data_base64_chunks.length - 1 &&
          (chunk.length !== MAX_CHUNK_CHARS || chunk.includes("=")))) {
      fail("render_v3_image_chunks_invalid");
    }
    encoded += chunk;
    if (encoded.length > MAX_BASE64_CHARS) fail("render_v3_image_chunks_invalid");
  }
  if (encoded.length % 4 !== 0) fail("render_v3_image_chunks_invalid");
  const bytes = Buffer.from(encoded, "base64");
  if (!bytes.length || bytes.byteLength > MAX_CLEAN_IMAGE_BYTES ||
      bytes.toString("base64") !== encoded ||
      createHash("sha256").update(bytes).digest("hex") !== v.sha256) {
    fail("render_v3_image_integrity_invalid");
  }
  let dimensions: readonly [number, number];
  if (mime === "image/png") {
    if (bytes.length < 33 ||
        !bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) ||
        bytes.readUInt32BE(8) !== 13 || bytes.subarray(12, 16).toString("ascii") !== "IHDR") {
      fail("render_v3_image_bytes_invalid");
    }
    dimensions = [bytes.readUInt32BE(16), bytes.readUInt32BE(20)];
  } else {
    dimensions = jpegSize(bytes);
  }
  if (dimensions[0] !== width || dimensions[1] !== height) {
    fail("render_v3_image_dimensions_invalid");
  }
  return { uri: "data:" + mime + ";base64," + encoded, width, height };
}

export function parseV3Envelope(raw: string): CheckedV3Envelope {
  if (typeof raw !== "string" || Buffer.byteLength(raw, "utf8") > MAX_V3_INPUT_BYTES) {
    fail("render_v3_input_too_large");
  }
  let parsed: unknown;
  try { parsed = JSON.parse(raw); }
  catch { fail("render_v3_json_invalid"); }
  const env = object(parsed, ROOT_KEYS, "render_v3_shape_invalid");
  if (env.contract_version !== "1.0.0" ||
      env.renderer_version !== "render-template/3" ||
      env.render_policy_version !== "render-policy/3" ||
      (env.presentation_version !== "presentation/1" && env.presentation_version !== "presentation/2")) {
    fail("render_v3_version_invalid");
  }
  if (!LAYOUTS.has(env.layout as string) ||
      (env.detail !== "SUMMARY" && env.detail !== "FULL") ||
      (env.locale !== "en" && env.locale !== "sv") ||
      typeof env.generated_at !== "string" || !RFC3339.test(env.generated_at)) {
    fail("render_v3_options_invalid");
  }
  // Premium-v2 must have a separately qualified saved reader. Free cannot
  // render a purchased overlay through this temporary offline v3 entrypoint.
  if (env.premium !== null) fail("render_v3_premium_not_released");
  const view = parseReportView(env.view);
  const locale = env.locale as "en" | "sv";
  if (view.generated_at !== env.generated_at ||
      (view.locale !== locale && view.locale !== locale + "-SE" &&
       view.locale !== locale + "-GB" && view.locale !== locale + "-US") ||
      view.sections.some((s) => s.premium_section_id !== null)) {
    fail("render_v3_view_source_mismatch");
  }
  const card = env.layout === "CARD_SQUARE" || env.layout === "CARD_STORY";
  if (view.projection !== (card ? "SHARE" : "EXPORT")) {
    fail("render_v3_projection_invalid");
  }
  if (card && (env.evidence !== null || env.source_image !== null)) {
    fail("render_v3_share_source_forbidden");
  }
  const evidence = env.evidence === null ? null : parseEvidenceBundle(env.evidence);
  if (evidence !== null) {
    const regionIds = new Set(evidence.regions.map((r) => r.region_id));
    if (view.facts.some((fact) => fact.source_region_ids.some((id) => !regionIds.has(id)))) {
      fail("render_v3_region_lineage_invalid");
    }
  }
  let uri: string | null = null;
  if (env.source_image !== null) {
    if (evidence === null) fail("render_v3_source_evidence_required");
    if (!view.authorized_asset_ids.includes(evidence.analysis.input_asset_id)) {
      fail("render_v3_source_not_authorized");
    }
    const roots = evidence.frames.filter((f) => f.parent_frame_id === null && f.unit === "px");
    if (roots.length !== 1 || roots[0]!.frame_id !== "frame_input") {
      fail("render_v3_source_frame_invalid");
    }
    const validated = rasterDataUri(env.source_image);
    const root = roots[0]!;
    // The trusted raster may be uniformly downscaled, never an unrelated
    // crop/rotation. One output pixel accounts for rounding on each axis.
    const expectedH = Math.round(root.height * validated.width / root.width);
    if (Math.abs(expectedH - validated.height) > 1 ||
        validated.width > root.width || validated.height > root.height) {
      fail("render_v3_source_frame_invalid");
    }
    uri = validated.uri;
  }
  // The generated TypeScript shape is a consequence of the explicit checks,
  // not permission to skip the untrusted process-input validation.
  return { envelope: { ...env, view, evidence } as unknown as RenderEnvelope, imageDataUri: uri };
}

export type V3SourceImage = RenderEnvelopeSourceImage;
