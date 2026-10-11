"""Protected offline ranking experiment for HAT-inspired descriptor baselines.

No production use, biometric ID claims, data export, model training or scores
interpreted as probabilities. Use licensed, consent-cleared local images only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from .descriptors import extract, match_descriptors

MAX_SAMPLES = 256


def _safe_load(record: dict, root: Path, *, authorized: bool, detector: str = "sift"):
    for key in ("sample_id", "writer_group", "capture_group", "image_path", "rights_decision_id"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ValueError("missing authorized sample property: " + key)
    if not authorized:
        raise ValueError("explicit approved-real-data guard required")
    raw_path = record["image_path"]
    path = (root / raw_path).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("specimen outside approved evaluation root")
    digest = record.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("invalid sample SHA")
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != digest:
        raise ValueError("sample SHA mismatch")
    decoded = cv2.imdecode(np.frombuffer(source, np.uint8), cv2.IMREAD_GRAYSCALE)
    if decoded is None:
        raise ValueError("invalid sample image")
    return extract(decoded, detector=detector)


def rank_samples(query, references, *, max_angle_diff_deg=None):
    """Return deterministic best-first ranking, no percent probability."""
    records = []
    for idx, reference in enumerate(references):
        value = match_descriptors(query, reference, max_angle_diff_deg=max_angle_diff_deg)
        fraction = value["match_fraction"]
        records.append((idx, fraction, value["matched_n"]))
    records.sort(key=lambda x: (x[1] is None, -(x[1] or 0), -x[2], x[0]))
    return tuple(records)


def evaluate_manifest(path: Path, *, image_root: Path, authorized=False,
                      detector="sift"):
    """Reject same-capture leakage, return aggregate known-writer ranking only."""
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("schema_version") != 1 or manifest.get("split") not in ("development", "holdout"):
        raise ValueError("invalid protected experiment manifest")
    queries, references = manifest.get("queries"), manifest.get("references")
    if not isinstance(queries, list) or not isinstance(references, list):
        raise ValueError("queries and references must be arrays")
    if not queries or not references or len(queries) + len(references) > MAX_SAMPLES:
        raise ValueError("experiment sample budget exceeded")
    # Authorization must be checked before specimen identifiers, manifests,
    # sample digests, or data paths are used for any matching operation.
    if not authorized:
        raise ValueError("explicit approved-real-data guard required")
    all_samples = queries + references
    for record in all_samples:
        if not isinstance(record, dict):
            raise ValueError("invalid sample manifest record")
        for key in ("sample_id", "writer_group", "capture_group", "image_path", "rights_decision_id"):
            if not isinstance(record.get(key), str) or not record[key]:
                raise ValueError("missing authorized sample property: " + key)
        digest = record.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(
            char not in "0123456789abcdef" for char in digest
        ):
            raise ValueError("invalid sample SHA256")
    ids = [record["sample_id"] for record in all_samples]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate sample_id")
    ref_captures = {r["capture_group"] for r in references}
    if any(q.get("capture_group") in ref_captures for q in queries):
        raise ValueError("same-capture query/reference leakage")
    # Different capture labels do not make identical image bytes independent evidence.
    ref_digests = {r.get("sha256") for r in references}
    if any(q.get("sha256") in ref_digests for q in queries):
        raise ValueError("identical query/reference image digest leakage")
    root = image_root.resolve(strict=True)
    ref_descs = [_safe_load(r, root, authorized=authorized, detector=detector) for r in references]
    exact, reciprocal, eligible = 0, 0.0, 0
    unavailable = 0
    for q in queries:
        # Open-set candidates need a separate protocol; do not claim match accuracy
        # when the query writer is not represented by any reference.
        if not any(r["writer_group"] == q["writer_group"] for r in references):
            unavailable += 1
            continue
        ranking = rank_samples(_safe_load(q, root, authorized=authorized, detector=detector),
                               ref_descs)
        if not ranking or all(score is None for _, score, _ in ranking):
            unavailable += 1
            continue
        rank = next((i + 1 for i, (j, score, _) in enumerate(ranking)
                     if score is not None and references[j]["writer_group"] == q["writer_group"]), None)
        if rank is None:
            unavailable += 1
            continue
        eligible += 1
        exact += int(rank == 1)
        reciprocal += 1.0 / rank
    return {"schema_version": 1, "split": manifest["split"], "detector": detector,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "queries_n": len(queries), "references_n": len(references),
            "eligible_queries_n": eligible, "unavailable_queries_n": unavailable,
            "top1_fraction": exact / eligible if eligible else None,
            "mean_reciprocal_rank": reciprocal / eligible if eligible else None,
            "status": "UNVALIDATED_RESEARCH_ONLY"}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--allow-authorized-real", action="store_true")
    parser.add_argument("--detector", choices=("sift", "fast_sift"), default="sift")
    args = parser.parse_args(argv)
    print(json.dumps(evaluate_manifest(args.manifest, image_root=args.image_root,
              authorized=args.allow_authorized_real, detector=args.detector), indent=2))


if __name__ == "__main__":
    main()
