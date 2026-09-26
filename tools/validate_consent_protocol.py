#!/usr/bin/env python3
"""Validate the T03 consent, retention, source-rights and collection-protocol drafts.

Stdlib only. JSON Schemas under contracts/consent/v1/schemas are enforced with a
strict subset validator that refuses unknown keywords instead of ignoring them;
T01 may replace it with a pinned full implementation. The semantic rules and the
reference permission evaluator below define behaviour that JSON Schema cannot
express and that T02/T04 must reproduce.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSENT_DIR = ROOT / "contracts" / "consent" / "v1"
SCHEMA_DIR = CONSENT_DIR / "schemas"
COLLECTION_DIR = ROOT / "content" / "collection" / "v1"
TASKS_JSON = ROOT / "docs" / "roadmap" / "tasks.json"

# Purposes the T03 contract handoff requires to exist as separate permissions.
REQUIRED_DISTINCT_PURPOSES = (
    "service_processing",
    "image_retention",
    "reference_contribution",
    "third_party_ai_processing",
    "ordinary_sharing",
    "partner_comparison",
    "public_example",
)
# Deletion lineage must start from these handwriting-bearing artifacts.
HANDWRITING_ROOTS = ("upload_original", "pilot_capture")
FREE_SERVICE_PURPOSE = "service_processing"
# Purposes designed to be offered. Only APPROVED ones are usable for real
# permission decisions; DRAFT is usable solely inside synthetic fixtures.
OFFERED = {"DRAFT", "APPROVED"}
# The pilot gate cannot be approved unless every one of these owner decisions is recorded.
REQUIRED_PILOT_DECISIONS = (
    "controller_and_legal_basis", "age_eligibility", "retention_periods", "aggregate_after_withdrawal",
    "notice_wording", "collection_agreement", "compensation", "recruitment_channels",
    "processors_and_storage_region", "annotator_access", "prompt_rights",
)
LOCALES = ("en", "sv")
EXTRA_LETTERS = {"sv": "åäö"}
REQUIRED_PUNCTUATION = ",.:?!"
FREE_PRIVACY_TERMS = {"en": ("names", "addresses"), "sv": ("namn", "adresser")}

# Ties at the same effective and recorded time resolve to the more restrictive state.
RESTRICTIVENESS = {"GRANT": 0, "DENY": 1, "WITHDRAW": 2}
EVENT_STATE = {"GRANT": "PERMITTED", "DENY": "DENIED", "WITHDRAW": "WITHDRAWN"}
SYSTEM_WITHDRAWAL_SOURCES = {"ACCOUNT_DELETION", "SHARE_REVOCATION", "PURPOSE_RETIREMENT"}
# The source-rights use a human release of the collection must have cleared,
# keyed by the release purpose. Participant consent alone never clears a use.
RELEASE_SOURCE_USES = {"engineering_evaluation": "engineering_testing", "reference_contribution": "benchmark_statistics"}
# A grant's evidence and surface must match how it claims to have been captured.
GRANT_EVIDENCE = {
    "EXPLICIT_CONTROL": ("UI_INTERACTION", {"WEB", "IOS", "ANDROID", "PILOT_SESSION"}),
    "SIGNED_PILOT_AGREEMENT": ("SIGNED_AGREEMENT", {"PILOT_SESSION"}),
}

TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z")


@dataclass(frozen=True)
class Issue:
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} {self.where}: {self.message}"


# --------------------------------------------------------------------------- JSON


def load_json(path: Path):
    """Strict JSON: duplicate keys and non-finite constants are errors."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"non-finite JSON constant {value} in {path}")

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not TIMESTAMP.fullmatch(value):
        raise ValueError(f"not a UTC RFC 3339 timestamp: {value!r}")
    return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def json_equal(left, right) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if is_number(left) and is_number(right):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    return left == right


# ------------------------------------------------------------------ JSON Schema


SCHEMA_KEYWORDS = {
    "$schema", "$id", "$comment", "title", "description", "$defs", "$ref", "type", "properties", "required",
    "additionalProperties", "enum", "const", "pattern", "minLength", "items", "minItems", "uniqueItems",
    "format", "minimum",
}
ANNOTATIONS = {"$schema", "$id", "$comment", "title", "description"}
TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": is_number,
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class SchemaSet:
    """A strict JSON Schema 2020-12 subset: unsupported keywords are rejected, never ignored."""

    def __init__(self, directory: Path = SCHEMA_DIR):
        self.schemas = {path.name: load_json(path) for path in sorted(directory.glob("*.schema.json"))}
        problems: list[str] = []
        for name, schema in self.schemas.items():
            self._check_schema(name, schema, "#", problems)
        if problems:
            raise ValueError("invalid schema set:\n" + "\n".join(problems))

    def _check_schema(self, name: str, node, pointer: str, problems: list[str]) -> None:
        if not isinstance(node, dict):
            problems.append(f"{name}{pointer}: subschema must be an object")
            return
        unknown = sorted(set(node) - SCHEMA_KEYWORDS)
        if unknown:
            problems.append(f"{name}{pointer}: unsupported keyword(s) {unknown}")
        if "$ref" in node:
            if set(node) - ANNOTATIONS - {"$ref"}:
                problems.append(f"{name}{pointer}: $ref must not have validation siblings")
            try:
                self.resolve(name, node["$ref"])
            except (KeyError, ValueError) as exc:
                problems.append(f"{name}{pointer}: unresolved $ref {node['$ref']!r} ({exc})")
        if "additionalProperties" in node and not isinstance(node["additionalProperties"], bool):
            problems.append(f"{name}{pointer}: additionalProperties must be a boolean")
        if "format" in node and node["format"] != "date-time":
            problems.append(f"{name}{pointer}: only format date-time is supported")
        if node.get("type") == "object" and node.get("additionalProperties") is not False and "properties" in node:
            problems.append(f"{name}{pointer}: objects with properties must be closed (additionalProperties: false)")
        for key in ("properties", "$defs"):
            for child_name, child in node.get(key, {}).items():
                self._check_schema(name, child, f"{pointer}/{key}/{child_name}", problems)
        if "items" in node:
            self._check_schema(name, node["items"], f"{pointer}/items", problems)

    def resolve(self, current: str, ref: str) -> tuple[str, dict]:
        file_part, _, fragment = ref.partition("#")
        name = file_part or current
        node = self.schemas[name]
        if fragment:
            if not fragment.startswith("/"):
                raise ValueError("only JSON-pointer fragments are supported")
            for part in fragment.lstrip("/").split("/"):
                node = node[part]
        return name, node

    def validate(self, instance, schema_name: str, where: str = "$") -> list[Issue]:
        """Validate against a schema file, or a subschema given as "file.schema.json#/$defs/name"."""
        issues: list[Issue] = []
        name, schema = self.resolve(schema_name.partition("#")[0], schema_name)
        self._validate(instance, schema, name, where, issues)
        return issues

    def _validate(self, value, schema: dict, name: str, path: str, issues: list[Issue]) -> None:
        def fail(message: str) -> None:
            issues.append(Issue("SCHEMA", path, message))

        if "$ref" in schema:
            target_name, target = self.resolve(name, schema["$ref"])
            self._validate(value, target, target_name, path, issues)
            return
        if "type" in schema:
            types = [schema["type"]] if isinstance(schema["type"], str) else schema["type"]
            if not any(TYPE_CHECKS[t](value) for t in types):
                fail(f"expected {'/'.join(types)}, got {type(value).__name__}")
                return
        if is_number(value) and isinstance(value, float) and value != value:
            fail("NaN is not allowed")
        if "const" in schema and not json_equal(value, schema["const"]):
            fail(f"must equal {schema['const']!r}")
        if "enum" in schema and not any(json_equal(value, option) for option in schema["enum"]):
            fail(f"{value!r} is not one of {schema['enum']!r}")
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                fail(f"shorter than {schema['minLength']} characters")
            if "pattern" in schema and not re.search(schema["pattern"], value):
                fail(f"{value!r} does not match {schema['pattern']!r}")
            if schema.get("format") == "date-time":
                try:
                    parse_timestamp(value)
                except ValueError as exc:
                    fail(str(exc))
        if is_number(value) and "minimum" in schema and value < schema["minimum"]:
            fail(f"{value} is below minimum {schema['minimum']}")
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                fail(f"fewer than {schema['minItems']} items")
            if schema.get("uniqueItems"):
                seen = [json.dumps(item, sort_keys=True) for item in value]
                if len(seen) != len(set(seen)):
                    fail("items are not unique")
            if "items" in schema:
                for index, item in enumerate(value):
                    self._validate(item, schema["items"], name, f"{path}[{index}]", issues)
        if isinstance(value, dict):
            for key in schema.get("required", []):
                if key not in value:
                    fail(f"missing required property {key!r}")
            properties = schema.get("properties", {})
            for key, item in value.items():
                if key in properties:
                    self._validate(item, properties[key], name, f"{path}.{key}", issues)
                elif schema.get("additionalProperties") is False:
                    fail(f"unexpected property {key!r}")


