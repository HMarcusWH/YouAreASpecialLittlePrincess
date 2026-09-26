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


def canonical_json(value: Any) -> str:
    _validate_json_value(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


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
    common = set(data["common_feature_ids"])
    _add(issues, all(fid in FEATURES for fid in common), "UNKNOWN_COMMON_FEATURE", "/common_feature_ids", "comparison common mask must use canonical features")
    facts = _unique(data["facts"], "fact_id", issues, "/facts", "DUPLICATE_FACT")
    del facts
    for i, fact in enumerate(data["facts"]):
        _fact_semantics(fact, issues, f"/facts/{i}")
        _add(issues, fact["feature_id"] in common, "FACT_OUTSIDE_COMMON_MASK", f"/facts/{i}/feature_id", "comparison fact must belong to common feature mask")
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
