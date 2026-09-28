#!/usr/bin/env python3
"""Generate deterministic T18 Comparison fixtures from synthetic report fixtures."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from princess_app.domain.comparison import build_comparison  # noqa: E402
from princess_app.domain.content import display_domain  # noqa: E402
from princess_app.domain.reports.assembly import build_notices, build_sections  # noqa: E402
from princess_contracts import canonical_digest, compile_document  # noqa: E402

REPORTS = ROOT / "fixtures" / "reports"
OUT = ROOT / "fixtures" / "comparisons"
CONTRACT_FIXTURE = ROOT / "contracts" / "product" / "v1" / "fixtures" / "valid" / "comparison.json"
CANDIDATES = tuple(sorted(
    json.loads((ROOT / "src" / "princess_app" / "domain" / "content" / "_presentation_v1.json")
               .read_text(encoding="utf-8"))["display_domains"]
))
T0 = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def dump(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _nudge(feature_id: str, value: float, fraction: float) -> float:
    domain = display_domain(feature_id)
    assert domain is not None
    low, high = float(domain["min"]), float(domain["max"])
    step = (high - low) * fraction
    candidate = value + step
    if candidate > high:
        candidate = value - abs(step)
    if candidate < low:
        candidate = value + abs(step)
    return min(high, max(low, candidate))


def _clone(base: dict, *, name: str, at: datetime, fraction: float = 0.0,
           missing_candidates: bool = False):
    data = copy.deepcopy(base)
    data["report_id"] = f"report_comparison_{name}"
    data["revision"] = 1
    data["created_at"] = at.isoformat().replace("+00:00", "Z")
    data["evidence_bundle_id"] = None
    data["premium_overlay_id"] = None
    data["reference_claims"] = []
    analysis = data["analysis"]
    analysis["analysis_id"] = f"analysis_comparison_{name}"
    analysis["run_id"] = f"run_comparison_{name}"
    analysis["input_asset_id"] = f"asset_comparison_{name}"
    analysis["input_sha256"] = _sha(f"comparison-input-{name}")
    analysis["processed_sha256"] = _sha(f"comparison-processed-{name}")
    analysis["created_at"] = data["created_at"]

    for fact in data["facts"]:
        feature_id = fact["feature_id"]
        if feature_id not in CANDIDATES:
            continue
        if missing_candidates:
            fact["availability"] = "MISSING"
            fact["value"] = None
            fact["quality"] = {
                "state": "MISSING",
                "missing_reason": "synthetic_no_overlap_fixture",
                "n_observations": 0,
                "confidence": None,
                "confidence_kind": "UNCALIBRATED",
            }
        elif fraction and type(fact["value"]) in {int, float}:
            fact["value"] = _nudge(feature_id, float(fact["value"]), fraction)

    data["sections"] = build_sections(
        data["facts"], reference_claims=(), premium_overlay_id=None,
        template_version=data["analysis"]["versions"]["template"],
    )
    data["notices"] = build_notices(data["facts"], has_reference=False, premium_overlay_id=None)
    data["document_digest"] = None
    data["document_digest"] = canonical_digest(data)
    compiled = compile_document("ReportDocument", data)
    if compiled.value is None:
        raise SystemExit(f"synthetic report {name} invalid: {[issue.code for issue in compiled.issues][:8]}")
    return compiled.value


def build() -> dict[Path, str]:
    base = json.loads((REPORTS / "report-document.v2.json").read_text(encoding="utf-8"))
    a = _clone(base, name="a", at=T0)
    b = _clone(base, name="b", at=T0.replace(hour=13), fraction=0.10)
    c = _clone(base, name="c", at=T0.replace(hour=14), fraction=-0.05)
    equal = _clone(base, name="equal", at=T0.replace(hour=15))
    missing = _clone(base, name="missing", at=T0.replace(hour=16), missing_candidates=True)

    cases = {
        "pair-ab.json": build_comparison(comparison_id="comparison_pair_ab", kind="PAIR",
                                         reports=[a, b], created_at=T0.replace(hour=17)),
        "pair-ba.json": build_comparison(comparison_id="comparison_pair_ba", kind="PAIR",
                                         reports=[b, a], created_at=T0.replace(hour=17)),
        "pair-equal.json": build_comparison(comparison_id="comparison_pair_equal", kind="PAIR",
                                            reports=[a, equal], created_at=T0.replace(hour=17)),
        "history.json": build_comparison(comparison_id="comparison_history", kind="HISTORY",
                                         reports=[c, a, b], created_at=T0.replace(hour=17)),
        "no-overlap.json": build_comparison(comparison_id="comparison_no_overlap", kind="PAIR",
                                            reports=[a, missing], created_at=T0.replace(hour=17)),
    }
    for name, outcome in cases.items():
        if outcome.value is None:
            raise SystemExit(f"{name} invalid: {[issue.code for issue in outcome.issues][:8]}")

    outputs = {OUT / name: dump(outcome.value.to_dict()) for name, outcome in cases.items()}
    outputs[CONTRACT_FIXTURE] = outputs[OUT / "pair-ab.json"]
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = build()
    stale = [path for path, content in outputs.items()
             if not path.is_file() or path.read_text(encoding="utf-8") != content]
    if args.check:
        if stale:
            print("stale comparison fixtures: " + ", ".join(str(path.relative_to(ROOT)) for path in stale))
            return 1
        print(f"PASS: {len(outputs)} comparison fixture outputs are current")
        return 0
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"wrote {len(outputs)} comparison fixture outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