# ---------------------------------------------------------------- shared helpers


def purpose_key(ref: dict) -> tuple[str, int]:
    return ref["purpose_id"], ref["purpose_version"]


def duplicates(values) -> list:
    seen, repeated = set(), []
    for value in values:
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return repeated


def known_gates(tasks_json: Path = TASKS_JSON) -> set[str]:
    return set(load_json(tasks_json)["gate_registry"])


def approved_by(purpose: dict, when: str) -> bool:
    """True when the purpose's recorded approval was decided at or before `when`."""
    decided_on = (purpose.get("approval") or {}).get("decided_on")
    return (purpose["status"] in {"APPROVED", "RETIRED"} and bool(decided_on)
            and parse_timestamp(decided_on) <= parse_timestamp(when))


def decided_with_ref(status: str, ref, code: str, where: str) -> list[Issue]:
    if status == "DECIDED" and not ref:
        return [Issue(code, where, "DECIDED requires a decision_ref")]
    return []


# ------------------------------------------------------------ registry semantics


def check_purposes(doc: dict, retention_ids: set[str], gates: set[str]) -> list[Issue]:
    issues: list[Issue] = []
    purposes = doc["purposes"]
    keys = [purpose_key(p) for p in purposes]
    for key in duplicates(keys):
        issues.append(Issue("DUPLICATE_PURPOSE", f"{key[0]}@{key[1]}", "purpose id/version declared twice"))
    ids = {p["purpose_id"] for p in purposes}
    for required in REQUIRED_DISTINCT_PURPOSES:
        if required not in ids:
            issues.append(Issue("MISSING_DISTINCT_PURPOSE", required, "handoff requires this as a separate purpose"))

    for p in purposes:
        where = f"{p['purpose_id']}@{p['purpose_version']}"
        offered = p["status"] in OFFERED
        if p["presented_default"] != "UNSELECTED":
            issues.append(Issue("PRECHECKED_DEFAULT", where, "choices must start unselected"))
        if p["required_for_service"] != (p["purpose_id"] == FREE_SERVICE_PURPOSE):
            issues.append(Issue("SERVICE_REQUIREMENT_MISMATCH", where,
                                f"only {FREE_SERVICE_PURPOSE} may be (and must be) required for the service"))
        if p["affects_free_report"] and not p["required_for_service"]:
            issues.append(Issue("OPTIONAL_PURPOSE_AFFECTS_FREE", where, "declining an optional purpose must not reduce Free"))
        if p["status"] == "APPROVED" and not (p.get("approval") or {}).get("decision_ref"):
            issues.append(Issue("APPROVAL_WITHOUT_EVIDENCE", where, "APPROVED requires an approval record with a decision_ref"))
        if p["status"] == "APPROVED" and p["legal_basis"] != "DECIDED":
            issues.append(Issue("APPROVED_WITHOUT_LEGAL_BASIS", where, "approval requires a decided legal basis"))
        if p["status"] == "APPROVED":
            passed = {d["gate"] for d in (p.get("approval") or {}).get("gate_decisions", [])}
            for gate in p["related_gates"]:
                if gate not in passed:
                    issues.append(Issue("GATE_NOT_APPROVED", where, f"{gate} has no recorded decision in approval.gate_decisions"))
        if p["legal_basis"] == "DECIDED" and p["status"] not in {"APPROVED", "RETIRED"}:
            issues.append(Issue("LEGAL_BASIS_WITHOUT_APPROVAL", where, "a decided legal basis belongs to an approved purpose"))
        if offered and not p["grant_scopes"]:
            issues.append(Issue("OFFERED_WITHOUT_SCOPE", where, "an offered purpose needs at least one grant scope"))
        # RETIRED keeps its definition: append-only history is interpreted against it.
        if p["status"] == "NOT_OFFERED" and (p["grant_scopes"] or p["recipients"] or p["retention_classes"]):
            issues.append(Issue("INACTIVE_PURPOSE_HAS_USE", where, "a purpose that is not offered cannot have scopes, recipients or retention"))
        if not p["withdrawal"]["available"]:
            issues.append(Issue("WITHDRAWAL_UNAVAILABLE", where, "withdrawal must remain available"))
        if p["subject_kind"] == "WRITER" and not p["requires_author_authority"]:
            issues.append(Issue("AUTHOR_AUTHORITY_REQUIRED", where, "handwriting purposes are granted only by the author"))
        if "purchase" not in p["not_implied_by"]:
            issues.append(Issue("PAYMENT_NOT_EXCLUDED", where, "a purchase must never imply this permission"))
        for gate in p["related_gates"]:
            if gate not in gates:
                issues.append(Issue("UNKNOWN_GATE", where, f"{gate} is not in docs/roadmap/tasks.json gate_registry"))
        for retention_class in p["retention_classes"]:
            if retention_class not in retention_ids:
                issues.append(Issue("UNKNOWN_RETENTION_CLASS", where, f"{retention_class} is not in retention.json"))

    if doc["registry_status"] == "APPROVED" and not (doc.get("approval") or {}).get("decision_ref"):
        issues.append(Issue("APPROVAL_WITHOUT_EVIDENCE", "purposes.json", "APPROVED registry requires an approval record"))
    if doc["registry_status"] == "APPROVED" and doc["legal_basis_status"] != "DECIDED":
        issues.append(Issue("APPROVED_WITHOUT_LEGAL_BASIS", "purposes.json", "approval requires decided legal bases"))
    if doc["legal_basis_status"] == "DECIDED" and doc["registry_status"] != "APPROVED":
        issues.append(Issue("LEGAL_BASIS_WITHOUT_APPROVAL", "purposes.json", "legal bases are decided with registry approval"))
    return issues


def check_purpose_retention(doc: dict, retention_doc: dict) -> list[Issue]:
    """An approved purpose may only use retention classes that are decided in an approved policy."""
    issues: list[Issue] = []
    classes = {c["class_id"]: c for c in retention_doc["classes"]}
    for p in doc["purposes"]:
        if p["status"] != "APPROVED":
            continue
        where = f"{p['purpose_id']}@{p['purpose_version']}"
        if retention_doc["status"] != "APPROVED":
            issues.append(Issue("PURPOSE_RETENTION_UNDECIDED", where, "retention.json must be APPROVED before a purpose using it"))
        for class_id in p["retention_classes"]:
            retention_class = classes.get(class_id)
            if retention_class is None:
                continue  # reported as UNKNOWN_RETENTION_CLASS by check_purposes
            if not (retention_class["decision_status"] == "DECIDED" and retention_class["max_retention"]["unit"] is not None):
                issues.append(Issue("PURPOSE_RETENTION_UNDECIDED", where,
                                    f"{class_id} has no decided maximum or explicit EVENT_BOUND choice"))
    return issues


def listed_purpose_issues(refs: list[dict], where: str) -> list[Issue]:
    """Choice copy is keyed by purpose_id, so one notice presents one version of each purpose."""
    return [Issue("NOTICE_LISTS_PURPOSE_TWICE", where, f"{purpose_id} appears in more than one version")
            for purpose_id in duplicates(ref["purpose_id"] for ref in refs)]


def check_notices(doc: dict, purposes: dict[tuple[str, int], dict]) -> list[Issue]:
    issues: list[Issue] = []
    for key in duplicates((n["notice_id"], n["version"]) for n in doc["notices"]):
        issues.append(Issue("DUPLICATE_NOTICE", f"{key[0]}@{key[1]}", "notice version declared twice"))
    for notice in doc["notices"]:
        where = f"{notice['notice_id']}@{notice['version']}"
        listed = set()
        for ref in notice["purposes"]:
            purpose = purposes.get(purpose_key(ref))
            if purpose is None:
                issues.append(Issue("UNKNOWN_PURPOSE", where, f"{ref['purpose_id']}@{ref['purpose_version']}"))
            elif purpose["status"] not in OFFERED and not (purpose["status"] == "RETIRED" and notice["status"] == "SUPERSEDED"):
                # A superseded notice is history; it may still list a purpose retired since.
                issues.append(Issue("NOTICE_OFFERS_INACTIVE_PURPOSE", where, ref["purpose_id"]))
            elif notice["status"] != "DRAFT" and purpose["status"] == "DRAFT":
                # Grants against unapproved purposes are rejected, so a live notice over them would be unusable.
                issues.append(Issue("NOTICE_ACTIVE_FOR_UNAPPROVED_PURPOSE", where, ref["purpose_id"]))
            elif notice["status"] != "DRAFT" and notice["effective_from"] and not approved_by(purpose, notice["effective_from"]):
                # Approval is never retroactive: a notice shown before it cannot have collected a valid grant.
                issues.append(Issue("NOTICE_PREDATES_APPROVAL", where,
                                    f"{ref['purpose_id']} was not yet approved at {notice['effective_from']}"))
            listed.add(ref["purpose_id"])
        issues += listed_purpose_issues(notice["purposes"], where)
        seen = [(c["purpose_id"], c["locale"]) for c in notice["copy"]]
        for item in duplicates(seen):
            issues.append(Issue("DUPLICATE_COPY", where, f"{item[0]} {item[1]}"))
        for purpose_id in sorted(listed):
            for locale in LOCALES:
                if (purpose_id, locale) not in seen:
                    issues.append(Issue("MISSING_COPY", where, f"{purpose_id} has no {locale} choice copy"))
        for purpose_id, _locale in seen:
            if purpose_id not in listed:
                issues.append(Issue("COPY_FOR_UNLISTED_PURPOSE", where, purpose_id))
        if notice["status"] == "DRAFT":
            if notice["effective_from"] or notice["effective_until"] or notice["decision_ref"]:
                issues.append(Issue("DRAFT_NOTICE_IN_EFFECT", where, "a draft notice has no effective window or decision"))
        elif not (notice["effective_from"] and notice["decision_ref"]):
            issues.append(Issue("NOTICE_ACTIVE_WITHOUT_DECISION", where, "ACTIVE/SUPERSEDED notices need a decision and start time"))
        elif notice["status"] == "SUPERSEDED" and not notice["effective_until"]:
            issues.append(Issue("NOTICE_WINDOW_INVALID", where, "a superseded notice needs the time it stopped being shown"))
    issues += notice_window_issues([n for n in doc["notices"] if n["effective_from"]], "notices.json")
    return issues


