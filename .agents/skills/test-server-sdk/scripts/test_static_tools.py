"""Exercise execution and coverage accounting using isolated source fixtures."""
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


class StaticToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'server_sdk_static_tools', Path(__file__).with_name('static_tools.py'))
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source'
        self.root.mkdir()

    def baseline(self, sources):
        files = {}
        for name, source in sources.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(source)
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        return {'schema_version': 1, 'repositories': {'fixture': {
            'root': str(self.root), 'available': True, 'errors': [],
            'files': files, 'skipped': ['node_modules/']}}}

    def test_real_node_separates_syntax_from_execution(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not installed')
        marker = self.base / 'MUST_NOT_EXIST'
        baseline = self.baseline({
            'good.js': 'require("fs").writeFileSync(' + json.dumps(str(marker)) + ', "executed");',
            'bad.js': 'const PRIVATE_FIXTURE_TOKEN = ;',
            'types.kt': 'class Example',
        })
        result = self.runner.audit(baseline, self.base / 'output', 5,
                                   tool_paths={'node': node, 'swiftc': None})
        states = {r['path']: r['status'] for r in result['checks']}
        self.assertEqual(states, {'bad.js': 'syntax_error', 'good.js': 'executed_ok',
                                  'types.kt': 'unsupported'})
        self.assertFalse(marker.exists())
        self.assertNotIn('PRIVATE_FIXTURE_TOKEN', json.dumps(result))
        self.assertFalse(result['complete'])

    def test_changed_source_is_not_checked_as_saved_baseline(self):
        baseline = self.baseline({'main.js': 'const x = 1;'})
        (self.root / 'main.js').write_text('const x = ;')
        result = self.runner.audit(baseline, self.base / 'output', 1,
                                   tool_paths={'node': None, 'swiftc': None})
        self.assertEqual(result['checks'][0]['status'], 'stale')

    def test_real_swift_parse_without_resolving_imports(self):
        swiftc = shutil.which('swiftc')
        if not swiftc:
            self.skipTest('swiftc not installed')
        result = self.runner.audit(self.baseline({
            'good.swift': 'import DeliberatelyMissingModule\nlet answer = 42\n',
            'bad.swift': 'let answer =\n',
        }), self.base / 'output', 15,
            tool_paths={'node': None, 'swiftc': swiftc})
        states = {r['path']: r['status'] for r in result['checks']}
        self.assertEqual(states, {'bad.swift': 'syntax_error', 'good.swift': 'executed_ok'})

    def test_missing_tool_is_not_success(self):
        result = self.runner.audit(self.baseline({'main.js': 'const x = 1;'}),
                                   self.base / 'output', 1,
                                   tool_paths={'node': None, 'swiftc': None})
        self.assertEqual(result['checks'][0]['status'], 'unavailable')
        self.assertFalse(result['complete'])

    def test_process_timeout_and_preload_environment(self):
        result = self.runner.run_process(
            [sys.executable, '-c', 'import time; time.sleep(20)'], self.base, .1)
        self.assertTrue(result['timed_out'])
        env = self.runner.clean_environment({'NODE_OPTIONS': '--require secret.js',
                                              'NODE_PATH': '/secret', 'PATH': '/bin'})
        self.assertNotIn('NODE_OPTIONS', env)
        self.assertNotIn('NODE_PATH', env)
        self.assertEqual(env['PATH'], '/bin')

    def test_rejects_path_escape_and_output_in_source(self):
        baseline = self.baseline({'main.js': 'const x = 1;'})
        with self.assertRaises(ValueError):
            self.runner.audit(baseline, self.root / 'output', 1)
        baseline['repositories']['fixture']['files']['../escape.js'] = '0' * 64
        with self.assertRaises(ValueError):
            self.runner.audit(baseline, self.base / 'output', 1)

    def test_symlink_is_not_followed(self):
        baseline = self.baseline({'main.js': 'const x = 1;'})
        (self.root / 'main.js').unlink()
        (self.root / 'main.js').symlink_to(self.base / 'elsewhere.js')
        (self.base / 'elsewhere.js').write_text('const x = 1;')
        result = self.runner.audit(baseline, self.base / 'output', 1,
                                   tool_paths={'node': None, 'swiftc': None})
        self.assertEqual(result['checks'][0]['status'], 'stale')


if __name__ == '__main__':
    unittest.main()
