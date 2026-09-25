#!/usr/bin/env python3
"""Compile the modular graphology interpretation database into the T15 runtime artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


DOMAINS = [
    "01-context", "02-global", "03-space", "04-size", "05-direction", "06-connection",
    "07-form", "08-stroke", "09-movement", "10-detail", "11-signature", "12-hierarchy",
    "13-interpretation", "14-reference", "15-pair", "16-history",
]


def load(path: Path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"Duplicate key in {path}: {key}")
            out[key] = value
        return out
    def constant(value):
        raise ValueError(f"Non-finite JSON in {path}: {value}")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=constant)


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def concat(root: Path, relative: str):
    return [item for name in DOMAINS for item in load(root / relative / f"{name}.json")]


def build_database(repo: Path) -> dict:
    root = repo / "schema/graphology_interpretation/v1"
    manifest = load(root / "manifest.json")
    contract = load(root / "runtime_contract.json")
    schools = load(root / "ontology/schools.json")
    domains = load(root / "ontology/domains.json")
    concepts = load(root / "ontology/concepts.json")
    values = load(root / "values/value_sets.json")
    selectors = concat(root, "selectors")
    questions = concat(root, "questions")
    packs = load(root / "packs/question_packs.json")["packs"]
    soft = load(root / "narrative/soft_fields.json")["records"]
    candidates = load(root / "candidates/candidate_definitions.json")["records"]
    tones = load(root / "narrative/tone_profiles.json")["records"]
    slots = load(root / "reports/report_slots.json")["records"]
    localization_policy = load(root / "localization/policy.json")

    association_contract = load(root / "traditional/association_contract.json")
    candidate_validation = load(root / "traditional/candidate_validation_policy.json")
    method_policies = load(root / "traditional/method_policies.json")["records"]
    jaminian = load(root / "traditional/associations/jaminian.json")
    rule_packs = load(root / "traditional/rule_pack_registry.json")["packs"]
    activation_gates = load(root / "traditional/activation_gates.json")

    slot_by_target = {x["report_target"]: x["report_slot_id"] for x in slots}
    report_mappings = []
    for q in questions:
        report_mappings.append({
            "content_kind": "QUESTION",
            "content_id": q["question_id"],
            "selector_id": q["selector_id"],
            "report_target": q["report_target"],
            "report_slot_id": slot_by_target[q["report_target"]],
        })
    for field in soft:
        report_mappings.append({
            "content_kind": "SOFT_FIELD",
            "content_id": field["soft_field_id"],
            "selector_id": None,
            "report_target": field["report_target"],
            "report_slot_id": slot_by_target[field["report_target"]],
        })

    en = {}
    for school in schools:
        en[f"school.{school['school_id'].lower()}.label"] = school["label"]
    for domain in domains:
        en[f"domain.{domain['domain_id'].lower()}.label"] = domain["label"]
    for value_set in values:
        for value in value_set["values"]:
            en[value["label_key"]] = value["label_en"]
    for q in questions:
        en[q["prompt_template_key"]] = q["prompt_text_en"]
    for field in soft:
        en[field["label_key"]] = field["purpose"]
    for tone in tones:
        en[tone["label_key"]] = tone["label_en"]
    for slot in slots:
        en[slot["label_key"]] = slot["label_en"]

    return {
        "version": "premium-interpretation-db/1",
        "status": "POPULATED_PENDING_REVIEW",
        "runtime_activation": False,
        "source_database_version": manifest["version"],
        "design_principles": contract["design_principles"],
        "enums": contract["enums"],
        "schools": schools,
        "domains": domains,
        "concepts": concepts,
        "selector_value_sets": values,
        "selector_definitions": selectors,
        "question_definitions": questions,
        "question_packs": packs,
        "soft_field_definitions": soft,
        "candidate_definitions": candidates,
        "tone_profiles": tones,
        "report_slots": slots,
        "report_mappings": report_mappings,
        "localization_policy": localization_policy,
        "localization_keys": sorted(en),
        "localization": {"en": en},
        "traditional": {
            "association_contract": association_contract,
            "candidate_validation_policy": candidate_validation,
            "method_policies": method_policies,
            "associations": {"jaminian": jaminian},
            "rule_pack_registry": rule_packs,
            "activation_gates": activation_gates,
        },
    }


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write and args.check:
        raise SystemExit("choose only one of --write or --check")
    target = repo / "schema/premium_interpretation_database_v1.json"
    data = encoded(build_database(repo))
    if args.write:
        target.write_bytes(data)
        return 0
    if args.check:
        if not target.exists() or target.read_bytes() != data:
            print("premium_interpretation_database_v1.json is out of date", file=sys.stderr)
            return 1
        return 0
    sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
