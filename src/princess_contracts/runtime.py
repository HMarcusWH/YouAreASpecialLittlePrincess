"""Pure runtime for the generated T01 product contracts.

The JSON Schemas and reviewed external authority projections are embedded in
``generated.py``. This module performs shape validation, cross-field semantics,
canonical hashing and construction of immutable validated documents without
filesystem, network, database or provider I/O.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, Mapping, TypeVar

from .generated import (
    CONTRACT_BUNDLE_SHA256,
    CONTRACT_MANIFEST,
    CONTRACT_VERSION,
    FEATURES,
    FEATURE_SCHEMA_VERSION,
    METHOD_CAPABILITIES,
    METHOD_MANIFEST_SHA256,
    PURPOSE_AUTHORITY,
    SCHEMAS,
    T26_AUTHORITY,
    T26_SHA256,
    T26_VERSION,
)

T = TypeVar("T")
_MAX_DEPTH = 128
_CONSTRUCTION_TOKEN = object()


@dataclass(frozen=True)
class ContractIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationResult(Generic[T]):
    value: T | None
    issues: tuple[ContractIssue, ...]

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.issues


class ValidatedDocument:
    """Immutable document constructible only through :func:`compile_document`."""

    __slots__ = ("schema_name", "_data", "digest")

    def __init__(self, schema_name: str, data: Mapping[str, Any], digest: str, *, _token: object) -> None:
        if _token is not _CONSTRUCTION_TOKEN:
            raise TypeError("ValidatedDocument must be constructed by compile_document")
        self.schema_name = schema_name
        self._data = data
        self.digest = digest

    @property
    def data(self) -> Mapping[str, Any]:
        return self._data

    def to_dict(self) -> dict[str, Any]:
        value = _thaw(self._data)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise TypeError("validated document root is not an object")
        return value

    def __repr__(self) -> str:
        return f"ValidatedDocument(schema_name={self.schema_name!r}, digest={self.digest!r})"


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise ValueError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def parse_json(text: str, *, max_bytes: int = 2 * 1024 * 1024) -> Any:
    if not isinstance(text, str) or len(text.encode("utf-8")) > max_bytes:
        raise ValueError("JSON input exceeds contract size limit")
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"non-finite JSON token {token}")),
        )
    except RecursionError as exc:
        raise ValueError("JSON input nested too deeply") from exc


def _validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        raise ValueError("canonical JSON nested too deeply")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("NaN and Infinity are forbidden")
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("JSON object keys must be strings")
            _validate_json_value(item, depth=depth + 1)
        return
    raise TypeError(f"not a canonical JSON value: {type(value).__name__}")


def _without_negative_zero(value: Any) -> Any:
    # JSON does not distinguish -0 from 0 in practice: PostgreSQL jsonb, JavaScript
    # JSON.stringify and RFC 8785 all emit 0. Canonicalize it so a document keeps
    # its digest after a storage or cross-client round trip.
    if type(value) is float:
        return 0.0 if value == 0.0 else value
    if type(value) is list:
        return [_without_negative_zero(item) for item in value]
    if type(value) is dict:
        return {key: _without_negative_zero(item) for key, item in value.items()}
    return value


def canonical_json(value: Any) -> str:
    _validate_json_value(value)
    return json.dumps(_without_negative_zero(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def _same_json(a: Any, b: Any) -> bool:
    try:
        return canonical_json(a) == canonical_json(b)
    except (TypeError, ValueError):
        return False


def _resolve_ref(current_file: str, ref: str) -> tuple[str, dict[str, Any]]:
    if ref.startswith("#"):
        file_name, fragment = current_file, ref
    else:
        parts = ref.split("#", 1)
        file_name = parts[0]
        fragment = "#" + parts[1] if len(parts) == 2 else ""
    if file_name not in SCHEMAS:
        raise KeyError(ref)
    node: Any = SCHEMAS[file_name]
    if fragment:
        if not fragment.startswith("#/"):
            raise KeyError(ref)
        for raw in fragment[2:].split("/"):
            part = raw.replace("~1", "/").replace("~0", "~")
            node = node[part]
    if not isinstance(node, dict):
        raise KeyError(ref)
    return file_name, node


def _schema_issues(node: dict[str, Any], value: Any, *, current_file: str, path: str, depth: int = 0) -> list[ContractIssue]:
    if depth > _MAX_DEPTH:
        return [ContractIssue("SCHEMA_DEPTH", path, "schema validation exceeded maximum depth")]
    if "$ref" in node:
        try:
            target_file, target = _resolve_ref(current_file, node["$ref"])
        except (KeyError, TypeError):
            return [ContractIssue("BROKEN_SCHEMA_REF", path, f"unresolved schema reference {node.get('$ref')!r}")]
        return _schema_issues(target, value, current_file=target_file, path=path, depth=depth + 1)
    if "anyOf" in node:
        alternatives = [_schema_issues(child, value, current_file=current_file, path=path, depth=depth + 1) for child in node["anyOf"]]
        if not any(not issues for issues in alternatives):
            return [ContractIssue("ANY_OF", path, "value matches none of the allowed alternatives")]
    if "const" in node and not _same_json(value, node["const"]):
        return [ContractIssue("CONST", path, f"expected constant {node['const']!r}")]
    if "enum" in node and not any(_same_json(value, item) for item in node["enum"]):
        return [ContractIssue("ENUM", path, "value is not in the closed enum")]

    typ = node.get("type")
    type_ok = True
    if typ == "object":
        type_ok = type(value) is dict
    elif typ == "array":
        type_ok = type(value) is list
    elif typ == "string":
        type_ok = type(value) is str
    elif typ == "number":
        type_ok = type(value) in (int, float) and math.isfinite(value)
    elif typ == "integer":
        type_ok = type(value) is int
    elif typ == "boolean":
        type_ok = type(value) is bool
    elif typ == "null":
        type_ok = value is None
    if typ is not None and not type_ok:
        return [ContractIssue("TYPE", path, f"expected {typ}")]

    issues: list[ContractIssue] = []
    if typ == "object":
        props = node["properties"]
        expected = set(props)
        actual = set(value)
        for key in sorted(expected - actual):
            issues.append(ContractIssue("REQUIRED", f"{path}/{key}", "required property is missing"))
        for key in sorted(actual - expected):
            issues.append(ContractIssue("UNKNOWN_PROPERTY", f"{path}/{key}", "closed object rejects unknown property"))
        for key in sorted(expected & actual):
            issues.extend(_schema_issues(props[key], value[key], current_file=current_file, path=f"{path}/{key}", depth=depth + 1))
    elif typ == "array":
        if len(value) < node.get("minItems", 0):
            issues.append(ContractIssue("MIN_ITEMS", path, "array contains too few items"))
        if len(value) > node["maxItems"]:
            issues.append(ContractIssue("MAX_ITEMS", path, "array contains too many items"))
        if node.get("uniqueItems"):
            seen = set()
            for i, item in enumerate(value):
                try:
                    key = canonical_json(item)
                except (TypeError, ValueError):
                    key = f"!invalid:{i}"
                if key in seen:
                    issues.append(ContractIssue("DUPLICATE_ITEM", f"{path}/{i}", "array requires unique items"))
                seen.add(key)
        for i, item in enumerate(value):
            issues.extend(_schema_issues(node["items"], item, current_file=current_file, path=f"{path}/{i}", depth=depth + 1))
    elif typ == "string":
        if len(value) < node.get("minLength", 0):
            issues.append(ContractIssue("MIN_LENGTH", path, "string is too short"))
        if "maxLength" in node and len(value) > node["maxLength"]:
            issues.append(ContractIssue("MAX_LENGTH", path, "string is too long"))
        if "pattern" in node and re.search(node["pattern"], value) is None:
            issues.append(ContractIssue("PATTERN", path, "string does not match required pattern"))
    elif typ in {"number", "integer"}:
        if "minimum" in node and value < node["minimum"]:
            issues.append(ContractIssue("MINIMUM", path, "number is below minimum"))
        if "maximum" in node and value > node["maximum"]:
            issues.append(ContractIssue("MAXIMUM", path, "number exceeds maximum"))
    return issues


def _method_map() -> dict[str, dict[str, Any]]:
    return {item["method_id"]: item for item in METHOD_CAPABILITIES["methods"]}


def _add(issues: list[ContractIssue], condition: bool, code: str, path: str, message: str) -> None:
    if not condition:
        issues.append(ContractIssue(code, path, message))


def _unique(rows: list[dict[str, Any]], key: str, issues: list[ContractIssue], path: str, code: str) -> dict[Any, dict[str, Any]]:
    out: dict[Any, dict[str, Any]] = {}
    duplicates: set[Any] = set()
    for index, row in enumerate(rows):
        value = row[key]
        if value in out:
            duplicates.add(value)
            issues.append(ContractIssue(code, f"{path}/{index}/{key}", f"duplicate canonical key {value!r}"))
        else:
            out[value] = row
    for value in duplicates:
        out.pop(value, None)
    return out


def _analysis_semantics(data: dict[str, Any], issues: list[ContractIssue], path: str = "") -> None:
    versions = data["versions"]
    _add(issues, versions["feature_schema"] == FEATURE_SCHEMA_VERSION, "FEATURE_SCHEMA_DRIFT", f"{path}/versions/feature_schema", "analysis must pin the canonical feature schema")
    _add(issues, versions["method_manifest"] == METHOD_MANIFEST_SHA256, "METHOD_MANIFEST_DRIFT", f"{path}/versions/method_manifest", "analysis must pin the resolved method capability manifest")
    _add(issues, versions["content_schema"] == CONTRACT_VERSION, "CONTENT_SCHEMA_DRIFT", f"{path}/versions/content_schema", "analysis must pin the product contract major")


def _feature_value_ok(data_type: str, value: Any) -> bool:
    if value is None:
        return True
    if data_type == "FLOAT":
        return type(value) in (int, float) and math.isfinite(value)
    if data_type == "INT":
        return type(value) is int
    if data_type == "BOOL":
        return type(value) is bool
    if data_type == "ENUM":
        return type(value) is str and bool(value)
    if data_type in {"VECTOR", "DISTRIBUTION"}:
        return type(value) is list and bool(value) and all(type(v) in (int, float) and math.isfinite(v) for v in value)
    return False


def _feature_method_semantics(row: dict[str, Any], issues: list[ContractIssue], path: str) -> None:
    fid = row["feature_id"]
    if fid not in FEATURES:
        issues.append(ContractIssue("UNKNOWN_FEATURE", f"{path}/feature_id", f"unknown canonical feature {fid!r}"))
        return
    definition = FEATURES[fid]
    unit = row.get("unit")
    _add(issues, unit == definition["unit"], "WRONG_UNIT", f"{path}/unit", f"{fid} requires canonical unit {definition['unit']!r}")
    if "value" in row and row.get("value") is not None:
        _add(issues, _feature_value_ok(definition["data_type"], row["value"]), "FEATURE_VALUE_TYPE", f"{path}/value", f"{fid} value must match canonical {definition['data_type']} type")
    methods = _method_map()
    method_id = row["method_id"]
    if method_id not in methods:
        issues.append(ContractIssue("UNKNOWN_METHOD", f"{path}/method_id", f"unknown method capability {method_id!r}"))
        return
    method = methods[method_id]
    _add(issues, row["method_version"] == method["method_version"], "METHOD_VERSION_DRIFT", f"{path}/method_version", "method version differs from resolved capability")
    _add(issues, fid in method["feature_ids"], "METHOD_FEATURE_MISMATCH", path, f"{method_id} does not produce {fid}")


def _fact_semantics(fact: dict[str, Any], issues: list[ContractIssue], path: str) -> None:
    _feature_method_semantics(fact, issues, path)
    availability = fact["availability"]
    value = fact["value"]
    quality = fact["quality"]
    present_states = {"READY", "UNCALIBRATED"}
    if availability in present_states:
        _add(issues, value is not None, "MISSING_AS_VALUE", f"{path}/value", "available fact must carry its actual value")
        _add(issues, quality["state"] != "MISSING", "QUALITY_MISMATCH", f"{path}/quality/state", "available fact cannot be quality MISSING")
        _add(issues, quality["n_observations"] > 0, "PRESENT_WITHOUT_OBSERVATIONS", f"{path}/quality/n_observations", "available fact needs at least one observation")
    else:
        _add(issues, value is None, "UNAVAILABLE_HAS_VALUE", f"{path}/value", "unavailable/locked/revoked fact cannot smuggle a numeric value")
    if quality["state"] == "MISSING":
        _add(issues, isinstance(quality["missing_reason"], str) and bool(quality["missing_reason"].strip()), "MISSING_REASON", f"{path}/quality/missing_reason", "missing quality requires a reason")
    else:
        _add(issues, quality["missing_reason"] is None, "SPURIOUS_MISSING_REASON", f"{path}/quality/missing_reason", "present quality cannot carry missing_reason")
    uncalibrated = quality["confidence_kind"] == "UNCALIBRATED"
    _add(issues, (quality["confidence"] is None) == uncalibrated, "CONFIDENCE_KIND_MISMATCH", f"{path}/quality/confidence", "numeric confidence requires an explicit non-UNCALIBRATED kind, and UNCALIBRATED confidence stays null")
    _add(issues, fact["evidence_class"] in {"MEASURED", "COMPUTATIONAL_PROXY", "REFERENCE_STATISTIC"}, "NONFACT_EVIDENCE_CLASS", f"{path}/evidence_class", "canonical fact rows cannot contain authored/traditional/AI prose classes")


def _self_digest_semantics(data: dict[str, Any], field: str, issues: list[ContractIssue], path: str = "") -> None:
    expected = data.get(field)
    if expected is None:
        return
    copy = dict(data)
    copy[field] = None
    _add(issues, expected == canonical_digest(copy), "SELF_DIGEST_MISMATCH", f"{path}/{field}", f"{field} must bind the canonical document with that field null")


def _evidence_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    _analysis_semantics(data["analysis"], issues, "/analysis")
    frames = _unique(data["frames"], "frame_id", issues, "/frames", "DUPLICATE_FRAME")
    roots = [f for f in data["frames"] if f["parent_frame_id"] is None]
    _add(issues, len(roots) == 1, "FRAME_ROOT_COUNT", "/frames", "evidence bundle requires exactly one coordinate-frame root")
    for i, frame in enumerate(data["frames"]):
        parent = frame["parent_frame_id"]
        if parent is None:
            _add(issues, frame["transform_to_parent"] is None, "ROOT_TRANSFORM", f"/frames/{i}/transform_to_parent", "root frame must not declare parent transform")
        else:
            _add(issues, parent in frames, "MISSING_FRAME_PARENT", f"/frames/{i}/parent_frame_id", "frame parent must exist uniquely")
            _add(issues, frame["transform_to_parent"] is not None, "MISSING_FRAME_TRANSFORM", f"/frames/{i}/transform_to_parent", "child frame needs 3x3 transform")
    for frame_id in frames:
        seen: set[str] = set()
        current = frame_id
        while current in frames and frames[current]["parent_frame_id"] is not None:
            if current in seen:
                issues.append(ContractIssue("FRAME_CYCLE", f"/frames/{frame_id}", "coordinate frame graph contains a cycle"))
                break
            seen.add(current)
            current = frames[current]["parent_frame_id"]

    regions = _unique(data["regions"], "region_id", issues, "/regions", "DUPLICATE_REGION")
    for i, region in enumerate(data["regions"]):
        frame = frames.get(region["frame_id"])
        _add(issues, frame is not None, "UNKNOWN_REGION_FRAME", f"/regions/{i}/frame_id", "region frame must exist uniquely")
        parent = region["parent_region_id"]
        _add(issues, parent is None or parent in regions, "MISSING_REGION_PARENT", f"/regions/{i}/parent_region_id", "region parent must exist uniquely")
        if parent in regions:
            parent_region = regions[parent]
            same_frame = parent_region["frame_id"] == region["frame_id"]
            _add(issues, same_frame, "REGION_PARENT_FRAME_MISMATCH", f"/regions/{i}/parent_region_id", "region hierarchy is defined within one coordinate frame")
            if same_frame:
                contained = (
                    parent_region["x"] <= region["x"]
                    and parent_region["y"] <= region["y"]
                    and parent_region["x"] + parent_region["width"] >= region["x"] + region["width"]
                    and parent_region["y"] + parent_region["height"] >= region["y"] + region["height"]
                )
                _add(issues, contained, "REGION_OUTSIDE_PARENT", f"/regions/{i}", "child region must lie inside its parent region")
        if frame is not None and frame["unit"] == "px":
            _add(issues, region["x"] + region["width"] <= frame["width"] and region["y"] + region["height"] <= frame["height"], "REGION_OUT_OF_BOUNDS", f"/regions/{i}", "pixel region exceeds its coordinate frame")
    for region_id in regions:
        seen: set[str] = set()
        current = region_id
        while current in regions and regions[current]["parent_region_id"] is not None:
            if current in seen:
                issues.append(ContractIssue("REGION_CYCLE", f"/regions/{region_id}", "region hierarchy contains a cycle"))
                break
            seen.add(current)
            current = regions[current]["parent_region_id"]

    observations = _unique(data["observations"], "observation_id", issues, "/observations", "DUPLICATE_OBSERVATION")
    del observations
    for i, observation in enumerate(data["observations"]):
        path = f"/observations/{i}"
        _feature_method_semantics(observation, issues, path)
        _add(issues, all(region_id in regions for region_id in observation["region_ids"]), "UNKNOWN_OBSERVATION_REGION", f"{path}/region_ids", "observation regions must exist uniquely")
        if observation["accepted"]:
            _add(issues, observation["rejection_reason"] is None, "ACCEPTED_WITH_REJECTION", f"{path}/rejection_reason", "accepted observation cannot carry a rejection reason")
        else:
            _add(issues, isinstance(observation["rejection_reason"], str) and bool(observation["rejection_reason"].strip()), "REJECTED_WITHOUT_REASON", f"{path}/rejection_reason", "rejected observation requires a reason")


def _report_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    _analysis_semantics(data["analysis"], issues, "/analysis")
    facts = _unique(data["facts"], "fact_id", issues, "/facts", "DUPLICATE_FACT")
    for i, fact in enumerate(data["facts"]):
        _fact_semantics(fact, issues, f"/facts/{i}")
    sections = _unique(data["sections"], "section_id", issues, "/sections", "DUPLICATE_SECTION")
    del sections
    for i, section in enumerate(data["sections"]):
        _add(issues, all(fid in facts for fid in section["fact_ids"]), "UNKNOWN_SECTION_FACT", f"/sections/{i}/fact_ids", "section references a fact not present in this immutable report")
    notice_ids = [item["notice_id"] for item in data["notices"]]
    _add(issues, len(notice_ids) == len(set(notice_ids)), "DUPLICATE_NOTICE", "/notices", "report notice IDs must be unique")
    claim_keys = [
        (claim["feature_id"], claim["cohort_id"], claim["benchmark_release_id"])
        for claim in data["reference_claims"]
    ]
    _add(issues, len(claim_keys) == len(set(claim_keys)), "DUPLICATE_REFERENCE_CLAIM", "/reference_claims", "reference claims must have unique feature/cohort/release identities")
    benchmark_release = data["analysis"]["versions"]["benchmark_release"]
    for i, claim in enumerate(data["reference_claims"]):
        path = f"/reference_claims/{i}"
        _add(issues, claim["feature_id"] in FEATURES, "UNKNOWN_REFERENCE_FEATURE", f"{path}/feature_id", "reference claim feature must be canonical")
        matching = [f for f in data["facts"] if f["feature_id"] == claim["feature_id"]]
        _add(issues, len(matching) == 1, "REFERENCE_FACT_AMBIGUOUS", path, "reference claim requires exactly one corresponding report fact")
        if len(matching) == 1:
            _add(issues, matching[0]["availability"] in {"READY", "UNCALIBRATED"}, "REFERENCE_FACT_UNAVAILABLE", path, "reference claim cannot be attached to an unavailable fact")
        _add(issues, benchmark_release is not None and claim["benchmark_release_id"] == benchmark_release, "REFERENCE_RELEASE_MISMATCH", f"{path}/benchmark_release_id", "reference claim must bind the analysis benchmark release")
    _self_digest_semantics(data, "document_digest", issues)


def _view_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    facts = _unique(data["facts"], "fact_id", issues, "/facts", "DUPLICATE_FACT")
    for i, fact in enumerate(data["facts"]):
        _fact_semantics(fact, issues, f"/facts/{i}")
    sections = _unique(data["sections"], "section_id", issues, "/sections", "DUPLICATE_SECTION")
    del sections
    for i, section in enumerate(data["sections"]):
        _add(issues, all(fid in facts for fid in section["fact_ids"]), "UNKNOWN_SECTION_FACT", f"/sections/{i}/fact_ids", "view section references absent fact")
    notices = _unique(data["notices"], "notice_id", issues, "/notices", "DUPLICATE_NOTICE")
    del notices
    action_ids = [a["action_id"] for a in data["actions"]]
    _add(issues, len(action_ids) == len(set(action_ids)), "DUPLICATE_ACTION", "/actions", "action IDs must be unique")
    for i, action in enumerate(data["actions"]):
        if action["enabled"]:
            _add(issues, action["reason"] is None, "ENABLED_ACTION_REASON", f"/actions/{i}/reason", "enabled action must not carry a disabled reason")
        else:
            _add(issues, isinstance(action["reason"], str) and bool(action["reason"].strip()), "DISABLED_ACTION_WITHOUT_REASON", f"/actions/{i}/reason", "disabled action requires an explicit reason")


def _comparison_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    candidate_ids = list(data["candidate_feature_ids"])
    common_ids = list(data["common_feature_ids"])
    candidate = set(candidate_ids)
    common = set(common_ids)
    _add(issues, all(fid in FEATURES for fid in candidate), "UNKNOWN_CANDIDATE_FEATURE",
         "/candidate_feature_ids", "comparison candidates must use canonical features")
    _add(issues, all(fid in FEATURES for fid in common), "UNKNOWN_COMMON_FEATURE",
         "/common_feature_ids", "comparison common mask must use canonical features")
    _add(issues, common <= candidate, "COMMON_OUTSIDE_CANDIDATES",
         "/common_feature_ids", "comparison common mask must be a subset of candidates")

    inputs = data["inputs"]
    input_ids = [row["report_id"] for row in inputs]
    _add(issues, input_ids == data["input_report_ids"], "COMPARISON_INPUT_ID_DRIFT",
         "/input_report_ids", "input_report_ids must match ordered input provenance")
    _add(issues, [row["position"] for row in inputs] == list(range(len(inputs))),
         "COMPARISON_INPUT_POSITION_DRIFT", "/inputs", "input positions must be contiguous from zero")

    if data["kind"] == "PAIR":
        _add(issues, len(inputs) == 2, "PAIR_INPUT_COUNT", "/inputs", "PAIR requires exactly two inputs")
        _add(issues, data["ordering_basis"] == "REQUEST_ORDER", "PAIR_ORDERING_DRIFT",
             "/ordering_basis", "PAIR preserves request order")
    else:
        _add(issues, 2 <= len(inputs) <= 16, "HISTORY_INPUT_COUNT", "/inputs", "HISTORY requires 2..16 inputs")
        _add(issues, data["ordering_basis"] == "REPORT_CREATED_AT", "HISTORY_ORDERING_DRIFT",
             "/ordering_basis", "HISTORY is ordered by report creation time")
        history_order = [(row["report_created_at"], row["report_id"]) for row in inputs]
        _add(issues, history_order == sorted(history_order), "HISTORY_NOT_CHRONOLOGICAL",
             "/inputs", "HISTORY inputs must be ordered by report creation time then report ID")

    coverage = data["coverage"]
    _add(issues, coverage["candidate_n"] == len(candidate_ids), "COVERAGE_CANDIDATE_COUNT",
         "/coverage/candidate_n", "candidate count must match candidate_feature_ids")
    _add(issues, coverage["common_n"] == len(common_ids), "COVERAGE_COMMON_COUNT",
         "/coverage/common_n", "common count must match common_feature_ids")
    _add(issues, coverage["excluded_n"] == len(data["exclusions"]), "COVERAGE_EXCLUDED_COUNT",
         "/coverage/excluded_n", "excluded count must match exclusions")
    _add(issues, coverage["candidate_n"] == coverage["common_n"] + coverage["excluded_n"],
         "COVERAGE_PARTITION", "/coverage", "candidate coverage must partition into common and excluded")
    expected_fraction = coverage["common_n"] / coverage["candidate_n"]
    _add(issues, coverage["common_fraction"] == expected_fraction, "COVERAGE_FRACTION",
         "/coverage/common_fraction", "coverage fraction must equal common/candidate")

    exclusions = _unique(data["exclusions"], "feature_id", issues, "/exclusions", "DUPLICATE_EXCLUSION")
    excluded_ids = set(exclusions)
    _add(issues, excluded_ids == candidate - common, "EXCLUSION_SET_DRIFT",
         "/exclusions", "exclusions must exactly cover candidate features outside the common mask")
    for i, exclusion in enumerate(data["exclusions"]):
        path = f"/exclusions/{i}"
        _add(issues, exclusion["feature_id"] in candidate, "EXCLUSION_OUTSIDE_CANDIDATES",
             f"{path}/feature_id", "excluded feature must be a candidate")
        _add(issues, all(0 <= position < len(inputs) for position in exclusion["affected_positions"]),
             "EXCLUSION_POSITION_OUT_OF_RANGE", f"{path}/affected_positions",
             "excluded positions must refer to comparison inputs")

    expected_edges = {(position, position + 1) for position in range(len(inputs) - 1)}
    seen: set[tuple[str, int, int]] = set()
    for i, row in enumerate(data["differences"]):
        path = f"/differences/{i}"
        feature_id = row["feature_id"]
        edge = (row["from_position"], row["to_position"])
        key = (feature_id, *edge)
        _add(issues, feature_id in common, "DIFFERENCE_OUTSIDE_COMMON_MASK",
             f"{path}/feature_id", "difference feature must be in common_feature_ids")
        _add(issues, edge in expected_edges, "DIFFERENCE_NONADJACENT_INPUTS",
             path, "differences must compare adjacent ordered inputs")
        _add(issues, key not in seen, "DUPLICATE_DIFFERENCE", path,
             "one difference per feature and adjacent input edge is allowed")
        seen.add(key)

        expected_signed = row["value_to"] - row["value_from"]
        if expected_signed == 0:
            expected_signed = 0.0
        _add(issues, row["signed_delta"] == expected_signed, "SIGNED_DELTA_DRIFT",
             f"{path}/signed_delta", "signed delta must equal value_to - value_from")
        _add(issues, row["absolute_delta"] == abs(expected_signed), "ABSOLUTE_DELTA_DRIFT",
             f"{path}/absolute_delta", "absolute delta must be abs(signed_delta)")
        direction = "EQUAL" if expected_signed == 0 else ("TO_GREATER" if expected_signed > 0 else "FROM_GREATER")
        _add(issues, row["direction"] == direction, "DIRECTION_DRIFT",
             f"{path}/direction", "direction must agree with signed delta")

        domain = row["display_domain"]
        _add(issues, domain["min"] < domain["max"], "DISPLAY_DOMAIN_ORDER",
             f"{path}/display_domain", "display domain min must be below max")
        _add(issues, domain["unit"] == row["unit"], "DISPLAY_DOMAIN_UNIT_DRIFT",
             f"{path}/display_domain/unit", "display domain unit must match difference unit")
        _add(issues, domain["min"] <= row["value_from"] <= domain["max"],
             "VALUE_FROM_OUTSIDE_DISPLAY_DOMAIN", f"{path}/value_from",
             "from value must lie inside the approved display domain")
        _add(issues, domain["min"] <= row["value_to"] <= domain["max"],
             "VALUE_TO_OUTSIDE_DISPLAY_DOMAIN", f"{path}/value_to",
             "to value must lie inside the approved display domain")
        if domain["accepted_min"] is not None or domain["accepted_max"] is not None:
            _add(issues, domain["accepted_min"] is not None and domain["accepted_max"] is not None,
                 "PARTIAL_ACCEPTED_DOMAIN", f"{path}/display_domain",
                 "accepted display bounds must be supplied together")
            if domain["accepted_min"] is not None and domain["accepted_max"] is not None:
                _add(issues, domain["min"] <= domain["accepted_min"] < domain["accepted_max"] <= domain["max"],
                     "ACCEPTED_DOMAIN_OUTSIDE_CANVAS", f"{path}/display_domain",
                     "accepted bounds must lie inside the display domain")

    expected_difference_keys = {
        (feature_id, from_position, to_position)
        for feature_id in common_ids
        for from_position, to_position in sorted(expected_edges)
    }
    _add(issues, seen == expected_difference_keys, "DIFFERENCE_SET_DRIFT",
         "/differences", "differences must cover every common feature on every adjacent input edge")
    _add(issues, data["facts"] == [], "AGGREGATE_COMPARISON_FACTS_UNSUPPORTED",
         "/facts", "comparison-v1 does not publish aggregate similarity facts")
    _self_digest_semantics(data, "comparison_digest", issues)


def _packet_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    _add(issues, data["interpretation_database_version"] == T26_VERSION, "T26_VERSION_DRIFT", "/interpretation_database_version", "packet must pin reviewed T26 database version")
    _add(issues, data["interpretation_database_sha256"] == T26_SHA256, "T26_DIGEST_DRIFT", "/interpretation_database_sha256", "packet must pin exact compiled T26 artifact")
    _add(issues, data["candidate_policy_version"] == T26_AUTHORITY["candidate_policy_version"], "CANDIDATE_POLICY_DRIFT", "/candidate_policy_version", "packet must use reviewed candidate validation policy")
    pack = T26_AUTHORITY["question_packs"].get(data["question_pack_id"])
    if pack is None:
        issues.append(ContractIssue("UNKNOWN_QUESTION_PACK", "/question_pack_id", "question pack is not in reviewed T26 database"))
        return
    _add(issues, data["output_schema_version"] == pack["output_schema_version"], "OUTPUT_SCHEMA_DRIFT", "/output_schema_version", "packet output schema must match selected T26 pack")
    _add(issues, set(data["soft_field_ids"]) == set(pack["soft_field_ids"]), "SOFT_FIELD_SET_DRIFT", "/soft_field_ids", "packet must freeze exactly the reviewed soft-field allowlist for the selected T26 pack")
    questions = _unique(data["questions"], "question_id", issues, "/questions", "DUPLICATE_QUESTION")
    candidates = _unique(data["candidates"], "candidate_id", issues, "/candidates", "DUPLICATE_CANDIDATE")
    allowed = set(data["allowed_fact_ids"])
    pack_questions = set(pack["question_ids"])
    for i, question in enumerate(data["questions"]):
        qid = question["question_id"]
        path = f"/questions/{i}"
        _add(issues, qid in pack_questions, "QUESTION_OUTSIDE_PACK", f"{path}/question_id", "packet may only contain questions from selected frozen pack")
        authority = T26_AUTHORITY["questions"].get(qid)
        if authority is not None:
            _add(issues, question["selection_domain"] == authority["selection_domain"], "SELECTION_DOMAIN_DRIFT", f"{path}/selection_domain", "packet must preserve T26 selector selection_domain")
            _add(issues, question["cardinality"] == authority["cardinality"], "CARDINALITY_DRIFT", f"{path}/cardinality", "packet must preserve T26 selector cardinality")
        _add(issues, set(question["candidate_ids"]) <= set(candidates), "UNKNOWN_QUESTION_CANDIDATE", f"{path}/candidate_ids", "question candidate must be frozen in this packet")
        _add(issues, set(question["support_fact_ids"]) <= allowed, "QUESTION_SUPPORT_OUTSIDE_FACTS", f"{path}/support_fact_ids", "question support must be in allowed fact set")
    for i, candidate in enumerate(data["candidates"]):
        _add(issues, set(candidate["support_fact_ids"]) <= allowed, "CANDIDATE_SUPPORT_OUTSIDE_FACTS", f"/candidates/{i}/support_fact_ids", "candidate support must be in allowed fact set")
    del questions


def _output_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    answer_ids = [a["question_id"] for a in data["answers"]]
    _add(issues, len(answer_ids) == len(set(answer_ids)), "DUPLICATE_ANSWER", "/answers", "one answer per question is allowed")
    field_ids = [f["field_id"] for f in data["soft_fields"]]
    _add(issues, len(field_ids) == len(set(field_ids)), "DUPLICATE_SOFT_FIELD", "/soft_fields", "soft field IDs must be unique")
    _add(issues, all(fid in T26_AUTHORITY["soft_field_ids"] for fid in field_ids), "UNKNOWN_SOFT_FIELD", "/soft_fields", "soft fields must come from reviewed T26 database")


def _grant_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    versions = PURPOSE_AUTHORITY["versions"].get(data["purpose_id"])
    _add(issues, versions is not None and data["purpose_version"] in versions, "UNKNOWN_PURPOSE_VERSION", "/purpose_id", "grant must reference a T03 purpose/version")
    recorded = datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
    effective = datetime.fromisoformat(data["effective_at"].replace("Z", "+00:00"))
    _add(issues, effective >= recorded, "GRANT_BACKDATING", "/effective_at", "grant snapshot cannot claim effect before its recorded decision")


def _reading_quad_valid(points: list[dict[str, float]]) -> bool:
    """Only nondegenerate ordered convex quads can cite a local image region."""
    if len(points) != 4:
        return False
    xy = [(point["x"], point["y"]) for point in points]
    turns = []
    for i in range(4):
        a, b, c = xy[i], xy[(i + 1) % 4], xy[(i + 2) % 4]
        turns.append((b[0] - a[0]) * (c[1] - b[1])
                     - (b[1] - a[1]) * (c[0] - b[0]))
    # Schema already checks numeric finiteness and normalized 0..1 bounds.
    return all(t > 1e-9 for t in turns) or all(t < -1e-9 for t in turns)


def _reading_support_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    """Validate saved support's internal bindings; report/rights checks remain upstream."""
    descriptors = _unique(data["descriptors"], "descriptor_id", issues,
                          "/descriptors", "DUPLICATE_READING_DESCRIPTOR")
    regions = _unique(data["regions"], "region_ref", issues,
                      "/regions", "DUPLICATE_READING_REGION")
    _unique(data["relations"], "relation_id", issues,
            "/relations", "DUPLICATE_READING_RELATION")
    for i, region in enumerate(data["regions"]):
        _add(issues, _reading_quad_valid(region["polygon_normalized_input"]),
             "READING_REGION_GEOMETRY", f"/regions/{i}/polygon_normalized_input",
             "local regions require an ordered nondegenerate convex quad")
    allowed_features = set(free_feature_ids())
    seen_candidates: set[str] = set()
    for i, descriptor in enumerate(data["descriptors"]):
        path = f"/descriptors/{i}"
        candidate_id = descriptor["source_candidate_id"]
        _add(issues, descriptor["descriptor_id"] == f"descriptor.{candidate_id}",
             "READING_DESCRIPTOR_ID_MISMATCH", f"{path}/descriptor_id",
             "descriptor must bind its versioned candidate ID")
        _add(issues, candidate_id not in seen_candidates,
             "READING_DUPLICATE_SOURCE_CANDIDATE", f"{path}/source_candidate_id",
             "one selected descriptor per source candidate")
        seen_candidates.add(candidate_id)
        _add(issues, candidate_id.startswith(f"{descriptor['family']}.")
             and descriptor["content_id"] == f"content.highlight.v2.{candidate_id}",
             "READING_DESCRIPTOR_SOURCE_MISMATCH", f"{path}/content_id",
             "descriptor family and reviewed v2 copy identity must agree")
        facts = descriptor["support_fact_ids"]
        _add(issues, all(
            fid.startswith("fact.") and fid[5:] in allowed_features for fid in facts
        ), "READING_UNKNOWN_FEATURE", f"{path}/support_fact_ids",
            "descriptors may cite only canonical Free measured feature identities")
        _add(issues, bool(facts) and len(facts) == len(set(facts))
             and all(fid.startswith("fact.") for fid in facts),
             "READING_DESCRIPTOR_SUPPORT_INVALID", f"{path}/support_fact_ids",
             "descriptor needs distinct measured fact references")
        region_ids = descriptor["support_region_ids"]
        _add(issues, len(region_ids) == len(set(region_ids))
             and set(region_ids) <= set(regions),
             "READING_FOREIGN_REGION", f"{path}/support_region_ids",
             "descriptor cannot cite an unbound region")
    for i, relation in enumerate(data["relations"]):
        path = f"/relations/{i}"
        members = [descriptors.get(cid) for cid in relation["descriptor_ids"]]
        _add(issues, len(members) >= 2 and all(row is not None for row in members),
             "READING_FOREIGN_DESCRIPTOR", f"{path}/descriptor_ids",
             "relation must cite selected descriptors")
        if any(row is None for row in members):
            continue
        _add(issues, len(relation["descriptor_ids"]) == len(set(relation["descriptor_ids"]))
             and len({row["family"] for row in members}) >= 2,
             "READING_SAME_FAMILY_RELATION", f"{path}/descriptor_ids",
             "relationship needs at least two distinct feature families")
        support_facts = {fid for row in members for fid in row["support_fact_ids"]}
        support_regions = {rid for row in members for rid in row["support_region_ids"]}
        _add(issues, set(relation["support_fact_ids"]) == support_facts
             and len(relation["support_fact_ids"]) == len(support_facts),
             "READING_RELATION_FACT_MISMATCH", f"{path}/support_fact_ids",
             "relationship cannot add or omit member facts")
        _add(issues, set(relation["support_region_ids"]) <= support_regions
             and len(relation["support_region_ids"]) == len(set(relation["support_region_ids"])),
             "READING_RELATION_REGION_ESCAPE", f"{path}/support_region_ids",
             "relationship cannot cite foreign evidence")
    expected = canonical_digest({**data, "support_digest": None})
    _add(issues, data["support_digest"] == expected,
         "READING_SUPPORT_DIGEST_MISMATCH", "/support_digest",
         "support must bind all fields with a canonical snapshot hash")


