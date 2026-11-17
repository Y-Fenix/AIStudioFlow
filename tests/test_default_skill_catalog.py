"""Offline provenance and actual runtime defaults; no GitHub or model calls."""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.studio_catalog import DEPARTMENTS, default_skill
from server.node_skills import defaults
from server.store import Store

ROOT = Path(__file__).resolve().parents[1]


class DefaultSkillCatalogTests(unittest.TestCase):
    def test_every_builtin_node_loads_a_pinned_reviewed_github_default(self):
        catalog = json.loads((ROOT / 'server/skills/github-defaults.json').read_text())
        expected = {f'{d["id"]}:{i}' for d in DEPARTMENTS for i in range(len(d['nodes']))}
        self.assertEqual(set(catalog['nodes']), expected)
        for key, entry in catalog['nodes'].items():
            with self.subTest(node=key):
                skill = default_skill(key)
                text = (ROOT / entry['path']).read_text()
                self.assertEqual(skill['content'], text)
                self.assertEqual(skill['name'], entry['name'])
                self.assertEqual(skill['source_kind'], 'bundled')
                self.assertEqual(skill['sha256'], hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(skill['upstream_sources'], entry['sources'])
                self.assertLessEqual(len(text), 16000)
                self.assertIn('## 输入', text)
                self.assertIn('## 输出', text)
                self.assertIn('## 证据', text)
                self.assertIn('## 平台边界', text)
                self.assertIn('不擅自提交、拉取或推送 Git', text)
                self.assertNotIn('${CLAUDE_SKILL_DIR}', text)
                self.assertEqual(len(re.findall(r'^```[^\n]*$', text, re.MULTILINE)) % 2, 0,
                                 'Exported Markdown must not swallow later sections in an open fence')
                self.assertTrue(entry['sources'])
                for ref in entry['sources']:
                    source = catalog['sources'][ref]
                    self.assertGreaterEqual(source['stars'], 10000)
                    self.assertRegex(source['commit'], r'^[0-9a-f]{40}$')
                    self.assertEqual(source['license'], 'MIT')
                    raw = (ROOT / source['snapshot']).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), source['sha256'])
                    self.assertIn(source['url'], text)
                    self.assertIn(source['skill'], text)
                    self.assertIn('Permission is hereby granted', (ROOT / source['license_path']).read_text())
                for excerpt in entry['excerpts']:
                    self.assertNotRegex(excerpt['text'], r'(?i)read\s+`references/',
                                        'A single-file port must not require unavailable upstream helpers')
                    original = (ROOT / catalog['sources'][excerpt['source']]['snapshot']).read_text()
                    self.assertIn(excerpt['text'], original)
                    self.assertIn(excerpt['text'], text)

    def test_machine_local_rules_cannot_silently_shadow_the_catalog(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'CODEX_HOME':folder}):
            for directory in ('test-test-case','test-testcase-codetest'):
                path = Path(folder) / 'skills' / directory / 'SKILL.md'
                path.parent.mkdir(parents=True)
                path.write_text('本机旧规则，不应覆盖新的团队默认')
            for stage, skill in defaults().items():
                self.assertEqual(skill['source_kind'], 'bundled')
                self.assertTrue(skill.get('upstream_sources'))
                self.assertNotIn('本机旧规则', skill['content'])

    def test_new_batches_use_catalog_but_imports_and_old_snapshots_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            project = store.create_project('默认规则隔离')['id']
            old = store.create_task(project, '旧批次')
            updated = store.save_node_skill(project, old['id'], 0, '团队自定义规则', old['revision'])
            new = store.create_task(project, '新批次')
            self.assertEqual(new['node_skills'], defaults())
            self.assertEqual(store.task(project, old['id'])['node_skills'], updated['node_skills'])
            self.assertEqual(updated['node_skills']['0']['content'], '团队自定义规则')
            self.assertTrue(new['node_skills']['0'].get('upstream_sources'))


if __name__ == '__main__':
    unittest.main()
