#!/usr/bin/env python3
"""Validate T26 PR2 observation/value/selector foundation against frozen research."""
from __future__ import annotations

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


def concat(root: Path, relative: str):
    return [item for name in DOMAINS for item in load(root / relative / f"{name}.json")]


def research_questions(repo: Path):
    root = repo / "research/graphology/foundations-v0.1/blueprint/questions"
    return [item for name in DOMAINS for item in load(root / f"{name}.json")]


def observation_question(q: dict) -> bool:
    return (
        bool(q["value_set_id"])
        and q["domain_id"] not in {"INTERPRETATION", "PAIR", "HISTORY"}
        and q["question_id"] != "Q_HIERARCHY_RELATION"
    )


def validate(repo: Path) -> list[str]:
    root = repo / "schema/graphology_interpretation/v1"
    questions = research_questions(repo)
    research_values = load(repo / "research/graphology/foundations-v0.1/blueprint/value_sets.json")
    research_meta = load(repo / "research/graphology/foundations-v0.1/blueprint/metadata.json")
    feature_db = load(repo / "schema/graphology_feature_database_v1.json")
    sources = load(root / "ontology/sources.json")
    domains = load(root / "ontology/domains.json")
    value_sets = load(root / "values/value_sets.json")
    answer_states = load(root / "values/answer_states.json")
    selection = load(root / "values/selection_contract.json")
    candidates = load(root / "candidates/candidate_definitions.json")["records"]
    selectors = concat(root, "selectors")
    observations = concat(root, "ontology/observations")
    mappings = concat(root, "ontology/feature_mappings")
    selector_trace = concat(root, "traceability/selectors")
    static_trace = load(root / "traceability/pr2_values_candidates_policies.json")["records"]
    exclusions = load(root / "traceability/exclusions.json")
    manifest = load(root / "manifest.json")
    scaffold = load(repo / "schema/premium_interpretation_database_v1.json")
    tasks = load(repo / "docs/roadmap/tasks.json")

    errors = []

    def unique(values, label):
        values = list(values)
        if len(values) != len(set(values)):
            errors.append(f"duplicate {label}")

    unique((x["value_set_id"] for x in value_sets), "value_set_id")
    unique((x["selector_id"] for x in selectors), "selector_id")
    unique((x["observation_id"] for x in observations), "observation_id")
    unique((x["mapping_id"] for x in mappings), "mapping_id")
    unique((x["candidate_kind_id"] for x in candidates), "candidate_kind_id")

    # Frozen research promotion: fixed values and universal policies must not drift.
    stripped_values = [
        {k: v for k, v in x.items() if k not in {"production_status", "runtime_activation"}}
        for x in value_sets
    ]
    if stripped_values != research_values:
        errors.append("production value sets drifted from frozen research")
    stripped_states = {k: v for k, v in answer_states.items() if k not in {"version", "production_status", "runtime_activation"}}
    if stripped_states != research_meta["answer_state_policy"]:
        errors.append("answer-state policy drifted from frozen research")
    stripped_selection = {k: v for k, v in selection.items() if k not in {"version", "production_status", "runtime_activation"}}
    if stripped_selection != research_meta["selection_contract"]:
        errors.append("selection contract drifted from frozen research")

    source_ids = {x["source_id"] for x in sources}
    domain_ids = {x["domain_id"] for x in domains}
    value_ids = {x["value_set_id"] for x in value_sets}
    candidate_ids = {x["candidate_kind_id"] for x in candidates}
    feature_ids = {x["id"] for x in feature_db["features"]}

    if len(questions) != 89 or len(selectors) != 89:
        errors.append("expected exactly 89 research questions/selectors")
    if sum(x["selection_domain"] == "FIXED" for x in selectors) != 54:
        errors.append("expected 54 fixed selectors")
    if sum(x["selection_domain"] == "DYNAMIC" for x in selectors) != 35:
        errors.append("expected 35 dynamic selectors")

    q_by_selector = {q["selector_id"]: q for q in questions}
    if set(q_by_selector) != {x["selector_id"] for x in selectors}:
        errors.append("selector IDs differ from frozen research")

    selector_keys = {
        "source_question_id", "domain_id", "scope", "answer_owner", "model_call_role",
        "selection_domain", "cardinality", "value_set_id", "candidate_kind", "required_inputs",
        "answer_state_policy", "numeric_threshold_policy", "permitted_evidence_class",
        "source_refs", "feature_mapping_relation", "report_target", "source_status",
    }
    non_model = {"USER_OR_REVIEWER", "DETERMINISTIC", "RULE_ENGINE"}
    for s in selectors:
        q = q_by_selector[s["selector_id"]]
        expected = {
            "source_question_id": q["question_id"],
            "domain_id": q["domain_id"],
            "scope": q["scope"],
            "answer_owner": q["answer_owner"],
            "model_call_role": q["model_call_role"],
            "selection_domain": q["selection_domain"],
            "cardinality": q["cardinality"],
            "value_set_id": q["value_set_id"],
            "candidate_kind": q["candidate_kind"],
            "required_inputs": q["required_inputs"],
            "answer_state_policy": q["answer_state_policy"],
            "numeric_threshold_policy": q["numeric_threshold_policy"],
            "permitted_evidence_class": q["permitted_evidence_class"],
            "source_refs": q["source_refs"],
            "feature_mapping_relation": q["feature_mapping_relation"],
            "report_target": q["report_target"],
            "source_status": q["status"],
        }
        if any(s[k] != expected[k] for k in selector_keys):
            errors.append(f"selector drifted from research: {s['selector_id']}")
        if "question_text_en" in s:
            errors.append(f"question text leaked into selector foundation: {s['selector_id']}")
        if s["domain_id"] not in domain_ids:
            errors.append(f"selector domain does not resolve: {s['selector_id']}")
        if {r["source_id"] for r in s["source_refs"]} - source_ids:
            errors.append(f"selector source does not resolve: {s['selector_id']}")
        if s["runtime_status"] != "DRAFT_NOT_ACTIVE":
            errors.append(f"selector became active: {s['selector_id']}")
        if s["answer_owner"] in non_model and s["model_call_role"] != "READ_ONLY_CONTEXT_OR_PRECOMPUTED":
            errors.append(f"non-model answer owner became model-answerable: {s['selector_id']}")
        if s["selection_domain"] == "FIXED":
            if not s["value_set_id"] or s["value_set_id"] not in value_ids or s["candidate_kind"] is not None:
                errors.append(f"invalid fixed selector: {s['selector_id']}")
        elif s["selection_domain"] == "DYNAMIC":
            if not s["candidate_kind"] or s["candidate_kind"] not in candidate_ids or s["value_set_id"] is not None:
                errors.append(f"invalid dynamic selector: {s['selector_id']}")
        else:
            errors.append(f"unknown selection domain: {s['selector_id']}")

    expected_obs_questions = [q for q in questions if observation_question(q)]
    if len(observations) != 49:
        errors.append("expected 49 PR2 observation descriptors")
    if {x["source_question_id"] for x in observations} != {q["question_id"] for q in expected_obs_questions}:
        errors.append("observation boundary differs from reviewed PR2 policy")
    if any(x["runtime_status"] != "DRAFT_NOT_ACTIVE" for x in observations):
        errors.append("observation became active")

    expected_mappings = {
        (q["selector_id"], fid, q["feature_mapping_relation"])
        for q in questions for fid in q["related_canonical_feature_ids"]
    }
    actual_mappings = {(x["selector_id"], x["canonical_feature_id"], x["relationship"]) for x in mappings}
    if len(mappings) != 50 or actual_mappings != expected_mappings:
        errors.append("canonical feature mappings differ from frozen research")
    if any(x["canonical_feature_id"] not in feature_ids for x in mappings):
        errors.append("canonical feature mapping does not resolve")
    if any(x["relationship"] != "SUPPORTING_NOT_AUTOMATIC_SEMANTIC_EQUIVALENCE" for x in mappings):
        errors.append("unsafe feature-mapping relationship")
    if any(x["mapping_status"] != "DRAFT_SUPPORT_ONLY" or x["runtime_activation"] is not False for x in mappings):
        errors.append("feature mapping became active")

    if len(value_sets) != 44 or sum(len(x["values"]) for x in value_sets) != 156:
        errors.append("expected 44 value sets / 156 value entries")
    if any(x["production_status"] != "DRAFT_NOT_ACTIVE" or x["runtime_activation"] is not False for x in value_sets):
        errors.append("value set became active")
    if set(candidate_ids) != set(research_meta["candidate_kinds"]):
        errors.append("candidate-kind registry differs from frozen research")
    if any(x["generator_status"] != "NOT_IMPLEMENTED_IN_T26_PR2" or x["runtime_status"] != "DRAFT_NOT_ACTIVE" for x in candidates):
        errors.append("candidate generator invented or activated")

    expected_selector_trace = {(q["question_id"], q["selector_id"]) for q in questions}
    actual_selector_trace = {(x["research_id"], x["production_id"]) for x in selector_trace}
    if expected_selector_trace != actual_selector_trace:
        errors.append("question→selector traceability incomplete")

    required_static = {("VALUE_SET", x["value_set_id"]) for x in research_values}
    required_static |= {("CANDIDATE_KIND", x) for x in research_meta["candidate_kinds"]}
    required_static |= {("ANSWER_STATE_POLICY", research_meta["answer_state_policy"]["policy_id"])}
    required_static |= {("SELECTION_CONTRACT", "selection_contract")}
    actual_static = {(x["research_kind"], x["research_id"]) for x in static_trace}
    if required_static != actual_static:
        errors.append("static PR2 traceability differs from frozen research")

    expected_exclusions = {
        "Production question text and executable question packs",
        "Executable traditional associations and support-rule evaluation",
        "Candidate generator implementations",
        "Soft-field activation and tone profiles",
        "Report mappings",
        "Localization",
        "Compiled premium_interpretation_database_v1.json",
    }
    if set(exclusions["intentionally_not_in_scope"]) != expected_exclusions:
        errors.append("PR2 exclusions are incomplete")

    expected_counts = {
        "observations": 49,
        "canonical_feature_mappings": 50,
        "mapped_canonical_feature_ids": 50,
        "value_sets": 44,
        "value_entries": 156,
        "selectors": 89,
        "fixed_selectors": 54,
        "dynamic_selectors": 35,
        "candidate_kinds": 33,
        "answer_states": 6,
    }
    for key, value in expected_counts.items():
        if manifest["counts"].get(key) != value:
            errors.append(f"manifest PR2 count differs for {key}")
    if manifest["runtime_activation"] is not False or manifest["t26_status"] != "PLANNED":
        errors.append("manifest activation/T26 status invalid")
    if manifest["production_scope"] != "ONTOLOGY_PROVENANCE_OBSERVATIONS_SELECTORS_VALUES":
        errors.append("manifest PR2 scope invalid")

    if scaffold.get("status") != "UNPOPULATED":
        errors.append("compiled Premium scaffold must remain UNPOPULATED in PR2")
    t26 = next(x for x in tasks["tasks"] if x["id"] == "T26")
    if t26["status"] != "PLANNED":
        errors.append("T26 must remain PLANNED in PR2")
    return errors


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    errors = validate(repo)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "scope": "T26_PR2_SELECTOR_FOUNDATION"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