def _reading_packet_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    """The new packet wraps, but never weakens, the frozen T26 selector packet."""
    base = data["selector_packet"]
    support = data["support"]
    _packet_semantics(base, issues)
    _reading_support_semantics(support, issues)
    _add(issues, data["packet_id"] == base["packet_id"],
         "READING_PACKET_ID_MISMATCH", "/packet_id", "wrapper and T26 packet must agree")
    for key, old in (("report_id", "report_id"), ("report_revision", "report_revision"),
                     ("report_digest", "report_digest")):
        _add(issues, support[key] == base[old], "READING_PACKET_REPORT_MISMATCH",
             f"/support/{key}", "wrapper cannot switch its source report")
    _unique(data["block_specs"], "block_id", issues,
            "/block_specs", "DUPLICATE_READING_BLOCK_SPEC")
    descriptor_ids = {d["descriptor_id"] for d in support["descriptors"]}
    relation_ids = {r["relation_id"] for r in support["relations"]}
    selector_ids = {c["candidate_id"] for c in base["candidates"]}
    selector_questions = {q["question_id"] for q in base["questions"]}
    allowed_facts = set(base["allowed_fact_ids"])
    support_facts = {fid for d in support["descriptors"] for fid in d["support_fact_ids"]}
    regions = {r["region_ref"] for r in support["regions"]}
    for i, block in enumerate(data["block_specs"]):
        path = f"/block_specs/{i}"
        if block["question_id"] is not None:
            _add(issues, block["kind"] == "VISUAL_OBSERVATION"
                 and block["question_id"] in selector_questions,
                 "READING_BLOCK_QUESTION_INVALID", f"{path}/question_id",
                 "visual block must bind a selector question")
        valid_candidates = selector_ids if block["kind"] == "VISUAL_OBSERVATION" else (
            relation_ids if block["kind"] == "RELATIONSHIP" else descriptor_ids
        )
        _add(issues, set(block["allowed_candidate_ids"]) <= valid_candidates,
             "READING_BLOCK_CANDIDATE_ESCAPE", f"{path}/allowed_candidate_ids",
             "block candidate IDs must be compiled, not invented")
        _add(issues, set(block["allowed_fact_ids"]) <= allowed_facts
             and set(block["allowed_fact_ids"]) <= support_facts | allowed_facts,
             "READING_BLOCK_FACT_ESCAPE", f"{path}/allowed_fact_ids",
             "block facts cannot exceed the frozen T26 packet")
        _add(issues, set(block["allowed_region_refs"]) <= regions,
             "READING_BLOCK_REGION_ESCAPE", f"{path}/allowed_region_refs",
             "block regions must be present in saved support")