def notice_window_issues(windows: list[dict], where: str) -> list[Issue]:
    """Each window must end after it starts; versions of one notice never overlap."""
    issues: list[Issue] = []
    spans: dict[str, list[tuple[datetime, datetime | None, int]]] = {}
    for window in windows:
        start = parse_timestamp(window["effective_from"])
        end = parse_timestamp(window["effective_until"]) if window["effective_until"] else None
        label = f"{where}:{window['notice_id']}@{window['version']}"
        if end is not None and end <= start:
            issues.append(Issue("NOTICE_WINDOW_INVALID", label, "effective_until must be after effective_from"))
            continue
        spans.setdefault(window["notice_id"], []).append((start, end, window["version"]))
    for notice_id, items in spans.items():
        items.sort(key=lambda item: item[0])
        for (start_a, end_a, version_a), (start_b, _end_b, version_b) in zip(items, items[1:]):
            if end_a is None or end_a > start_b:
                issues.append(Issue("NOTICE_WINDOW_OVERLAP", f"{where}:{notice_id}",
                                    f"versions {version_a} and {version_b} are both in effect at {start_b.isoformat()}"))
    return issues


def check_retention(doc: dict) -> list[Issue]:
    issues: list[Issue] = []
    ids = [c["class_id"] for c in doc["classes"]]
    for class_id in duplicates(ids):
        issues.append(Issue("DUPLICATE_RETENTION_CLASS", class_id, "declared twice"))
    for required in ("consent_ledger", "deletion_tombstones"):
        if required not in ids:
            issues.append(Issue("MISSING_RETENTION_CLASS", required, "required for provable withdrawal and safe restores"))
    for c in doc["classes"]:
        where = c["class_id"]
        value, unit = c["max_retention"]["value"], c["max_retention"]["unit"]
        # null/null is the pending state; DAYS needs a number; EVENT_BOUND is the
        # explicit, reviewed choice of no fixed maximum (ends only on listed events).
        if (unit == "DAYS") != (value is not None):
            issues.append(Issue("RETENTION_UNIT_MISMATCH", where, "DAYS needs a value; other units carry none"))
        if unit is not None and not (c["decision_status"] == "DECIDED" and c["decision_ref"]):
            issues.append(Issue("RETENTION_WITHOUT_DECISION", where, "a retention period needs a recorded owner decision"))
        if unit == "EVENT_BOUND" and not c["ends_when"]:
            issues.append(Issue("RETENTION_EVENT_BOUND_WITHOUT_END", where, "EVENT_BOUND needs at least one ending event"))
        if c["decision_status"] == "DECIDED" and unit is None:
            issues.append(Issue("RETENTION_DECIDED_WITHOUT_PERIOD", where,
                                "a decided class records DAYS or the explicit EVENT_BOUND choice"))
        issues += decided_with_ref(c["decision_status"], c["decision_ref"], "DECISION_WITHOUT_REF", where)
        if c["contains_handwriting"]:
            if not c["deletion_actions"]:
                issues.append(Issue("HANDWRITING_WITHOUT_DELETION", where, "handwriting classes need deletion actions"))
            if c["backup_restore"] != "TOMBSTONE_RECONCILED_BEFORE_SERVICE" and c["external_copies"] != "PROCESSOR_CONTRACT_GOVERNED":
                issues.append(Issue("HANDWRITING_BACKUP_UNSAFE", where, "restores must reconcile tombstones first"))
    if doc["status"] == "APPROVED" and any(c["decision_status"] != "DECIDED" for c in doc["classes"]):
        issues.append(Issue("APPROVED_WITH_PENDING_DECISIONS", "retention.json", "every class must be decided"))
    return issues


def check_lineage(doc: dict, retention: dict[str, dict]) -> list[Issue]:
    issues: list[Issue] = []
    nodes = {n["artifact_kind"]: n for n in doc["nodes"]}
    for kind in duplicates(n["artifact_kind"] for n in doc["nodes"]):
        issues.append(Issue("DUPLICATE_ARTIFACT_KIND", kind, "declared twice"))
    for root in doc["roots"]:
        if root not in nodes or nodes[root]["parents"]:
            issues.append(Issue("INVALID_ROOT", root, "roots must exist and have no parents"))
    for root in HANDWRITING_ROOTS:
        node = nodes.get(root)
        root_class = retention.get(node["retention_class"]) if node else None
        if (root not in doc["roots"] or node is None or not node["contains_handwriting"]
                or root_class is None or not root_class["contains_handwriting"]):
            issues.append(Issue("HANDWRITING_ROOT_REQUIRED", root,
                                "a declared root that contains handwriting and uses a handwriting retention class"))
    for kind, node in nodes.items():
        if not node["parents"] and kind not in doc["roots"]:
            issues.append(Issue("UNDECLARED_ROOT", kind, "a parentless kind must be a declared root"))
        for parent in node["parents"]:
            if parent not in nodes:
                issues.append(Issue("UNKNOWN_PARENT", kind, parent))
        retention_class = retention.get(node["retention_class"])
        if retention_class is None:
            issues.append(Issue("UNKNOWN_RETENTION_CLASS", kind, node["retention_class"]))
        elif node["contains_handwriting"] and not retention_class["contains_handwriting"]:
            issues.append(Issue("RETENTION_CLASS_UNDERSTATES_HANDWRITING", kind, node["retention_class"]))
        if node["contains_handwriting"] and node["on_upstream_deletion"] == "RETAIN_UNDER_SEPARATE_OBLIGATION":
            issues.append(Issue("HANDWRITING_RETAINED", kind, "handwriting-bearing artifacts are never retained after deletion"))

    state: dict[str, int] = {}

    def visit(kind: str, trail: list[str]) -> None:
        if state.get(kind) == 1:
            issues.append(Issue("LINEAGE_CYCLE", kind, " -> ".join([*trail, kind])))
            return
        if state.get(kind) == 2 or kind not in nodes:
            return
        state[kind] = 1
        for parent in nodes[kind]["parents"]:
            visit(parent, [*trail, kind])
        state[kind] = 2

    for kind in nodes:
        visit(kind, [])

    children: dict[str, list[str]] = {kind: [] for kind in nodes}
    for kind, node in nodes.items():
        for parent in node["parents"]:
            children.setdefault(parent, []).append(kind)
    reached, pending = set(), [root for root in doc["roots"] if root in nodes]
    while pending:
        kind = pending.pop()
        if kind not in reached:
            reached.add(kind)
            pending.extend(children.get(kind, []))
    for kind in sorted(set(nodes) - reached):
        issues.append(Issue("LINEAGE_UNREACHABLE", kind, "not derived from any root, so deletion cannot find it"))
    return issues


def check_source_rights(doc: dict) -> list[Issue]:
    issues: list[Issue] = []
    for source_id in duplicates(s["source_id"] for s in doc["sources"]):
        issues.append(Issue("DUPLICATE_SOURCE", source_id, "declared twice"))
    for s in doc["sources"]:
        where = s["source_id"]
        statuses = [r["status"] for r in s["rights"].values()] + list(s["allowed_uses"].values())
        reviewed = s["review_status"] == "REVIEWED" and "review" in s
        if s["review_status"] == "REVIEWED" and "review" not in s:
            issues.append(Issue("REVIEW_WITHOUT_RECORD", where, "REVIEWED requires a review record"))
        if "CLEARED" in statuses and not reviewed:
            issues.append(Issue("CLEARED_WITHOUT_REVIEW", where, "clearance requires a recorded review"))
        if reviewed and s["kind"] == "EXTERNAL_DATASET" and not s["review"]["archive_sha256"]:
            issues.append(Issue("REVIEW_WITHOUT_ARCHIVE_HASH", where, "an external review pins the exact archive checksum"))
        data = s["rights"]["data"]["status"]
        for use, status in s["allowed_uses"].items():
            if status == "CLEARED" and data != "CLEARED":
                issues.append(Issue("USE_CLEARED_WITHOUT_DATA_RIGHTS", where,
                                    f"{use}: code or weight rights never clear the data"))
            if data == "NOT_CLEARED" and status != "NOT_CLEARED":
                issues.append(Issue("USE_OPEN_ON_UNCLEARED_DATA", where, f"{use} must be NOT_CLEARED while data rights are"))
    return issues


