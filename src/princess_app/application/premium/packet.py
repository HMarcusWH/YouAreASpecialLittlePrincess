"""Compile one bounded, immutable Premium packet from a saved report (T15).

Only questions the model is meant to answer (``model_call_role == ANSWER``)
and whose required inputs exist for this report enter the packet; every other
question in the pack is recorded as an explicit omission with a reason.
FIXED questions offer their reviewed value set. DYNAMIC questions need a
registered deterministic candidate producer; none is implemented yet, so they
are omitted rather than offered an empty or invented candidate list.

The model input carries the report's present facts, question text, candidate
labels, soft-field limits and deterministic limitations, but no owner, report
or asset identifiers. It is digested so the provider request
can be bound to exactly what was compiled.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from princess_contracts import ValidatedDocument, canonical_digest, compile_document
from princess_contracts import generated as g

from ...domain.analysis import rfc3339
from ...ports.base import InvalidInput, require_opaque_id
from .database import InterpretationDatabase
from .prompt import PROMPT_VERSION

DEFAULT_PACK = "PREMIUM_INDIVIDUAL_GRAPHIC_V1"
PRESENT = frozenset({"READY", "UNCALIBRATED"})
ANSWER_STATES = ("ANSWERED", "OBSERVED_ABSENT", "NOT_ASSESSABLE", "NOT_APPLICABLE", "CONFLICTING_EVIDENCE",
                 "NO_ELIGIBLE_CANDIDATE")
# Produced by the compiler itself when the question's producer yields candidates.
CANDIDATE_INPUT = "CURRENT_REPORT_CANDIDATES"


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    kind: str
    label_key: str
    label_en: str
    support_fact_ids: tuple[str, ...] = ()


# A deterministic producer receives the report's present facts by fact ID and
# returns eligible candidates (possibly none). Registered per T26 generator ID.
CandidateProducer = Callable[[Mapping[str, Mapping[str, Any]]], Sequence[Candidate]]


@dataclass(frozen=True)
class Omission:
    item_id: str  # a question or soft-field ID
    reason: str
    detail: str | None = None


class NotApplicable(Exception):
    """No bounded packet can be built for this report; no provider call is made."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class PacketCompilation:
    packet: ValidatedDocument
    model_input: Mapping[str, Any]
    model_input_digest: str
    omissions: tuple[Omission, ...]
    # Soft fields whose required support exists: field_id -> (max_characters, max_sentences).
    soft_field_limits: Mapping[str, tuple[int, int]]


def available_inputs(report: Mapping[str, Any], image_asset_id: str | None) -> frozenset[str]:
    """Inputs this deployment can actually supply. Example sets, rubrics,
    graphic signs, outliers and traditional candidates have no producer yet."""
    inputs = set()
    if image_asset_id is not None:
        inputs.add("AUTHORIZED_IMAGE")
        if report.get("evidence_bundle_id") is not None:
            inputs.add("IDENTIFIED_EVIDENCE_REGION")
    if limitations(report):
        inputs.add("SUPPLIED_LIMITATIONS")
    return frozenset(inputs)


def limitations(report: Mapping[str, Any]) -> list[dict[str, str]]:
    """Deterministic limitations the model may explain (never invent)."""
    items = [{"limitation_id": n["notice_id"], "key": n["localization_key"]} for n in report["notices"]
             if n["class"] in ("PROXY", "REFERENCE", "TRADITIONAL")]
    items += [{"limitation_id": f["fact_id"], "key": f"missing:{f['quality']['missing_reason'] or 'unspecified'}"}
              for f in report["facts"] if f["availability"] == "MISSING"]
    return items