def _reading_output_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    """Internal shape checks only. Cross-packet validation is a separate gate."""
    _output_semantics(data["selector_output"], issues)
    _add(issues, data["packet_id"] == data["selector_output"]["packet_id"],
         "READING_OUTPUT_PACKET_MISMATCH", "/packet_id",
         "editorial output cannot switch T26 packet identity")
    _unique(data["blocks"], "block_id", issues,
            "/blocks", "DUPLICATE_READING_OUTPUT_BLOCK")
    for i, block in enumerate(data["blocks"]):
        path = f"/blocks/{i}"
        if block["answer_state"] != "ANSWERED":
            _add(issues, block["text"] is None
                 and not block["selected_candidate_ids"]
                 and not block["support_fact_ids"]
                 and not block["support_region_refs"],
                 "READING_UNANSWERED_PAYLOAD", path,
                 "non-answer cannot contain text or evidence")
        else:
            _add(issues, isinstance(block["text"], str) and bool(block["text"].strip()),
                 "READING_EMPTY_ANSWER", f"{path}/text",
                 "answered editorial block must contain text")


def _reading_view_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    _add(issues, data["basis_revision"] + 1 == data["source_revision"],
         "READING_BASIS_REVISION_MISMATCH", "/basis_revision",
         "published Premium reading must append exactly one immutable revision")
    _add(issues, data["basis_digest"] != data["source_digest"],
         "READING_BASIS_DIGEST_MISMATCH", "/basis_digest",
         "Premium base and published immutable snapshot are distinct")
    _unique(data["blocks"], "block_id", issues,
            "/blocks", "DUPLICATE_READING_VIEW_BLOCK")


