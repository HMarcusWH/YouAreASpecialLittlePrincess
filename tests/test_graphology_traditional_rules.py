"""Traditional-rule safety regressions."""
from pathlib import Path
import importlib.util, json
REPO=Path(__file__).resolve().parents[1]; TOOLS=REPO/"tools"
spec=importlib.util.spec_from_file_location("trad",TOOLS/"validate_graphology_traditional_rules.py"); m=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(m)
def load(p): return json.loads((REPO/p).read_text())
def test_validator_passes(): assert m.validate(REPO)==[]
def test_historical_stubs_stay_blocked():
    rows=load("schema/graphology_interpretation/v1/traditional/associations/jaminian.json")
    assert len(rows)==2 and all(x["runtime_eligibility"]=="BLOCKED_RESEARCH_ONLY" and not x["eligible_for_rule_engine"] and not x["eligible_for_model_candidate"] for x in rows)
def test_rule_packs_stay_inactive():
    packs=load("schema/graphology_interpretation/v1/traditional/rule_pack_registry.json")["packs"]; assert all(not p["runtime_activation"] and p["runtime_eligible_association_ids"]==[] for p in packs)
