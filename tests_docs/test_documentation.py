"""Read-only documentation checker regressions and guarded runner-refusal tests."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("documentation", ROOT / "tools/documentation.py")
assert SPEC is not None and SPEC.loader is not None
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class DocumentationTests(unittest.TestCase):
    def test_literal_routes_and_request_models(self):
        source = '''class ExampleBody(BaseModel):\n    value: str\ndef app_factory():\n    @app.post("/v1/example", status_code=202)\n    def handler(body: ExampleBody, who=Depends(principal)) -> dict:\n        return {}\n'''
        routes, models = DOCS.routes(source)
        self.assertEqual([(r['method'], r['path'], r['status']) for r in routes], [('POST', '/v1/example', 202)])
        self.assertTrue(routes[0]['principal'])
        self.assertEqual(routes[0]['models'], ['ExampleBody'])
        self.assertEqual(models[0].name, 'ExampleBody')

    def test_dynamic_or_duplicate_route_is_not_silently_documented(self):
        with self.assertRaises(ValueError):
            DOCS.routes('@app.get(prefix + "/x")\ndef x(): pass\n')
        with self.assertRaises(ValueError):
            DOCS.routes('@app.get("/x")\ndef x(): pass\n@app.get("/x")\ndef y(): pass\n')

    def test_missing_path_and_script_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json').write_text('{"scripts":{"test":"node test.js"}}', encoding='utf-8')
            errors = DOCS.target_errors(root, {'required_paths': ['missing.py', '../escape'], 'package_scripts': {'package.json': ['absent']}})
            self.assertEqual(len(errors), 3)
            self.assertTrue(any('absent' in error for error in errors))

    def test_links_and_anchors_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc = root / 'README.md'
            doc.write_text('# Home\n[bad](missing.md)\n[anchor](other.md#absent)\n', encoding='utf-8')
            (root / 'other.md').write_text('# Present\n', encoding='utf-8')
            self.assertEqual(len(DOCS.link_errors(root, [doc])), 2)

    def test_frozen_snapshot_exclusion_is_narrow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = root / 'research/graphology/foundations-v0.1'
            frozen.mkdir(parents=True)
            (frozen / 'README.md').write_text('# Frozen\n', encoding='utf-8')
            wrapper = frozen.parent / 'README.md'
            wrapper.write_text('# Current wrapper\n', encoding='utf-8')
            self.assertEqual(DOCS.markdown_files(root), [wrapper])

    def test_source_change_changes_generated_route_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'apps/api/princess_api/app.py'
            path.parent.mkdir(parents=True)
            path.write_text('@app.get("/v1/a")\ndef a(): pass\n', encoding='utf-8')
            before = DOCS.render_api(root)
            path.write_text('@app.get("/v1/b")\ndef a(): pass\n', encoding='utf-8')
            self.assertNotEqual(before, DOCS.render_api(root))

    @unittest.skipUnless(shutil.which('bash'), 'Bash required for guarded shell refusal')
    def test_reset_refusal_happens_before_external_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            poison = root / 'bin'
            poison.mkdir()
            for name in ('python', 'python3', 'psql', 'curl', 'docker', 'node', 'pnpm'):
                path = poison / name
                path.write_text('#!/bin/sh\necho FORBIDDEN_EXTERNAL_COMMAND >&2\nexit 97\n', encoding='utf-8')
                path.chmod(0o755)
            env = {'PATH': str(poison) + os.pathsep + os.environ.get('PATH', ''), 'HOME': directory,
                   'PRINCESS_E2E_ADMIN_URL': 'postgresql://unused:unused@127.0.0.1:5432/postgres',
                   'PRINCESS_E2E_ALLOW_RESET': '0'}
            for name in ('run_mobile_journey.sh', 'run_web_e2e.sh'):
                result = subprocess.run([shutil.which('bash'), str(ROOT / 'tools' / name)],
                                        cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('REFUSE', result.stdout + result.stderr)
                self.assertNotIn('FORBIDDEN_EXTERNAL_COMMAND', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
