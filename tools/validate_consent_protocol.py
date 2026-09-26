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
import copy
import hashlib
import itertools
import math
import os
import stat
from collections import Counter
import json
import re
import sys
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from pathlib import Path

from consent_primitives import (
    Issue, ValidationResult, digest, freeze_json, input_tree_issues, rooted_nodes, unique_index,
)

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
# Artifact kinds that carry page pixels by construction; their classification is not a per-node choice.
HANDWRITING_ARTIFACTS = (
    "upload_original", "pilot_capture", "normalized_image", "crop_overlay_thumbnail", "premium_payload",
    "provider_copy", "export_artifact", "reference_member", "support_case_copy",
)
# The reviewed deletion plan: what deletion or withdrawal upstream does to each artifact kind, and the
# derivation edges deletion must follow. A lineage may add edges but never drop these, change an
# action or add a kind without this table changing in the same reviewed change.
LINEAGE_PLAN = {
    "upload_original": ("DELETE", ()),
    "pilot_capture": ("DELETE", ()),
    "normalized_image": ("DELETE", ("upload_original", "pilot_capture")),
    "crop_overlay_thumbnail": ("DELETE", ("normalized_image",)),
    "analysis_run": ("DELETE", ("normalized_image",)),
    "report_revision": ("DELETE", ("analysis_run",)),
    "premium_payload": ("DELETE", ("report_revision", "crop_overlay_thumbnail")),
    "provider_copy": ("REQUEST_PROCESSOR_DELETION", ("premium_payload",)),
    "export_artifact": ("DELETE", ("report_revision", "crop_overlay_thumbnail")),
    "share_route": ("REVOKE_THEN_DELETE", ("report_revision", "export_artifact")),
    "comparison_report": ("DELETE", ("report_revision",)),
    "reference_member": ("EXCLUDE_AND_REBUILD_OR_RETIRE", ("analysis_run", "normalized_image")),
    "benchmark_artifact": ("EXCLUDE_AND_REBUILD_OR_RETIRE", ("reference_member",)),
    "annotation": ("DELETE", ("pilot_capture", "normalized_image")),
    "support_case_copy": ("DELETE", ("upload_original", "report_revision")),
    "purchase_ledger_entry": ("RETAIN_UNDER_SEPARATE_OBLIGATION", ("report_revision",)),
}
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

    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError(f"JSON input exceeds 32 MiB: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except RecursionError as exc:
        raise ValueError(f"JSON nesting is too deep: {path.name}") from exc
    issues = input_tree_issues(value, path.name)
    if issues:
        raise ValueError(str(issues[0]))
    return value


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
        if isinstance(value, float) and not math.isfinite(value):
            fail("non-finite numbers are not allowed")
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
    seen, repeated = set(), set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return sorted(repeated, key=repr)


def known_gates(tasks_json: Path = TASKS_JSON) -> set[str]:
    return set(load_json(tasks_json)["gate_registry"])


# Lifecycle fields a decision's digest leaves out. Everything else is bound, including the decision
# record itself (reference, role, dates, gate decisions), except the digest it carries.
APPROVAL_LIFECYCLE = ("status", "retirement")
NOTICE_LIFECYCLE = (
    "status", "effective_until",
    "end_decision_ref", "end_decided_by_role", "end_decided_on", "end_content_sha256",
    "content_sha256",
)
SOURCE_REVIEW_LIFECYCLE = ("review_status",)


def content_sha256(document: dict, lifecycle: tuple[str, ...] = APPROVAL_LIFECYCLE, record: str | None = "approval") -> str:
    """What a decision covers: SHA-256 of the canonical JSON of the document without its lifecycle fields.

    Canonical means sorted keys, no insignificant whitespace and UTF-8. The
    decision record named by `record` stays in, minus its own content_sha256,
    so backdating or re-attributing a decision voids it like any content edit.
    A later lifecycle change (such as RETIRED or a superseded notice's end)
    keeps it.
    """
    body = {key: value for key, value in document.items() if key not in lifecycle}
    if record is not None and isinstance(body.get(record), dict):
        body[record] = {key: value for key, value in body[record].items() if key != "content_sha256"}
    return digest(body)


def notice_digest(notice: dict) -> str:
    return content_sha256(notice, NOTICE_LIFECYCLE, record=None)


def retirement_digest(purpose: dict) -> str:
    """Bind a retirement transition separately from the purpose's original approval."""
    retirement = purpose.get("retirement") or {}
    body = {
        "purpose_id": purpose.get("purpose_id"),
        "purpose_version": purpose.get("purpose_version"),
        "approval_content_sha256": (purpose.get("approval") or {}).get("content_sha256"),
        "retirement": {key: value for key, value in retirement.items() if key != "content_sha256"},
    }
    return digest(body)


def retirement_recorded(purpose: dict) -> bool:
    retirement = purpose.get("retirement") or {}
    approval = purpose.get("approval") or {}
    if not (purpose.get("status") == "RETIRED" and decision_metadata_valid(retirement)
            and decision_metadata_valid(approval) and retirement.get("retired_on")):
        return False
    try:
        ordered = (parse_timestamp(approval["decided_on"]) < parse_timestamp(retirement["decided_on"])
                   <= parse_timestamp(retirement["retired_on"]))
    except ValueError:
        return False
    return ordered and retirement.get("content_sha256") == retirement_digest(purpose)


def notice_end_digest(notice: dict) -> str:
    """Bind the final end of an approved notice without rewriting its original decision."""
    body = {
        "notice_id": notice.get("notice_id"),
        "version": notice.get("version"),
        "notice_content_sha256": notice.get("content_sha256"),
        "effective_until": notice.get("effective_until"),
        "end_decision_ref": notice.get("end_decision_ref"),
        "end_decided_by_role": notice.get("end_decided_by_role"),
        "end_decided_on": notice.get("end_decided_on"),
    }
    return digest(body)


def notice_end_recorded(notice: dict) -> bool:
    end = {"decision_ref": notice.get("end_decision_ref"), "decided_by_role": notice.get("end_decided_by_role"),
           "decided_on": notice.get("end_decided_on")}
    if not (notice.get("status") == "SUPERSEDED" and decision_metadata_valid(end)
            and notice_decision_bound(notice) and notice.get("effective_until")):
        return False
    try:
        ordered = (parse_timestamp(notice["effective_from"]) < parse_timestamp(notice["effective_until"])
                   and parse_timestamp(notice["decided_on"]) <= parse_timestamp(end["decided_on"])
                   <= parse_timestamp(notice["effective_until"]))
    except ValueError:
        return False
    return ordered and notice.get("end_content_sha256") == notice_end_digest(notice)


def review_digest(source: dict) -> str:
    return content_sha256(source, SOURCE_REVIEW_LIFECYCLE, record="review")


def decision_metadata_valid(record: dict, *, role: str = "decided_by_role", time: str = "decided_on") -> bool:
    """Common evidence shape; a digest binds content, not the truth of the claimed decision."""
    if not isinstance(record, dict):
        return False
    if not all(isinstance(record.get(k), str) and record[k].strip() for k in ("decision_ref", role, time)):
        return False
    if not re.fullmatch(r"decision:[a-z0-9][a-z0-9-]{3,80}", record["decision_ref"]):
        return False
    try:
        parse_timestamp(record[time])
    except ValueError:
        return False
    return True


def approval_recorded(document: dict | None) -> bool:
    approval = (document or {}).get("approval") or {}
    return decision_metadata_valid(approval) and approval.get("content_sha256") == content_sha256(document)


def approval_issues(document: dict, where: str) -> list[Issue]:
    approval = document.get("approval") or {}
    if not decision_metadata_valid(approval):
        return [Issue("APPROVAL_WITHOUT_EVIDENCE", where, "approval needs a decision reference, role and UTC decision time")]
    if approval.get("content_sha256") != content_sha256(document):
        return [Issue("APPROVAL_CONTENT_MISMATCH", where, "content or decision metadata changed since approval")]
    return []


def notice_decision_bound(notice: dict) -> bool:
    """Activation is a dated decision, not a backdatable status/wording label."""
    return (decision_metadata_valid(notice) and bool(notice.get("effective_from"))
            and parse_timestamp(notice["decided_on"]) <= parse_timestamp(notice["effective_from"])
            and notice.get("content_sha256") == notice_digest(notice))


def review_bound(source: dict) -> bool:
    review = source.get("review") or {}
    return (source["review_status"] == "REVIEWED"
            and decision_metadata_valid(review, role="reviewer_role", time="reviewed_on")
            and review.get("content_sha256") == review_digest(source))


def attribution_consistent(review: dict) -> bool:
    """Wording and delivery are recorded exactly when the reviewed terms require attribution."""
    attribution = review["attribution"]
    given = attribution["wording"] is not None and attribution["delivery"] is not None
    absent = attribution["wording"] is None and attribution["delivery"] is None
    return given if attribution["required"] else absent


def purpose_approval_complete(purpose: dict) -> bool:
    """Approved with every piece of evidence the registry rules require, for the purpose's current content."""
    approval = purpose.get("approval") or {}
    passed = {d["gate"] for d in approval.get("gate_decisions", []) if d.get("decision_ref")}
    base = (
        purpose["status"] in {"APPROVED", "RETIRED"}
        and purpose["legal_basis"] == "DECIDED"
        and not duplicates(d["gate"] for d in approval.get("gate_decisions", []))
        and set(purpose["related_gates"]) == passed
        and approval_recorded(purpose)
    )
    return base and (purpose["status"] != "RETIRED" or retirement_recorded(purpose))


def retired_at(purpose: dict) -> datetime | None:
    """When a content-bound RETIRED transition took effect; malformed retirement fails closed."""
    if not retirement_recorded(purpose):
        return None
    return parse_timestamp(purpose["retirement"]["retired_on"])


def approved_by(purpose: dict, when: str) -> bool:
    """True when the purpose's complete approval was decided at or before `when`."""
    return (purpose_approval_complete(purpose)
            and parse_timestamp(purpose["approval"]["decided_on"]) <= parse_timestamp(when))


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
        if p["status"] == "APPROVED":
            issues += approval_issues(p, where)
        if p["status"] == "APPROVED" and p["legal_basis"] != "DECIDED":
            issues.append(Issue("APPROVED_WITHOUT_LEGAL_BASIS", where, "approval requires a decided legal basis"))
        if p["status"] == "APPROVED":
            passed = {d["gate"] for d in (p.get("approval") or {}).get("gate_decisions", [])}
            for unexpected in sorted(passed - set(p["related_gates"])):
                issues.append(Issue("UNRELATED_GATE_DECISION", where, unexpected))
            for gate in p["related_gates"]:
                if gate not in passed:
                    issues.append(Issue("GATE_NOT_APPROVED", where, f"{gate} has no recorded decision in approval.gate_decisions"))
        retirement = p.get("retirement")
        if p["status"] == "RETIRED" and not retirement_recorded(p):
            if not retirement or not all(retirement.get(key) for key in (
                    "retired_on", "decision_ref", "decided_by_role", "decided_on", "content_sha256")):
                issues.append(Issue("RETIREMENT_WITHOUT_RECORD", where,
                                    "RETIRED needs a complete content-bound retirement decision record"))
            elif retirement.get("content_sha256") == retirement_digest(p) and decision_metadata_valid(retirement):
                code = "RETIREMENT_BEFORE_APPROVAL" if parse_timestamp(retirement["decided_on"]) <= parse_timestamp(p["approval"]["decided_on"]) else "RETIREMENT_BACKDATED"
                issues.append(Issue(code, where, "retirement decision chronology is invalid"))
            else:
                issues.append(Issue("RETIREMENT_CONTENT_MISMATCH", where,
                                    "retirement decision does not bind the current retired_on/reference/content"))
        elif p["status"] != "RETIRED" and retirement is not None:
            issues.append(Issue("RETIREMENT_ON_ACTIVE_PURPOSE", where, "only a RETIRED purpose carries a retirement record"))
        elif retirement is not None:
            approval_on = (p.get("approval") or {}).get("decided_on")
            decided_on = parse_timestamp(retirement["decided_on"])
            retired_on = parse_timestamp(retirement["retired_on"])
            if approval_on and decided_on <= parse_timestamp(approval_on):
                issues.append(Issue("RETIREMENT_BEFORE_APPROVAL", where, "retirement decision must follow the purpose approval"))
            elif decided_on > retired_on:
                issues.append(Issue("RETIREMENT_BACKDATED", where,
                                    "retired_on cannot precede the recorded retirement decision"))
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

    if doc["registry_status"] == "APPROVED":
        issues += approval_issues(doc, "purposes.json")
    if doc["registry_status"] == "APPROVED" and doc["legal_basis_status"] != "DECIDED":
        issues.append(Issue("APPROVED_WITHOUT_LEGAL_BASIS", "purposes.json", "approval requires decided legal bases"))
    if doc["legal_basis_status"] == "DECIDED" and doc["registry_status"] != "APPROVED":
        issues.append(Issue("LEGAL_BASIS_WITHOUT_APPROVAL", "purposes.json", "legal bases are decided with registry approval"))
    return issues


def check_purpose_retention(doc: dict, retention_doc: dict) -> list[Issue]:
    """An approved purpose may only use retention classes that are decided in an approved policy."""
    issues: list[Issue] = []
    indexed = unique_index(retention_doc["classes"], lambda c: c["class_id"],
                           code="DUPLICATE_RETENTION_CLASS", where="retention.json")
    if indexed.issues:
        return list(indexed.issues)
    classes = indexed.value
    issues += check_retention(retention_doc)
    for p in doc["purposes"]:
        if p["status"] not in {"APPROVED", "RETIRED"}:
            continue
        where = f"{p['purpose_id']}@{p['purpose_version']}"
        purpose_approved_on = (p.get("approval") or {}).get("decided_on")
        if (retention_doc["status"] != "APPROVED" or not approval_recorded(retention_doc) or not purpose_approved_on
                or parse_timestamp(retention_doc["approval"]["decided_on"]) > parse_timestamp(purpose_approved_on)):
            issues.append(Issue("PURPOSE_RETENTION_UNDECIDED", where,
                                "retention.json must be APPROVED, with a recorded approval, before a purpose using it"))
        for class_id in p["retention_classes"]:
            retention_class = classes.get(class_id)
            if retention_class is None:
                issues.append(Issue("UNKNOWN_RETENTION_CLASS", where, class_id))
                continue
            if not (
                retention_class["decision_status"] == "DECIDED"
                and retention_class["decision_ref"]
                and retention_class["max_retention"]["unit"] is not None
            ):
                issues.append(Issue("PURPOSE_RETENTION_UNDECIDED", where,
                                    f"{class_id} has no recorded decision for its maximum or explicit EVENT_BOUND choice"))
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
        end_fields = (
            notice.get("end_decision_ref"), notice.get("end_decided_by_role"),
            notice.get("end_decided_on"), notice.get("end_content_sha256"),
        )
        if notice["status"] == "DRAFT":
            if (notice["effective_from"] or notice["effective_until"] or notice["decision_ref"] or notice["content_sha256"]
                    or notice.get("decided_on") or notice.get("decided_by_role") or any(end_fields)):
                issues.append(Issue("DRAFT_NOTICE_IN_EFFECT", where, "a draft notice has no effective window or decision"))
        elif not (notice["effective_from"] and decision_metadata_valid(notice)):
            issues.append(Issue("NOTICE_ACTIVE_WITHOUT_DECISION", where, "ACTIVE/SUPERSEDED notices need a decision and start time"))
        elif parse_timestamp(notice["decided_on"]) > parse_timestamp(notice["effective_from"]):
            issues.append(Issue("NOTICE_ACTIVATION_BACKDATED", where, "activation must be decided before its window starts"))
        elif not notice_decision_bound(notice):
            # Wording or purposes edited after the decision are a new notice version, never the approved one.
            issues.append(Issue("NOTICE_CONTENT_MISMATCH", where,
                                "content_sha256 does not match the notice's purposes, wording and start; record a new version"))
        elif notice["status"] == "ACTIVE" and (notice["effective_until"] or any(end_fields)):
            issues.append(Issue("NOTICE_END_ON_ACTIVE", where, "an ACTIVE notice has no final end-decision record"))
        elif notice["status"] == "SUPERSEDED":
            if not notice["effective_until"]:
                issues.append(Issue("NOTICE_WINDOW_INVALID", where, "a superseded notice needs the time it stopped being shown"))
            elif not notice_end_recorded(notice):
                if not all(end_fields):
                    issues.append(Issue("NOTICE_END_WITHOUT_DECISION", where,
                                        "a superseded notice needs a complete content-bound end decision"))
                else:
                    issues.append(Issue("NOTICE_END_CONTENT_MISMATCH", where,
                                        "the end decision does not bind the current effective_until/reference/content"))
            elif parse_timestamp(notice["end_decided_on"]) > parse_timestamp(notice["effective_until"]):
                issues.append(Issue("NOTICE_END_BACKDATED", where,
                                    "effective_until cannot precede the recorded end decision"))
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
    if doc["status"] == "APPROVED":
        issues += approval_issues(doc, "retention.json")
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
    for kind in HANDWRITING_ARTIFACTS:
        node = nodes.get(kind)
        if node is not None and not node["contains_handwriting"]:
            issues.append(Issue("HANDWRITING_ARTIFACT_DECLASSIFIED", kind, "this artifact kind always carries page pixels"))
        elif node is None:
            issues.append(Issue("HANDWRITING_ARTIFACT_MISSING", kind, "deletion lineage must track every handwriting-bearing kind"))
    for kind, (action, parents) in LINEAGE_PLAN.items():
        node = nodes.get(kind)
        if node is None:
            if kind not in HANDWRITING_ARTIFACTS:  # handwriting kinds are reported above
                issues.append(Issue("LINEAGE_ARTIFACT_MISSING", kind, "deletion lineage must track every reviewed artifact kind"))
            continue
        if node["on_upstream_deletion"] != action:
            issues.append(Issue("DELETION_ACTION_MISMATCH", kind,
                                f"upstream deletion must {action}, not {node['on_upstream_deletion']}"))
        for parent in parents:
            if parent in nodes and parent not in node["parents"]:
                issues.append(Issue("LINEAGE_EDGE_MISSING", kind, f"deleting {parent} must still reach this kind"))
    for kind in nodes:
        if kind not in LINEAGE_PLAN:
            issues.append(Issue("UNREVIEWED_ARTIFACT_KIND", kind, "add the kind and its deletion action to LINEAGE_PLAN in the same change"))
    if doc["status"] == "APPROVED":
        issues += approval_issues(doc, "deletion_lineage.json")
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

    if set(nodes) - set(LINEAGE_PLAN):
        return issues  # an unreviewed, unbounded graph is not an approved deletion plan

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
        elif reviewed and not review_bound(s):
            issues.append(Issue("REVIEW_CONTENT_MISMATCH", where,
                                "review.content_sha256 does not match the rights, uses, restrictions and review record it covers"))
        if reviewed and not attribution_consistent(s["review"]):
            issues.append(Issue("ATTRIBUTION_INCONSISTENT", where,
                                "attribution wording and delivery are recorded exactly when the reviewed terms require them"))
        if "CLEARED" in statuses and not reviewed:
            issues.append(Issue("CLEARED_WITHOUT_REVIEW", where, "clearance requires a recorded review"))
        if reviewed and s["kind"] == "EXTERNAL_DATASET" and not s["review"]["archive_sha256"]:
            issues.append(Issue("REVIEW_WITHOUT_ARCHIVE_HASH", where, "an external review pins the exact archive checksum"))
        if reviewed and s["kind"] == "EXTERNAL_DATASET" and not (s["canonical_url"] and s["release"]):
            issues.append(Issue("REVIEW_WITHOUT_RELEASE_PIN", where,
                                "an external review names the publisher's canonical URL and the exact release it reviewed"))
        if reviewed and s["review"]["expires_on"] is not None and (
                parse_timestamp(s["review"]["expires_on"]) <= parse_timestamp(s["review"]["reviewed_on"])):
            issues.append(Issue("REVIEW_WINDOW_INVALID", where, "expires_on must be after reviewed_on"))
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
    gated = {key for key, p in purposes.items() if gate["gate"] in p["related_gates"]}
    gated |= {purpose_key(ref) for ref in protocol["consent_purposes"]}
    if gate["status"] == "APPROVED":
        issues += approval_issues(gate, "pilot_gate.json")
        if any(d["status"] != "DECIDED" for d in gate["decisions"]):
            issues.append(Issue("APPROVED_WITH_PENDING_DECISIONS", "pilot_gate.json", "every gate decision must be decided"))
        protocol_approval = protocol.get("approval") or {}
        if protocol["status"] == "APPROVED" and not gate_approved_by(gate, protocol_approval.get("decided_on")):
            issues.append(Issue("GATE_APPROVED_AFTER_PROTOCOL", "pilot_gate.json",
                                "the participant-rights gate must be approved before the collection protocol"))
        # Consent is acquired only after the participant-rights gate: nothing gated takes effect before it.
        gate_at = (gate.get("approval") or {}).get("decided_on")
        if gate_at:
            live = [n for n in notices["notices"] if n["status"] != "DRAFT" and n["effective_from"]]
            early_purposes, early_notices = gated_before(gated, purposes, live, gate_at)
            issues += [Issue("PURPOSE_APPROVED_BEFORE_GATE", where, f"approved before {gate['gate']} at {gate_at}")
                       for where in early_purposes]
            issues += [Issue("NOTICE_PREDATES_GATE", where, f"in effect before {gate['gate']} at {gate_at}")
                       for where in early_notices]
        return issues
    # While the gate is pending nothing downstream may behave as if it were approved.
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


def gated_before(gated: set[tuple[str, int]], purposes: dict[tuple[str, int], dict], windows: list[dict],
                 gate_at: str) -> tuple[list[str], list[str]]:
    """Gated purposes approved, and notice windows over them started, before the gate's approval at `gate_at`."""
    cutoff = parse_timestamp(gate_at)
    early_purposes = sorted(
        f"{key[0]}@{key[1]}" for key in gated
        if (decided := ((purposes.get(key) or {}).get("approval") or {}).get("decided_on"))
        and parse_timestamp(decided) < cutoff
    )
    early_notices = sorted(
        f"{n['notice_id']}@{n['version']}" for n in windows
        if parse_timestamp(n["effective_from"]) < cutoff and any(purpose_key(ref) in gated for ref in n["purposes"])
    )
    return early_purposes, early_notices


def gate_approved_by(gate: dict | None, when: str | None) -> bool:
    """True when the pilot gate is APPROVED, with every required decision recorded and its approval at or before `when`."""
    gate = gate or {}
    approval = gate.get("approval") or {}
    decisions = gate.get("decisions", [])
    keys = [d["decision_key"] for d in decisions]
    # Every row counts: an added or duplicated row that is still pending keeps the gate open.
    all_decided = all(d["status"] == "DECIDED" and d["decision_ref"] for d in decisions)
    return (gate.get("status") == "APPROVED" and approval_recorded(gate) and all_decided and not duplicates(keys)
            and set(REQUIRED_PILOT_DECISIONS) <= set(keys) and bool(when)
            and parse_timestamp(approval["decided_on"]) <= parse_timestamp(when))


# ---------------------------------------------------------- collection protocol


def extract_passage(text: str) -> str | None:
    match = re.search(r"^```text\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else None


def read_collection_asset(base: Path, relative: str) -> bytes:
    """Local assets only; no traversal, symlink, special file or unbounded read."""
    path = Path(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("collection asset path must stay beneath its root")
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("this platform lacks safe no-follow asset opens")
    root = Path(base).resolve(strict=True)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    handle = None
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        handle = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(handle).st_mode):
            raise ValueError("collection asset must be a regular file")
        with os.fdopen(handle, "rb") as reader:
            handle = None
            data = reader.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError("collection asset exceeds 1 MiB")
        return data
    finally:
        os.close(directory)
        if handle is not None:
            os.close(handle)


def check_protocol(protocol: dict, purposes: dict[tuple[str, int], dict], base: Path = COLLECTION_DIR, *,
                   sources: dict[str, dict] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    if protocol["status"] == "APPROVED":
        # The approval binds the prompt and guidance hashes: new wording needs a new approval or version.
        issues += approval_issues(protocol, "protocol")
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
        try:
            data = read_collection_asset(base, task["prompt_file"])
        except (OSError, ValueError) as exc:
            issues.append(Issue("MISSING_PROMPT", where, str(exc)))
            continue
        if hashlib.sha256(data).hexdigest() != task["prompt_sha256"]:
            issues.append(Issue("PROMPT_HASH_MISMATCH", where, "prompt text changed without a new reviewed version/hash"))
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(Issue("PROMPT_ENCODING", where, "prompt must be UTF-8"))
            continue
        passage = extract_passage(text)
        if task["task_kind"] == "FREE":
            if passage is not None:
                issues.append(Issue("FREE_TASK_HAS_PASSAGE", where, "free writing must not contain text to copy"))
            lowered = text.lower()
            for term in FREE_PRIVACY_TERMS.get(task["language"], ()):
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
        try:
            data = read_collection_asset(base, guidance["file"])
        except (OSError, ValueError) as exc:
            issues.append(Issue("MISSING_GUIDANCE", guidance["guidance_id"], str(exc)))
            continue
        if hashlib.sha256(data).hexdigest() != guidance["sha256"]:
            issues.append(Issue("GUIDANCE_HASH_MISMATCH", guidance["guidance_id"], "guidance changed without a new hash"))
    for locale in languages:
        if not any(g["locale"] == locale for g in protocol["guidance"]):
            issues.append(Issue("MISSING_GUIDANCE", locale, "every supported language needs participant guidance"))

    indexes = sorted(s["session_index"] for s in protocol["session_plan"])
    if indexes != list(range(1, len(indexes) + 1)):
        issues.append(Issue("SESSION_PLAN_ORDER", "session_plan", f"session indexes must be 1..n in order, got {indexes}"))
    elif next(s for s in protocol["session_plan"] if s["session_index"] == 1)["participants"] != "ALL_ENROLLED":
        issues.append(Issue("SESSION_PLAN_ORDER", "session_plan", "session 1 covers every enrolled writer"))
    return issues


# ------------------------------------------------ authoritative policy boundary

POLICY_SCHEMAS = {
    "purposes": "purpose-registry.schema.json", "notices": "notice-registry.schema.json",
    "retention": "retention-policy.schema.json", "lineage": "deletion-lineage.schema.json",
    "sources": "source-rights.schema.json", "gate": "pilot-gate.schema.json",
    "protocol": "collection-protocol.schema.json",
}
POLICY_INDEXES = (
    ("purposes", "purposes", purpose_key, "DUPLICATE_PURPOSE"),
    ("notices", "notices", lambda n: (n["notice_id"], n["version"]), "DUPLICATE_NOTICE"),
    ("retention", "classes", lambda c: c["class_id"], "DUPLICATE_RETENTION_CLASS"),
    ("lineage", "nodes", lambda n: n["artifact_kind"], "DUPLICATE_ARTIFACT_KIND"),
    ("sources", "sources", lambda s: s["source_id"], "DUPLICATE_SOURCE"),
    ("gate", "decisions", lambda d: d["decision_key"], "DUPLICATE_DECISION"),
    ("protocol", "tasks", lambda t: t["task_id"], "DUPLICATE_TASK"),
    ("protocol", "session_plan", lambda s: s["session_index"], "SESSION_PLAN_ORDER"),
    ("protocol", "guidance", lambda g: g["guidance_id"], "DUPLICATE_GUIDANCE"),
)


def policy_document_issues(documents: dict, *, collection_dir: Path = COLLECTION_DIR,
                           schemas: SchemaSet | None = None, tasks_json: Path = TASKS_JSON) -> list[Issue]:
    """The *same* complete validation pipeline for repository drafts and releases.

    Valid drafts may pass this structural/semantic validation. Readiness for a
    human release is a separate, strictly stronger predicate in the compiler.
    """
    schemas = schemas or SchemaSet()
    issues = []
    for name, schema in POLICY_SCHEMAS.items():
        document = documents.get(name)
        if document is None:
            issues.append(Issue("MISSING_POLICY_DOCUMENT", name, "required policy document is absent"))
            continue
        found = input_tree_issues(document, name)
        issues += found or schemas.validate(document, schema, name)
    if issues:
        return issues  # no indexing or semantic assumptions on malformed shapes
    indexes = {}
    for name, rows, key, code in POLICY_INDEXES:
        result = unique_index(documents[name][rows], key, code=code, where=f"{name}.{rows}")
        issues += result.issues
        if result.value is not None:
            indexes[(name, rows)] = result.value
    for purpose in documents["purposes"]["purposes"]:
        result = unique_index((purpose.get("approval") or {}).get("gate_decisions", []), lambda d: d["gate"],
                              code="DUPLICATE_GATE_DECISION", where=str(purpose_key(purpose)))
        issues += result.issues
    if issues:
        return issues  # duplicate keys never choose a winner by array position
    registry, notices, retention = documents["purposes"], documents["notices"], documents["retention"]
    purposes, classes, sources = indexes[("purposes", "purposes")], indexes[("retention", "classes")], indexes[("sources", "sources")]
    protocol, gate, lineage = documents["protocol"], documents["gate"], documents["lineage"]
    issues += check_purposes(registry, set(classes), known_gates(tasks_json))
    issues += check_retention(retention)
    issues += check_purpose_retention(registry, retention)
    issues += check_notices(notices, purposes)
    issues += check_lineage(lineage, classes)
    issues += check_source_rights(documents["sources"])
    issues += check_protocol(protocol, purposes, collection_dir, sources=sources)
    issues += check_pilot_gate(gate, protocol, notices, purposes)
    # Schema cannot express equality across related references.
    if protocol["gate"] != gate["gate"]:
        issues.append(Issue("PROTOCOL_GATE_MISMATCH", "protocol.gate", "protocol and supplied gate differ"))
    return sorted(set(issues), key=lambda i: (i.code, i.where, i.message))


@dataclass(frozen=True, init=False)
class ReleasePolicy:
    """Immutable, in-process result of compile_release_policy; never deserialize this type.

    This is a validated-code boundary, not a defence against code execution in
    the Python process. Trusted decision storage is responsible for authentic
    decision references and append-only history; hashes alone cannot prove them.
    """
    documents: dict
    fingerprint: str
    collection_dir: Path
    assets: tuple[tuple[str, str], ...]

    def __new__(cls, *_args, **_kwargs):
        raise TypeError("construct a release policy through compile_release_policy")


def compile_release_policy(*, registry: dict | None = None, notices: dict | None = None,
                           protocol: dict | None = None, retention: dict | None = None,
                           lineage: dict | None = None, sources: dict | None = None, gate: dict | None = None,
                           collection_dir: Path = COLLECTION_DIR) -> ValidationResult[ReleasePolicy]:
    """No usable value escapes if any dependency is missing, invalid or unapproved."""
    documents = dict(purposes=registry, notices=notices, protocol=protocol, retention=retention,
                     lineage=lineage, sources=sources, gate=gate)
    try:
        collection_dir = Path(collection_dir)
        issues = policy_document_issues(documents, collection_dir=collection_dir)
        if issues:
            return ValidationResult(None, tuple(issues))
        for name, field in (("purposes", "registry_status"), ("protocol", "status"),
                            ("retention", "status"), ("lineage", "status"), ("gate", "status")):
            if documents[name][field] != "APPROVED" or not approval_recorded(documents[name]):
                issues.append(Issue("POLICY_NOT_APPROVED", name, "human use needs a complete, content-bound approval"))
        purposes = unique_index(registry["purposes"], purpose_key, code="DUPLICATE_PURPOSE", where="purposes").value
        for ref in protocol["consent_purposes"]:
            if not purpose_approval_complete(purposes[purpose_key(ref)]):
                issues.append(Issue("PURPOSE_NOT_APPROVED", str(purpose_key(ref)), "protocol purpose is not approved"))
        if issues:
            return ValidationResult(None, tuple(issues))
        # Snapshot the actual asset digests as well as the protocol JSON. Rechecked
        # at the release boundary, so a stale compiled object cannot hide file edits.
        paths = [(t["prompt_file"], t["prompt_sha256"]) for t in protocol["tasks"]]
        paths += [(g["file"], g["sha256"]) for g in protocol["guidance"]]
        for path, expected in paths:
            if hashlib.sha256(read_collection_asset(collection_dir, path)).hexdigest() != expected:
                issues.append(Issue("ASSET_CHANGED_DURING_COMPILATION", path, "asset no longer matches the approved protocol"))
        if issues:
            return ValidationResult(None, tuple(issues))
        result = object.__new__(ReleasePolicy)
        object.__setattr__(result, "documents", freeze_json(documents))
        object.__setattr__(result, "fingerprint", digest(documents))
        object.__setattr__(result, "collection_dir", collection_dir.resolve(strict=True))
        object.__setattr__(result, "assets", tuple(paths))
        return ValidationResult(result)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        return ValidationResult(None, (Issue("INVALID_POLICY_INPUT", "policy", str(exc)),))


PUBLICATION_CHECKS = ("WITHDRAWAL_RECONCILIATION", "DELETION_PROPAGATION", "RESTORE_TOMBSTONES")


def release_evidence_issues(evidence: dict | None, policy: ReleasePolicy, manifest: dict,
                            consent: ConsentContext, publish_at: datetime) -> list[Issue]:
    """Require a current, content-bound attestation of the external deletion checks.

    This reference validator verifies the attestation contract, not a live
    storage system. T02/T11 must issue it from authoritative snapshots and fence
    the subsequent atomic publication on those snapshots (see the handoff).
    """
    if evidence is None:
        return [Issue("PUBLICATION_EVIDENCE_REQUIRED", "release", "withdrawal/deletion check evidence is required")]
    issues = input_tree_issues(evidence, "release_evidence")
    issues += [] if issues else SchemaSet().validate(evidence, "release-evidence.schema.json")
    if issues:
        return issues
    expected = {"policy_sha256": policy.fingerprint, "manifest_sha256": digest(manifest),
                "consent_events_sha256": digest(consent.events)}
    for field_name, value in expected.items():
        if evidence[field_name] != value:
            issues.append(Issue("PUBLICATION_EVIDENCE_MISMATCH", field_name, "check evidence is for different inputs"))
    if parse_timestamp(evidence["checked_at"]) != publish_at:
        issues.append(Issue("STALE_PUBLICATION_EVIDENCE", "checked_at", "evidence must be from the publication snapshot"))
    if not approval_recorded(evidence) or parse_timestamp(evidence["approval"]["decided_on"]) != publish_at:
        issues.append(Issue("PUBLICATION_EVIDENCE_UNBOUND", "approval", "attestation must bind the exact publication snapshot"))
    for name in PUBLICATION_CHECKS:
        if evidence["checks"][name]["status"] != "PASS":
            issues.append(Issue("PUBLICATION_CHECK_FAILED", name, "a pending or failed check cannot authorize release"))
    return issues


@dataclass(frozen=True, init=False)
class ApprovedCollection:
    writers: int
    specimens: int
    captures: int
    by_task: dict
    attribution: dict | None
    writer_ids: tuple[str, ...]
    specimen_ids: tuple[str, ...]
    capture_ids: tuple[str, ...]
    manifest_sha256: str
    policy_sha256: str
    consent_events_sha256: str
    evidence_sha256: str
    publish_at: datetime
    synthetic: bool = False

    def __new__(cls, *_args, **_kwargs):
        raise TypeError("obtain an approved collection through check_collection_manifest")


def _approved_collection(**values) -> ApprovedCollection:
    result = object.__new__(ApprovedCollection)
    for item in fields(ApprovedCollection):
        object.__setattr__(result, item.name, values[item.name] if item.name in values else item.default)
    return result


def check_collection_manifest(manifest: dict, policy: ReleasePolicy, consent: ConsentContext, *,
                              publish_at: datetime | None = None, release_evidence: dict | None = None
                              ) -> ValidationResult[ApprovedCollection]:
    """The ONLY human-release entry point. Invalid inputs never return release counts."""
    if not isinstance(policy, ReleasePolicy):
        return ValidationResult(None, (Issue("UNCOMPILED_POLICY", "policy", "raw contracts are not release authority"),))
    try:
        issues = input_tree_issues(manifest, "manifest")
        issues += [] if issues else SchemaSet().validate(manifest, "collection-manifest.schema.json")
        if issues:
            return ValidationResult(None, tuple(issues))
        for rows, field in (("writers", "writer_id"), ("writers", "enrollment_id"),
                            ("specimens", "specimen_id"), ("captures", "capture_id")):
            checked = unique_index(manifest[rows], lambda row: row[field], code="DUPLICATE_ID", where=field)
            issues += checked.issues
        if issues:
            return ValidationResult(None, tuple(issues))
        if manifest["synthetic"]:
            return ValidationResult(None, (Issue("SYNTHETIC_IN_HUMAN_RELEASE", "manifest", "fixtures are not human evidence"),))
        if not isinstance(consent, ConsentContext) or consent.fixture_mode:
            return ValidationResult(None, (Issue("FIXTURE_CONSENT_IN_HUMAN_RELEASE", "consent", "a production context is required"),))
        if (not isinstance(consent, AuthoritativeConsentContext) or consent.policy_sha256 != policy.fingerprint
                or consent.manifest_sha256 != digest(manifest)):
            return ValidationResult(None, (Issue("CONSENT_CONTEXT_MISMATCH", "consent", "context must be compiled for this policy and manifest"),))
        if consent.issues:
            return ValidationResult(None, consent.issues)
        if not isinstance(publish_at, datetime) or publish_at.tzinfo is None or publish_at.utcoffset() != timezone.utc.utcoffset(publish_at):
            return ValidationResult(None, (Issue("PUBLICATION_NOT_RECHECKED", "publish_at", "an explicit UTC publication instant is required"),))
        for path, expected in policy.assets:
            if hashlib.sha256(read_collection_asset(policy.collection_dir, path)).hexdigest() != expected:
                issues.append(Issue("PROTOCOL_ASSET_MISMATCH", path, "bytes changed after policy compilation"))
        issues += release_evidence_issues(release_evidence, policy, manifest, consent, publish_at)
        if issues:
            return ValidationResult(None, tuple(issues))
        docs = policy.documents
        for name in ("purposes", "protocol", "retention", "lineage", "gate"):
            if parse_timestamp(docs[name]["approval"]["decided_on"]) > publish_at:
                issues.append(Issue("POLICY_APPROVED_AFTER_PUBLICATION", name, "future approval is not release evidence"))
        if issues:
            return ValidationResult(None, tuple(issues))
        sources = unique_index(docs["sources"]["sources"], lambda s: s["source_id"], code="DUPLICATE_SOURCE", where="sources").value
        issues, summary = _collection_counts(manifest, docs["protocol"], consent, human_release=True,
                                             sources=sources, publish_at=publish_at, gate=docs["gate"], retention=docs["retention"])
        # Diagnostics are not authorization. Preview/filter rows in the fixture
        # tooling, then submit a clean, correctly counted release manifest.
        if issues:
            return ValidationResult(None, tuple(issues))
        return ValidationResult(_approved_collection(
            writers=summary.writers, specimens=summary.specimens, captures=summary.captures,
            by_task=freeze_json(summary.by_task), attribution=freeze_json(summary.attribution),
            writer_ids=summary.writer_ids, specimen_ids=summary.specimen_ids, capture_ids=summary.capture_ids,
            manifest_sha256=digest(manifest), policy_sha256=policy.fingerprint,
            consent_events_sha256=digest(consent.events), evidence_sha256=digest(release_evidence), publish_at=publish_at,
        ))
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        return ValidationResult(None, (Issue("INVALID_RELEASE_INPUT", "release", str(exc)),))


def check_fixture_collection_manifest(manifest: dict, protocol: dict, consent: ConsentContext, *,
                                      publish_at: datetime | None = None) -> tuple[list[Issue], CollectionSummary]:
    """Explicit synthetic-only diagnostic path. No switch turns this into a human release."""
    if not isinstance(manifest, dict) or manifest.get("synthetic") is not True:
        return [Issue("NON_SYNTHETIC_FIXTURE", "manifest", "fixture summaries are only for synthetic data")], CollectionSummary(synthetic=True)
    found = []
    for name, value, spec in (("manifest", manifest, "collection-manifest.schema.json"),
                              ("protocol", protocol, "collection-protocol.schema.json")):
        bad = input_tree_issues(value, name)
        found += bad or SchemaSet().validate(value, spec, name)
    if not isinstance(consent, ConsentContext):
        found.append(Issue("SCHEMA", "consent", "an evaluated fixture context is required"))
    if found:
        return found, CollectionSummary(synthetic=True)
    try:
        return _collection_counts(manifest, protocol, consent, human_release=False, publish_at=publish_at)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        return [Issue("INVALID_FIXTURE_INPUT", "fixture", str(exc))], CollectionSummary(synthetic=True)


@dataclass
class CollectionSummary:
    synthetic: bool = False
    writers: int = 0
    specimens: int = 0
    captures: int = 0
    by_task: dict[str, dict[str, int]] = field(default_factory=dict)
    # For a cleared human release: the attribution its source review requires, carried with the counts.
    attribution: dict | None = None
    writer_ids: tuple[str, ...] = ()
    specimen_ids: tuple[str, ...] = ()
    capture_ids: tuple[str, ...] = ()


def source_clearance_issues(protocol: dict, release_purpose: dict, sources: dict[str, dict] | None,
                            cutoff: datetime, publish_at: datetime | None = None) -> list[Issue]:
    """A human release needs the collection's own data rights and the release's use cleared by a review recorded by the cutoff."""
    use = RELEASE_SOURCE_USES.get(release_purpose["purpose_id"])
    source = (sources or {}).get(protocol["source_id"])
    if use is None:
        return [Issue("SOURCE_NOT_CLEARED", "release_purpose", f"no source-rights use is defined for {release_purpose['purpose_id']}")]
    if source is None:
        return [Issue("SOURCE_NOT_CLEARED", protocol["source_id"], "the source-rights register has no entry for this collection")]
    if source["kind"] != "OWNED_COLLECTION":
        return [Issue("SOURCE_NOT_CLEARED", protocol["source_id"],
                      "not an owned collection: another dataset's clearance never covers pilot pages")]
    if not (review_bound(source) and attribution_consistent(source["review"])
            and source["rights"]["data"]["status"] == "CLEARED" and source["allowed_uses"][use] == "CLEARED"):
        bound = "a review bound to them" if review_bound(source) else "no review bound to the current rights"
        return [Issue("SOURCE_NOT_CLEARED", protocol["source_id"],
                      f"{use} is {source['allowed_uses'][use]} and data rights are {source['rights']['data']['status']} "
                      f"({source['review_status']}, {bound})")]
    if parse_timestamp(source["review"]["reviewed_on"]) > cutoff:
        return [Issue("SOURCE_NOT_CLEARED", protocol["source_id"],
                      f"cleared by a review dated {source['review']['reviewed_on']}, after the release cutoff")]
    expires_on = source["review"]["expires_on"]
    if expires_on is not None and parse_timestamp(expires_on) <= max(cutoff, publish_at or cutoff):
        return [Issue("SOURCE_NOT_CLEARED", protocol["source_id"], f"the clearance expired at {expires_on}")]
    return []


def _collection_counts(
    manifest: dict, protocol: dict, consent: ConsentContext, *, human_release: bool = True,
    sources: dict[str, dict] | None = None, publish_at: datetime | None = None, gate: dict | None = None,
    retention: dict | None = None,
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
        if protocol["status"] != "APPROVED" or not approval_recorded(protocol):
            issues.append(Issue("PROTOCOL_NOT_APPROVED", "protocol",
                                f"collected under a {protocol['status']} protocol without a recorded approval of its current content"))
            releasable = False
        elif any(not (task["rights"]["decision_status"] == "DECIDED" and task["rights"]["decision_ref"])
                 for task in protocol["tasks"]):
            issues.append(Issue("PROTOCOL_NOT_APPROVED", "protocol", "every prompt's rights must be decided before a human release"))
            releasable = False
        else:
            protocol_approved_at = parse_timestamp(approval["decided_on"])
            if not gate_approved_by(gate, approval["decided_on"]):
                issues.append(Issue("PILOT_GATE_NOT_APPROVED", "pilot_gate",
                                    "pilot_rights_consent must be APPROVED, with its approval preceding the protocol's"))
                releasable = False
            else:
                gated = {purpose_key(ref) for ref in protocol["consent_purposes"]}
                early = [*itertools.chain(*gated_before(gated, consent.purposes, list(consent.notices.values()),
                                                        gate["approval"]["decided_on"]))]
                if early:
                    issues.append(Issue("PILOT_GATE_NOT_APPROVED", "pilot_gate",
                                        f"{', '.join(early)} took effect before pilot_rights_consent was approved"))
                    releasable = False
        clearance = source_clearance_issues(protocol, manifest["release_purpose"], sources, cutoff, publish_at)
        issues += clearance
        releasable = releasable and not clearance
        if not clearance:
            summary.attribution = copy.deepcopy(sources[protocol["source_id"]]["review"]["attribution"])
        # The protocol's purposes may only rely on retention classes decided in the approved, content-bound policy.
        if retention is None:
            retention_issues = [Issue("PURPOSE_RETENTION_UNDECIDED", "retention",
                                      "a human release needs the approved retention policy (retention.json)")]
        else:
            protocol_purposes = [consent.purposes[purpose_key(ref)] for ref in protocol["consent_purposes"]
                                 if purpose_key(ref) in consent.purposes]
            retention_issues = check_purpose_retention({"purposes": protocol_purposes}, retention)
        issues += retention_issues
        releasable = releasable and not retention_issues
        if publish_at is None:
            issues.append(Issue("PUBLICATION_NOT_RECHECKED", "publish_at",
                                "a human release re-evaluates every permission immediately before publication"))
            releasable = False
        elif publish_at < cutoff:
            issues.append(Issue("PUBLICATION_BEFORE_CUTOFF", "publish_at", "publication cannot precede the release cutoff"))
            releasable = False
    if (manifest["protocol"]["protocol_id"], manifest["protocol"]["version"]) != (protocol["protocol_id"], protocol["version"]):
        issues.append(Issue("PROTOCOL_MISMATCH", "protocol", "manifest was collected under another protocol version"))
        releasable = False  # its prompts and consent contract are not the ones being checked
    for label, rows, key in (("writer", manifest["writers"], "writer_id"), ("enrollment", manifest["writers"], "enrollment_id"),
                             ("specimen", manifest["specimens"], "specimen_id"), ("capture", manifest["captures"], "capture_id")):
        for value in duplicates(row[key] for row in rows):
            issues.append(Issue("DUPLICATE_ID", label, value))
    # Identities that are not unique cannot be counted: which row is the real writer, page or photo?
    ambiguous_writers = set(duplicates(w["writer_id"] for w in manifest["writers"]))
    shared_enrollments = set(duplicates(w["enrollment_id"] for w in manifest["writers"]))
    ambiguous_writers |= {w["writer_id"] for w in manifest["writers"] if w["enrollment_id"] in shared_enrollments}
    ambiguous_specimens = set(duplicates(s["specimen_id"] for s in manifest["specimens"]))
    ambiguous_captures = set(duplicates(c["capture_id"] for c in manifest["captures"]))

    writers = {w["writer_id"]: w for w in manifest["writers"]}
    specimens = {s["specimen_id"]: s for s in manifest["specimens"]}
    captures = {c["capture_id"]: c for c in manifest["captures"]}
    duplicate_task_ids = set(duplicates(t["task_id"] for t in protocol["tasks"]))
    for task_id in sorted(duplicate_task_ids):
        issues.append(Issue("DUPLICATE_TASK", task_id,
                            "human release cannot choose between conflicting task definitions with one canonical ID"))
    if duplicate_task_ids:
        releasable = False
    tasks = {t["task_id"]: t for t in protocol["tasks"]}
    sessions = {session["session_index"]: session for session in protocol["session_plan"]}
    scripts = set(protocol["supported_contexts"]["scripts"])
    languages = set(protocol["supported_contexts"]["languages"])
    release_purpose = manifest["release_purpose"]
    release_allowed = purpose_key(release_purpose) in {purpose_key(ref) for ref in protocol["consent_purposes"]}
    if not release_allowed:
        issues.append(Issue("RELEASE_PURPOSE_NOT_IN_PROTOCOL", "release_purpose",
                            f"{release_purpose['purpose_id']}@{release_purpose['purpose_version']} is not a protocol purpose"))

    def collection_permitted(specimen: dict, at: datetime) -> bool:
        """Some protocol purpose permits collecting this page at `at`, directly or through the writer's enrollment."""
        enrollment = ({"kind": "PILOT_ENROLLMENT", "id": writers[specimen["writer_id"]]["enrollment_id"]},)
        return any(
            evaluate_permission(consent, {"kind": "WRITER", "id": specimen["writer_id"]}, ref,
                                {"kind": "SPECIMEN", "id": specimen["specimen_id"]}, at, covering_scopes=enrollment) == "PERMITTED"
            for ref in protocol["consent_purposes"]
        )

    # Each participant writes in one chosen language, so a writer never enters two language cohorts.
    chosen: dict[str, set[str]] = {}
    for s in manifest["specimens"]:
        if s["specimen_id"] not in ambiguous_specimens and s["declared_script"] in scripts and s["declared_language"] in languages:
            chosen.setdefault(s["writer_id"], set()).add(s["declared_language"])
    multilingual = {writer_id for writer_id, found in chosen.items() if len(found) > 1}

    # Two pages claiming one writer/task/session slot leave no unambiguous page for it, whatever the order.
    slots: dict[tuple[str, str, int], list[str]] = {}
    for s in manifest["specimens"]:
        if s["specimen_id"] not in ambiguous_specimens and s["writer_id"] not in ambiguous_writers:
            slots.setdefault((s["writer_id"], s["task_id"], s["session_index"]), []).append(s["specimen_id"])

    included: set[str] = set()
    for s in manifest["specimens"]:
        where = s["specimen_id"]
        if where in ambiguous_specimens or s["writer_id"] in ambiguous_writers:
            continue  # reported as DUPLICATE_ID; never counted
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
        if s["writer_id"] in multilingual:
            issues.append(Issue("WRITER_LANGUAGE_CONFLICT", where,
                                f"{s['writer_id']} has supported pages in {', '.join(sorted(chosen[s['writer_id']]))}"))
            continue
        if s["declared_language"] != task["language"]:
            issues.append(Issue("TASK_LANGUAGE_MISMATCH", where, f"{s['task_id']} is a {task['language']} task"))
            continue
        slot = slots[(s["writer_id"], s["task_id"], s["session_index"])]
        if len(slot) > 1:
            others = f"{len(slot) - 1} other records"
            issues.append(Issue("DUPLICATE_SPECIMEN_IN_SESSION", where, f"same writer/task/session as {others}"))
            continue
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
        if not collection_permitted(s, collected):
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

    # A capture is evidence only when its own provenance, its bytes and its whole repeat chain hold.
    # Array order is never provenance: every exclusion below is decided without it.
    excluded: set[str] = set(ambiguous_captures)
    for c in manifest["captures"]:
        if c["specimen_id"] not in specimens:
            issues.append(Issue("DANGLING_REFERENCE", c["capture_id"], f"unknown specimen {c['specimen_id']}"))
            excluded.add(c["capture_id"])
    known = [c for c in manifest["captures"] if c["capture_id"] not in excluded]
    slots = set(duplicates((c["specimen_id"], c["capture_index"]) for c in known))
    for c in known:
        where = c["capture_id"]
        broken = []
        if (c["specimen_id"], c["capture_index"]) in slots:
            broken.append(Issue("CAPTURE_INDEX_CONFLICT", where, "several captures claim this capture_index, so none is the original"))
        repeat = c["repeat_of_capture_id"]
        if repeat is None and c["capture_index"] != 1:
            broken.append(Issue("REPEAT_WITHOUT_ORIGINAL", where, "every capture after the first names the earlier capture it repeats"))
        page = specimens[c["specimen_id"]]
        captured, written = parse_timestamp(c["captured_at"]), parse_timestamp(page["collected_at"])
        if captured < written:
            broken.append(Issue("CAPTURED_BEFORE_WRITING", where, f"photographed before the page was written at {page['collected_at']}"))
        elif captured > cutoff and written <= cutoff:  # a page written after the cutoff is reported as such
            broken.append(Issue("CAPTURED_AFTER_CUTOFF", where, f"captured at {c['captured_at']}"))
        elif c["specimen_id"] in included and not collection_permitted(page, captured):
            # The photo is when private bytes entered the system: collection must be permitted then too.
            broken.append(Issue("NO_CAPTURE_PERMISSION", where, f"no protocol purpose was permitted at {c['captured_at']}"))
        session = sessions.get(page["session_index"])
        if (repeat is not None or c["capture_index"] != 1) and session is not None and session["repeat_captures"] == "NONE":
            broken.append(Issue("REPEAT_NOT_IN_SESSION_PLAN", where,
                                f"session {session['session_index']} takes no repeat captures"))
        if repeat is not None:
            original = captures.get(repeat)
            if original is None or repeat == where:
                broken.append(Issue("DANGLING_REFERENCE", where, f"repeat_of_capture_id {repeat} is not another capture"))
            elif original["specimen_id"] != c["specimen_id"]:
                broken.append(Issue("REPEAT_CROSSES_SPECIMEN", where, "a repeat photo belongs to the same page"))
            elif (original["capture_index"] >= c["capture_index"]
                  or parse_timestamp(original["captured_at"]) > captured):
                # Pointing only backwards keeps repeat lineage acyclic, with an original at its root.
                broken.append(Issue("REPEAT_NOT_EARLIER", where, f"{repeat} is not an earlier capture of this page"))
        issues += broken
        if broken:
            excluded.add(where)

    # Identical bytes are one photo. Recorded twice for one page, only its earliest capture stands;
    # recorded for several pages, it cannot show which page it is, so none of them does.
    by_hash: dict[str, list[dict]] = {}
    for c in known:
        by_hash.setdefault(c["content_sha256"], []).append(c)
    for group in by_hash.values():
        if len(group) < 2:
            continue
        keep = min(group, key=lambda c: (c["capture_index"], c["capture_id"]))
        one_page = len({c["specimen_id"] for c in group}) == 1
        writers_with_bytes = {specimens[c["specimen_id"]]["writer_id"] for c in group}
        for c in group:
            if one_page and c is keep:
                continue
            others = f"a group of {len(group)} identical byte records"
            code = "DUPLICATE_COUNTED_AS_WRITER" if len(writers_with_bytes) > 1 else "DUPLICATE_CAPTURE_BYTES"
            issues.append(Issue(code, c["capture_id"], f"identical bytes to {others}"))
            excluded.add(c["capture_id"])

    rooted = rooted_nodes({cid: c["repeat_of_capture_id"] for cid, c in captures.items()}, excluded)

    counted: list[str] = []
    counted_capture_ids = []
    for c in known:
        where = c["capture_id"]
        if where in excluded:
            continue  # a capture whose provenance or bytes failed validation is not evidence of anything
        if where not in rooted:
            issues.append(Issue("REPEAT_OF_INVALID_CAPTURE", where, "its repeat chain does not reach a valid original"))
            continue
        if c["specimen_id"] in included:
            counted.append(c["specimen_id"])
            counted_capture_ids.append(c["capture_id"])

    # A specimen evidenced only by someone else's bytes is not evidence of another writer.
    included &= set(counted)
    # Later sessions estimate within-writer variation, so they need the same writer's
    # session-1 specimen for the same task in this release, and come on a later day
    # than every earlier session of that task.
    by_writer_task: dict[tuple[str, str], list[str]] = {}
    for specimen_id in included:
        by_writer_task.setdefault((specimens[specimen_id]["writer_id"], specimens[specimen_id]["task_id"]), []).append(specimen_id)
    for specimen_id in sorted(included, key=lambda i: (specimens[i]["session_index"], i)):
        s = specimens[specimen_id]
        if s["session_index"] == 1:
            continue
        earlier = [specimens[o] for o in by_writer_task[(s["writer_id"], s["task_id"])]
                   if o in included and specimens[o]["session_index"] < s["session_index"]]
        day = parse_timestamp(s["collected_at"]).date()
        if not any(o["session_index"] == 1 for o in earlier):
            issues.append(Issue("SESSION_WITHOUT_BASELINE", specimen_id,
                                f"session {s['session_index']} has no included session-1 {s['task_id']} specimen"))
            included.discard(specimen_id)
        elif any(parse_timestamp(o["collected_at"]).date() >= day for o in earlier):
            issues.append(Issue("SESSION_NOT_AFTER_EARLIER", specimen_id,
                                f"session {s['session_index']} must be written on a later day than the earlier sessions of {s['task_id']}"))
            included.discard(specimen_id)
    summary.writer_ids = tuple(sorted({specimens[s]["writer_id"] for s in included}))
    summary.specimen_ids = tuple(sorted(included))
    summary.capture_ids = tuple(sorted(cid for cid in counted_capture_ids if captures[cid]["specimen_id"] in included))
    summary.writers = len(summary.writer_ids)
    summary.specimens = len(included)
    summary.captures = sum(1 for specimen_id in counted if specimen_id in included)
    capture_counts = Counter(counted)
    for specimen_id in sorted(included):
        s = specimens[specimen_id]
        cohort = summary.by_task.setdefault(s["task_id"], {"writers": 0, "specimens": 0, "captures": 0})
        cohort["specimens"] += 1
        cohort["captures"] += capture_counts[specimen_id]  # repeat photos stay in their page's task cohort
    for task_id, cohort in summary.by_task.items():
        cohort["writers"] = len({specimens[s]["writer_id"] for s in included if specimens[s]["task_id"] == task_id})

    claimed = manifest["claimed_counts"]
    computed = {"writers": summary.writers, "specimens": summary.specimens, "captures": summary.captures}
    for key, value in computed.items():
        if claimed[key] != value:
            issues.append(Issue("COUNT_MISMATCH", f"claimed_counts.{key}", f"claimed {claimed[key]}, lineage supports {value}"))
    return issues, summary


# ------------------------------------------------------- permission evaluation


@dataclass(frozen=True)
class ConsentContext:
    purposes: dict[tuple[str, int], dict]
    notices: dict[tuple[str, int], dict]
    writers: dict[str, dict]
    events: list[dict]
    usable_statuses: frozenset[str] = frozenset({"APPROVED"})
    fixture_mode: bool = False
    valid: list[tuple[int, dict]] = field(default_factory=list)
    event_issues: dict[str, list[str]] = field(default_factory=dict)
    issues: tuple[Issue, ...] = ()
    invalid_writers: frozenset[str] = frozenset()
    authority: dict = field(default_factory=dict)
    policy_sha256: str | None = None
    manifest_sha256: str | None = None


@dataclass(frozen=True, init=False)
class AuthoritativeConsentContext(ConsentContext):
    """Only collection_consent_context can construct the human-release context."""

    def __new__(cls, *_args, **_kwargs):
        raise TypeError("construct authoritative consent from a compiled policy and ledger")


def build_context(registry: dict, scenario: dict, *, fixture_mode: bool = False) -> ConsentContext:
    """Index a scenario's event log.

    Only APPROVED purposes can grant anything. fixture_mode additionally lets
    DRAFT purposes run so synthetic scenarios can exercise the rules before
    any owner approval exists; it must never be used for real decisions.
    """
    problems = input_tree_issues(registry, "registry") + input_tree_issues(scenario, "scenario")
    if not isinstance(registry, dict) or not isinstance(scenario, dict):
        problems.append(Issue("SCHEMA", "context", "registry and scenario must be objects"))
    if problems:
        return ConsentContext({}, {}, {}, [], fixture_mode=fixture_mode, issues=tuple(problems))
    schema = SchemaSet()
    problems += schema.validate(registry, "purpose-registry.schema.json")
    for name in ("writers", "notices", "events"):
        if not isinstance(scenario.get(name), list):
            problems.append(Issue("SCHEMA", name, "context requires an array"))
    if problems:
        return ConsentContext({}, {}, {}, [], fixture_mode=fixture_mode, issues=tuple(problems))
    for name, rows, spec in (("writers", scenario.get("writers", []), "consent-scenario.schema.json#/$defs/writer"),
                              ("notices", scenario.get("notices", []), "consent-scenario.schema.json#/$defs/notice_window"),
                              ("events", scenario.get("events", []), "consent-event.schema.json")):
        found = input_tree_issues(rows, name)
        problems += found
        if not found:
            for index, row in enumerate(rows):
                problems += schema.validate(row, spec, f"{name}[{index}]")
    if problems:
        return ConsentContext({}, {}, {}, [], fixture_mode=fixture_mode, issues=tuple(problems))
    extras = scenario.get("extra_purposes", [])
    if not isinstance(extras, list):
        problems.append(Issue("SCHEMA", "extra_purposes", "extra purposes must be an array"))
    else:
        for index, row in enumerate(extras):
            problems += schema.validate(row, "purpose-registry.schema.json#/$defs/purpose", f"extra_purposes[{index}]")
    if problems:
        return ConsentContext({}, {}, {}, [], fixture_mode=fixture_mode, issues=tuple(problems))
    purpose_rows = [*registry["purposes"], *extras]
    indexes = []
    for rows, key, code, name in (
        (purpose_rows, purpose_key, "DUPLICATE_PURPOSE", "purposes"),
        (scenario["notices"], lambda n: (n["notice_id"], n["version"]), "DUPLICATE_NOTICE", "notices"),
        (scenario["writers"], lambda w: w["writer_id"], "DUPLICATE_WRITER", "writers"),
    ):
        result = unique_index(rows, key, code=code, where=name)
        problems += result.issues
        indexes.append(result.value or {})
    purposes, notices, writers = indexes
    problems += notice_window_issues(scenario["notices"], "context")
    for notice in scenario["notices"]:
        problems += listed_purpose_issues(notice["purposes"], str((notice["notice_id"], notice["version"])))
    invalid_writers, authority = set(), {}
    for writer in scenario["writers"]:
        found = account_link_issues(writer)
        if found:
            invalid_writers.add(writer["writer_id"])
        else:
            authority[writer["writer_id"]] = tuple(sorted(account_links(writer), key=lambda link: link[1]))
    context = ConsentContext(
        purposes=freeze_json(purposes), notices=freeze_json(notices), writers=freeze_json(writers),
        events=freeze_json(scenario["events"]),
        usable_statuses=frozenset({"APPROVED", "DRAFT"} if fixture_mode else {"APPROVED"}),
        fixture_mode=fixture_mode, issues=tuple(problems), invalid_writers=frozenset(invalid_writers),
        authority=freeze_json(authority),
    )
    valid, event_issues = [], {}
    repeated = set(duplicates(e["event_id"] for e in context.events))
    if repeated:
        problems += [Issue("DUPLICATE_EVENT_ID", eid, "ambiguous ledger identity; cannot discard a possible withdrawal")
                     for eid in sorted(repeated)]
    for index, event in enumerate(context.events):
        codes = event_validity(event, context)
        if event["event_id"] in repeated:
            codes = sorted(set(codes) | {"DUPLICATE_EVENT_ID"})
        event_issues[event["event_id"]] = codes
        if (codes and event["event_type"] in {"DENY", "WITHDRAW"} and event_actor_authorized(event, context)):
            problems.append(Issue("AMBIGUOUS_RESTRICTION", event["event_id"],
                                  "an authorized restrictive choice cannot be dropped to revive an older grant"))
        if not codes:
            valid.append((index, event))
    return replace(context, valid=freeze_json(valid), event_issues=freeze_json(event_issues), issues=tuple(problems))


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


def account_links(writer: dict) -> list[tuple[str, datetime, datetime | None]]:
    """Every account ever linked to the writer, with when the link started and (for earlier links) ended."""
    links = [(link["account_id"], parse_timestamp(link["linked_at"]), parse_timestamp(link["unlinked_at"]))
             for link in writer["previous_account_links"]]
    if writer["self_account_id"] is not None and writer["self_account_linked_at"] is not None:
        links.append((writer["self_account_id"], parse_timestamp(writer["self_account_linked_at"]), None))
    return links


def account_link_issues(writer: dict) -> list[Issue]:
    invalid = (writer["self_account_id"] is None) != (writer["self_account_linked_at"] is None)
    spans = sorted(account_links(writer), key=lambda link: link[1])
    invalid |= any(end is not None and end <= start for _account, start, end in spans)
    invalid |= any(end is None or end > next_start
                   for (_a, _s, end), (_b, next_start, _e) in zip(spans, spans[1:]))
    return [Issue("ACCOUNT_LINK_INCONSISTENT", writer["writer_id"], "authority intervals are inconsistent/overlapping")] if invalid else []


def has_authority(event: dict, context: ConsentContext) -> bool:
    actor, subject = event["actor"], event["subject"]
    if subject["kind"] == "WRITER" and subject["id"] in context.invalid_writers:
        return False
    if subject["kind"] == "ACCOUNT":
        return actor["kind"] == "ACCOUNT" and actor["id"] == subject["id"]
    writer = context.writers.get(subject["id"])
    if writer is None:
        return False
    if actor["kind"] == "ACCOUNT":
        # Authority is judged as of the event against the link then in effect: linking an account later never
        # revives an uploader's choice, and relinking never voids a choice the earlier account made.
        recorded = parse_timestamp(event["recorded_at"])
        return any(account_id == actor["id"] and start <= recorded and (end is None or recorded < end)
                   for account_id, start, end in context.authority.get(subject["id"], ()))
    if actor["kind"] == "PILOT_PARTICIPANT":
        return actor["id"] == writer["writer_id"]
    return False


def event_actor_authorized(event: dict, context: ConsentContext) -> bool:
    """One actor-authority predicate for validation AND fail-closed restrictions.

    SYSTEM/support inputs must already come from authenticated application ports;
    the reference ledger records their verified source, not a public identity claim.
    """
    if event["event_type"] != "WITHDRAW" or event["actor"]["kind"] in {"ACCOUNT", "PILOT_PARTICIPANT"}:
        return has_authority(event, context)
    derived = event["derived_from"] or {}
    if event["actor"]["kind"] == "SUPPORT_STAFF":
        return derived.get("kind") == "SUPPORT_REQUEST" and event["capture_method"] == "VERIFIED_REQUEST"
    return event["actor"]["kind"] == "SYSTEM" and derived.get("kind") in SYSTEM_WITHDRAWAL_SOURCES


def event_validity(event: dict, context: ConsentContext) -> list[str]:
    """Codes that make an event ineffective. An invalid event never changes permission state."""
    codes: list[str] = []
    kind = event["event_type"]
    purpose = context.purposes.get(purpose_key(event["purpose"]))
    if purpose is None:
        return ["UNKNOWN_PURPOSE"]
    if kind == "GRANT" and purpose["status"] == "RETIRED":
        # Grants recorded while the purpose was offered keep their history; none are taken after retirement.
        retired = retired_at(purpose)
        if retired is None or parse_timestamp(event["recorded_at"]) >= retired:
            codes.append("PURPOSE_RETIRED")
    elif kind == "GRANT" and purpose["status"] not in context.usable_statuses:
        codes.append("PURPOSE_NOT_APPROVED" if purpose["status"] == "DRAFT" else "PURPOSE_NOT_OFFERED")
    if event["subject"]["kind"] != purpose["subject_kind"]:
        codes.append("SUBJECT_KIND_MISMATCH")
    if event["subject"]["kind"] == "WRITER" and event["subject"]["id"] not in context.writers:
        codes.append("UNKNOWN_WRITER")
    scope = event["scope"]
    # A denial or withdrawal may always cover the whole subject: it only ever narrows what is permitted.
    restrictive_wide = kind in {"DENY", "WITHDRAW"} and scope["kind"] == "SUBJECT_WIDE"
    if (scope["kind"] not in purpose["grant_scopes"] and not restrictive_wide
            and not (kind == "WITHDRAW" and purpose["status"] not in OFFERED)):
        codes.append("SCOPE_NOT_ALLOWED")
    if scope["kind"] == "SUBJECT_WIDE" and scope["id"] != event["subject"]["id"]:
        codes.append("SCOPE_SUBJECT_MISMATCH")
    codes += notice_window_codes(event, context)

    # Only grants may be scheduled; a denial or withdrawal always takes effect when recorded (effective_time).
    if kind == "GRANT" and parse_timestamp(event["effective_at"]) < parse_timestamp(event["recorded_at"]):
        codes.append("BACKDATED_EVENT")

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
        if purpose["status"] in {"APPROVED", "RETIRED"} and not purpose_approval_complete(purpose):
            codes.append("PURPOSE_NOT_APPROVED")
        elif purpose["status"] in {"APPROVED", "RETIRED"} and not approved_by(purpose, event["recorded_at"]):
            codes.append("GRANTED_BEFORE_APPROVAL")
    if not event_actor_authorized(event, context):
        codes.append("NO_AUTHOR_AUTHORITY" if kind in {"GRANT", "DENY"} and purpose["requires_author_authority"] else "NO_AUTHORITY")
    return sorted(set(codes))


def effective_time(event: dict) -> datetime:
    """When an event changes permission: restrictive choices apply as soon as they are recorded."""
    field = "effective_at" if event["event_type"] == "GRANT" else "recorded_at"
    return parse_timestamp(event[field])


def scope_covers(event_scope: dict, query_scope: dict, subject: dict, covering_scopes: tuple[dict, ...] = ()) -> bool:
    if event_scope == query_scope or event_scope in covering_scopes:
        return True
    return event_scope["kind"] == "SUBJECT_WIDE" and event_scope["id"] == subject["id"] and query_scope["kind"] != "SUBJECT_WIDE"


def evaluate_permission(
    context: ConsentContext, subject: dict, purpose_ref: dict, scope: dict, at: datetime,
    covering_scopes: tuple[dict, ...] = (),
) -> str:
    """The most recently recorded valid event in effect at `at` wins. covering_scopes are broader scopes the caller vouches
    contain the query scope (e.g. a specimen's pilot enrollment)."""
    if context.issues:
        return "INVALID_CONTEXT"
    if subject["kind"] == "WRITER" and subject["id"] in context.invalid_writers:
        return "INVALID_AUTHORITY"
    purpose = context.purposes.get(purpose_key(purpose_ref))
    if purpose is not None and purpose["status"] == "RETIRED":
        # History before retirement is evaluated as it was; from retirement on nothing is permitted.
        retired = retired_at(purpose)
        if retired is None or at >= retired:
            return "RETIRED"
    elif purpose is None or purpose["status"] not in OFFERED:
        return "NOT_OFFERED"
    elif purpose["status"] not in context.usable_statuses:
        return "NOT_APPROVED"
    if purpose["status"] in {"APPROVED", "RETIRED"} and not purpose_approval_complete(purpose):
        return "NOT_APPROVED"  # a status edit without its decisions, gate decisions or unchanged content
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
        and effective_time(event) <= at
    ]
    if not candidates:
        return "NOT_ASKED"
    # Among events already in effect, the choice recorded last wins: a scheduled grant
    # never overrides a denial or withdrawal the subject recorded after it.
    _index, latest = max(
        candidates,
        key=lambda item: (
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


def registry_notice_windows(notices_doc: dict | None, purposes: dict[tuple[str, int], dict] | None = None) -> list[dict]:
    """Windows of the notices the authoritative registry actually put in effect.

    With `purposes`, a notice counts only if every purpose it lists had a
    complete approval before the notice took effect: a notice that also offers
    a draft purpose is invalid as a whole, not valid for its approved part.
    """
    if notices_doc is None:
        return []
    # Historical windows are all-or-nothing: no contradictory duplicate, overlap,
    # bad copy or invalid lifecycle transition is authoritative.
    if purposes is None:
        return []
    if SchemaSet().validate(notices_doc, "notice-registry.schema.json") or check_notices(notices_doc, purposes):
        return []
    return [{key: n[key] for key in ("notice_id", "version", "effective_from", "effective_until", "purposes")}
            for n in notices_doc["notices"] if n["status"] != "DRAFT"]


def collection_consent_context(registry: dict, manifest: dict, consent_log: dict, *, fixture_mode: bool = False,
                               notices: dict | None = None) -> ConsentContext:
    """Consent ledger for a collection manifest: pilot writers have no accounts.

    Outside fixture mode, notice windows come only from the authoritative
    notice registry (`notices`, i.e. notices.json); windows a ledger describes
    for itself are ignored, so a fabricated notice cannot make a grant valid.
    """
    policy = registry if isinstance(registry, ReleasePolicy) else None
    if policy is not None:
        registry, notices = policy.documents["purposes"], policy.documents["notices"]
        if fixture_mode:
            raise ValueError("a compiled human policy cannot use fixture mode")
    problems = []
    schema = SchemaSet()
    for name, value, spec in (("manifest", manifest, "collection-manifest.schema.json"),
                               ("registry", registry, "purpose-registry.schema.json")):
        found = input_tree_issues(value, name)
        problems += found or schema.validate(value, spec, name)
    problems += input_tree_issues(consent_log, "consent_log")
    if not isinstance(consent_log, dict) or not isinstance(consent_log.get("events"), list):
        problems.append(Issue("SCHEMA", "consent_log.events", "a ledger object with an event array is required"))
    if fixture_mode and (not isinstance(consent_log, dict) or not isinstance(consent_log.get("notices"), list)):
        problems.append(Issue("SCHEMA", "consent_log.notices", "synthetic fixtures require notice windows"))
    if problems:
        return ConsentContext({}, {}, {}, [], fixture_mode=fixture_mode, issues=tuple(problems))
    if fixture_mode and not manifest["synthetic"]:
        raise ValueError("fixture mode is only for synthetic manifests")
    result = unique_index(registry["purposes"], purpose_key, code="DUPLICATE_PURPOSE", where="purposes")
    windows = consent_log["notices"] if fixture_mode else registry_notice_windows(notices, result.value)
    writers = [
        {"writer_id": w["writer_id"], "self_account_id": None, "self_account_linked_at": None,
         "previous_account_links": [], "adult_eligibility": w["adult_eligibility"]}
        for w in manifest["writers"]
    ]
    scenario = {"notices": windows, "writers": writers, "events": consent_log["events"]}
    context = build_context(registry, scenario, fixture_mode=fixture_mode)
    if policy is not None:
        authoritative = object.__new__(AuthoritativeConsentContext)
        for item in fields(ConsentContext):
            object.__setattr__(authoritative, item.name, getattr(context, item.name))
        object.__setattr__(authoritative, "policy_sha256", policy.fingerprint)
        object.__setattr__(authoritative, "manifest_sha256", digest(manifest))
        return authoritative
    return context


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
        issues += account_link_issues(writer)
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

    registry = loaded["purposes.json"]
    documents = {"purposes": registry, "notices": loaded["notices.json"], "retention": loaded["retention.json"],
                 "lineage": loaded["deletion_lineage.json"], "sources": loaded["source_rights.json"],
                 "gate": loaded["pilot_gate.json"], "protocol": protocol}
    policy_issues = policy_document_issues(documents, collection_dir=collection_dir, schemas=schemas, tasks_json=tasks_json)
    report.issues += policy_issues
    report.lines.append(f"{'FAIL' if policy_issues else 'PASS'} policy documents: same complete pipeline as human release")
    if policy_issues:
        return report

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
            actual, _summary = check_fixture_collection_manifest(fixture["manifest"], protocol, consent, publish_at=publish_at)
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
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
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