def _reading_offer_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    action = data["action"]
    if action in {"PURCHASE", "GENERATE", "RETRY"}:
        _add(issues, data["sample_state"] == "SUPPORTED"
             and data["source_image_state"] == "AVAILABLE"
             and data["support_state"] == "SUFFICIENT"
             and data["runtime_state"] == "AVAILABLE",
             "READING_UNAVAILABLE_ACTION", "/action",
             "new paid actions require a supported, enabled offer")
        _add(issues, data["permission_state"] == "GRANTED",
             "READING_CONSENT_REQUIRED", "/permission_state",
             "an offer cannot bypass separate AI-processing permission")
    if action in {"GENERATE", "RETRY"}:
        _add(issues, data["entitlement_state"] == "CREDIT",
             "READING_CREDIT_REQUIRED", "/entitlement_state",
             "client flags never grant a credit")
    if action == "VIEW":
        _add(issues, data["entitlement_state"] == "PUBLISHED",
             "READING_VIEW_UNAUTHORIZED", "/entitlement_state",
             "saved Premium requires a verified published entitlement")
    if action == "WAIT":
        _add(issues, data["job_state"] in {"QUEUED", "RUNNING", "AMBIGUOUS"},
             "READING_WAIT_WITHOUT_JOB", "/job_state",
             "waiting requires an existing durable job")


