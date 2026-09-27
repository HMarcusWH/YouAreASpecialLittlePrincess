"""Read-only view of the compiled T26 interpretation database.

The artifact is loaded from bytes whose SHA-256 must equal the digest pinned in
the generated contracts, so a packet can never be compiled from a drifted or
locally edited database. Nothing here activates T26: ``runtime_activation``
is reported as stored and callers decide what an inactive database permits.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from princess_contracts import generated as g

from ...ports.base import PermanentFailure

DEFAULT_PATH = Path(__file__).resolve().parents[4] / "schema" / "premium_interpretation_database_v1.json"


@dataclass(frozen=True)
class Choice:
    value_id: str
    label_key: str
    label_en: str


@dataclass(frozen=True)
class QuestionSpec:
    question_id: str
    selector_id: str
    prompt_text_en: str
    answer_owner: str
    model_call_role: str
    selection_domain: str
    cardinality: str
    required_inputs: tuple[str, ...]
    value_set_id: str | None
    generator_id: str | None
    mapped_feature_ids: tuple[str, ...]


@dataclass(frozen=True)
class SoftFieldSpec:
    field_id: str
    prompt_text_en: str
    max_characters: int
    max_sentences: int
    allow_new_numbers: bool
    required_support: tuple[str, ...]


class InterpretationDatabase:
    def __init__(self, data: Mapping[str, Any], sha256: str) -> None:
        self.sha256 = sha256
        self.version: str = data["version"]
        self.runtime_activation: bool = bool(data["runtime_activation"])
        self.candidate_policy_version: str = g.T26_AUTHORITY["candidate_policy_version"]
        value_sets = {v["value_set_id"]: tuple(Choice(x["value_id"], x["label_key"], x["label_en"])
                                               for x in v["values"]) for v in data["selector_value_sets"]}
        selectors = {s["selector_id"]: s for s in data["selector_definitions"]}
        generator_for = {m["selector_id"]: m["generator_id"] for m in data["selector_generator_map"]}
        mappings: dict[str, list[str]] = {}
        for m in data["feature_mappings"]:
            mappings.setdefault(m["selector_id"], []).append(m["canonical_feature_id"])
        questions = {}
        for q in data["question_definitions"]:
            s = selectors[q["selector_id"]]
            generator = generator_for.get(s["selector_id"])
            questions[q["question_id"]] = QuestionSpec(
                question_id=q["question_id"], selector_id=s["selector_id"], prompt_text_en=q["prompt_text_en"],
                answer_owner=q["answer_owner"], model_call_role=q["model_call_role"],
                selection_domain=s["selection_domain"], cardinality=s["cardinality"],
                required_inputs=tuple(q["required_inputs"]), value_set_id=s["value_set_id"],
                generator_id=generator,
                mapped_feature_ids=tuple(mappings.get(s["selector_id"], ())))
        self.questions: Mapping[str, QuestionSpec] = MappingProxyType(questions)
        self.value_sets: Mapping[str, tuple[Choice, ...]] = MappingProxyType(value_sets)
        self.soft_fields: Mapping[str, SoftFieldSpec] = MappingProxyType({
            f["soft_field_id"]: SoftFieldSpec(f["soft_field_id"], f["prompt_text_en"], f["max_characters"],
                                              f["max_sentences"], bool(f["allow_new_numbers"]),
                                              tuple(f["required_support"]))
            for f in data["soft_field_definitions"]})
        self.packs: Mapping[str, Mapping[str, Any]] = MappingProxyType(
            {p["pack_id"]: MappingProxyType({"question_ids": tuple(p["question_ids"]),
                                             "soft_field_ids": tuple(p["soft_field_ids"]),
                                             "output_schema_version": p["output_schema_version"],
                                             "runtime_activation": bool(p["runtime_activation"])})
             for p in data["question_packs"]})


def load_interpretation_database(path: Path = DEFAULT_PATH) -> InterpretationDatabase:
    """Load the compiled artifact, refusing anything but the pinned bytes."""
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != g.T26_SHA256:
        raise PermanentFailure("interpretation_database_drift")
    data = json.loads(raw)
    if data.get("version") != g.T26_VERSION:
        raise PermanentFailure("interpretation_database_drift")
    return InterpretationDatabase(data, digest)


__all__ = ["Choice", "InterpretationDatabase", "QuestionSpec", "SoftFieldSpec", "load_interpretation_database"]