def check_pilot_gate(gate: dict, protocol: dict, notices: dict, purposes: dict[tuple[str, int], dict]) -> list[Issue]:
    issues: list[Issue] = []
    for key in duplicates(d["decision_key"] for d in gate["decisions"]):
        issues.append(Issue("DUPLICATE_DECISION", key, "declared twice"))
    for decision in gate["decisions"]:
        issues += decided_with_ref(decision["status"], decision["decision_ref"], "DECISION_WITHOUT_REF", decision["decision_key"])
    present = {d["decision_key"] for d in gate["decisions"]}
    for key in REQUIRED_PILOT_DECISIONS:
        if key not in present:
            issues.append(Issue("MISSING_GATE_DECISION", key, "required owner decision was removed from the gate"))
    if gate["status"] == "APPROVED":
        if not (gate.get("approval") or {}).get("decision_ref"):
            issues.append(Issue("APPROVAL_WITHOUT_EVIDENCE", "pilot_gate.json", "APPROVED requires an approval record with a decision_ref"))
        if any(d["status"] != "DECIDED" for d in gate["decisions"]):
            issues.append(Issue("APPROVED_WITH_PENDING_DECISIONS", "pilot_gate.json", "every gate decision must be decided"))
        protocol_approval = protocol.get("approval") or {}
        if protocol["status"] == "APPROVED" and not gate_approved_by(gate, protocol_approval.get("decided_on")):
            issues.append(Issue("GATE_APPROVED_AFTER_PROTOCOL", "pilot_gate.json",
                                "the participant-rights gate must be approved before the collection protocol"))
        return issues
    # While the gate is pending nothing downstream may behave as if it were approved.
    gated = {key for key, p in purposes.items() if gate["gate"] in p["related_gates"]}
    gated |= {purpose_key(ref) for ref in protocol["consent_purposes"]}
    if protocol["status"] == "APPROVED":
        issues.append(Issue("GATE_BYPASSED", "content/collection/v1/manifest.json", "protocol approved while the gate is pending"))
    for notice in notices["notices"]:
        if notice["status"] != "DRAFT" and any(purpose_key(ref) in gated for ref in notice["purposes"]):
            issues.append(Issue("GATE_BYPASSED", f"{notice['notice_id']}@{notice['version']}",
                                "notice for a gated purpose is in effect while the gate is pending"))
    for key in sorted(gated):
        if purposes.get(key, {}).get("status") == "APPROVED":
            issues.append(Issue("GATE_BYPASSED", f"{key[0]}@{key[1]}", "gated purpose approved while the gate is pending"))
    return issues


def gate_approved_by(gate: dict | None, when: str | None) -> bool:
    """True when the pilot gate is APPROVED with a recorded approval decided at or before `when`."""
    decided_on = ((gate or {}).get("approval") or {}).get("decided_on")
    return ((gate or {}).get("status") == "APPROVED" and bool(decided_on) and bool(when)
            and parse_timestamp(decided_on) <= parse_timestamp(when))


# ---------------------------------------------------------- collection protocol


