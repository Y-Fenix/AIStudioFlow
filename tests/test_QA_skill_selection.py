"""Selecting a saved rule uses the existing per-batch import contract."""
import tempfile
import unittest
from pathlib import Path
from server.store import Store


class QA_SkillSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'db.sqlite')
        self.project = self.store.create_project('选择规则')['id']
        self.task = self.store.create_task(self.project, '原批次')

    def test_selected_name_and_content_persist_only_to_target_stage_and_batch(self):
        other = self.store.create_task(self.project, '另一批次')
        text = '---\nname: team-review\ndescription: 团队审查规则\n---\n仅依据真实来源。'
        updated = self.store.save_node_skill(self.project, self.task['id'], 1, text,
                                             self.task['revision'], name='团队审查规则')
        self.assertEqual(updated['node_skills']['1']['name'], '团队审查规则')
        self.assertEqual(updated['node_skills']['1']['content'], text)
        self.assertEqual(updated['node_skills']['0'], self.task['node_skills']['0'])
        self.assertEqual(self.store.task(self.project, other['id'])['node_skills'], other['node_skills'])
        self.assertEqual(Store(self.store.path).task(self.project, self.task['id'])['node_skills']['1'],
                         updated['node_skills']['1'])
        self.assertIn('团队审查规则', updated['events'][-1]['detail'])

    def test_invalid_display_names_do_not_write(self):
        for name in ('', '   ', 'x' * 201, {}, 7):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.save_node_skill(self.project, self.task['id'], 1, '真实规则',
                                           self.task['revision'], name=name)
        self.assertEqual(self.store.task(self.project, self.task['id'])['revision'], self.task['revision'])
