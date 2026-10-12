"""Offline line/word detection evaluation. Never emit raw images or annotations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections import defaultdict
from pathlib import Path, PurePosixPath

import cv2
import numpy as np

from princess_graphology.context import prepare_context
from princess_graphology.models import Box
from princess_graphology.preprocessing.grid import GridQualityError
from princess_graphology.segmentation_projection import propose_lines
from princess_graphology.segmentation_words import propose_words

from .strict_json import strict_loads

PAPER = frozenset(("blank", "lined", "grid", "form", "unknown"))
SPLIT = frozenset(("synthetic", "development", "validation", "holdout"))
DATA_ORIGIN_SYNTHETIC = "SYNTHETIC_FIXTURE"
DATA_ORIGIN_REAL = "REAL_SOURCE_DECLARED"  # Provenance classification, not a rights attestation.
DATA_ORIGINS = frozenset((DATA_ORIGIN_SYNTHETIC, DATA_ORIGIN_REAL))
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


def validate_record(row, split, *, allow_real=False, synthetic_fixture=False):
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
    if split != "synthetic" and not synthetic_fixture and (
        not allow_real or not row.get("rights_decision_id")
    ):
        raise ValueError("authorized rights decision required for real data")
    if synthetic_fixture and allow_real:
        raise ValueError("fixture mode and real-data mode cannot be combined")
    if split == "synthetic" and allow_real:
        raise ValueError("synthetic split cannot be evaluated as real data")
    # Missing annotations are unknown, never a ground-truth empty page.
    return (_validated_boxes(row["lines"], label="line") if "lines" in row else None), (
        _validated_boxes(row["words"], label="word") if "words" in row else None)


def evaluate(image, row, *, split="synthetic", profile="grid-v1", allow_real=False,
             shadow_projection=False, shadow_words=False, annotation_frame="analysis_canvas",
             synthetic_fixture=False):
    expected_lines, expected_words = validate_record(
        row, split, allow_real=allow_real, synthetic_fixture=synthetic_fixture
    )
    if annotation_frame not in FRAMES:
        raise ValueError("unrecognized annotation frame")
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim not in (2, 3):
        raise ValueError("invalid benchmark image")
    if image.shape[0] * image.shape[1] > MAX_PIXELS:
        raise ValueError("decoded image exceeds benchmark pixel budget")
    label = {"specimen_id": row["specimen_id"], "split": split, "paper": row["paper"],
             "data_origin": DATA_ORIGIN_SYNTHETIC if (split == "synthetic" or synthetic_fixture)
                            else DATA_ORIGIN_REAL,
             "line_reference_n": len(expected_lines) if expected_lines is not None else None,
             "word_reference_n": len(expected_words) if expected_words is not None else None}
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
        if expected_lines is not None:
            expected_lines = to_analysis_boxes(expected_lines, matrix,
                                               source_size=source, destination_size=target)
        if expected_words is not None:
            expected_words = to_analysis_boxes(expected_words, matrix,
                                               source_size=source, destination_size=target)
    else:
        if expected_lines is not None and any(
            b.x2 > context.width or b.y2 > context.height for b in expected_lines
        ):
            raise ValueError("line annotation exceeds analysis canvas")
        if expected_words is not None and any(
            b.x2 > context.width or b.y2 > context.height for b in expected_words
        ):
            raise ValueError("word annotation exceeds analysis canvas")
    shadow = None
    if shadow_projection and expected_lines is not None:
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
    qualification = context.metadata.get("qualification")
    line_available = qualification is None or qualification.get("lines") == "qualified"
    word_available = qualification is None or qualification.get("words") == "qualified"
    status = "MEASURED" if line_available and word_available else "PARTIAL"
    return {**label, "status": status,
            "reason": None if status == "MEASURED" else "some_evidence_unqualified",
            "qualification": qualification, "line_shadow": shadow, "word_shadow": word_shadow,
            "word_trace": trace,
            "lines": match(expected_lines, context.lines)
                     if expected_lines is not None and line_available else None,
            "words": match(expected_words, context.words)
                     if expected_words is not None and word_available else None,
            "unavailable_words": expected_words is not None and not word_available,
            "false_zero_words": (bool(expected_words) and not context.words)
                                if expected_words is not None and word_available else None}


def summarize(rows):
    """Report provenance-safe accuracy and abstentions; never mix source origins.

    An unknown origin is not real evidence. Reject mixed or unmarked rows rather
    than silently laundering synthetic results into a human population.
    """
    origins = {r.get("data_origin") for r in rows if isinstance(r, dict)}
    if len(origins) != 1 or not origins.issubset(DATA_ORIGINS) or len(rows) == 0:
        raise ValueError("unknown or mixed benchmark data origin")
    data_origin = next(iter(origins))
    groups = defaultdict(list)
    for row in rows:
        groups[row["split"] + "/" + row["paper"]].append(row)

    def stats(items):
        measured = [r for r in items if r["status"] in ("MEASURED", "PARTIAL")]

        def family(kind):
            key = "line_reference_n" if kind in ("lines", "line_shadow") else "word_reference_n"
            eligible = []
            for r in items:
                n = r.get(key)
                if n is None and isinstance(r.get(kind), dict):
                    n = r[kind].get("reference_n")
                if n is not None:
                    eligible.append((r, n))
            available = [(r, n) for r, n in eligible if isinstance(r.get(kind), dict)]
            values = [r[kind] for r, _ in available]
            nonempty = [r[kind] for r, n in available if n > 0]
            nonempty_eligible_n = sum(n > 0 for _, n in eligible)
            empty = [r[kind] for r, n in available if n == 0]
            empty_eligible_n = sum(n == 0 for _, n in eligible)
            empty_correct_n = sum(v["detected_n"] == 0 for v in empty)
            def avg(field, subset):
                numbers = [v[field] for v in subset if v.get(field) is not None]
                return float(np.mean(numbers)) if numbers else None

            return {"eligible_n": len(eligible),
                    "annotation_unknown_n": len(items) - len(eligible),
                    "annotated_n": len(values),
                    "available_n": len(available),
                    "unavailable_n": len(eligible) - len(available),
                    "coverage": len(available) / len(eligible) if eligible else None,
                    "nonempty_eligible_n": nonempty_eligible_n,
                    "nonempty_available_n": len(nonempty),
                    "nonempty_coverage": len(nonempty) / nonempty_eligible_n
                                          if nonempty_eligible_n else None,
                    "nonempty_macro_f1": avg("f1", nonempty),
                    "empty_eligible_n": empty_eligible_n,
                    "empty_annotated_n": len(empty),
                    "empty_available_n": len(empty),
                    "empty_unavailable_n": empty_eligible_n - len(empty),
                    "empty_correct_n": empty_correct_n,
                    "empty_false_positive_n": len(empty) - empty_correct_n,
                    "empty_coverage": len(empty) / empty_eligible_n if empty_eligible_n else None,
                    "macro_precision": avg("precision", values),
                    "macro_recall": avg("recall", values),
                    "macro_f1": avg("f1", values),
                    "macro_count_mae": avg("count_mae", values),
                    "macro_matched_iou": avg("mean_iou", values),
                    "macro_center_error_px": avg("mean_center_error_px", values)}

        return {"data_origin": data_origin, "count": len(items), "measured": len(measured),
                "partial": sum(r["status"] == "PARTIAL" for r in measured),
                "rejected": sum(r["status"] == "REJECTED" for r in items),
                "unavailable_words": sum(r.get("unavailable_words") is True for r in items),
                "false_zero_words": sum(r.get("false_zero_words") is True for r in items),
                "lines": family("lines"), "words": family("words"),
                "line_shadow": family("line_shadow"), "word_shadow": family("word_shadow")}

    return {"version": 2, "data_origin": data_origin, "overall": stats(rows),
            "conditions": {key: stats(group) for key, group in sorted(groups.items())}}



def _read_verified_image(root: Path, relative: str, expected_digest: str) -> bytes:
    """Open under the reviewed root without following symlinks or decoding unverified bytes."""
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or not path.parts
            or any(part in ("", ".", "..") for part in relative.split("/"))
            or "\\" in relative or "\x00" in relative):
        raise ValueError("invalid specimen image path")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError("symlink-safe specimen admission is unavailable")
    current_fd = None
    try:
        current_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for component in path.parts[:-1]:
            child_fd = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = child_fd
        file_fd = os.open(
            path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            dir_fd=current_fd,
        )
        try:
            metadata = os.fstat(file_fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_FILE_BYTES:
                raise ValueError("specimen exceeds encoded byte budget or is not a regular file")
            with os.fdopen(file_fd, "rb", closefd=False) as stream:
                blob = stream.read(MAX_FILE_BYTES + 1)
            if len(blob) > MAX_FILE_BYTES:
                raise ValueError("specimen exceeds encoded byte budget")
        finally:
            os.close(file_fd)
        if hashlib.sha256(blob).hexdigest() != expected_digest:
            raise ValueError("image SHA256 mismatch")
        return blob
    except OSError as exc:
        raise ValueError("specimen admission failed") from exc
    finally:
        if current_fd is not None:
            os.close(current_fd)


def run_manifest(manifest: Path, root: Path, *, profile="grid-v1", allow_real=False,
                 shadow_projection=False, shadow_words=False, synthetic_split=False,
                 manifest_bytes: bytes | None = None):
    """Execute frozen approved bytes, or read an ordinary benchmark manifest once."""
    if manifest_bytes is None:
        manifest_bytes = manifest.read_bytes()
    elif not isinstance(manifest_bytes, bytes):
        raise ValueError("frozen manifest must be encoded bytes")
    document = strict_loads(manifest_bytes)
    version = document.get("schema_version")
    if version not in (1, 2) or document.get("split") not in SPLIT:
        raise ValueError("invalid manifest")
    frame = document.get("annotation_frame", "analysis_canvas")
    if frame not in FRAMES or (version == 2 and "annotation_frame" not in document):
        raise ValueError("v2 manifests require explicit annotation_frame")
    split = document["split"]
    # Provenance comes from the admitted input mode, not a caller-supplied
    # result label. A synthetic-marked manifest cannot use the real-data path.
    marked_synthetic = document.get("synthetic")
    if version == 2 and marked_synthetic is not None and type(marked_synthetic) is not bool:
        raise ValueError("invalid synthetic provenance declaration")
    if split == "synthetic" and marked_synthetic is False:
        raise ValueError("synthetic split contradicts source provenance")
    if synthetic_split and not (version == 2 and marked_synthetic is True):
        raise ValueError("synthetic fixture authorization requires explicit synthetic manifest")
    if allow_real and (marked_synthetic is True or split == "synthetic"):
        raise ValueError("synthetic inputs cannot use the real-data admission path")
    # Synthetic split fixtures exercise development/validation/holdout partitions
    # without manufacturing a participant-rights decision.
    fixture = (synthetic_split is True and version == 2 and marked_synthetic is True)
    if split != "synthetic" and not (allow_real or fixture):
        raise ValueError("real-data execution requires authorization")
    data_origin = DATA_ORIGIN_SYNTHETIC if (split == "synthetic" or fixture) else DATA_ORIGIN_REAL
    resolved_root = root.resolve(strict=True)
    specimens = document.get("specimens")
    if not isinstance(specimens, list) or len(specimens) > MAX_SPECIMENS:
        raise ValueError("invalid specimen count/budget")
    rows, seen = [], set()
    for record in specimens:
        validate_record(record, split, allow_real=allow_real, synthetic_fixture=fixture)
        name = record["specimen_id"]
        if name in seen:
            raise ValueError("duplicate specimen id")
        seen.add(name)
        blob = _read_verified_image(resolved_root, record["image_path"], record["sha256"])
        image = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError("undecodable image")
        if image.shape[0] * image.shape[1] > MAX_PIXELS:
            raise ValueError("decoded image exceeds benchmark pixel budget")
        rows.append(evaluate(image, record, split=split, profile=profile,
                             allow_real=allow_real, synthetic_fixture=fixture,
                             shadow_projection=shadow_projection, shadow_words=shadow_words,
                             annotation_frame=frame))
    return {"version": 2, "profile": profile, "split": split, "annotation_frame": frame,
            "data_origin": data_origin,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "summary": summarize(rows), "results": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--image-root", required=True, type=Path)
    parser.add_argument("--profile", choices=("legacy", "grid-v1", "qualified-v2"), default="grid-v1")
    parser.add_argument("--allow-authorized-real", action="store_true")
    parser.add_argument("--shadow-projection", action="store_true")
    parser.add_argument("--shadow-words", action="store_true")
    args = parser.parse_args()
    try:
        result = run_manifest(args.manifest, args.image_root, profile=args.profile,
                              allow_real=args.allow_authorized_real,
                              shadow_projection=args.shadow_projection,
                              shadow_words=args.shadow_words)
    except (OSError, ValueError, cv2.error):
        if args.allow_authorized_real:
            parser.exit(2, "Protected evaluation failed; details withheld from CLI.\n")
        raise
    # Real specimen-level IDs and diagnostics must not flow to public stdout.
    if args.allow_authorized_real:
        print(json.dumps({"status": "PROTECTED_RESULTS_WITHHELD",
                          "publication": "NOT_AUTHORIZED",
                          "message": "Keep protected evaluation details offline."},
                         sort_keys=True))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
