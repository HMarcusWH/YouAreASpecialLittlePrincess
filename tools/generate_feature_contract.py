"""Generate the packaged runtime contract; never hand-edit its JSON output."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'schema/graphology_feature_database_v1.json'
OUTPUT = ROOT / 'src/princess_graphology/_feature_contract.json'


def project_database(database: dict) -> dict:
    features = database['features']
    ids = [f['id'] for f in features]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate feature IDs in canonical database')
    fields = ('unit', 'data_type', 'scope', 'input_mode')
    return {
        'schema_version': database['version'],
        'feature_count': len(features),
        'evidence_status': database['enums']['evidence_status'],
        'features': {f['id']: {key: f[key] for key in fields} for f in features},
    }


def render(source: Path = SOURCE) -> str:
    raw = source.read_bytes()
    contract = project_database(json.loads(raw))
    contract['source_sha256'] = hashlib.sha256(raw).hexdigest()
    return json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding='utf-8') != expected:
            raise SystemExit('Runtime schema is stale. Run tools/generate_feature_contract.py')
    else:
        OUTPUT.write_text(expected, encoding='utf-8')


if __name__ == '__main__':
    main()
