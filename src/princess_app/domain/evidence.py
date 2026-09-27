"""EvidenceBundle assembly and coordinate-frame helpers (T05 handoff).

The engine emits an ``evidence/1`` payload with engine-local identifiers.
This module binds it to one analysis (run/owner/versions), fills canonical
method versions from the resolved capability manifest, and compiles it
through the T01 contract. Anything the contract rejects yields no value.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from princess_contracts import ContractIssue, ValidatedDocument, ValidationResult, compile_document

from .analysis import method_versions

EVIDENCE_PAYLOAD_VERSION = "evidence/1"
MAX_WARNING_LENGTH = 256


def build_evidence_bundle(payload: Mapping[str, Any], analysis: Mapping[str, Any],
                          bundle_id: str) -> ValidationResult[ValidatedDocument]:
    if payload.get("evidence_version") != EVIDENCE_PAYLOAD_VERSION:
        return ValidationResult(None, (ContractIssue("EVIDENCE_PAYLOAD_VERSION", "/evidence_version",
                                                     f"expected {EVIDENCE_PAYLOAD_VERSION}"),))
    versions = method_versions()
    observations = []
    for row in payload.get("observations", ()):
        version = versions.get(row.get("method_id"))
        if version is None:
            return ValidationResult(None, (ContractIssue("UNKNOWN_METHOD", "/observations",
                                                         f"method {row.get('method_id')!r} is not in the manifest"),))
        observations.append({**row, "method_version": version})
    document = {
        "contract_version": analysis.get("contract_version"),
        "bundle_id": bundle_id,
        "analysis": dict(analysis),
        "frames": [dict(f) for f in payload.get("frames", ())],
        "regions": [dict(r) for r in payload.get("regions", ())],
        "observations": observations,
        "warnings": [str(w)[:MAX_WARNING_LENGTH] for w in payload.get("warnings", ())],
    }
    return compile_document("EvidenceBundle", document)


Matrix = Sequence[float]


def _matmul(a: Matrix, b: Matrix) -> list[float]:
    return [sum(a[3 * r + k] * b[3 * k + c] for k in range(3)) for r in range(3) for c in range(3)]


def _apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    px = m[0] * x + m[1] * y + m[2]
    py = m[3] * x + m[4] * y + m[5]
    pw = m[6] * x + m[7] * y + m[8]
    if pw == 0:
        raise ValueError("point maps to infinity")
    return px / pw, py / pw


def _identity() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def transform_to_ancestor(frames: Sequence[Mapping[str, Any]], frame_id: str, ancestor_id: str) -> list[float]:
    """Compose ``transform_to_parent`` matrices from ``frame_id`` up to ``ancestor_id``."""
    by_id = {f["frame_id"]: f for f in frames}
    matrix = _identity()
    current = frame_id
    seen: set[str] = set()
    while current != ancestor_id:
        frame = by_id.get(current)
        if frame is None or frame["parent_frame_id"] is None or current in seen:
            raise ValueError(f"{ancestor_id!r} is not an ancestor of {frame_id!r}")
        seen.add(current)
        matrix = _matmul(frame["transform_to_parent"], matrix)
        current = frame["parent_frame_id"]
    return matrix


def map_point(frames: Sequence[Mapping[str, Any]], frame_id: str, ancestor_id: str,
              x: float, y: float) -> tuple[float, float]:
    return _apply(transform_to_ancestor(frames, frame_id, ancestor_id), x, y)


def prepend_source_frame(frames: Sequence[Mapping[str, Any]], *, frame_id: str, width: int, height: int,
                         root_to_new_parent: Matrix) -> list[dict[str, Any]]:
    """Attach a new root (for example the uploaded photo before crop/perspective
    rectification) above the current root. ``root_to_new_parent`` maps current
    root coordinates into the new frame."""
    if len(root_to_new_parent) != 9:
        raise ValueError("transform must be a flat 3x3 matrix")
    out = [dict(f) for f in frames]
    roots = [f for f in out if f["parent_frame_id"] is None]
    if len(roots) != 1:
        raise ValueError("frames must have exactly one root")
    if any(f["frame_id"] == frame_id for f in out):
        raise ValueError("frame id already present")
    roots[0]["parent_frame_id"] = frame_id
    roots[0]["transform_to_parent"] = [float(v) for v in root_to_new_parent]
    return [{"frame_id": frame_id, "width": int(width), "height": int(height), "unit": "px",
             "parent_frame_id": None, "transform_to_parent": None}, *out]
