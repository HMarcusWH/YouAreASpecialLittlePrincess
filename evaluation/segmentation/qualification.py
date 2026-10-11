"""Rights-gated protocol qualification: writer-disjoint and predeclared holdout.

This is a protocol checker, not a license/consent validator and not a
substitute for reviewing raw evidence with authorized annotators.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


def _records(path: Path, expected_split: str):
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get("schema_version") != 2 or data.get("split") != expected_split:
        raise ValueError("expected v2 " + expected_split + " manifest")
    if data.get("annotation_frame") not in ("original_image", "analysis_canvas"):
        raise ValueError("annotation frame must be explicit")
    records = data.get("specimens")
    if not isinstance(records, list) or not records or len(records) > 256:
        raise ValueError("invalid specimen count")
    for row in records:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k]
                for k in ("specimen_id", "writer_group", "capture_group",
                          "sha256", "rights_decision_id")):
            raise ValueError("missing specimen identity/rights fields")
    for field in ("specimen_id", "sha256"):
        if len({x[field] for x in records}) != len(records):
            raise ValueError("duplicate " + field)
    return data, hashlib.sha256(raw).hexdigest()


def predeclared_holdout_gate(development: Path, holdout: Path, policy: Path) -> dict:
    """Check frozen policy/holdout identity without disclosing writer IDs."""
    dev, _ = _records(development, "development")
    held, digest = _records(holdout, "holdout")
    approved = json.loads(policy.read_text("utf-8"))
    if approved.get("schema_version") != 1 or approved.get("holdout_manifest_sha256") != digest:
        raise ValueError("holdout manifest does not match predeclared reviewed SHA")
    for label in ("writer_group", "capture_group", "sha256"):
        a = {r[label] for r in dev["specimens"]}
        b = {r[label] for r in held["specimens"]}
        if a & b:
            raise ValueError("development/holdout " + label + " leakage")
    targets = approved.get("thresholds")
    required = {"minimum_holdout_n", "min_line_macro_f1", "min_word_macro_f1",
                "min_qualified_fraction", "max_false_zero_words"}
    if not isinstance(targets, dict) or set(targets) != required:
        raise ValueError("all acceptance thresholds must be predeclared")
    for key, value in targets.items():
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError("invalid acceptance threshold")
    if not (0 <= targets["min_line_macro_f1"] <= 1
            and 0 <= targets["min_word_macro_f1"] <= 1
            and 0 <= targets["min_qualified_fraction"] <= 1
            and type(targets["minimum_holdout_n"]) is int
            and type(targets["max_false_zero_words"]) is int):
        raise ValueError("invalid metric bounds")
    return {"schema_version": 1, "protocol_qualified": True,
            "development_n": len(dev["specimens"]),
            "holdout_n": len(held["specimens"]),
            "holdout_manifest_sha256": digest, "thresholds": targets}


def score_holdout(summary: dict, approved: dict) -> dict:
    """Score only explicitly qualified benchmark runs against frozen targets."""
    if not approved.get("protocol_qualified"):
        raise ValueError("unqualified protocol")
    block = summary.get("overall")
    if not isinstance(block, dict):
        raise ValueError("missing holdout benchmark aggregate")
    targets = approved["thresholds"]
    qualified = block["measured"] - block.get("partial", 0)
    fraction = qualified / block["count"] if block["count"] else 0.0
    line = block["lines"]["macro_f1"]
    word = block["words"]["macro_f1"]
    scores = {
        "minimum_holdout_n": block["count"] >= targets["minimum_holdout_n"],
        "min_line_macro_f1": line is not None and line >= targets["min_line_macro_f1"],
        "min_word_macro_f1": word is not None and word >= targets["min_word_macro_f1"],
        "min_qualified_fraction": fraction >= targets["min_qualified_fraction"],
        "max_false_zero_words": block["false_zero_words"] <= targets["max_false_zero_words"],
    }
    return {"accepted": all(scores.values()), "gates": scores,
            "evaluated_n": block["count"], "qualified_n": qualified}