def compile_packet(report: ValidatedDocument, db: InterpretationDatabase, *, packet_id: str, created_at: datetime,
                   image_asset_id: str | None, pack_id: str = DEFAULT_PACK,
                   producers: Mapping[str, CandidateProducer] | None = None) -> PacketCompilation:
    if report.schema_name != "ReportDocument":
        raise InvalidInput("expected_report_document")
    require_opaque_id(packet_id, "packet_id")
    if image_asset_id is not None:
        require_opaque_id(image_asset_id, "image_asset_id")
    pack = db.packs.get(pack_id)
    if pack is None:
        raise InvalidInput("unknown_question_pack")
    producers = producers or {}
    doc = report.to_dict()
    facts = {f["fact_id"]: f for f in doc["facts"] if f["availability"] in PRESENT}
    if not facts:
        raise NotApplicable("no_present_facts")
    present_features = {f["feature_id"]: f["fact_id"] for f in facts.values()}
    inputs = available_inputs(doc, image_asset_id)

    omissions: list[Omission] = []
    questions: list[dict[str, Any]] = []
    candidates: dict[str, Candidate] = {}
    for question_id in pack["question_ids"]:
        spec = db.questions[question_id]
        if spec.model_call_role != "ANSWER":
            omissions.append(Omission(question_id, "not_model_answered", spec.answer_owner))
            continue
        missing = [i for i in spec.required_inputs if i != CANDIDATE_INPUT and i not in inputs]
        if missing:
            omissions.append(Omission(question_id, "missing_input", missing[0]))
            continue
        if spec.selection_domain == "FIXED":
            offered = [Candidate(f"{spec.value_set_id}.{c.value_id}", "FIXED_VALUE", c.label_key, c.label_en)
                       for c in db.value_sets[spec.value_set_id]]
        else:
            producer = producers.get(spec.generator_id or "")
            if producer is None:
                omissions.append(Omission(question_id, "candidate_generator_not_implemented", spec.generator_id))
                continue
            offered = list(producer(facts))
            for candidate in offered:
                if not set(candidate.support_fact_ids) <= set(facts):
                    raise InvalidInput("candidate_support_outside_report")
        if not offered:
            omissions.append(Omission(question_id, "no_eligible_candidate", spec.generator_id))
            continue
        for candidate in offered:
            if candidates.setdefault(candidate.candidate_id, candidate) != candidate:
                raise InvalidInput("conflicting_candidate_definition")
        support = sorted({present_features[f] for f in spec.mapped_feature_ids if f in present_features})
        questions.append({"question_id": question_id, "selection_domain": spec.selection_domain,
                          "cardinality": spec.cardinality, "candidate_ids": [c.candidate_id for c in offered],
                          "support_fact_ids": support})
    if not questions:
        raise NotApplicable("no_applicable_questions")

    used = sorted({cid for q in questions for cid in q["candidate_ids"]})
    packet = {
        "contract_version": g.CONTRACT_VERSION, "packet_id": packet_id, "owner_id": doc["analysis"]["owner_id"],
        "report_id": doc["report_id"], "report_revision": doc["revision"], "report_digest": report.digest,
        "created_at": rfc3339(created_at), "locale": doc["locale"],
        "interpretation_database_version": db.version, "interpretation_database_sha256": db.sha256,
        "question_pack_id": pack_id, "candidate_policy_version": db.candidate_policy_version,
        "prompt_version": PROMPT_VERSION, "output_schema_version": pack["output_schema_version"],
        "soft_field_ids": list(pack["soft_field_ids"]), "allowed_fact_ids": sorted(facts),
        "questions": questions,
        "candidates": [{"candidate_id": cid, "kind": candidates[cid].kind, "label_key": candidates[cid].label_key,
                        "support_fact_ids": list(candidates[cid].support_fact_ids)} for cid in used],
        "image_asset_id": image_asset_id,
    }
    compiled = compile_document("PremiumPacket", packet)
    if compiled.value is None:
        raise InvalidInput("packet_contract_rejected", detail=compiled.issues[0].code)

    soft = {}
    for fid in pack["soft_field_ids"]:
        missing = [r for r in db.soft_fields[fid].required_support if r not in inputs]
        if missing:
            omissions.append(Omission(fid, "missing_support", missing[0]))
        else:
            soft[fid] = db.soft_fields[fid]
    # Data minimization: the provider sees what it needs to answer, not owner,
    # report or asset identifiers; the full packet stays bound by digest here.
    model_input = {
        "packet_id": packet_id, "locale": doc["locale"], "output_schema_version": pack["output_schema_version"],
        "allowed_fact_ids": sorted(facts),
        "facts": [{"fact_id": f["fact_id"], "feature_id": f["feature_id"], "value": f["value"], "unit": f["unit"],
                   "availability": f["availability"], "evidence_class": f["evidence_class"]}
                  for _, f in sorted(facts.items())],
        "questions": [{"question_id": q["question_id"], "text": db.questions[q["question_id"]].prompt_text_en,
                       "cardinality": q["cardinality"],
                       "candidates": [{"candidate_id": cid, "label": candidates[cid].label_en}
                                      for cid in q["candidate_ids"]],
                       "support_fact_ids": q["support_fact_ids"]} for q in questions],
        "soft_fields": [{"field_id": s.field_id, "instruction": s.prompt_text_en,
                         "max_characters": s.max_characters, "max_sentences": s.max_sentences}
                        for s in soft.values()],
        "limitations": limitations(doc) if "SUPPLIED_LIMITATIONS" in inputs else [],
        "answer_states": list(ANSWER_STATES),
    }
    return PacketCompilation(compiled.value, model_input, canonical_digest(model_input), tuple(omissions),
                             {fid: (s.max_characters, s.max_sentences) for fid, s in soft.items()})


__all__ = ["ANSWER_STATES", "Candidate", "CandidateProducer", "DEFAULT_PACK", "NotApplicable", "Omission",
           "PacketCompilation", "available_inputs", "compile_packet"]