def _render_envelope_semantics(data: dict[str, Any], issues: list[ContractIssue]) -> None:
    premium = data["premium"]
    if premium is None:
        return
    view = data["view"]
    for left, right in (
        ("source_report_id", "source_report_id"),
        ("source_revision", "source_revision"),
        ("source_digest", "source_digest"),
        ("locale", "locale"),
    ):
        _add(issues, premium[left] == view[right],
             "RENDER_PREMIUM_SOURCE_MISMATCH", f"/premium/{left}",
             "Premium render must refer to the same authorized published view")


def _semantic_issues(schema_name: str, data: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    if schema_name == "AnalysisReference":
        _analysis_semantics(data, issues)
    elif schema_name == "EvidenceBundle":
        _evidence_semantics(data, issues)
    elif schema_name == "ReportDocument":
        _report_semantics(data, issues)
    elif schema_name == "ReportViewModel":
        _view_semantics(data, issues)
    elif schema_name == "Comparison":
        _comparison_semantics(data, issues)
    elif schema_name == "PremiumPacket":
        _packet_semantics(data, issues)
    elif schema_name == "PremiumOutput":
        _output_semantics(data, issues)
    elif schema_name == "GrantSnapshot":
        _grant_semantics(data, issues)
    elif schema_name == "ReadingSupport":
        _reading_support_semantics(data, issues)
    elif schema_name == "PremiumReadingPacket":
        _reading_packet_semantics(data, issues)
    elif schema_name == "PremiumReadingOutput":
        _reading_output_semantics(data, issues)
    elif schema_name == "PremiumReadingView":
        _reading_view_semantics(data, issues)
    elif schema_name == "PremiumOffer":
        _reading_offer_semantics(data, issues)
    elif schema_name == "RenderEnvelope":
        _render_envelope_semantics(data, issues)
    return issues


def compile_document(schema_name: str, data: Any) -> ValidationResult[ValidatedDocument]:
    file_name = CONTRACT_MANIFEST["root_schemas"].get(schema_name)
    if file_name is None:
        return ValidationResult(None, (ContractIssue("UNKNOWN_SCHEMA", "", f"unknown root schema {schema_name!r}"),))
    try:
        _validate_json_value(data)
    except (TypeError, ValueError) as exc:
        return ValidationResult(None, (ContractIssue("INVALID_JSON_VALUE", "", str(exc)),))
    issues = _schema_issues(SCHEMAS[file_name], data, current_file=file_name, path="")
    if not issues and isinstance(data, dict):
        issues.extend(_semantic_issues(schema_name, data))
    if issues:
        return ValidationResult(None, tuple(issues))
    mutable = json.loads(canonical_json(data), object_pairs_hook=_pairs)
    digest = canonical_digest(mutable)
    return ValidationResult(ValidatedDocument(schema_name, _freeze(mutable), digest, _token=_CONSTRUCTION_TOKEN), ())


def validate_projection(report: ValidatedDocument, view: ValidatedDocument) -> tuple[ContractIssue, ...]:
    if report.schema_name != "ReportDocument" or view.schema_name != "ReportViewModel":
        return (ContractIssue("WRONG_DOCUMENT_KIND", "", "projection validation requires ReportDocument + ReportViewModel"),)
    source = report.to_dict()
    projected = view.to_dict()
    issues: list[ContractIssue] = []
    _add(issues, projected["source_report_id"] == source["report_id"], "PROJECTION_REPORT_MISMATCH", "/source_report_id", "projection belongs to another report")
    _add(issues, projected["source_revision"] == source["revision"], "PROJECTION_REVISION_MISMATCH", "/source_revision", "projection revision differs from report")
    source_digest = source["document_digest"] or canonical_digest({**source, "document_digest": None})
    _add(issues, projected["source_digest"] == source_digest, "PROJECTION_DIGEST_MISMATCH", "/source_digest", "projection must bind exact immutable report")
    source_facts = {fact["fact_id"]: fact for fact in source["facts"]}
    for i, fact in enumerate(projected["facts"]):
        _add(issues, fact["fact_id"] in source_facts and _same_json(fact, source_facts.get(fact["fact_id"])), "PROJECTION_FACT_MUTATION", f"/facts/{i}", "projection may omit facts but cannot change or invent them")
    source_sections = {section["section_id"]: section for section in source["sections"]}
    projected_fact_ids = {fact["fact_id"] for fact in projected["facts"]}
    for i, section in enumerate(projected["sections"]):
        original = source_sections.get(section["section_id"])
        _add(issues, original is not None and _same_json(section, original), "PROJECTION_SECTION_MUTATION", f"/sections/{i}", "projection may omit sections but cannot change or invent them")
        _add(issues, set(section["fact_ids"]) <= projected_fact_ids, "PROJECTION_HIDDEN_FACT_REFERENCE", f"/sections/{i}/fact_ids", "projected section cannot reference an omitted fact")
        if projected["projection"] == "FREE" and original is not None:
            _add(issues, original["premium_section_id"] is None, "FREE_PREMIUM_LEAK", f"/sections/{i}", "Free projection cannot contain Premium section")
    return tuple(issues)


def validate_premium_output(packet: ValidatedDocument, output: ValidatedDocument) -> tuple[ContractIssue, ...]:
    if packet.schema_name != "PremiumPacket" or output.schema_name != "PremiumOutput":
        return (ContractIssue("WRONG_DOCUMENT_KIND", "", "Premium validation requires PremiumPacket + PremiumOutput"),)
    p = packet.to_dict()
    o = output.to_dict()
    issues: list[ContractIssue] = []
    _add(issues, o["packet_id"] == p["packet_id"], "OUTPUT_PACKET_MISMATCH", "/packet_id", "output must bind exact packet")
    _add(issues, o["output_schema_version"] == p["output_schema_version"], "OUTPUT_SCHEMA_MISMATCH", "/output_schema_version", "output schema differs from packet")
    questions = {q["question_id"]: q for q in p["questions"]}
    candidates = {c["candidate_id"]: c for c in p["candidates"]}
    allowed = set(p["allowed_fact_ids"])
    answer_ids = {a["question_id"] for a in o["answers"]}
    _add(issues, answer_ids == set(questions), "OUTPUT_QUESTION_SET_MISMATCH", "/answers", "output must contain exactly one explicit answer state for every frozen packet question")
    for i, answer in enumerate(o["answers"]):
        path = f"/answers/{i}"
        question = questions.get(answer["question_id"])
        if question is None:
            issues.append(ContractIssue("UNKNOWN_OUTPUT_QUESTION", f"{path}/question_id", "model answered a question not present in frozen packet"))
            continue
        selections = answer["selected_candidate_ids"]
        _add(issues, set(selections) <= set(question["candidate_ids"]), "OUTPUT_CANDIDATE_ESCAPE", f"{path}/selected_candidate_ids", "model selected candidate outside question packet")
        _add(issues, set(selections) <= set(candidates), "OUTPUT_UNKNOWN_CANDIDATE", f"{path}/selected_candidate_ids", "selected candidate is not frozen in packet")
        if question["cardinality"] == "SINGLE":
            _add(issues, len(selections) <= 1, "OUTPUT_CARDINALITY", f"{path}/selected_candidate_ids", "SINGLE question cannot select multiple candidates")
        _add(issues, set(answer["support_fact_ids"]) <= allowed, "OUTPUT_SUPPORT_ESCAPE", f"{path}/support_fact_ids", "model support IDs must remain inside allowed packet facts")
        if answer["answer_state"] == "ANSWERED":
            _add(issues, bool(selections) or bool(answer["prose"]), "EMPTY_ANSWERED", path, "ANSWERED must contain a selection or bounded prose")
        else:
            _add(issues, not selections, "NONANSWERED_SELECTION", f"{path}/selected_candidate_ids", "non-ANSWERED states cannot smuggle selections")
    permitted_soft = set(p["soft_field_ids"])
    for i, field in enumerate(o["soft_fields"]):
        path = f"/soft_fields/{i}"
        _add(issues, field["field_id"] in permitted_soft, "SOFT_FIELD_ESCAPE", f"{path}/field_id", "soft field must be frozen in the selected packet")
        authority = T26_AUTHORITY["soft_fields"].get(field["field_id"])
        if authority is not None:
            _add(issues, len(field["text"]) <= authority["max_characters"], "SOFT_FIELD_TOO_LONG", f"{path}/text", "soft field exceeds the reviewed T26 character bound")
        _add(issues, set(field["support_fact_ids"]) <= allowed, "SOFT_FIELD_SUPPORT_ESCAPE", f"{path}/support_fact_ids", "soft-field support IDs must remain inside allowed packet facts")
    return tuple(issues)


def free_method_ids() -> tuple[str, ...]:
    return tuple(item["method_id"] for item in METHOD_CAPABILITIES["methods"] if item["free_eligible"])


def free_feature_ids() -> tuple[str, ...]:
    return tuple(feature_id for feature_id, value in METHOD_CAPABILITIES["features"].items() if value["free_available"])


def contract_identity() -> tuple[str, str]:
    return CONTRACT_VERSION, CONTRACT_BUNDLE_SHA256
