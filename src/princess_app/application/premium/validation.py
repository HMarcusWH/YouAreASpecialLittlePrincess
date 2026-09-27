"""Per-request strict output schema and output validation (T15).

The schema is compiled from the frozen packet: every answer and soft field is
an exact ``anyOf`` branch with enums for its own question, candidates and
allowed fact IDs, all properties required and no additional properties. A
strict structured-output provider therefore cannot even encode a foreign
candidate or support ID. The same output is still validated here, because a
syntactically valid response is necessary, not sufficient:

1. the PremiumOutput contract and ``validate_premium_output`` (exact question
   set, candidate confinement, cardinality, support escape, soft-field bounds);
2. text policy on every prose/soft field: no digits or numeric words (numbers
   render from saved facts), no links or markup, the T26 sentence limit, and a
   screen for prohibited consequential inference classes;
3. soft fields only where their required support existed in this packet.

The keyword screen is a guardrail, not semantic correctness; T16 owns
human/adversarial evaluation.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from princess_contracts import (
    ContractIssue,
    ValidatedDocument,
    ValidationResult,
    compile_document,
    validate_premium_output,
)
from princess_contracts import generated as g

from .packet import ANSWER_STATES, PacketCompilation

MAX_PROSE = 600
NON_ANSWERED = tuple(s for s in ANSWER_STATES if s != "ANSWERED")

_DIGITS = re.compile(r"[0-9%‰]|[٠-٩۰-۹०-९０-９]")
# Cardinals and rates only: "one", "half" or "double" are too often descriptive
# ("one of", "double loops"), and Swedish "en"/"ett" are articles.
_NUMBER_WORDS = re.compile(
    r"\b(zero|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|"
    r"hundred|thousand|million|percent|percentage|percentile|per\s?cent|"
    r"noll|två|fyra|fem|sju|åtta|nio|tio|hundra|tusen|procent|percentil)\b", re.IGNORECASE)
_LINK_OR_MARKUP = re.compile(r"(https?:|www\.|\w+\.(?:com|net|org|io|se)\b|<[^>]*>|\]\(|javascript:|data:)",
                             re.IGNORECASE)
_PROHIBITED = re.compile(
    r"\b(diagnos\w*|disorder\w*|adhd|autis\w*|dyslexi\w*|depress\w*|anxiety|schizo\w*|bipolar|psychopath\w*|"
    r"narcissis\w*|mental(?:ly)? ill\w*|illness|disease|intelligen\w*|iq|genius|stupid\w*|"
    r"criminal\w*|dishonest\w*|liar|lying|deceptive|deception|trustworth\w*|untrustworth\w*|"
    r"hire|hiring|employab\w*|job candidate|suitable for|compatib\w*|soulmate|divorce|cheat\w*|"
    r"moral(?:ly)?|immoral|evil)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"[.!?…]+(?:\s|$)")


def answer_support(packet: Mapping[str, Any]) -> dict[str, list[str]]:
    """Facts an answer may cite: its question's mapped facts plus the support
    of the candidates offered for it, never the whole packet."""
    candidate_support = {c["candidate_id"]: c["support_fact_ids"] for c in packet["candidates"]}
    return {q["question_id"]: sorted(set(q["support_fact_ids"]).union(
        *(candidate_support.get(cid, ()) for cid in q["candidate_ids"]))) for q in packet["questions"]}


def output_schema(compilation: PacketCompilation) -> dict[str, Any]:
    packet = compilation.packet.to_dict()
    facts = packet["allowed_fact_ids"]
    support = answer_support(packet)

    def ids(values: list[str], max_items: int) -> dict[str, Any]:
        if not values:
            return {"type": "array", "items": {"type": "string"}, "maxItems": 0}
        return {"type": "array", "items": {"type": "string", "enum": list(values)}, "maxItems": max_items,
                "uniqueItems": True}

    def answer(q: Mapping[str, Any]) -> dict[str, Any]:
        cap = 1 if q["cardinality"] == "SINGLE" else len(q["candidate_ids"])
        return {"type": "object", "additionalProperties": False,
                "required": ["question_id", "answer_state", "selected_candidate_ids", "support_fact_ids", "prose"],
                "properties": {
                    "question_id": {"type": "string", "enum": [q["question_id"]]},
                    "answer_state": {"type": "string", "enum": list(ANSWER_STATES)},
                    "selected_candidate_ids": ids(list(q["candidate_ids"]), cap),
                    "support_fact_ids": ids(support[q["question_id"]], min(len(support[q["question_id"]]), 32)),
                    "prose": {"anyOf": [{"type": "string", "maxLength": MAX_PROSE}, {"type": "null"}]}}}

    def soft(field_id: str, max_chars: int) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": False, "required": ["field_id", "text", "support_fact_ids"],
                "properties": {"field_id": {"type": "string", "enum": [field_id]},
                               "text": {"type": "string", "maxLength": max_chars},
                               "support_fact_ids": ids(facts, min(len(facts), 32))}}

    questions = packet["questions"]
    limits = compilation.soft_field_limits
    soft_items: dict[str, Any] = ({"anyOf": [soft(fid, lim[0]) for fid, lim in limits.items()]}
                                  if limits else {"type": "object"})
    return {
        "type": "object", "additionalProperties": False,
        "required": ["contract_version", "packet_id", "output_schema_version", "answers", "soft_fields"],
        "properties": {
            "contract_version": {"type": "string", "enum": [g.CONTRACT_VERSION]},
            "packet_id": {"type": "string", "enum": [packet["packet_id"]]},
            "output_schema_version": {"type": "string", "enum": [packet["output_schema_version"]]},
            "answers": {"type": "array", "minItems": len(questions), "maxItems": len(questions),
                        "items": {"anyOf": [answer(q) for q in questions]}},
            "soft_fields": {"type": "array", "maxItems": len(limits), "items": soft_items},
        },
    }


def _issue(code: str, path: str, message: str) -> ContractIssue:
    return ContractIssue(code, path, message)


def text_issues(text: str, path: str, *, max_sentences: int | None = None) -> list[ContractIssue]:
    issues = []
    if _DIGITS.search(text) or _NUMBER_WORDS.search(text):
        issues.append(_issue("NEW_NUMERIC_CLAIM", path, "numbers render from saved facts, never model text"))
    if _LINK_OR_MARKUP.search(text):
        issues.append(_issue("LINK_OR_MARKUP", path, "no links, markup or code in report text"))
    if _PROHIBITED.search(text):
        issues.append(_issue("PROHIBITED_INFERENCE", path, "consequential or diagnostic inference is out of scope"))
    if any(ord(ch) < 32 and ch not in "\n" for ch in text):
        issues.append(_issue("CONTROL_CHARACTER", path, "control characters are not allowed"))
    if max_sentences is not None and len(_SENTENCE_END.findall(text.strip() + " ")) > max_sentences:
        issues.append(_issue("TOO_MANY_SENTENCES", path, "text exceeds the reviewed sentence limit"))
    return issues


def validate_output(compilation: PacketCompilation, raw: Any) -> ValidationResult[ValidatedDocument]:
    compiled = compile_document("PremiumOutput", raw)
    if compiled.value is None:
        return compiled
    output = compiled.value
    issues = list(validate_premium_output(compilation.packet, output))
    data = output.to_dict()
    support = answer_support(compilation.packet.to_dict())
    for i, answer in enumerate(data["answers"]):
        path = f"/answers/{i}"
        if not set(answer["support_fact_ids"]) <= set(support.get(answer["question_id"], ())):
            issues.append(_issue("ANSWER_SUPPORT_OUTSIDE_QUESTION", f"{path}/support_fact_ids",
                                 "an answer cites only its own question's facts and candidate support"))
        prose = answer["prose"]
        if answer["answer_state"] != "ANSWERED" and prose:
            issues.append(_issue("NONANSWERED_PROSE", f"{path}/prose", "unanswered states carry no text"))
        if prose is not None:
            if len(prose) > MAX_PROSE:
                issues.append(_issue("PROSE_TOO_LONG", f"{path}/prose", "answer prose exceeds its bound"))
            issues.extend(text_issues(prose, f"{path}/prose", max_sentences=2))
        if answer["answer_state"] == "ANSWERED" and not answer["selected_candidate_ids"]:
            issues.append(_issue("ANSWERED_WITHOUT_CANDIDATE", path,
                                 "a selector question is answered only by one of its frozen candidates"))
    for i, field in enumerate(data["soft_fields"]):
        path = f"/soft_fields/{i}"
        limits = compilation.soft_field_limits.get(field["field_id"])
        if limits is None:
            issues.append(_issue("SOFT_FIELD_UNSUPPORTED", f"{path}/field_id",
                                 "soft field's required support was not supplied in this packet"))
            continue
        if len(field["text"]) > limits[0]:
            issues.append(_issue("SOFT_FIELD_TOO_LONG", f"{path}/text", "soft field exceeds its bound"))
        issues.extend(text_issues(field["text"], f"{path}/text", max_sentences=limits[1]))
    if issues:
        return ValidationResult(None, tuple(issues))
    return compiled


__all__ = ["MAX_PROSE", "answer_support", "output_schema", "text_issues", "validate_output"]
