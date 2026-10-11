"""Offline line/word detection evaluation. Never emit raw images or annotations."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

from princess_graphology.context import prepare_context
from princess_graphology.models import Box
from princess_graphology.preprocessing.grid import GridQualityError
from princess_graphology.segmentation_projection import propose_lines
from princess_graphology.segmentation_words import propose_words

PAPER = frozenset(("blank", "lined", "grid", "form", "unknown"))
SPLIT = frozenset(("synthetic", "development", "holdout"))
FRAMES = frozenset(("analysis_canvas", "original_image"))
MAX_SPECIMENS = 256
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 24_000_000
MAX_BOXES_PER_FAMILY = 4096


def _box(seq):
    values = tuple(seq)
    if len(values) != 4:
        raise ValueError("box must be [x,y,width,height]")
    return Box(*values)


def _validated_boxes(items, *, label):
    if not isinstance(items, list) or len(items) > MAX_BOXES_PER_FAMILY:
        raise ValueError("invalid or excessive " + label + " annotations")
    return tuple(_box(value) for value in items)


def to_analysis_boxes(boxes, matrix, *, source_size, destination_size):
    """Map the four corners of original-image rectangles to the analysis canvas.

    A rotated rectangle becomes its enclosing axis-aligned half-open pixel box.
    This introduces a known rasterization error of at most about one pixel per
    axis for pure resize, so raw center errors should always be reported.
    """
    a = np.asarray(matrix, dtype=np.float64)
    if a.shape != (3, 3) or not np.isfinite(a).all() or abs(np.linalg.det(a)) < 1e-12:
        raise ValueError("invalid original_to_analysis transform")
    sw, sh = source_size
    dw, dh = destination_size
    if min(sw, sh, dw, dh) <= 0:
        raise ValueError("invalid annotation frame dimensions")
    mapped = []
    for box in boxes:
        if box.x2 > sw or box.y2 > sh:
            raise ValueError("annotation exceeds original image")
        corners = np.asarray([[box.x, box.y, 1], [box.x2, box.y, 1],
                              [box.x2, box.y2, 1], [box.x, box.y2, 1]], dtype=np.float64)
        transformed = (a @ corners.T).T
        if not np.isfinite(transformed).all() or np.any(np.abs(transformed[:, 2]) < 1e-12):
            raise ValueError("invalid projected annotation corners")
        xy = transformed[:, :2] / transformed[:, 2:3]
        x1 = max(0, min(dw, int(np.floor(np.min(xy[:, 0])))))
        y1 = max(0, min(dh, int(np.floor(np.min(xy[:, 1])))))
        x2 = max(0, min(dw, int(np.ceil(np.max(xy[:, 0])))))
        y2 = max(0, min(dh, int(np.ceil(np.max(xy[:, 1])))))
        if x2 <= x1 or y2 <= y1:
            raise ValueError("annotation is outside analysis image")
        mapped.append(Box(x1, y1, x2 - x1, y2 - y1))
    return tuple(mapped)


def iou(a: Box, b: Box) -> float:
    dx = max(0, min(a.x2, b.x2) - max(a.x, b.x))
    dy = max(0, min(a.y2, b.y2) - max(a.y, b.y))
    overlap = dx * dy
    union = a.area + b.area - overlap
    return overlap / union if union else 0.0


def match(reference, detected, threshold=0.5):
    """One-to-one maximum-cardinality IoU match; duplicates cannot inflate recall."""
    if not 0 < threshold <= 1:
        raise ValueError("invalid IoU threshold")
    refs, boxes = tuple(reference), tuple(detected)
    graph = [[j for j, score in sorted(
        ((j, iou(ref, box)) for j, box in enumerate(boxes)),
        key=lambda pair: (-pair[1], pair[0])) if score >= threshold] for ref in refs]
    assigned = {}

    def augment(i, visited):
        for j in graph[i]:
            if j in visited:
                continue
            visited.add(j)
            if j not in assigned or augment(assigned[j], visited):
                assigned[j] = i
                return True
        return False

    for i in range(len(refs)):
        augment(i, set())
    tp = len(assigned)
    fp, fn = len(boxes) - tp, len(refs) - tp
    precision = tp / len(boxes) if boxes else (1.0 if not refs else 0.0)
    recall = tp / len(refs) if refs else (1.0 if not boxes else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    matches = sorted((i, j) for j, i in assigned.items())
    center_errors = [float(np.hypot(
        refs[i].x + refs[i].width / 2 - boxes[j].x - boxes[j].width / 2,
        refs[i].y + refs[i].height / 2 - boxes[j].y - boxes[j].height / 2))
        for i, j in matches]
    return {"reference_n": len(refs), "detected_n": len(boxes),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
            "count_mae": abs(len(refs) - len(boxes)),
            "mean_iou": float(np.mean([iou(refs[i], boxes[j]) for i, j in matches]))
                        if matches else None,
            "mean_center_error_px": float(np.mean(center_errors)) if matches else None}


def validate_record(row, split, *, allow_real=False):
    if split not in SPLIT:
        raise ValueError("unknown split")
    if not isinstance(row, dict):
        raise ValueError("invalid record")
    for name in ("specimen_id", "writer_group", "capture_group", "image_path"):
        value = row.get(name)
        if not isinstance(value, str) or not value or len(value) > 256:
            raise ValueError("invalid or missing " + name)
    if row.get("paper") not in PAPER:
        raise ValueError("invalid paper")
    digest = row.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest):
        raise ValueError("invalid image digest")
    if split != "synthetic" and (not allow_real or not row.get("rights_decision_id")):
        raise ValueError("authorized rights decision required for real data")
    return _validated_boxes(row.get("lines", []), label="line"), (
        _validated_boxes(row["words"], label="word") if "words" in row else None)


def evaluate(image, row, *, split="synthetic", profile="grid-v1", allow_real=False,
             shadow_projection=False, shadow_words=False, annotation_frame="analysis_canvas"):
    expected_lines, expected_words = validate_record(row, split, allow_real=allow_real)
    if annotation_frame not in FRAMES:
        raise ValueError("unrecognized annotation frame")
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim not in (2, 3):
        raise ValueError("invalid benchmark image")
    if image.shape[0] * image.shape[1] > MAX_PIXELS:
        raise ValueError("decoded image exceeds benchmark pixel budget")
    label = {"specimen_id": row["specimen_id"], "split": split, "paper": row["paper"]}
    trace = {}
    try:
        context = prepare_context(image, grid_profile=profile, word_trace=trace)
    except GridQualityError as error:
        return {**label, "status": "REJECTED", "reason": error.code,
                "lines": None, "words": None, "false_zero_words": None}
    if annotation_frame == "original_image":
        matrix = context.metadata["original_to_analysis"]
        source = (image.shape[1], image.shape[0])
        target = (context.width, context.height)
        expected_lines = to_analysis_boxes(expected_lines, matrix,
                                           source_size=source, destination_size=target)
        if expected_words is not None:
            expected_words = to_analysis_boxes(expected_words, matrix,
                                               source_size=source, destination_size=target)
    else:
        if any(b.x2 > context.width or b.y2 > context.height for b in expected_lines):
            raise ValueError("line annotation exceeds analysis canvas")
        if expected_words is not None and any(
            b.x2 > context.width or b.y2 > context.height for b in expected_words
        ):
            raise ValueError("word annotation exceeds analysis canvas")
    shadow = None
    if shadow_projection:
        projection = propose_lines(context.mask)
        if projection.diagnostics["truncated"]:
            raise ValueError("line candidate cap reached; specimen not scoreable")
        shadow = match(expected_lines, projection.boxes)
    word_shadow = None
    if shadow_words and expected_words is not None:
        proposals = propose_words(context.mask, context.lines)
        if proposals.diagnostics["truncated"]:
            raise ValueError("word candidate cap reached; specimen not scoreable")
        word_shadow = match(expected_words, proposals.boxes)
    return {**label, "status": "MEASURED", "reason": None,
            "line_shadow": shadow, "word_shadow": word_shadow, "word_trace": trace,
            "lines": match(expected_lines, context.lines),
            "words": match(expected_words, context.words) if expected_words is not None else None,
            "false_zero_words": (bool(expected_words) and not context.words)
                                if expected_words is not None else None}


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["split"] + "/" + row["paper"]].append(row)
    def stats(items):
        measured = [r for r in items if r["status"] == "MEASURED"]
        def family(kind):
            values = [r.get(kind) for r in measured if r.get(kind) is not None]
            return {"annotated_n": len(values),
                    "macro_precision": float(np.mean([v["precision"] for v in values])) if values else None,
                    "macro_recall": float(np.mean([v["recall"] for v in values])) if values else None,
                    "macro_f1": float(np.mean([v["f1"] for v in values])) if values else None,
                    "macro_count_mae": float(np.mean([v["count_mae"] for v in values])) if values else None,
                    "macro_matched_iou": float(np.mean([v["mean_iou"] for v in values
                                                       if v["mean_iou"] is not None]))
                                         if any(v["mean_iou"] is not None for v in values) else None,
                    "macro_center_error_px": float(np.mean([v["mean_center_error_px"] for v in values
                                                            if v["mean_center_error_px"] is not None]))
                                             if any(v["mean_center_error_px"] is not None for v in values) else None}
        return {"count": len(items), "measured": len(measured),
                "rejected": len(items) - len(measured),
                "false_zero_words": sum(r.get("false_zero_words") is True for r in measured),
                "lines": family("lines"), "words": family("words"),
                "line_shadow": family("line_shadow"), "word_shadow": family("word_shadow")}
    return {"version": 1, "overall": stats(rows),
            "conditions": {key: stats(group) for key, group in sorted(groups.items())}}


def run_manifest(manifest: Path, root: Path, *, profile="grid-v1", allow_real=False,
                 shadow_projection=False, shadow_words=False):
    """Only explicitly authorized local reads; no image bytes in JSON output."""
    document = json.loads(manifest.read_text("utf-8"))
    version = document.get("schema_version")
    if version not in (1, 2) or document.get("split") not in SPLIT:
        raise ValueError("invalid manifest")
    frame = document.get("annotation_frame", "analysis_canvas")
    if frame not in FRAMES or (version == 2 and "annotation_frame" not in document):
        raise ValueError("v2 manifests require explicit annotation_frame")
    split = document["split"]
    if split != "synthetic" and not allow_real:
        raise ValueError("real-data execution requires authorization")
    resolved_root = root.resolve(strict=True)
    specimens = document.get("specimens")
    if not isinstance(specimens, list) or len(specimens) > MAX_SPECIMENS:
        raise ValueError("invalid specimen count/budget")
    rows, seen = [], set()
    for record in specimens:
        validate_record(record, split, allow_real=allow_real)
        name = record["specimen_id"]
        if name in seen:
            raise ValueError("duplicate specimen id")
        seen.add(name)
        path = (resolved_root / record["image_path"]).resolve(strict=True)
        if not path.is_relative_to(resolved_root) or not path.is_file():
            raise ValueError("specimen outside approved root")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("specimen exceeds encoded byte budget")
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != record["sha256"]:
            raise ValueError("image SHA256 mismatch")
        image = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError("undecodable image")
        if image.shape[0] * image.shape[1] > MAX_PIXELS:
            raise ValueError("decoded image exceeds benchmark pixel budget")
        rows.append(evaluate(image, record, split=split, profile=profile, allow_real=allow_real,
                             shadow_projection=shadow_projection, shadow_words=shadow_words,
                             annotation_frame=frame))
    return {"version": 2, "profile": profile, "annotation_frame": frame,
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "summary": summarize(rows), "results": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--image-root", required=True, type=Path)
    parser.add_argument("--profile", choices=("legacy", "grid-v1"), default="grid-v1")
    parser.add_argument("--allow-authorized-real", action="store_true")
    parser.add_argument("--shadow-projection", action="store_true")
    parser.add_argument("--shadow-words", action="store_true")
    args = parser.parse_args()
    result = run_manifest(args.manifest, args.image_root, profile=args.profile,
                          allow_real=args.allow_authorized_real,
                          shadow_projection=args.shadow_projection,
                          shadow_words=args.shadow_words)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
