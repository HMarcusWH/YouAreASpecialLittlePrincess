"""Shared build-time helpers for T01 product contracts.

This module is stdlib-only. Runtime consumers use :mod:`princess_contracts`
and never import build tooling.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "contracts" / "product" / "v1" / "schemas"
METHOD_SOURCE = ROOT / "schema" / "method_capabilities" / "v1" / "methods.json"
FEATURE_SOURCE = ROOT / "schema" / "graphology_feature_database_v1.json"
FEATURE_RUNTIME = ROOT / "src" / "princess_graphology" / "_feature_contract.json"
T26_SOURCE = ROOT / "schema" / "premium_interpretation_database_v1.json"
PURPOSE_SOURCE = ROOT / "contracts" / "consent" / "v1" / "purposes.json"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
MAX_JSON_BYTES = 2 * 1024 * 1024

ALLOWED_SCHEMA_KEYS = {
    "$schema", "$id", "$defs", "$ref", "title", "description", "type", "properties", "required",
    "additionalProperties", "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength",
    "pattern", "enum", "const", "anyOf", "minimum", "maximum",
}


class ContractSourceError(ValueError):
    pass


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise ContractSourceError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def require_regular_file(path: Path) -> None:
    path = path.absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ContractSourceError(f"symlink is not reviewed contract input: {component}")
    try:
        mode = path.stat().st_mode
    except FileNotFoundError as exc:
        raise ContractSourceError(f"missing contract input: {path}") from exc
    if not stat.S_ISREG(mode):
        raise ContractSourceError(f"contract input is not a regular file: {path}")
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ContractSourceError(f"contract input exceeds {MAX_JSON_BYTES} bytes: {path}")


def load_json(path: Path) -> Any:
    require_regular_file(path)
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(ContractSourceError(f"non-finite JSON token {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ContractSourceError(f"invalid JSON in {path}: {exc}") from exc


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    require_regular_file(path)
    return sha256_bytes(path.read_bytes())


def schema_files() -> list[Path]:
    if not SCHEMA_ROOT.is_dir() or SCHEMA_ROOT.is_symlink():
        raise ContractSourceError("product schema root must be a real directory")
    files = sorted(SCHEMA_ROOT.glob("*.schema.json"))
    if not files:
        raise ContractSourceError("no product schemas found")
    return files


def load_schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    ids: set[str] = set()
    for path in schema_files():
        value = load_json(path)
        if not isinstance(value, dict):
            raise ContractSourceError(f"schema must be an object: {path.name}")
        if value.get("$schema") != DRAFT_2020_12 or value.get("$id") != path.name:
            raise ContractSourceError(f"{path.name}: $schema/$id must identify the local Draft 2020-12 file")
        if path.name in schemas or path.name in ids:
            raise ContractSourceError(f"duplicate schema identity: {path.name}")
        schemas[path.name] = value
        ids.add(path.name)
    _validate_schema_bundle(schemas)
    return schemas


def _validate_schema_bundle(schemas: dict[str, dict[str, Any]]) -> None:
    def walk(node: Any, *, file_name: str, path: str, root: dict[str, Any]) -> None:
        if not isinstance(node, dict):
            raise ContractSourceError(f"{file_name}{path}: schema node must be an object")
        unknown = set(node) - ALLOWED_SCHEMA_KEYS
        if unknown:
            raise ContractSourceError(f"{file_name}{path}: unsupported schema keywords: {sorted(unknown)}")
        if "$ref" in node:
            if set(node) != {"$ref"}:
                raise ContractSourceError(f"{file_name}{path}: $ref must be the only keyword")
            resolve_ref(schemas, file_name, node["$ref"])
            return
        if "anyOf" in node:
            if not isinstance(node["anyOf"], list) or not 2 <= len(node["anyOf"]) <= 16:
                raise ContractSourceError(f"{file_name}{path}: anyOf must contain 2..16 alternatives")
            for i, child in enumerate(node["anyOf"]):
                walk(child, file_name=file_name, path=f"{path}/anyOf/{i}", root=root)
        typ = node.get("type")
        if typ is not None and typ not in {"object", "array", "string", "number", "integer", "boolean", "null"}:
            raise ContractSourceError(f"{file_name}{path}: unsupported type {typ!r}")
        if typ == "object":
            props = node.get("properties")
            required = node.get("required")
            if not isinstance(props, dict) or not isinstance(required, list) or node.get("additionalProperties") is not False:
                raise ContractSourceError(f"{file_name}{path}: objects require properties, required and additionalProperties=false")
            if len(props) > 256 or len(required) != len(set(required)) or set(required) != set(props):
                raise ContractSourceError(f"{file_name}{path}: every property must be required exactly once; use explicit null for absence")
            for key, child in props.items():
                if not isinstance(key, str) or not key or len(key) > 128:
                    raise ContractSourceError(f"{file_name}{path}: invalid property name")
                walk(child, file_name=file_name, path=f"{path}/properties/{key}", root=root)
        if typ == "array":
            if not isinstance(node.get("maxItems"), int) or not 0 <= node["maxItems"] <= 100000:
                raise ContractSourceError(f"{file_name}{path}: arrays require bounded maxItems")
            if not isinstance(node.get("minItems", 0), int) or not 0 <= node.get("minItems", 0) <= node["maxItems"]:
                raise ContractSourceError(f"{file_name}{path}: invalid minItems")
            walk(node.get("items"), file_name=file_name, path=f"{path}/items", root=root)
        if typ == "string":
            if "enum" not in node and "const" not in node:
                maximum = node.get("maxLength")
                if not isinstance(maximum, int) or not 0 <= maximum <= 100000:
                    raise ContractSourceError(f"{file_name}{path}: strings require bounded maxLength")
            if "pattern" in node:
                try:
                    re.compile(node["pattern"])
                except (TypeError, re.error) as exc:
                    raise ContractSourceError(f"{file_name}{path}: invalid pattern") from exc
        if "enum" in node:
            values = node["enum"]
            if not isinstance(values, list) or not values or len(values) > 512:
                raise ContractSourceError(f"{file_name}{path}: invalid enum")
            fingerprints = [canonical_bytes(v) for v in values]
            if len(fingerprints) != len(set(fingerprints)):
                raise ContractSourceError(f"{file_name}{path}: duplicate enum value")
        if "$defs" in node:
            defs = node["$defs"]
            if not isinstance(defs, dict) or len(defs) > 256:
                raise ContractSourceError(f"{file_name}{path}: invalid $defs")
            for key, child in defs.items():
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key):
                    raise ContractSourceError(f"{file_name}{path}: invalid definition name {key!r}")
                walk(child, file_name=file_name, path=f"{path}/$defs/{key}", root=root)

    for name, schema in schemas.items():
        walk(schema, file_name=name, path="", root=schema)

    # Ref graph must be acyclic: product contracts are snapshots, not recursive object graphs.
    graph: dict[tuple[str, str], set[tuple[str, str]]] = {}

    def collect(node: Any, current: tuple[str, str], file_name: str) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                target_name, target_path, _ = resolve_ref(schemas, file_name, node["$ref"])
                graph.setdefault(current, set()).add((target_name, target_path))
            for value in node.values():
                collect(value, current, file_name)
        elif isinstance(node, list):
            for value in node:
                collect(value, current, file_name)

    for name, schema in schemas.items():
        graph.setdefault((name, ""), set())
        collect(schema, (name, ""), name)
        for def_name, value in schema.get("$defs", {}).items():
            key = (name, f"#/$defs/{def_name}")
            graph.setdefault(key, set())
            collect(value, key, name)

    visiting: set[tuple[str, str]] = set()
    visited: set[tuple[str, str]] = set()

    def visit(key: tuple[str, str]) -> None:
        if key in visiting:
            raise ContractSourceError(f"recursive product schema reference: {key[0]}{key[1]}")
        if key in visited:
            return
        visiting.add(key)
        for dep in graph.get(key, ()):
            visit(dep)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)


def resolve_ref(schemas: dict[str, dict[str, Any]], current_file: str, ref: Any) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(ref, str) or len(ref) > 256 or ".." in ref or ref.startswith(("/", "http:", "https:")):
        raise ContractSourceError(f"unsafe/non-local schema ref {ref!r}")
    if ref.startswith("#"):
        file_name, fragment = current_file, ref
    else:
        parts = ref.split("#", 1)
        file_name = parts[0]
        fragment = "#" + parts[1] if len(parts) == 2 else ""
    if file_name not in schemas:
        raise ContractSourceError(f"unknown schema ref file {file_name!r}")
    node: Any = schemas[file_name]
    if fragment:
        if not fragment.startswith("#/"):
            raise ContractSourceError(f"unsupported schema ref fragment {fragment!r}")
        for raw_part in fragment[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                raise ContractSourceError(f"unresolved schema ref {ref!r}")
            node = node[part]
    if not isinstance(node, dict):
        raise ContractSourceError(f"schema ref does not resolve to object {ref!r}")
    return file_name, fragment, node


def feature_authority() -> dict[str, Any]:
    source = load_json(FEATURE_SOURCE)
    runtime = load_json(FEATURE_RUNTIME)
    features = source.get("features")
    if not isinstance(features, list) or len(features) != 272:
        raise ContractSourceError("canonical feature database must contain 272 features")
    by_id: dict[str, dict[str, Any]] = {}
    for item in features:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in by_id:
            raise ContractSourceError("invalid/duplicate canonical feature ID")
        by_id[item["id"]] = item
    runtime_features = runtime.get("features")
    if not isinstance(runtime_features, dict) or set(runtime_features) != set(by_id):
        raise ContractSourceError("runtime feature projection does not match canonical feature IDs")
    for feature_id, item in by_id.items():
        projected = runtime_features[feature_id]
        for key in ("unit", "data_type", "scope", "input_mode"):
            if projected.get(key) != item.get(key):
                raise ContractSourceError(f"runtime feature projection drift for {feature_id}:{key}")
    return {
        "schema_version": source.get("version"),
        "source_sha256": file_sha256(FEATURE_SOURCE),
        "runtime_sha256": file_sha256(FEATURE_RUNTIME),
        "features": {feature_id: {"unit": item["unit"], "data_type": item["data_type"], "scope": item["scope"], "input_mode": item["input_mode"]} for feature_id, item in sorted(by_id.items())},
    }


def t26_authority() -> dict[str, Any]:
    data = load_json(T26_SOURCE)
    packs = data.get("question_packs")
    questions = data.get("question_definitions")
    selectors = data.get("selector_definitions")
    soft = data.get("soft_field_definitions")
    selection_contract = data.get("selection_contract")
    answer_state_policy = data.get("answer_state_policy")
    candidate_policy = data.get("candidate_validation_policy")
    if not all(isinstance(x, list) for x in (packs, questions, selectors, soft)) or not all(isinstance(x, dict) for x in (selection_contract, answer_state_policy, candidate_policy)):
        raise ContractSourceError("T26 compiled database is missing required collections/contracts")
    pack_map: dict[str, dict[str, Any]] = {}
    for pack in packs:
        pack_id = pack.get("pack_id") if isinstance(pack, dict) else None
        if not isinstance(pack_id, str) or pack_id in pack_map:
            raise ContractSourceError("invalid/duplicate T26 question pack")
        pack_map[pack_id] = {
            "version": pack.get("version"),
            "output_schema_version": pack.get("output_schema_version"),
            "question_ids": tuple(pack.get("question_ids", [])),
            "soft_field_ids": tuple(pack.get("soft_field_ids", [])),
            "runtime_activation": bool(pack.get("runtime_activation", False)),
        }
    selector_map = {}
    for selector in selectors:
        sid = selector.get("selector_id") if isinstance(selector, dict) else None
        if not isinstance(sid, str) or sid in selector_map:
            raise ContractSourceError("invalid/duplicate T26 selector definition")
        selector_map[sid] = selector
    question_map = {}
    for item in questions:
        qid = item.get("question_id") if isinstance(item, dict) else None
        selector_id = item.get("selector_id") if isinstance(item, dict) else None
        if not isinstance(qid, str) or qid in question_map or selector_id not in selector_map:
            raise ContractSourceError("invalid/duplicate T26 question definition")
        selector = selector_map[selector_id]
        domain = selector.get("selection_domain")
        cardinality = selector.get("cardinality")
        if domain not in selection_contract.get("selection_domain", []) or cardinality not in selection_contract.get("cardinality", []):
            raise ContractSourceError(f"{qid}: selector disagrees with T26 selection contract")
        question_map[qid] = {"selector_id": selector_id, "selection_domain": domain, "cardinality": cardinality}
    soft_fields: dict[str, dict[str, Any]] = {}
    for item in soft:
        sid = item.get("soft_field_id") if isinstance(item, dict) else None
        max_characters = item.get("max_characters") if isinstance(item, dict) else None
        max_sentences = item.get("max_sentences") if isinstance(item, dict) else None
        allow_new_numbers = item.get("allow_new_numbers") if isinstance(item, dict) else None
        if (
            not isinstance(sid, str)
            or sid in soft_fields
            or type(max_characters) is not int
            or not 1 <= max_characters <= 10000
            or type(max_sentences) is not int
            or not 1 <= max_sentences <= 100
            or type(allow_new_numbers) is not bool
        ):
            raise ContractSourceError("invalid/duplicate T26 soft field")
        soft_fields[sid] = {
            "max_characters": max_characters,
            "max_sentences": max_sentences,
            "allow_new_numbers": allow_new_numbers,
        }
    for pack_id, pack in pack_map.items():
        unknown_soft = set(pack["soft_field_ids"]) - set(soft_fields)
        if unknown_soft:
            raise ContractSourceError(f"{pack_id}: unknown soft fields {sorted(unknown_soft)}")
    return {
        "version": data.get("version"),
        "status": data.get("status"),
        "runtime_activation": bool(data.get("runtime_activation")),
        "sha256": file_sha256(T26_SOURCE),
        "question_packs": {k: v for k, v in sorted(pack_map.items())},
        "questions": {k: v for k, v in sorted(question_map.items())},
        "soft_fields": {k: v for k, v in sorted(soft_fields.items())},
        "soft_field_ids": tuple(sorted(soft_fields)),
        "selection_contract_version": selection_contract.get("version"),
        "answer_state_policy_version": answer_state_policy.get("version"),
        "answer_states": tuple(sorted(answer_state_policy.get("states", {}))),
        "candidate_policy_version": candidate_policy.get("version"),
    }


def purpose_authority() -> dict[str, Any]:
    data = load_json(PURPOSE_SOURCE)
    purposes = data.get("purposes")
    if not isinstance(purposes, list):
        raise ContractSourceError("consent purpose registry missing purposes")
    versions: dict[str, tuple[int, ...]] = {}
    for item in purposes:
        if not isinstance(item, dict) or not isinstance(item.get("purpose_id"), str) or type(item.get("purpose_version")) is not int:
            raise ContractSourceError("invalid purpose registry entry")
        versions.setdefault(item["purpose_id"], tuple())
        versions[item["purpose_id"]] = tuple(sorted((*versions[item["purpose_id"]], item["purpose_version"])))
    return {"sha256": file_sha256(PURPOSE_SOURCE), "versions": dict(sorted(versions.items()))}


def resolve_method_capabilities(features: dict[str, Any]) -> dict[str, Any]:
    data = load_json(METHOD_SOURCE)
    if not isinstance(data, dict) or set(data) != {"contract_version", "methods"} or data["contract_version"] != "1.0.0":
        raise ContractSourceError("method capability source must be contract_version 1.0.0 plus methods")
    methods = data["methods"]
    if not isinstance(methods, list) or not methods or len(methods) > 512:
        raise ContractSourceError("method capability source needs 1..512 methods")
    required = {
        "method_id", "method_version", "feature_ids", "input_modes", "requires_learned_inference",
        "requires_external_provider", "dependencies", "runtime_component", "license_review_id",
        "validation_release", "supported_cohorts",
    }
    by_id: dict[str, dict[str, Any]] = {}
    for method in methods:
        if not isinstance(method, dict) or set(method) != required:
            raise ContractSourceError("method capability fields differ from reviewed contract")
        mid = method["method_id"]
        if not isinstance(mid, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", mid) or mid in by_id:
            raise ContractSourceError(f"invalid/duplicate method_id {mid!r}")
        if not isinstance(method["method_version"], str) or not method["method_version"]:
            raise ContractSourceError(f"{mid}: invalid method_version")
        if not isinstance(method["feature_ids"], list) or not method["feature_ids"] or len(method["feature_ids"]) != len(set(method["feature_ids"])):
            raise ContractSourceError(f"{mid}: feature_ids must be unique/nonempty")
        unknown = set(method["feature_ids"]) - set(features)
        if unknown:
            raise ContractSourceError(f"{mid}: unknown canonical features {sorted(unknown)}")
        if not isinstance(method["input_modes"], list) or not method["input_modes"] or not all(isinstance(x, str) and x for x in method["input_modes"]):
            raise ContractSourceError(f"{mid}: invalid input_modes")
        if type(method["requires_learned_inference"]) is not bool or type(method["requires_external_provider"]) is not bool:
            raise ContractSourceError(f"{mid}: learned/provider flags must be booleans")
        if not isinstance(method["dependencies"], list) or len(method["dependencies"]) != len(set(method["dependencies"])):
            raise ContractSourceError(f"{mid}: invalid dependencies")
        if method["runtime_component"] not in {"free-core", "signature-extra", "premium", "reference", "other"}:
            raise ContractSourceError(f"{mid}: invalid runtime_component")
        for optional in ("license_review_id", "validation_release"):
            if method[optional] is not None and (not isinstance(method[optional], str) or not method[optional]):
                raise ContractSourceError(f"{mid}: invalid {optional}")
        if not isinstance(method["supported_cohorts"], list) or not all(isinstance(x, str) and x for x in method["supported_cohorts"]):
            raise ContractSourceError(f"{mid}: invalid supported_cohorts")
        by_id[mid] = method
    for mid, method in by_id.items():
        unknown = set(method["dependencies"]) - set(by_id)
        if unknown or mid in method["dependencies"]:
            raise ContractSourceError(f"{mid}: invalid dependency refs {sorted(unknown)}")

    visiting: set[str] = set()
    resolved: dict[str, dict[str, Any]] = {}

    def resolve(mid: str) -> dict[str, Any]:
        if mid in resolved:
            return resolved[mid]
        if mid in visiting:
            raise ContractSourceError(f"method capability dependency cycle at {mid}")
        visiting.add(mid)
        method = by_id[mid]
        deps = [resolve(dep) for dep in method["dependencies"]]
        learned = method["requires_learned_inference"] or any(d["requires_learned_inference"] for d in deps)
        provider = method["requires_external_provider"] or any(d["requires_external_provider"] for d in deps)
        free = method["runtime_component"] == "free-core" and not learned and not provider
        value = {
            **method,
            "requires_learned_inference": learned,
            "requires_external_provider": provider,
            "free_eligible": free,
            "dependency_closure": sorted({x for dep in method["dependencies"] for x in [dep, *resolved[dep]["dependency_closure"]]}),
        }
        visiting.remove(mid)
        resolved[mid] = value
        return value

    for mid in sorted(by_id):
        resolve(mid)
    feature_methods: dict[str, list[str]] = {fid: [] for fid in features}
    for mid, method in resolved.items():
        for fid in method["feature_ids"]:
            feature_methods[fid].append(mid)
    feature_capabilities = {
        fid: {
            "methods": sorted(mids),
            "free_available": any(resolved[mid]["free_eligible"] for mid in mids),
            "learned_only": bool(mids) and all(resolved[mid]["requires_learned_inference"] for mid in mids),
        }
        for fid, mids in sorted(feature_methods.items())
    }
    payload = {
        "contract_version": data["contract_version"],
        "source_sha256": file_sha256(METHOD_SOURCE),
        "methods": [resolved[mid] for mid in sorted(resolved)],
        "features": feature_capabilities,
    }
    payload["manifest_sha256"] = sha256_bytes(canonical_bytes(payload))
    return payload
