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

PAPER = frozenset(("blank", "lined", "grid", "form", "unknown"))
SPLIT = frozenset(("synthetic", "development", "holdout"))


def _box(seq):
    values = tuple(seq)
    if len(values) != 4:
        raise ValueError("box must be [x,y,width,height]")
    return Box(*values)


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
    return tuple(_box(box) for box in row.get("lines", [])), (
        tuple(_box(box) for box in row["words"]) if "words" in row else None)


def evaluate(image, row, *, split="synthetic", profile="grid-v1", allow_real=False):
    expected_lines, expected_words = validate_record(row, split, allow_real=allow_real)
    label = {"specimen_id": row["specimen_id"], "split": split, "paper": row["paper"]}
    try:
        context = prepare_context(image, grid_profile=profile)
    except GridQualityError as error:
        return {**label, "status": "REJECTED", "reason": error.code,
                "lines": None, "words": None, "false_zero_words": None}
    return {**label, "status": "MEASURED", "reason": None,
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
            values = [r[kind] for r in measured if r[kind] is not None]
            return {"annotated_n": len(values),
                    "macro_f1": float(np.mean([v["f1"] for v in values])) if values else None,
                    "macro_count_mae": float(np.mean([v["count_mae"] for v in values])) if values else None}
        return {"count": len(items), "rejected": len(items) - len(measured),
                "false_zero_words": sum(r["false_zero_words"] is True for r in measured),
                "lines": family("lines"), "words": family("words")}
    return {"version": 1, "overall": stats(rows),
            "conditions": {key: stats(group) for key, group in sorted(groups.items())}}


def run_manifest(manifest: Path, root: Path, *, profile="grid-v1", allow_real=False):
    """Only explicitly authorized local reads; no image bytes in JSON output."""
    document = json.loads(manifest.read_text("utf-8"))
    if document.get("schema_version") != 1 or document.get("split") not in SPLIT:
        raise ValueError("invalid manifest")
    split = document["split"]
    if split != "synthetic" and not allow_real:
        raise ValueError("real-data execution requires authorization")
    resolved_root = root.resolve(strict=True)
    rows, seen = [], set()
    for record in document["specimens"]:
        validate_record(record, split, allow_real=allow_real)
        name = record["specimen_id"]
        if name in seen:
            raise ValueError("duplicate specimen id")
        seen.add(name)
        path = (resolved_root / record["image_path"]).resolve(strict=True)
        if not path.is_relative_to(resolved_root) or not path.is_file():
            raise ValueError("specimen outside approved root")
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != record["sha256"]:
            raise ValueError("image SHA256 mismatch")
        image = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError("undecodable image")
        rows.append(evaluate(image, record, split=split, profile=profile, allow_real=allow_real))
    return {"version": 1, "profile": profile,
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "summary": summarize(rows), "results": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--image-root", required=True, type=Path)
    parser.add_argument("--profile", choices=("legacy", "grid-v1"), default="grid-v1")
    parser.add_argument("--allow-authorized-real", action="store_true")
    args = parser.parse_args()
    result = run_manifest(args.manifest, args.image_root, profile=args.profile,
                          allow_real=args.allow_authorized_real)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
