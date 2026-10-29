"""R5-F1: private, source-bound Free render-envelope preparation.

No public exporter selects this path yet. Renderer v2 and historical export
jobs remain unchanged until the separately reviewed v3 transport is wired.
No caller URL, provider credential, decoded pixels, or model text is accepted.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
from dataclasses import dataclass
from typing import Mapping

import numpy as np
from PIL import Image

from princess_contracts import ValidatedDocument, canonical_json, compile_document, validate_projection

from ...adapters.imaging import decode_image, inspect_header
from ...domain.intake import MAX_UPLOAD_BYTES, sniff_media_type
from ...ports.base import CallContext, InvalidInput, NotFound, PermanentFailure
from ...ports.storage import ObjectStore, StoredObject
from ..reports import ReportAccessResolver

RENDERER_VERSION = "render-template/3"
RENDER_POLICY_VERSION = "render-policy/3"
MAX_RASTER_BYTES = 2 * 1024 * 1024
MAX_SIDE = 1600
CHUNK_SIZE = 65_536
MAX_CHUNKS = 43
MAX_BASE64_CHARS = 2_796_204
MAX_ENVELOPE_BYTES = 8 * 1024 * 1024
_ALLOWED = frozenset(("image/jpeg", "image/png"))
_CHUNK = re.compile(r"^[A-Za-z0-9+/]*={0,2}$")


def _refuse(code: str) -> None:
    raise InvalidInput(code)


def _checked_source(report: ValidatedDocument, view: ValidatedDocument,
                    evidence: ValidatedDocument | None) -> tuple[dict, dict, dict | None]:
    if report.schema_name != "ReportDocument" or view.schema_name != "ReportViewModel":
        _refuse("render_source_contract_invalid")
    if validate_projection(report, view):
        _refuse("render_view_source_mismatch")
    original, projection = report.to_dict(), view.to_dict()
    evidence_doc = None
    if evidence is not None:
        if evidence.schema_name != "EvidenceBundle":
            _refuse("render_evidence_contract_invalid")
        evidence_doc = evidence.to_dict()
        if (original["evidence_bundle_id"] != evidence_doc["bundle_id"]
                or evidence_doc["analysis"] != original["analysis"]):
            _refuse("render_evidence_source_mismatch")
        known = {row["region_id"] for row in evidence_doc["regions"]}
        if any(not set(fact["source_region_ids"]) <= known for fact in projection["facts"]):
            _refuse("render_evidence_region_missing")
    return original, projection, evidence_doc


def _encoded_chunks(blob: bytes) -> tuple[str, ...]:
    encoded = base64.b64encode(blob).decode("ascii")
    if len(encoded) > MAX_BASE64_CHARS:
        _refuse("render_raster_encoding_too_large")
    parts = tuple(encoded[index:index + CHUNK_SIZE]
                  for index in range(0, len(encoded), CHUNK_SIZE))
    if not 1 <= len(parts) <= MAX_CHUNKS:
        _refuse("render_raster_encoding_too_large")
    return parts


def _verified_raster(media_type: str, sha256: str, width: int, height: int,
                     chunks: tuple[str, ...]) -> bytes:
    if (media_type not in _ALLOWED or type(width) is not int or type(height) is not int
            or not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE)
            or not isinstance(sha256, str) or re.fullmatch(r"[a-f0-9]{64}", sha256) is None
            or type(chunks) is not tuple or not (1 <= len(chunks) <= MAX_CHUNKS)):
        _refuse("render_raster_invalid")
    if any(type(chunk) is not str or not chunk or len(chunk) > CHUNK_SIZE
           or _CHUNK.fullmatch(chunk) is None or "=" in chunk for chunk in chunks[:-1]):
        _refuse("render_raster_chunks_invalid")
    joined = "".join(chunks)
    if len(joined) > MAX_BASE64_CHARS or len(joined) % 4:
        _refuse("render_raster_chunks_invalid")
    try:
        blob = base64.b64decode(joined, validate=True)
    except (binascii.Error, ValueError):
        _refuse("render_raster_chunks_invalid")
    if (not blob or len(blob) > MAX_RASTER_BYTES
            or base64.b64encode(blob).decode("ascii") != joined
            or hashlib.sha256(blob).hexdigest() != sha256):
        _refuse("render_raster_integrity_invalid")
    try:
        if sniff_media_type(blob) != media_type:
            _refuse("render_raster_media_mismatch")
        header = inspect_header(blob)
    except InvalidInput:
        _refuse("render_raster_media_mismatch")
    if (header.oriented_size != (width, height)
            or header.exif_orientation != 1 or header.frames != 1):
        _refuse("render_raster_geometry_mismatch")
    return blob


@dataclass(frozen=True)
class PreparedRaster:
    """Verified cleaned render raster; no raw source image or path is retained."""

    media_type: str
    sha256: str
    width: int
    height: int
    data_base64_chunks: tuple[str, ...]
    # Private provenance, never serialized into the RenderEnvelope contract.
    source_asset_id: str
    source_input_sha256: str
    report_digest: str
    report_revision: int
    evidence_digest: str

    def __post_init__(self) -> None:
        _verified_raster(self.media_type, self.sha256, self.width, self.height,
                         self.data_base64_chunks)
        if (not self.source_asset_id or type(self.report_revision) is not int
                or self.report_revision < 1
                or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in
                       (self.source_input_sha256, self.report_digest, self.evidence_digest))):
            _refuse("render_source_provenance_invalid")

    def to_dict(self) -> dict:
        return {
            "media_type": self.media_type, "sha256": self.sha256,
            "width": self.width, "height": self.height,
            "data_base64_chunks": list(self.data_base64_chunks),
        }


def _reencode_oriented(pixels: np.ndarray, *, source_asset_id: str,
                       source_input_sha256: str, report_digest: str,
                       report_revision: int, evidence_digest: str) -> PreparedRaster:
    """Deterministic, metadata-free scaled raster; never crop or invent pixels."""
    if pixels.ndim == 2:
        image = Image.fromarray(pixels, "L")
    elif pixels.ndim == 3 and pixels.shape[2] == 3:
        image = Image.fromarray(np.ascontiguousarray(pixels[:, :, ::-1]), "RGB")
    else:
        _refuse("render_raster_pixels_invalid")
    w, h = image.size
    if w > MAX_SIDE or h > MAX_SIDE:
        scale = min(MAX_SIDE / w, MAX_SIDE / h)
        image = image.resize((max(1, int(round(w * scale))),
                              max(1, int(round(h * scale)))), Image.Resampling.LANCZOS)
    # Both outputs originate from the already oriented, metadata-free pixels.
    # A photo PNG can exceed the strict 2 MiB envelope: use bounded JPEG
    # quality reductions instead of discarding or retaining the source bytes.
    for fmt, options in (
        ("PNG", {"optimize": True}),
        ("JPEG", {"quality": 88, "subsampling": 0}),
        ("JPEG", {"quality": 78, "subsampling": 0}),
        ("JPEG", {"quality": 64}),
        ("JPEG", {"quality": 48}),
    ):
        stream = io.BytesIO()
        image.save(stream, format=fmt, **options)
        blob = stream.getvalue()
        if len(blob) <= MAX_RASTER_BYTES:
            media_type = "image/png" if fmt == "PNG" else "image/jpeg"
            return PreparedRaster(
                media_type, hashlib.sha256(blob).hexdigest(), image.width,
                image.height, _encoded_chunks(blob), source_asset_id,
                source_input_sha256, report_digest, report_revision,
                evidence_digest,
            )
    _refuse("render_raster_too_large")


def _frame_matches(evidence_doc: dict, original_width: int, original_height: int) -> None:
    roots = [frame for frame in evidence_doc["frames"] if frame["parent_frame_id"] is None]
    if (len(roots) != 1 or roots[0]["frame_id"] != "frame_input"
            or roots[0]["width"] != original_width
            or roots[0]["height"] != original_height):
        _refuse("render_source_frame_mismatch")


def prepare_authorized_render_assets(*, owner_id: str, report_owner_id: str,
                                     report: ValidatedDocument, view: ValidatedDocument,
                                     evidence: ValidatedDocument, source: StoredObject,
                                     store: ObjectStore, access: ReportAccessResolver,
                                     ctx: CallContext) -> PreparedRaster:
    """Prepare one source raster after current owner/snapshot/source authorization.

    The source StoredObject must come from a trusted internal capture lookup,
    never a request body. Caller must recheck the live access before publication
    and download; those later lifecycle checks belong to R5-F2/F3.
    """
    if owner_id != report_owner_id:
        raise NotFound("report_not_found")
    original, projection, evidence_doc = _checked_source(report, view, evidence)
    if projection["projection"] != "EXPORT":
        _refuse("render_image_requires_owner_export_evidence")
    if evidence_doc is None:
        _refuse("render_evidence_required")
    asset_id = original["analysis"]["input_asset_id"]
    if (asset_id not in projection["authorized_asset_ids"]
            or source.asset_id != asset_id
            or source.sha256 != original["analysis"]["input_sha256"]
            or source.media_type not in _ALLOWED
            or source.size_bytes <= 0 or source.size_bytes > MAX_UPLOAD_BYTES):
        raise NotFound("source_image_not_available")
    if not access.resolve(owner_id, report).source_image_available:
        raise NotFound("source_image_not_available")
    blob = store.read_object(source, ctx)
    if (not isinstance(blob, bytes) or len(blob) != source.size_bytes
            or hashlib.sha256(blob).hexdigest() != source.sha256):
        raise PermanentFailure("render_source_digest_mismatch")
    decoded = decode_image(blob, source.media_type)
    oriented_height, oriented_width = decoded.pixels.shape[:2]
    _frame_matches(evidence_doc, oriented_width, oriented_height)
    prepared = _reencode_oriented(
        decoded.pixels, source_asset_id=asset_id,
        source_input_sha256=source.sha256,
        report_digest=projection["source_digest"],
        report_revision=projection["source_revision"],
        evidence_digest=evidence.digest,
    )
    if not access.resolve(owner_id, report).source_image_available:
        raise NotFound("source_image_not_available")
    return prepared


def compile_free_render_envelope(*, report: ValidatedDocument, view: ValidatedDocument,
                                 layout: str, detail: str = "SUMMARY",
                                 evidence: ValidatedDocument | None = None,
                                 source_image: PreparedRaster | None = None) -> ValidatedDocument:
    """Build the already-generated v3 RenderEnvelope schema from one Free view.

    No Premium, provider output, request-controlled source, or credentials.
    This constructs a candidate document; the legacy renderer never sees it.
    """
    original, projection, evidence_doc = _checked_source(report, view, evidence)
    if layout not in ("A4", "LETTER", "CARD_SQUARE", "CARD_STORY"):
        _refuse("render_layout_invalid")
    if detail not in ("SUMMARY", "FULL"):
        _refuse("render_detail_invalid")
    card = layout.startswith("CARD_")
    if (projection["projection"] != ("SHARE" if card else "EXPORT")
            or (card and (source_image is not None or evidence is not None))):
        _refuse("render_projection_scope_invalid")
    if source_image is not None:
        if not isinstance(source_image, PreparedRaster) or evidence_doc is None:
            _refuse("render_source_evidence_required")
        if original["analysis"]["input_asset_id"] not in projection["authorized_asset_ids"]:
            _refuse("render_image_not_authorized")
        if (source_image.source_asset_id != original["analysis"]["input_asset_id"]
                or source_image.source_input_sha256 != original["analysis"]["input_sha256"]
                or source_image.report_digest != projection["source_digest"]
                or source_image.report_revision != projection["source_revision"]
                or source_image.evidence_digest != evidence.digest):
            _refuse("render_image_source_mismatch")
    template = original["analysis"]["versions"]["template"]
    presentation = "presentation/2" if template == "individual-report/4" else "presentation/1"
    document = {
        "contract_version": "1.0.0", "renderer_version": RENDERER_VERSION,
        "view": projection, "premium": None, "evidence": evidence_doc,
        "source_image": source_image.to_dict() if source_image is not None else None,
        "layout": layout, "detail": detail, "locale": projection["locale"],
        "generated_at": projection["generated_at"],
        "presentation_version": presentation,
        "render_policy_version": RENDER_POLICY_VERSION,
    }
    if len(canonical_json(document).encode("utf-8")) > MAX_ENVELOPE_BYTES:
        _refuse("render_envelope_too_large")
    compiled = compile_document("RenderEnvelope", document)
    if compiled.value is None:
        raise InvalidInput("render_envelope_contract_invalid")
    return compiled.value


__all__ = [
    "CHUNK_SIZE", "MAX_BASE64_CHARS", "MAX_CHUNKS", "MAX_ENVELOPE_BYTES",
    "MAX_RASTER_BYTES", "MAX_SIDE", "PreparedRaster", "RENDERER_VERSION",
    "RENDER_POLICY_VERSION", "compile_free_render_envelope",
    "prepare_authorized_render_assets",
]