def extract_passage(text: str) -> str | None:
    match = re.search(r"^```text\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else None


def check_protocol(protocol: dict, purposes: dict[tuple[str, int], dict], base: Path = COLLECTION_DIR, *,
                   sources: dict[str, dict] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    if protocol["status"] == "APPROVED" and not (protocol.get("approval") or {}).get("decision_ref"):
        issues.append(Issue("APPROVAL_WITHOUT_EVIDENCE", "protocol", "APPROVED requires an approval record with a decision_ref"))
    if sources is not None:
        source = sources.get(protocol["source_id"])
        if source is None or source["kind"] != "OWNED_COLLECTION":
            issues.append(Issue("UNKNOWN_SOURCE", "source_id", f"{protocol['source_id']} is not an owned collection in source_rights.json"))
    for task_id in duplicates(t["task_id"] for t in protocol["tasks"]):
        issues.append(Issue("DUPLICATE_TASK", task_id, "declared twice"))
    for ref in protocol["consent_purposes"]:
        purpose = purposes.get(purpose_key(ref))
        if purpose is None or purpose["status"] not in OFFERED:
            issues.append(Issue("UNKNOWN_PURPOSE", "consent_purposes", f"{ref['purpose_id']}@{ref['purpose_version']}"))

    languages = protocol["supported_contexts"]["languages"]
    for language in languages:
        for kind in ("COPY", "FREE"):
            count = sum(1 for t in protocol["tasks"] if t["language"] == language and t["task_kind"] == kind)
            if count != 1:
                issues.append(Issue("TASK_COVERAGE", f"{language}/{kind}", f"expected exactly one task, found {count}"))

    for task in protocol["tasks"]:
        where = task["task_id"]
        if protocol["status"] == "APPROVED" and not (task["rights"]["decision_status"] == "DECIDED" and task["rights"]["decision_ref"]):
            issues.append(Issue("PROTOCOL_APPROVED_WITH_PENDING_RIGHTS", where, "prompt rights must be decided before approval"))
        if task["language"] not in languages:
            issues.append(Issue("UNSUPPORTED_TASK_LANGUAGE", where, task["language"]))
        issues += decided_with_ref(task["rights"]["decision_status"], task["rights"]["decision_ref"], "DECISION_WITHOUT_REF", where)
        path = base / task["prompt_file"]
        if not path.is_file():
            issues.append(Issue("MISSING_PROMPT", where, task["prompt_file"]))
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != task["prompt_sha256"]:
            issues.append(Issue("PROMPT_HASH_MISMATCH", where, "prompt text changed without a new reviewed version/hash"))
        text = data.decode("utf-8")
        passage = extract_passage(text)
        if task["task_kind"] == "FREE":
            if passage is not None:
                issues.append(Issue("FREE_TASK_HAS_PASSAGE", where, "free writing must not contain text to copy"))
            lowered = text.lower()
            for term in FREE_PRIVACY_TERMS[task["language"]]:
                if term not in lowered:
                    issues.append(Issue("FREE_PRIVACY_INSTRUCTION", where, f"missing instruction not to write {term}"))
            continue
        if passage is None:
            issues.append(Issue("COPY_PASSAGE_MISSING", where, "copy prompts carry the passage in a ```text block"))
            continue
        lines = [line for line in passage.splitlines() if line.strip()]
        if len(lines) < 4:
            issues.append(Issue("COPY_PASSAGE_TOO_SHORT", where, "aim for several natural lines"))
        letters = set("abcdefghijklmnopqrstuvwxyz" + EXTRA_LETTERS.get(task["language"], ""))
        missing = sorted(letters - set(passage.lower()))
        if missing:
            issues.append(Issue("COPY_LETTER_COVERAGE", where, f"missing letters {''.join(missing)}"))
        absent = [mark for mark in REQUIRED_PUNCTUATION if mark not in passage]
        if absent:
            issues.append(Issue("COPY_PUNCTUATION", where, f"missing punctuation {''.join(absent)}"))
        if not any(ch.isupper() for ch in passage) or not any(ch.isdigit() for ch in passage):
            issues.append(Issue("COPY_SHAPES", where, "include capitals and digits"))

    for guidance in protocol["guidance"]:
        path = base / guidance["file"]
        if not path.is_file():
            issues.append(Issue("MISSING_GUIDANCE", guidance["guidance_id"], guidance["file"]))
        elif hashlib.sha256(path.read_bytes()).hexdigest() != guidance["sha256"]:
            issues.append(Issue("GUIDANCE_HASH_MISMATCH", guidance["guidance_id"], "guidance changed without a new hash"))
    for locale in languages:
        if not any(g["locale"] == locale for g in protocol["guidance"]):
            issues.append(Issue("MISSING_GUIDANCE", locale, "every supported language needs participant guidance"))

    indexes = [s["session_index"] for s in protocol["session_plan"]]
    if indexes != list(range(1, len(indexes) + 1)):
        issues.append(Issue("SESSION_PLAN_ORDER", "session_plan", f"session indexes must be 1..n in order, got {indexes}"))
    elif protocol["session_plan"][0]["participants"] != "ALL_ENROLLED":
        issues.append(Issue("SESSION_PLAN_ORDER", "session_plan", "session 1 covers every enrolled writer"))
    return issues


@dataclass
class CollectionSummary:
    synthetic: bool = False
    writers: int = 0
    specimens: int = 0
    captures: int = 0
    by_task: dict[str, dict[str, int]] = field(default_factory=dict)


def source_clearance_issues(protocol: dict, release_purpose: dict, sources: dict[str, dict] | None,
                            cutoff: datetime) -> list[Issue]:
    """A human release needs the collection's own data rights and the release's use cleared by a review recorded by the cutoff."""
    use = RELEASE_SOURCE_USES.get(release_purpose["purpose_id"])
    source = (sources or {}).get(protocol["source_id"])
    if use is None:
        return [Issue("SOURCE_NOT_CLEARED", "release_purpose", f"no source-rights use is defined for {release_purpose['purpose_id']}")]
    if source is None:
        return [Issue("SOURCE_NOT_CLEARED", protocol["source_id"], "the source-rights register has no entry for this collection")]
    reviewed = source["review_status"] == "REVIEWED" and "review" in source
    if not (reviewed and source["rights"]["data"]["status"] == "CLEARED" and source["allowed_uses"][use] == "CLEARED"):
        return [Issue("SOURCE_NOT_CLEARED", protocol["source_id"],
                      f"{use} is {source['allowed_uses'][use]} and data rights are {source['rights']['data']['status']} "
                      f"({source['review_status']})")]
    if parse_timestamp(source["review"]["reviewed_on"]) > cutoff:
        return [Issue("SOURCE_NOT_CLEARED", protocol["source_id"],
                      f"cleared by a review dated {source['review']['reviewed_on']}, after the release cutoff")]
    return []


def check_collection_manifest(
    manifest: dict, protocol: dict, consent: ConsentContext, *, human_release: bool = True,
    sources: dict[str, dict] | None = None, publish_at: datetime | None = None, gate: dict | None = None,
) -> tuple[list[Issue], CollectionSummary]:
    """Writer/specimen/capture lineage: pages, photos and sessions never become extra people.

    Every included specimen needs the manifest's release purpose to be
    PERMITTED at the release cutoff in the consent ledger, directly or through
    its writer's pilot enrollment. By default the manifest is treated as a human
    release: it must not be synthetic or use a fixture-mode consent context,
    the pilot gate (`gate`, pilot_gate.json) must be approved before the
    protocol, its protocol must be APPROVED with a
    recorded approval that precedes every included specimen, the collection's
    entry in `sources` (source_rights.json by source_id) must clear the
    release's use by the cutoff, and every permission is evaluated again at
    `publish_at`, immediately before publication; otherwise nothing is
    counted. Fixture checks pass human_release=False; their summary stays
    marked synthetic and must never feed human statistics.
    """
    issues: list[Issue] = []
    summary = CollectionSummary(synthetic=manifest["synthetic"])
    cutoff = parse_timestamp(manifest["release_cutoff"])
    releasable = True
    protocol_approved_at = None
    if human_release:
        if manifest["synthetic"]:
            issues.append(Issue("SYNTHETIC_IN_HUMAN_RELEASE", "synthetic", "synthetic samples are excluded from human statistics"))
            releasable = False
        if consent.fixture_mode:
            issues.append(Issue("FIXTURE_CONSENT_IN_HUMAN_RELEASE", "consent",
                                "fixture mode treats draft purposes and self-described notices as usable"))
            releasable = False
        approval = protocol.get("approval") or {}
        if protocol["status"] != "APPROVED" or not approval.get("decision_ref"):
            issues.append(Issue("PROTOCOL_NOT_APPROVED", "protocol",
                                f"collected under a {protocol['status']} protocol without a recorded approval"))
            releasable = False
        else:
            protocol_approved_at = parse_timestamp(approval["decided_on"])
            if not gate_approved_by(gate, approval["decided_on"]):
                issues.append(Issue("PILOT_GATE_NOT_APPROVED", "pilot_gate",
                                    "pilot_rights_consent must be APPROVED, with its approval preceding the protocol's"))
                releasable = False
        clearance = source_clearance_issues(protocol, manifest["release_purpose"], sources, cutoff)
        issues += clearance
        releasable = releasable and not clearance
        if publish_at is None:
            issues.append(Issue("PUBLICATION_NOT_RECHECKED", "publish_at",
                                "a human release re-evaluates every permission immediately before publication"))
            releasable = False
        elif publish_at < cutoff:
            issues.append(Issue("PUBLICATION_BEFORE_CUTOFF", "publish_at", "publication cannot precede the release cutoff"))
            releasable = False
    if (manifest["protocol"]["protocol_id"], manifest["protocol"]["version"]) != (protocol["protocol_id"], protocol["version"]):
        issues.append(Issue("PROTOCOL_MISMATCH", "protocol", "manifest was collected under another protocol version"))
    for label, rows, key in (("writer", manifest["writers"], "writer_id"), ("enrollment", manifest["writers"], "enrollment_id"),
                             ("specimen", manifest["specimens"], "specimen_id"), ("capture", manifest["captures"], "capture_id")):
        for value in duplicates(row[key] for row in rows):
            issues.append(Issue("DUPLICATE_ID", label, value))

    writers = {w["writer_id"]: w for w in manifest["writers"]}
    specimens = {s["specimen_id"]: s for s in manifest["specimens"]}
    captures = {c["capture_id"]: c for c in manifest["captures"]}
    tasks = {t["task_id"]: t for t in protocol["tasks"]}
    sessions = {session["session_index"]: session for session in protocol["session_plan"]}
    scripts = set(protocol["supported_contexts"]["scripts"])
    languages = set(protocol["supported_contexts"]["languages"])
    release_purpose = manifest["release_purpose"]
    release_allowed = purpose_key(release_purpose) in {purpose_key(ref) for ref in protocol["consent_purposes"]}
    if not release_allowed:
        issues.append(Issue("RELEASE_PURPOSE_NOT_IN_PROTOCOL", "release_purpose",
                            f"{release_purpose['purpose_id']}@{release_purpose['purpose_version']} is not a protocol purpose"))

    included: set[str] = set()
    seen_session_task: dict[tuple[str, str, int], str] = {}
    for s in manifest["specimens"]:
        where = s["specimen_id"]
        writer = writers.get(s["writer_id"])
        if writer is None:
            issues.append(Issue("DANGLING_REFERENCE", where, f"unknown writer {s['writer_id']}"))
            continue
        if writer["adult_eligibility"] != "DECLARED_ADULT":
            issues.append(Issue("INELIGIBLE_WRITER", where, f"writer eligibility is {writer['adult_eligibility']}"))
            continue
        task = tasks.get(s["task_id"])
        if task is None:
            issues.append(Issue("UNKNOWN_TASK", where, s["task_id"]))
            continue
        session = sessions.get(s["session_index"])
        if session is None:
            issues.append(Issue("UNKNOWN_SESSION", where, f"session {s['session_index']} is not in the protocol session plan"))
            continue
        if task["task_kind"] not in session["tasks_per_language"]:
            issues.append(Issue("TASK_NOT_IN_SESSION", where,
                                f"session {s['session_index']} schedules {', '.join(session['tasks_per_language'])}, not {task['task_kind']}"))
            continue
        supported = s["declared_script"] in scripts and s["declared_language"] in languages
        if supported != (s["context_status"] == "SUPPORTED"):
            issues.append(Issue("CONTEXT_STATUS_MISMATCH", where, "context_status must follow the declared script/language"))
            continue
        if not supported:
            continue  # recorded honestly, never counted into a supported cohort
        if s["declared_language"] != task["language"]:
            issues.append(Issue("TASK_LANGUAGE_MISMATCH", where, f"{s['task_id']} is a {task['language']} task"))
            continue
        session_key = (s["writer_id"], s["task_id"], s["session_index"])
        if session_key in seen_session_task:
            issues.append(Issue("DUPLICATE_SPECIMEN_IN_SESSION", where, f"same writer/task/session as {seen_session_task[session_key]}"))
            continue
        seen_session_task[session_key] = where
        collected = parse_timestamp(s["collected_at"])
        if collected > cutoff:
            issues.append(Issue("COLLECTED_AFTER_CUTOFF", where, f"collected at {s['collected_at']}"))
            continue
        if protocol_approved_at is not None and collected < protocol_approved_at:
            issues.append(Issue("COLLECTED_BEFORE_PROTOCOL_APPROVAL", where,
                                "approval is never retroactive: this page was written under an unapproved protocol"))
            continue
        if not (release_allowed and releasable):
            continue
        # The page itself needs some protocol purpose permitted when it was written;
        # a later grant never legitimizes collection that had no permission.
        enrollment = ({"kind": "PILOT_ENROLLMENT", "id": writer["enrollment_id"]},)
        if not any(
            evaluate_permission(consent, {"kind": "WRITER", "id": s["writer_id"]}, ref, {"kind": "SPECIMEN", "id": where},
                                collected, covering_scopes=enrollment) == "PERMITTED"
            for ref in protocol["consent_purposes"]
        ):
            issues.append(Issue("NO_COLLECTION_PERMISSION", where, f"no protocol purpose was permitted at {s['collected_at']}"))
            continue
        checks = [("the release cutoff", cutoff)] + ([("publication", publish_at)] if publish_at is not None else [])
        for label, instant in checks:
            state = evaluate_permission(
                consent, {"kind": "WRITER", "id": s["writer_id"]}, release_purpose, {"kind": "SPECIMEN", "id": where},
                instant, covering_scopes=enrollment,
            )
            if state != "PERMITTED":
                issues.append(Issue("NO_RELEASE_PERMISSION", where, f"{release_purpose['purpose_id']} is {state} at {label}"))
                break
        else:
            included.add(where)

    by_hash: dict[str, str] = {}
    counted: list[str] = []
    indexes: set[tuple[str, int]] = set()
    for c in manifest["captures"]:
        where = c["capture_id"]
        specimen = specimens.get(c["specimen_id"])
        if specimen is None:
            issues.append(Issue("DANGLING_REFERENCE", where, f"unknown specimen {c['specimen_id']}"))
            continue
        if (c["specimen_id"], c["capture_index"]) in indexes:
            issues.append(Issue("CAPTURE_INDEX_CONFLICT", where, "capture_index repeats within a specimen"))
        indexes.add((c["specimen_id"], c["capture_index"]))
        repeat = c["repeat_of_capture_id"]
        if repeat is None and c["capture_index"] != 1:
            issues.append(Issue("REPEAT_WITHOUT_ORIGINAL", where, "every capture after the first names the earlier capture it repeats"))
        if repeat is not None:
            original = captures.get(repeat)
            if original is None or repeat == where:
                issues.append(Issue("DANGLING_REFERENCE", where, f"repeat_of_capture_id {repeat} is not another capture"))
            elif original["specimen_id"] != c["specimen_id"]:
                issues.append(Issue("REPEAT_CROSSES_SPECIMEN", where, "a repeat photo belongs to the same page"))
            elif original["capture_index"] >= c["capture_index"]:
                # Pointing only backwards keeps repeat lineage acyclic, with an original at its root.
                issues.append(Issue("REPEAT_NOT_EARLIER", where, f"{repeat} is not an earlier capture of this page"))
        first = by_hash.get(c["content_sha256"])
        if first is not None:
            other = specimens.get(captures[first]["specimen_id"])
            if other is not None and other["writer_id"] != specimen["writer_id"]:
                issues.append(Issue("DUPLICATE_COUNTED_AS_WRITER", where, f"identical bytes to {first} under another writer"))
            else:
                issues.append(Issue("DUPLICATE_CAPTURE_BYTES", where, f"identical bytes to {first}"))
            continue
        by_hash[c["content_sha256"]] = where
        if c["specimen_id"] in included:
            counted.append(c["specimen_id"])

    # A specimen evidenced only by someone else's bytes is not evidence of another writer.
    included &= set(counted)
    # Later sessions estimate within-writer variation, so they need the same
    # writer's session-1 specimen for the same task in this release.
    baseline = {(specimens[i]["writer_id"], specimens[i]["task_id"]) for i in included if specimens[i]["session_index"] == 1}
    for specimen_id in sorted(included):
        s = specimens[specimen_id]
        if s["session_index"] != 1 and (s["writer_id"], s["task_id"]) not in baseline:
            issues.append(Issue("SESSION_WITHOUT_BASELINE", specimen_id,
                                f"session {s['session_index']} has no included session-1 {s['task_id']} specimen"))
            included.discard(specimen_id)
    summary.writers = len({specimens[s]["writer_id"] for s in included})
    summary.specimens = len(included)
    summary.captures = sum(1 for specimen_id in counted if specimen_id in included)
    for specimen_id in sorted(included):
        s = specimens[specimen_id]
        cohort = summary.by_task.setdefault(s["task_id"], {"writers": 0, "specimens": 0})
        cohort["specimens"] += 1
    for task_id, cohort in summary.by_task.items():
        cohort["writers"] = len({specimens[s]["writer_id"] for s in included if specimens[s]["task_id"] == task_id})

    claimed = manifest["claimed_counts"]
    computed = {"writers": summary.writers, "specimens": summary.specimens, "captures": summary.captures}
    for key, value in computed.items():
        if claimed[key] != value:
            issues.append(Issue("COUNT_MISMATCH", f"claimed_counts.{key}", f"claimed {claimed[key]}, lineage supports {value}"))
    return issues, summary


# ------------------------------------------------------- permission evaluation


@dataclass
class ConsentContext:
    purposes: dict[tuple[str, int], dict]
    notices: dict[tuple[str, int], dict]
    writers: dict[str, dict]
    events: list[dict]
    usable_statuses: frozenset[str] = frozenset({"APPROVED"})
    fixture_mode: bool = False
    valid: list[tuple[int, dict]] = field(default_factory=list)
    event_issues: dict[str, list[str]] = field(default_factory=dict)


def build_context(registry: dict, scenario: dict, *, fixture_mode: bool = False) -> ConsentContext:
    """Index a scenario's event log.

    Only APPROVED purposes can grant anything. fixture_mode additionally lets
    DRAFT purposes run so synthetic scenarios can exercise the rules before
    any owner approval exists; it must never be used for real decisions.
    """
    purposes = {purpose_key(p): p for p in registry["purposes"]}
    for extra in scenario.get("extra_purposes", []):
        purposes.setdefault(purpose_key(extra), extra)
    context = ConsentContext(
        purposes=purposes,
        notices={(n["notice_id"], n["version"]): n for n in scenario["notices"]},
        writers={w["writer_id"]: w for w in scenario["writers"]},
        events=scenario["events"],
        usable_statuses=frozenset({"APPROVED", "DRAFT"} if fixture_mode else {"APPROVED"}),
        fixture_mode=fixture_mode,
    )
    for index, event in enumerate(context.events):
        codes = event_validity(event, context)
        context.event_issues[event["event_id"]] = codes
        if not codes:
            context.valid.append((index, event))
    for event_id in duplicates(e["event_id"] for e in context.events):
        context.event_issues[event_id] = sorted(set(context.event_issues[event_id]) | {"DUPLICATE_EVENT_ID"})
        context.valid = [(i, e) for i, e in context.valid if e["event_id"] != event_id]
    return context


def notice_window_codes(event: dict, context: ConsentContext) -> list[str]:
    notice = context.notices.get((event["notice"]["notice_id"], event["notice"]["version"]))
    if notice is None:
        return ["UNKNOWN_NOTICE"]
    codes = []
    if purpose_key(event["purpose"]) not in {purpose_key(ref) for ref in notice["purposes"]}:
        codes.append("NOTICE_DOES_NOT_COVER_PURPOSE")
    if event["event_type"] == "GRANT":  # denials and withdrawals are honoured under any notice ever shown
        recorded = parse_timestamp(event["recorded_at"])
        start = parse_timestamp(notice["effective_from"])
        end = parse_timestamp(notice["effective_until"]) if notice["effective_until"] else None
        if recorded < start:
            codes.append("NOTICE_NOT_YET_IN_EFFECT")
        elif end is not None and recorded >= end:
            codes.append("OBSOLETE_NOTICE")
    return codes


def has_authority(event: dict, context: ConsentContext) -> bool:
    actor, subject = event["actor"], event["subject"]
    if subject["kind"] == "ACCOUNT":
        return actor["kind"] == "ACCOUNT" and actor["id"] == subject["id"]
    writer = context.writers.get(subject["id"])
    if writer is None:
        return False
    if actor["kind"] == "ACCOUNT":
        # Authority is judged as of the event: linking the account later never revives an uploader's choice.
        linked_at = writer.get("self_account_linked_at")
        return (writer["self_account_id"] is not None and actor["id"] == writer["self_account_id"]
                and linked_at is not None and parse_timestamp(linked_at) <= parse_timestamp(event["recorded_at"]))
    if actor["kind"] == "PILOT_PARTICIPANT":
        return actor["id"] == writer["writer_id"]
    return False


def event_validity(event: dict, context: ConsentContext) -> list[str]:
    """Codes that make an event ineffective. An invalid event never changes permission state."""
    codes: list[str] = []
    kind = event["event_type"]
    purpose = context.purposes.get(purpose_key(event["purpose"]))
    if purpose is None:
        return ["UNKNOWN_PURPOSE"]
    if kind == "GRANT" and purpose["status"] not in context.usable_statuses:
        codes.append("PURPOSE_NOT_APPROVED" if purpose["status"] == "DRAFT" else "PURPOSE_NOT_OFFERED")
    if event["subject"]["kind"] != purpose["subject_kind"]:
        codes.append("SUBJECT_KIND_MISMATCH")
    if event["subject"]["kind"] == "WRITER" and event["subject"]["id"] not in context.writers:
        codes.append("UNKNOWN_WRITER")
    scope = event["scope"]
    if scope["kind"] not in purpose["grant_scopes"] and not (kind == "WITHDRAW" and purpose["status"] not in OFFERED):
        codes.append("SCOPE_NOT_ALLOWED")
    if scope["kind"] == "SUBJECT_WIDE" and scope["id"] != event["subject"]["id"]:
        codes.append("SCOPE_SUBJECT_MISMATCH")
    codes += notice_window_codes(event, context)

    recorded, effective = parse_timestamp(event["recorded_at"]), parse_timestamp(event["effective_at"])
    if effective < recorded:
        codes.append("BACKDATED_EVENT")
    if kind == "WITHDRAW" and effective != recorded:
        codes.append("DELAYED_WITHDRAWAL")

    derived = event["derived_from"]
    if kind == "GRANT":
        if derived is not None:
            codes.append("PAYMENT_IS_NOT_CONSENT" if derived["kind"] in {"PURCHASE", "ENTITLEMENT"} else "GRANT_MUST_BE_DIRECT")
        if event["presented_default"] == "SELECTED":
            codes.append("PRECHECKED_GRANT")
        elif event["presented_default"] == "NOT_PRESENTED":
            codes.append("CHOICE_NOT_PRESENTED")
        if event["capture_method"] not in {"EXPLICIT_CONTROL", "SIGNED_PILOT_AGREEMENT"}:
            codes.append("GRANT_NOT_EXPLICIT")
        # Eligibility is bound to the grant: a later declaration never revives it.
        if purpose["requires_adult_declaration"] and event["subject_eligibility"] != "DECLARED_ADULT":
            codes.append("INELIGIBLE_AT_GRANT")
        # Only grants wait for evidence; restrictive choices take effect regardless.
        if event["evidence"]["status"] != "RECORDED":
            codes.append("EVIDENCE_PENDING")
        expected = GRANT_EVIDENCE.get(event["capture_method"])
        if expected and (event["evidence"]["kind"] != expected[0] or event["surface"] not in expected[1]):
            codes.append("EVIDENCE_MISMATCH")  # a label alone never proves a signature or an explicit choice
        # Pilot grants come from the signed agreement; a pilot denial through any explicit control is honoured.
        if event["actor"]["kind"] == "PILOT_PARTICIPANT" and event["capture_method"] != "SIGNED_PILOT_AGREEMENT":
            codes.append("GRANT_NOT_EXPLICIT")
        # Approval is never retroactive: a grant captured while the purpose was a draft stays invalid.
        if purpose["status"] == "APPROVED" and not approved_by(purpose, event["recorded_at"]):
            codes.append("GRANTED_BEFORE_APPROVAL")
    if kind in {"GRANT", "DENY"}:
        if not has_authority(event, context):
            codes.append("NO_AUTHOR_AUTHORITY" if purpose["requires_author_authority"] else "NO_AUTHORITY")
    else:
        actor = event["actor"]["kind"]
        if actor in {"ACCOUNT", "PILOT_PARTICIPANT"}:
            permitted = has_authority(event, context)
        elif actor == "SUPPORT_STAFF":
            permitted = (derived or {}).get("kind") == "SUPPORT_REQUEST" and event["capture_method"] == "VERIFIED_REQUEST"
        else:
            permitted = (derived or {}).get("kind") in SYSTEM_WITHDRAWAL_SOURCES
        if not permitted:
            codes.append("NO_AUTHORITY")
    return sorted(set(codes))


def scope_covers(event_scope: dict, query_scope: dict, subject: dict, covering_scopes: tuple[dict, ...] = ()) -> bool:
    if event_scope == query_scope or event_scope in covering_scopes:
        return True
    return event_scope["kind"] == "SUBJECT_WIDE" and event_scope["id"] == subject["id"] and query_scope["kind"] != "SUBJECT_WIDE"


def evaluate_permission(
    context: ConsentContext, subject: dict, purpose_ref: dict, scope: dict, at: datetime,
    covering_scopes: tuple[dict, ...] = (),
) -> str:
    """Latest valid event wins. covering_scopes are broader scopes the caller vouches
    contain the query scope (e.g. a specimen's pilot enrollment)."""
    purpose = context.purposes.get(purpose_key(purpose_ref))
    if purpose is None or purpose["status"] not in OFFERED:
        return "NOT_OFFERED"
    if purpose["status"] not in context.usable_statuses:
        return "NOT_APPROVED"
    if scope["kind"] not in purpose["grant_scopes"]:
        # A use the purpose never offered cannot be authorized by any broader grant.
        return "SCOPE_NOT_GRANTABLE"
    covering_scopes = tuple(c for c in covering_scopes if c["kind"] in purpose["grant_scopes"])
    if purpose["requires_adult_declaration"] and subject["kind"] == "WRITER":
        writer = context.writers.get(subject["id"])
        if writer is None or writer["adult_eligibility"] != "DECLARED_ADULT":
            return "INELIGIBLE"
    candidates = [
        (index, event) for index, event in context.valid
        if event["subject"] == subject
        and purpose_key(event["purpose"]) == purpose_key(purpose_ref)
        and scope_covers(event["scope"], scope, subject, covering_scopes)
        and parse_timestamp(event["effective_at"]) <= at
    ]
    if not candidates:
        return "NOT_ASKED"
    _index, latest = max(
        candidates,
        key=lambda item: (
            parse_timestamp(item[1]["effective_at"]),
            parse_timestamp(item[1]["recorded_at"]),
            RESTRICTIVENESS[item[1]["event_type"]],
            item[0],
        ),
    )
    return EVENT_STATE[latest["event_type"]]


def evaluate_use(context: ConsentContext, subject: dict, purpose_ref: dict, scope: dict, started: datetime, publish: datetime) -> str:
    """A use must be permitted when it starts and again immediately before publication."""
    if evaluate_permission(context, subject, purpose_ref, scope, started) != "PERMITTED":
        return "BLOCKED_AT_START"
    if evaluate_permission(context, subject, purpose_ref, scope, publish) != "PERMITTED":
        return "BLOCKED_AT_PUBLICATION"
    return "ALLOWED"


def notices_in_effect(context: ConsentContext, at: datetime) -> list[dict]:
    return [n for n in context.notices.values()
            if parse_timestamp(n["effective_from"]) <= at
            and (n["effective_until"] is None or at < parse_timestamp(n["effective_until"]))]


def evaluate_free_report(context: ConsentContext, writer_id: str, scope: dict, at: datetime) -> str:
    """Free availability depends only on purposes required for the service, never on optional choices.

    The service purpose is evaluated at the one version presented by the
    notices in effect at `at`. Historical versions stay in the registry for
    interpretation but are not extra prerequisites; after a material change a
    grant for the old version does not cover new processing.
    """
    versions = {ref["purpose_version"] for notice in notices_in_effect(context, at)
                for ref in notice["purposes"] if ref["purpose_id"] == FREE_SERVICE_PURPOSE}
    if len(versions) != 1:
        return "UNAVAILABLE"  # nothing, or more than one version, is being offered
    current = {"purpose_id": FREE_SERVICE_PURPOSE, "purpose_version": versions.pop()}
    permitted = evaluate_permission(context, {"kind": "WRITER", "id": writer_id}, current, scope, at) == "PERMITTED"
    return "AVAILABLE" if permitted else "UNAVAILABLE"


def registry_notice_windows(notices_doc: dict | None) -> list[dict]:
    """Windows of the notices the authoritative registry actually put in effect."""
    return [
        {key: n[key] for key in ("notice_id", "version", "effective_from", "effective_until", "purposes")}
        for n in (notices_doc or {}).get("notices", []) if n["status"] != "DRAFT" and n["effective_from"]
    ]


def collection_consent_context(registry: dict, manifest: dict, consent_log: dict, *, fixture_mode: bool = False,
                               notices: dict | None = None) -> ConsentContext:
    """Consent ledger for a collection manifest: pilot writers have no accounts.

    Outside fixture mode, notice windows come only from the authoritative
    notice registry (`notices`, i.e. notices.json); windows a ledger describes
    for itself are ignored, so a fabricated notice cannot make a grant valid.
    """
    if fixture_mode and not manifest["synthetic"]:
        raise ValueError("fixture mode is only for synthetic manifests; human data needs approved purposes and registry notices")
    windows = consent_log["notices"] if fixture_mode else registry_notice_windows(notices)
    writers = [
        {"writer_id": w["writer_id"], "self_account_id": None, "self_account_linked_at": None,
         "adult_eligibility": w["adult_eligibility"]}
        for w in manifest["writers"]
    ]
    scenario = {"notices": windows, "writers": writers, "events": consent_log["events"]}
    return build_context(registry, scenario, fixture_mode=fixture_mode)


CHECK_FIELDS = {
    "EVENT_VALIDITY": {"event_id"},
    "PERMISSION": {"subject", "purpose", "scope", "at"},
    "USE": {"subject", "purpose", "scope", "started_at", "publish_at"},
    "COMPARISON": {"writers", "purpose", "scope", "at"},
    "FREE_REPORT": {"subject", "scope", "at"},
}


def run_scenario(registry: dict, scenario: dict) -> list[Issue]:
    scenario_id = scenario["scenario_id"]
    issues = notice_window_issues(scenario["notices"], scenario_id)
    for window in scenario["notices"]:
        issues += listed_purpose_issues(window["purposes"], f"{scenario_id}:{window['notice_id']}@{window['version']}")
    for writer in scenario["writers"]:
        if (writer["self_account_id"] is None) != (writer["self_account_linked_at"] is None):
            issues.append(Issue("ACCOUNT_LINK_INCONSISTENT", f"{scenario_id}:{writer['writer_id']}",
                                "self_account_linked_at is set exactly when self_account_id is"))
    context = build_context(registry, scenario, fixture_mode=scenario["synthetic"] is True)
    for index, check in enumerate(scenario["checks"]):
        where = f"{scenario_id}.checks[{index}]"
        kind = check["kind"]
        missing = CHECK_FIELDS[kind] - set(check)
        if missing:
            issues.append(Issue("MALFORMED_CHECK", where, f"{kind} needs {sorted(missing)}"))
            continue
        if kind == "EVENT_VALIDITY":
            if check["event_id"] not in context.event_issues:
                issues.append(Issue("MALFORMED_CHECK", where, f"unknown event {check['event_id']}"))
                continue
            actual = context.event_issues[check["event_id"]]
            expected = sorted(check["expect"]) if isinstance(check["expect"], list) else None
        elif kind == "PERMISSION":
            actual = evaluate_permission(context, check["subject"], check["purpose"], check["scope"], parse_timestamp(check["at"]))
            expected = check["expect"]
        elif kind == "USE":
            actual = evaluate_use(context, check["subject"], check["purpose"], check["scope"],
                                  parse_timestamp(check["started_at"]), parse_timestamp(check["publish_at"]))
            expected = check["expect"]
        elif kind == "COMPARISON":
            at = parse_timestamp(check["at"])
            states = [evaluate_permission(context, {"kind": "WRITER", "id": w}, check["purpose"], check["scope"], at) for w in check["writers"]]
            actual = "ALLOWED" if all(state == "PERMITTED" for state in states) else "BLOCKED"
            expected = check["expect"]
        else:
            if check["subject"]["kind"] != "WRITER":
                issues.append(Issue("MALFORMED_CHECK", where, "FREE_REPORT is evaluated for a writer"))
                continue
            actual = evaluate_free_report(context, check["subject"]["id"], check["scope"], parse_timestamp(check["at"]))
            expected = check["expect"]
        if actual != expected:
            issues.append(Issue("SCENARIO_EXPECTATION", where, f"{kind}: expected {expected!r}, got {actual!r}"))
    return issues


# ------------------------------------------------------------------- repository


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def validate_repository(consent_dir: Path = CONSENT_DIR, collection_dir: Path = COLLECTION_DIR,
                        tasks_json: Path = TASKS_JSON) -> Report:
    report = Report()
    schemas = SchemaSet(consent_dir / "schemas")
    documents = {
        "purposes.json": "purpose-registry.schema.json",
        "notices.json": "notice-registry.schema.json",
        "retention.json": "retention-policy.schema.json",
        "deletion_lineage.json": "deletion-lineage.schema.json",
        "source_rights.json": "source-rights.schema.json",
        "pilot_gate.json": "pilot-gate.schema.json",
    }
    loaded = {}
    for filename, schema in documents.items():
        loaded[filename] = load_json(consent_dir / filename)
        report.issues += schemas.validate(loaded[filename], schema, filename)
    protocol = load_json(collection_dir / "manifest.json")
    report.issues += schemas.validate(protocol, "collection-protocol.schema.json", "content/collection/v1/manifest.json")
    if report.issues:
        return report  # semantic rules assume schema-valid documents

    registry, notices = loaded["purposes.json"], loaded["notices.json"]
    retention = {c["class_id"]: c for c in loaded["retention.json"]["classes"]}
    sources = {s["source_id"]: s for s in loaded["source_rights.json"]["sources"]}
    purposes = {purpose_key(p): p for p in registry["purposes"]}
    checks = [
        ("purposes", check_purposes(registry, set(retention), known_gates(tasks_json))
         + check_purpose_retention(registry, loaded["retention.json"]),
         f"{len(purposes)} purposes, {sum(p['status'] in OFFERED for p in purposes.values())} offered, "
         f"{sum(p['status'] == 'APPROVED' for p in purposes.values())} approved"),
        ("notices", check_notices(notices, purposes),
         f"{len(notices['notices'])} notices, {sum(len(n['copy']) for n in notices['notices'])} choice texts, "
         f"{sum(n['status'] != 'DRAFT' for n in notices['notices'])} in effect"),
        ("retention", check_retention(loaded["retention.json"]),
         f"{len(retention)} classes, {sum(c['max_retention']['value'] is not None for c in retention.values())} periods decided"),
        ("deletion lineage", check_lineage(loaded["deletion_lineage.json"], retention),
         f"{len(loaded['deletion_lineage.json']['nodes'])} artifact kinds from {len(loaded['deletion_lineage.json']['roots'])} roots"),
        ("source rights", check_source_rights(loaded["source_rights.json"]),
         f"{len(loaded['source_rights.json']['sources'])} sources, "
         f"{sum(s['review_status'] == 'REVIEWED' for s in loaded['source_rights.json']['sources'])} reviewed"),
        ("collection protocol", check_protocol(protocol, purposes, collection_dir, sources=sources),
         f"{len(protocol['tasks'])} tasks, {len(protocol['guidance'])} guidance files"),
        ("pilot gate", check_pilot_gate(loaded["pilot_gate.json"], protocol, notices, purposes),
         f"{loaded['pilot_gate.json']['status']}, "
         f"{sum(d['status'] == 'DECIDED' for d in loaded['pilot_gate.json']['decisions'])}/{len(loaded['pilot_gate.json']['decisions'])} decisions recorded"),
    ]
    for label, issues, detail in checks:
        report.issues += issues
        report.lines.append(f"{'PASS' if not issues else 'FAIL'} {label}: {detail}")

    scenario_files = sorted((consent_dir / "fixtures" / "scenarios").glob("*.json"))
    scenario_checks = 0
    scenario_issues: list[Issue] = []
    for path in scenario_files:
        scenario = load_json(path)
        found = schemas.validate(scenario, "consent-scenario.schema.json", path.name)
        scenario_issues += found or run_scenario(registry, scenario)
        scenario_checks += len(scenario.get("checks", []))
    report.issues += scenario_issues
    report.lines.append(f"{'PASS' if not scenario_issues else 'FAIL'} consent scenarios: "
                        f"{len(scenario_files)} scenarios, {scenario_checks} checks")

    collection_files = sorted((consent_dir / "fixtures" / "collection").glob("*.json"))
    collection_issues: list[Issue] = []
    for path in collection_files:
        fixture = load_json(path)
        found = schemas.validate(fixture["manifest"], "collection-manifest.schema.json", path.name)
        if not fixture["manifest"]["synthetic"]:
            found.append(Issue("NON_SYNTHETIC_FIXTURE", path.name, "repository fixtures must be synthetic"))
        for index, event in enumerate(fixture["consent_log"]["events"]):
            found += schemas.validate(event, "consent-event.schema.json", f"{path.name}:consent_log.events[{index}]")
        for index, window in enumerate(fixture["consent_log"]["notices"]):
            found += schemas.validate(window, "consent-scenario.schema.json#/$defs/notice_window",
                                      f"{path.name}:consent_log.notices[{index}]")
        if not found:
            found += notice_window_issues(fixture["consent_log"]["notices"], path.name)
            for window in fixture["consent_log"]["notices"]:
                found += listed_purpose_issues(window["purposes"], f"{path.name}:{window['notice_id']}@{window['version']}")
        if not found:
            consent = collection_consent_context(registry, fixture["manifest"], fixture["consent_log"], fixture_mode=True)
            publish_at = parse_timestamp(fixture["publish_at"]) if "publish_at" in fixture else None
            actual, _summary = check_collection_manifest(fixture["manifest"], protocol, consent, human_release=False,
                                                         sources=sources, publish_at=publish_at)
            codes = sorted({issue.code for issue in actual})
            if codes != sorted(fixture["expected_errors"]):
                found.append(Issue("FIXTURE_EXPECTATION", path.name, f"expected {sorted(fixture['expected_errors'])}, got {codes}"))
        collection_issues += found
    report.issues += collection_issues
    report.lines.append(f"{'PASS' if not collection_issues else 'FAIL'} collection fixtures: {len(collection_files)} manifests")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)
    try:
        report = validate_repository()
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    for line in report.lines:
        print(line)
    for issue in report.issues:
        print(issue)
    if report.issues:
        return 1
    print("Drafts only: no purpose, notice, retention period, source clearance or pilot gate is approved by this validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
