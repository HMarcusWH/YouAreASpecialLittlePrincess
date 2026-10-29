"""Issue #92: four-profile, exact-input SYNTHETIC diagnostic comparison.

This is a rights-safe engineering probe. No real-photo mode, publication gate,
model inference, OCR, production profile activation, or calibration is provided.
Use the protected T11 pathway for real handwriting; never commit real pixels.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from princess_app.application.intake import analysis_config_sha256
from princess_graphology import GraphologyEngine
from princess_graphology.engine import input_pixels_sha256
from princess_graphology.preprocessing.grid import GridQualityError

from .benchmark import (
    MAX_PIXELS, MAX_RUN_MATCH_WORK, _MatchingBudget, _checked_benchmark_image_header,
    _read_verified_image, match, to_analysis_boxes, validate_record,
)
from .strict_json import MAX_MANIFEST_JSON_BYTES, read_bounded_json_bytes, strict_loads

PROBE_VERSION = "issue92-synthetic-probe/1"
MAX_PROBE_SPECIMENS = 16
# The fourth candidate differs from the third ONLY by the opt-in v5 audit.
CANDIDATES = (
    ("legacy", "legacy", False),
    ("grid-v1", "grid-v1", False),
    ("qualified-v2", "qualified-v2", False),
    ("qualified-v2-guard-v5", "qualified-v2", True),
)
WORD_TRACE_KEYS = (
    "raw_contours", "raw_proposals", "after_geometry_filter",
    "reject_no_unique_line", "reject_ambiguous_lines", "accepted_geometry_groups",
)


def _profile_probe(image, reference_lines, reference_words, *, candidate, budget):
    """Return only bounded numeric diagnostics; never an image, pixel or box."""
    identity, profile, guard = candidate
    config = analysis_config_sha256(grid_profile=profile, evidence_guard_enabled=guard)
    began = time.process_time()
    try:
        result, evidence = GraphologyEngine(
            grid_profile=profile, evidence_guard_enabled=guard,
        ).analyze_with_evidence(image, source="<synthetic-probe>")
    except GridQualityError as exc:
        return {
            "profile": identity, "analysis_config_sha256": config,
            "status": "REJECTED", "reason": exc.code,
            "cpu_ms": round(1000 * (time.process_time() - began), 2),
            "line_count": None, "word_group_count": None,
            "text_area_ratio": None, "baseline_points": None,
            "line_region_count": None, "word_region_count": None,
            "line_match": None, "word_match": None,
            "false_zero_words": None, "qualification": None,
            "support_abstention": None, "word_audit": None,
        }

    meta = result.metadata
    if (meta.get("input_pixels_sha256") != input_pixels_sha256(image)
            or evidence.get("input_pixels_sha256") != meta["input_pixels_sha256"]):
        raise ValueError("source pixel provenance mismatch")
    forward = np.asarray(meta.get("original_to_analysis"), dtype=np.float64)
    backward = np.asarray(meta.get("analysis_to_original"), dtype=np.float64)
    if (forward.shape != (3, 3) or backward.shape != (3, 3)
            or not np.isfinite(forward).all() or not np.isfinite(backward).all()
            or not np.allclose(forward @ backward, np.eye(3), atol=1e-6)):
        raise ValueError("source-to-analysis coordinate mapping invalid")

    def measured(feature):
        return result.measurements[feature].raw_value

    line_count = measured("PAGE_LINE_COUNT")
    word_count = measured("PAGE_WORD_COUNT")
    line_regions = tuple(r.box for r in result.regions if r.scope == "LINE")
    word_regions = tuple(r.box for r in result.regions if r.scope == "WORD")
    if line_count is None and line_regions:
        raise ValueError("unqualified line evidence was emitted")
    if word_count is None and word_regions:
        raise ValueError("unqualified word evidence was emitted")
    baseline = sum(r.get("scope") == "BASELINE_POINT"
                   for r in evidence["regions"])
    if line_count is None and baseline:
        raise ValueError("unqualified baseline evidence was emitted")

    def score(expected, observed, available):
        if expected is None or not available:
            return None
        corrected = to_analysis_boxes(
            expected, forward, source_size=(image.shape[1], image.shape[0]),
            destination_size=(result.width, result.height),
        )
        return match(corrected, observed, budget=budget)

    audit = meta.get("evidence_support_audit")
    if guard and not isinstance(audit, dict):
        raise ValueError("research support audit missing")
    word_stages = audit.get("word_stages", {}) if guard else {}
    counters = word_stages.get("counts") if isinstance(word_stages, dict) else None
    word_audit = (
        {key: counters.get(key) for key in WORD_TRACE_KEYS}
        if isinstance(counters, dict) else None
    )
    qualifications = meta.get("qualification")
    qualification = (
        {key: qualifications.get(key) for key in ("foreground", "lines", "words", "page")}
        if isinstance(qualifications, dict) else None
    )
    available_lines = line_count is not None
    available_words = word_count is not None
    status = ("MEASURED" if available_lines and available_words
              else "PARTIAL" if available_lines or available_words
              else "UNQUALIFIED")
    return {
        "profile": identity, "analysis_config_sha256": config,
        "status": status, "reason": None,
        "cpu_ms": round(1000 * (time.process_time() - began), 2),
        "line_count": line_count, "word_group_count": word_count,
        "text_area_ratio": measured("PAGE_TEXT_AREA_RATIO"),
        "baseline_points": baseline,
        "line_region_count": len(line_regions),
        "word_region_count": len(word_regions),
        "line_match": score(reference_lines, line_regions, available_lines),
        "word_match": score(reference_words, word_regions, available_words),
        "false_zero_words": (
            (len(reference_words) > 0 and word_count == 0)
            if reference_words is not None and available_words else None
        ),
        "qualification": qualification,
        "support_abstention": audit.get("reason") if audit else None,
        "word_audit": word_audit,
    }


def _aggregate(rows, kind):
    labelled = [
        row for row in rows
        if row["reference_" + kind + "_n"] is not None
        and row["reference_" + kind + "_n"] > 0
    ]
    scores = [
        row["result"][kind + "_match"] for row in labelled
        if row["result"][kind + "_match"] is not None
    ]
    return {
        "nonempty_eligible_n": len(labelled),
        "nonempty_available_n": len(scores),
        "nonempty_coverage": len(scores) / len(labelled) if labelled else None,
        "nonempty_macro_f1": (
            sum(score["f1"] for score in scores) / len(scores)
            if scores else None
        ),
    }


def run_synthetic_manifest(manifest: Path, image_root: Path) -> dict:
    """Reuse bounded admission and matcher; reject ALL real-data execution.

    No original photo, path, specimen ID, writer ID, pixel hash, annotation
    coordinate, or evidence overlay is put into the returned receipt.
    """
    document = strict_loads(read_bounded_json_bytes(manifest, MAX_MANIFEST_JSON_BYTES))
    if not isinstance(document, dict) or (
            document.get("schema_version") != 2
            or document.get("split") != "synthetic"
            or document.get("synthetic") is not True
            or document.get("annotation_frame") != "original_image"):
        raise ValueError("synthetic-only v2 original-frame manifest required")
    records = document.get("specimens")
    if not isinstance(records, list) or not (1 <= len(records) <= MAX_PROBE_SPECIMENS):
        raise ValueError("synthetic specimen budget exceeded")
    root = image_root.resolve(strict=True)
    budget = _MatchingBudget(MAX_RUN_MATCH_WORK)
    rows = []
    for ordinal, record in enumerate(records):
        reference_lines, reference_words = validate_record(record, "synthetic")
        blob = _read_verified_image(root, record["image_path"], record["sha256"])
        header = _checked_benchmark_image_header(blob)
        image = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_UNCHANGED)
        if (image is None or image.dtype != np.uint8 or image.ndim not in (2, 3)
                or (image.ndim == 3 and image.shape[2] not in (3, 4))
                or image.shape[:2] != (header.height, header.width)
                or image.shape[0] * image.shape[1] > MAX_PIXELS):
            raise ValueError("synthetic source decoder or geometry mismatch")
        exact_pixels = input_pixels_sha256(image)
        probes = [
            _profile_probe(image, reference_lines, reference_words,
                           candidate=candidate, budget=budget)
            for candidate in CANDIDATES
        ]
        if exact_pixels != input_pixels_sha256(image):
            raise ValueError("candidate changed immutable input pixels")
        rows.append({
            "case_index": ordinal, "paper": record["paper"],
            "reference_lines_n": len(reference_lines) if reference_lines is not None else None,
            "reference_words_n": len(reference_words) if reference_words is not None else None,
            "profiles": probes,
        })

    aggregates = {}
    for identity, _, _ in CANDIDATES:
        entries = [{
            "reference_lines_n": case["reference_lines_n"],
            "reference_words_n": case["reference_words_n"],
            "result": next(row for row in case["profiles"] if row["profile"] == identity),
        } for case in rows]
        aggregates[identity] = {
            "cases_n": len(entries),
            "measured_n": sum(row["result"]["status"] == "MEASURED" for row in entries),
            "partial_n": sum(row["result"]["status"] == "PARTIAL" for row in entries),
            "rejected_n": sum(row["result"]["status"] == "REJECTED" for row in entries),
            "unqualified_n": sum(row["result"]["status"] == "UNQUALIFIED" for row in entries),
            "false_zero_words_n": sum(row["result"]["false_zero_words"] is True for row in entries),
            "lines": _aggregate(entries, "line"),
            "words": _aggregate(entries, "word"),
        }
    return {
        "probe_version": PROBE_VERSION,
        "data_origin": "SYNTHETIC_FIXTURE",
        "public_qualification": "NOT_AUTHORIZED",
        "thresholds_or_accuracy_approval": None,
        "case_count": len(rows),
        "profiles": aggregates,
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue #92 synthetic-only four-profile probe")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_synthetic_manifest(args.manifest, args.image_root)
    except (OSError, ValueError, cv2.error):
        parser.exit(2, "Issue #92 synthetic-only probe refused input; details withheld.\n")
    print(json.dumps(result, allow_nan=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
