#!/usr/bin/env python3
"""Validate and compile the T08A presentation registry with standard-library-only tooling."""
from __future__ import annotations

import argparse
import json
import math
import stat
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    path = path.absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"symlink is not reviewed presentation input: {path.name}")
    try:
        mode = path.stat().st_mode
    except FileNotFoundError as exc:
        raise ValueError(f"missing presentation input: {path.name}") from exc
    if not stat.S_ISREG(mode):
        raise ValueError(f"presentation input is not a regular file: {path.name}")
    if path.stat().st_size > 262_144:
        raise ValueError(f"presentation input too large: {path.name}")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON token {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"invalid presentation JSON: {path.name}") from exc


SOURCE = ROOT / "content" / "presentation" / "v1" / "presentation.json"
OUTPUTS = (
    ROOT / "src" / "princess_app" / "domain" / "content" / "_presentation_v1.json",
    ROOT / "contracts" / "product" / "v1" / "presentation-content.v1.json",
)
TS_OUTPUT = ROOT / "packages" / "report-core" / "src" / "presentation.generated.ts"
LOCALES = ("en", "sv")
FAMILIES = ("slant", "layout", "baseline", "spacing", "size", "ink")
CLAUSE_OPS = {"range", "abs_range", "difference_range", "max_range", "count_at_least"}
STRENGTH_OPS = {
    "normalize", "distance_from", "relative_difference", "max_feature",
    "abs_normalize", "max_abs_features",
}
TOP_LEVEL_KEYS = {
    "version", "policy_version", "locales", "family_order", "primary_families",
    "threshold_policy", "selection_strength_semantics", "feature_labels",
    "display_domains", "fallback_content_id", "content", "candidates",
}
CANDIDATE_KEYS = {
    "candidate_id", "family", "correlation_group", "content_id", "support_features",
    "minimum_observations", "clauses", "strength", "witness", "priority",
}
CLAUSE_KEYS = {
    "range": {"op", "feature", "min", "max", "max_inclusive"},
    "abs_range": {"op", "feature", "min", "max", "max_inclusive"},
    "difference_range": {"op", "left", "right", "min", "max", "max_inclusive"},
    "max_range": {"op", "features", "min", "max", "max_inclusive"},
    "count_at_least": {"op", "features", "threshold", "count"},
}
STRENGTH_KEYS = {
    "normalize": {"op", "feature", "min", "max", "invert", "weight"},
    "distance_from": {"op", "feature", "center", "max_distance", "invert", "weight"},
    "relative_difference": {"op", "left", "right", "weight"},
    "max_feature": {"op", "features", "invert", "weight"},
    "abs_normalize": {"op", "feature", "max_abs", "invert", "weight"},
    "max_abs_features": {"op", "features", "max_abs", "weight"},
}
BANNED = {
    "en": ("percentile", " rare ", "rarity", " unique", "unusual", "personality", "pressure",
           "intelligence", "diagnos", "honest", "dishonest", " typical", "abnormal", " better ", " worse "),
    "sv": ("percentil", "sällsynt", " unik", "ovanlig", "personlighet", "intelligens",
           "diagnos", "ärlig", "oärlig", "pentryck", " typisk", "onormal", " bättre ", " sämre "),
}


def _free_feature_ids() -> set[str]:
    # Import the current registered Free surface rather than copying another list.
    from princess_graphology.measurements import IMPLEMENTED_FEATURE_IDS
    return set(IMPLEMENTED_FEATURE_IDS)


def _canonical_units() -> dict[str, str | None]:
    source = _load_json(ROOT / "schema" / "graphology_feature_database_v1.json")
    return {row["id"]: row.get("unit") for row in source["features"]}


