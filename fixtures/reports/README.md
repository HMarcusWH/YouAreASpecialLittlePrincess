# Shared report fixtures (synthetic)

Every file here comes from a **programmatically drawn synthetic page** (OpenCV Hershey script text). No participant or user handwriting is involved. Keep these files out of human statistics.

| File | What it is |
|---|---|
| `source/engine-result.synthetic.json` | Canonical `AnalysisResult` JSON captured once from the engine |
| `source/evidence-payload.synthetic.json` | The engine's `evidence/1` payload from the same run |
| `source/analysis-reference.synthetic.json` | The `AnalysisReference` (IDs, digests, version pins) |
| `evidence-bundle.json` | Compiled T01 `EvidenceBundle` |
| `report-document.json` | Revision 1 `ReportDocument` (no reference cohort, Premium `LOCKED`) |
| `report-document.premium.json` | Revision 2 with a Premium overlay reference attached |
| `view.free.json` | `FREE` projection with owner actions matching the currently implemented UI/API capability boundary (only export enabled; unavailable flows carry reviewed reasons) |
| `view.owner-premium.json` | `OWNER` projection of revision 2 with Premium unlocked; unavailable owner actions remain disabled with reasons |
| `view.share.json` | `SHARE` projection scoped to slant and baseline, no image, no actions |
| `view.export-no-image.json` | `EXPORT` projection with the source image omitted |
| `view.owner-image-revoked.json` | `OWNER` projection after the source image was revoked, with the same current owner-action capability boundary |

The outputs are regenerated with no engine dependency, so numpy/OpenCV version differences cannot make them drift:

```bash
python tools/generate_report_fixtures.py --check   # CI via tests/test_reports.py
python tools/generate_report_fixtures.py           # rewrite outputs after a contract/template change
python tools/generate_report_fixtures.py --capture # re-run the engine to refresh source/ (reviewed change)
```

Web (T17), native (T29–T31), PDF/card rendering (T21) and design (T10) consume these files. They must render the same facts, units, precision and notices, and must not recompute measurements.