def _number(value: Any) -> float:
    if type(value) not in {int, float}:
        raise ValueError(f"expected numeric rule value, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"rule numbers must be finite, got {value!r}")
    return number


def _bound(value: float, clause: dict[str, Any]) -> bool:
    if "min" in clause and value < _number(clause["min"]):
        return False
    if "max" in clause:
        maximum = _number(clause["max"])
        if clause.get("max_inclusive", False):
            if value > maximum:
                return False
        elif value >= maximum:
            return False
    return True


def _clause_matches(clause: dict[str, Any], values: dict[str, float]) -> bool:
    op = clause["op"]
    if op == "range":
        return clause["feature"] in values and _bound(values[clause["feature"]], clause)
    if op == "abs_range":
        return clause["feature"] in values and _bound(abs(values[clause["feature"]]), clause)
    if op == "difference_range":
        left, right = clause["left"], clause["right"]
        return left in values and right in values and _bound(values[left] - values[right], clause)
    if op == "max_range":
        features = clause["features"]
        return all(feature in values for feature in features) and _bound(max(values[f] for f in features), clause)
    if op == "count_at_least":
        features = clause["features"]
        return (
            all(feature in values for feature in features)
            and sum(values[f] >= _number(clause["threshold"]) for f in features) >= int(clause["count"])
        )
    raise ValueError(f"unsupported clause op {op!r}")


def validate(data: dict[str, Any]) -> None:
    if set(data) != TOP_LEVEL_KEYS:
        raise ValueError(f"unexpected presentation top-level keys: {sorted(set(data) ^ TOP_LEVEL_KEYS)}")
    if data.get("version") != "presentation/1" or data.get("policy_version") != "highlight-policy/1":
        raise ValueError("unexpected presentation/policy version")
    if tuple(data.get("locales", ())) != LOCALES:
        raise ValueError("v1 locales must be exactly en, sv")
    if tuple(data.get("family_order", ())) != FAMILIES:
        raise ValueError("unexpected family order")
    primary_families = data.get("primary_families")
    if not isinstance(primary_families, list) or not primary_families or len(primary_families) != len(set(primary_families)):
        raise ValueError("primary_families must be a nonempty unique list")
    if not set(primary_families) <= set(FAMILIES) or "ink" in primary_families:
        raise ValueError("primary families must be known and must exclude capture-sensitive ink proxies")
    if data.get("threshold_policy") != "PRODUCT_PRESENTATION_BANDS_NOT_POPULATION_CALIBRATION":
        raise ValueError("presentation thresholds must be explicitly non-population product bands")
    if data.get("selection_strength_semantics") != "INTERNAL_DETERMINISTIC_PRIORITY_NOT_USER_SCORE":
        raise ValueError("selection strength semantics must stay internal/non-user-facing")

    free = _free_feature_ids()
    labels = data.get("feature_labels")
    if not isinstance(labels, dict) or set(labels) != free:
        missing = sorted(free - set(labels or {}))
        extra = sorted(set(labels or {}) - free)
        raise ValueError(f"feature labels must cover exactly the 64 Free features; missing={missing[:3]} extra={extra[:3]}")
    for feature_id, localized in labels.items():
        if set(localized) != set(LOCALES) or not all(isinstance(localized[k], str) and localized[k].strip() for k in LOCALES):
            raise ValueError(f"bad feature label localization for {feature_id}")
        if "percentile" in localized["en"].lower() or "percentil" in localized["sv"].lower():
            raise ValueError(f"reviewed feature label must not look like a population rank: {feature_id}")
        if feature_id.startswith(("INK_", "STROKE_")):
            if "image" not in localized["en"].lower() or "bild" not in localized["sv"].lower():
                raise ValueError(f"image-proxy feature label must be image-qualified: {feature_id}")

    content = data.get("content")
    fallback = data.get("fallback_content_id")
    if not isinstance(content, dict) or fallback not in content:
        raise ValueError("fallback content must exist")
    for content_id, localized in content.items():
        if not content_id.startswith("content.highlight.v1."):
            raise ValueError(f"unexpected content id {content_id}")
        if set(localized) != set(LOCALES):
            raise ValueError(f"content {content_id} must have en/sv")
        for locale in LOCALES:
            text = localized[locale]
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"empty {locale} content for {content_id}")
            padded = " " + text.lower() + " "
            for banned in BANNED[locale]:
                if banned in padded:
                    raise ValueError(f"prohibited presentation wording {banned!r} in {content_id}/{locale}")

    domains = data.get("display_domains")
    if not isinstance(domains, dict) or not domains:
        raise ValueError("display domains required")
    canonical_units = _canonical_units()
    for feature_id, domain in domains.items():
        if feature_id not in free:
            raise ValueError(f"display domain uses non-Free feature {feature_id}")
        if domain.get("unit") != canonical_units.get(feature_id):
            raise ValueError(f"display domain unit drift for {feature_id}")
        if domain.get("kind") not in {"GEOMETRIC_CANVAS", "MATHEMATICAL_DOMAIN"}:
            raise ValueError(f"unsupported domain kind for {feature_id}")
        if _number(domain["min"]) >= _number(domain["max"]):
            raise ValueError(f"invalid display domain for {feature_id}")
        if "accepted_min" in domain or "accepted_max" in domain:
            if not ("accepted_min" in domain and "accepted_max" in domain):
                raise ValueError(f"partial accepted range for {feature_id}")
            if not (_number(domain["min"]) <= _number(domain["accepted_min"])
                    < _number(domain["accepted_max"]) <= _number(domain["max"])):
                raise ValueError(f"accepted range outside display domain for {feature_id}")

    candidates = data.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 42:
        raise ValueError("presentation v1 requires at least 42 candidate states")
    ids, family_counts = set(), {family: 0 for family in FAMILIES}
    for row in candidates:
        if set(row) != CANDIDATE_KEYS:
            raise ValueError(f"candidate has unexpected/missing keys: {sorted(set(row) ^ CANDIDATE_KEYS)}")
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in ids:
            raise ValueError(f"duplicate/invalid candidate id {candidate_id!r}")
        ids.add(candidate_id)
        family = row.get("family")
        if family not in family_counts:
            raise ValueError(f"unknown family {family!r}")
        family_counts[family] += 1
        if row.get("content_id") not in content:
            raise ValueError(f"{candidate_id}: unknown content id")
        if not isinstance(row.get("correlation_group"), str) or not row["correlation_group"].strip():
            raise ValueError(f"{candidate_id}: correlation group required")
        if type(row.get("priority")) is not int:
            raise ValueError(f"{candidate_id}: priority must be integer")
        support = row.get("support_features")
        if not isinstance(support, list) or not support or len(support) != len(set(support)) or not set(support) <= free:
            raise ValueError(f"{candidate_id}: invalid support features")
        if type(row.get("minimum_observations")) is not int or row["minimum_observations"] < 1:
            raise ValueError(f"{candidate_id}: invalid minimum observations")
        if family == "spacing" and row["minimum_observations"] < 3:
            raise ValueError(f"{candidate_id}: spacing highlight requires at least three accepted gap observations")
        clauses = row.get("clauses")
        if not isinstance(clauses, list) or not clauses:
            raise ValueError(f"{candidate_id}: clauses required")
        if any(clause.get("op") not in CLAUSE_OPS for clause in clauses):
            raise ValueError(f"{candidate_id}: unsupported clause op")
        clause_features: set[str] = set()
        for clause in clauses:
            op = clause["op"]
            if not set(clause) <= CLAUSE_KEYS[op]:
                raise ValueError(f"{candidate_id}: unexpected {op} clause keys")
            if op != "count_at_least" and "min" not in clause and "max" not in clause:
                raise ValueError(f"{candidate_id}: bounded clause needs min or max")
            if op in {"max_range", "count_at_least"}:
                features = clause.get("features")
                if not isinstance(features, list) or not features or len(features) != len(set(features)):
                    raise ValueError(f"{candidate_id}: clause features must be a nonempty unique list")
            if op == "count_at_least":
                if type(clause.get("count")) is not int or not 1 <= clause["count"] <= len(clause["features"]):
                    raise ValueError(f"{candidate_id}: count_at_least count is invalid")
                _number(clause["threshold"])
            clause_features.update(
                value for key, value in clause.items()
                if key in {"feature", "left", "right"} and isinstance(value, str)
            )
            clause_features.update(clause.get("features", []))
            if "min" in clause and "max" in clause and _number(clause["min"]) >= _number(clause["max"]):
                raise ValueError(f"{candidate_id}: empty clause range")
        if not clause_features <= set(support):
            raise ValueError(f"{candidate_id}: clause escapes support set")
        strength = row.get("strength")
        if not isinstance(strength, dict) or strength.get("op") not in STRENGTH_OPS:
            raise ValueError(f"{candidate_id}: unsupported strength op")
        strength_op = strength["op"]
        if not set(strength) <= STRENGTH_KEYS[strength_op]:
            raise ValueError(f"{candidate_id}: unexpected {strength_op} strength keys")
        if "weight" in strength:
            weight = _number(strength["weight"])
            if not 0 < weight <= 1:
                raise ValueError(f"{candidate_id}: strength weight must be in (0,1]")
        if strength_op == "normalize" and _number(strength["min"]) >= _number(strength["max"]):
            raise ValueError(f"{candidate_id}: normalize strength requires min < max")
        if strength_op == "distance_from" and _number(strength["max_distance"]) <= 0:
            raise ValueError(f"{candidate_id}: distance strength requires positive max_distance")
        if strength_op in {"abs_normalize", "max_abs_features"} and _number(strength["max_abs"]) <= 0:
            raise ValueError(f"{candidate_id}: absolute strength requires positive max_abs")
        if strength_op in {"max_feature", "max_abs_features"} and not strength.get("features"):
            raise ValueError(f"{candidate_id}: strength feature list cannot be empty")
        strength_features = {
            value for key, value in strength.items()
            if key in {"feature", "left", "right"} and isinstance(value, str)
        }
        strength_features.update(strength.get("features", []))
        if not strength_features <= set(support):
            raise ValueError(f"{candidate_id}: strength escapes support set")
        witness = row.get("witness")
        if not isinstance(witness, dict) or not witness:
            raise ValueError(f"{candidate_id}: witness required")
        if set(witness) != set(support):
            raise ValueError(f"{candidate_id}: witness must cover exactly the support set")
        numeric_witness = {key: _number(value) for key, value in witness.items()}
        if not all(_clause_matches(clause, numeric_witness) for clause in clauses):
            raise ValueError(f"{candidate_id}: witness does not satisfy its own rule")
        if family == "ink":
            for locale, token in (("en", "image"), ("sv", "bild")):
                if token not in content[row["content_id"]][locale].lower():
                    raise ValueError(f"{candidate_id}: ink copy must be explicitly image-qualified in {locale}")

    expected_content = {fallback, *(row["content_id"] for row in candidates)}
    if set(content) != expected_content:
        raise ValueError("presentation content contains orphaned or missing IDs")

    thin = {family: count for family, count in family_counts.items() if count < 5}
    if thin:
        raise ValueError(f"candidate families too thin: {thin}")


def compiled_registry(data: dict[str, Any]) -> dict[str, Any]:
    """Remove source-only reachability witnesses from runtime/client handoff."""
    compiled = json.loads(json.dumps(data, ensure_ascii=False, allow_nan=False))
    for row in compiled["candidates"]:
        row.pop("witness", None)
    return compiled


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"

def render_typescript(data: dict[str, Any]) -> str:
    payload = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    return (
        "// GENERATED by tools/generate_presentation_content.py; do not edit.\\n"
        "export const PRESENTATION = " + payload + " as const;\\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = _load_json(SOURCE)
    validate(data)
    expected = render(compiled_registry(data))
    stale = [path for path in OUTPUTS if not path.is_file() or path.read_text(encoding="utf-8") != expected]
    if args.check:
        if stale:
            print("stale presentation outputs: " + ", ".join(str(path.relative_to(ROOT)) for path in stale))
            return 1
        print(f"PASS presentation/1: {len(data['feature_labels'])} labels, {len(data['candidates'])} candidates")
        return 0
    for path in OUTPUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")
    print("wrote " + ", ".join(str(path.relative_to(ROOT)) for path in OUTPUTS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
