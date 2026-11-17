"""Public execution regressions. Models/adapters here are explicit fixtures."""
import tempfile
import json
import unittest
from unittest.mock import patch

from server.store import Store
from server.core.integrations import AdapterRegistry, ExecutionService
from server.department_jobs import DepartmentExecutionQueue
from server.studio_workspaces import Workspaces
from server.core.node_blocks.runtime import Runs
from server.core.node_blocks.service import Builder
from server.ai_models import ModelSettings, current_selection


class WorkbenchExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name + '/test.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('隔离工作台测试', self.studio)['id']

    def registry(self, result):
        class Fixture:
            def execute(self, context):
                return result
        registry = AdapterRegistry()
        registry.register('product', Fixture())
        return registry

    def test_blank_adapter_output_never_saves_or_advances_revision(self):
        service = ExecutionService(self.store, self.registry({'deliverable': ' \n '}))
        with self.assertRaisesRegex(ValueError, '正文|为空'):
            service.execute(self.studio, self.project, 'product:0', 0)
        workspace = Workspaces(self.store).get(self.studio, self.project, 'product:0')
        self.assertEqual(workspace['revision'], 0)

    def test_quality_report_survives_department_queue_result(self):
        report = {'fact_checked': False, 'sections_checked': 4, 'source_quotes_checked': 1}
        queue = DepartmentExecutionQueue(self.store, self.registry({
            'deliverable': '模型替身正文', 'evidence': ['引用'], 'gaps': ['待审核'], 'quality': report}))
        job = queue.enqueue(self.studio, self.project, 'product:0', 0)
        queue.run_once()
        result = queue.get(self.studio, self.project, job['id'])['result']
        self.assertEqual(result['quality'], report)
        self.assertEqual(result['workspace']['status'], 'waiting_user')

    def test_latest_job_uses_insertion_order_when_timestamps_equal(self):
        with self.store.connection() as db:
            for identity in ('z-old', 'a-new'):
                db.execute("""INSERT INTO department_jobs
                    (id,studio_id,project_id,node,actor,revision,status,created_at)
                    VALUES(?,?,?,'product:0','local',0,'failed','2026-10-22 01:00:00')""",
                    (identity, self.studio, self.project))
        latest = DepartmentExecutionQueue(self.store, AdapterRegistry()).latest(
            self.studio, self.project, 'product:0')
        self.assertEqual(latest['id'], 'a-new')

    def test_custom_ai_blank_output_stops_at_failed_step(self):
        blueprint = Builder(self.store).save_blueprint(self.studio, self.project, 'product:0', {
            'revision': 0, 'blocks': [{'id': 'ai', 'type': 'ai', 'config': {'prompt': '整理给定资料'}}]})
        runs = Runs(self.store)
        run = runs.start(self.studio, self.project, {'node': 'product:0', 'revision': blueprint['revision'], 'input': '资料'})
        with patch('server.codex_model.CodexModel.request_json', return_value={'deliverable': '  '}):
            runs.tick()
        current = runs.get(self.studio, self.project, run['id'])
        self.assertEqual(current['status'], 'failed')
        self.assertEqual(current['cursor'], 0)

    def test_custom_adapter_quality_report_is_retained(self):
        registry = self.registry({'deliverable': '替身正文', 'quality': {'fact_checked': False}})
        builder = Builder(self.store)
        flow = builder.save_flow(self.studio, self.project, {'revision': 0, 'name': '独立执行器流程',
            'blocks': [{'id': 'node', 'type': 'node', 'config': {'node': 'product:0'}}]})
        runs = Runs(self.store, registry)
        run = runs.start(self.studio, self.project, {'flow': flow['id'], 'revision': flow['revision'], 'input': '资料'})
        runs.tick()
        current = runs.get(self.studio, self.project, run['id'])
        self.assertEqual(current['steps'][0]['quality'], {'fact_checked': False})

    def document_fixture(self, prompt):
        """Transport fixture only; real registry/contracts/queue/persistence run."""
        payload = json.loads(prompt.split('\n', 1)[1])
        self.calls.append((payload, current_selection()))
        return {
            'sections': [{'id': section['id'], 'content': '隔离模型替身交付：' + section['title']}
                         for section in payload['contract']['sections']],
            'claims': [{'statement': '输入含已给定需求', 'kind': 'fact',
                        'quote': payload['inputs'].splitlines()[0]}],
            'risks': ['此为模型替身，不代表真实业务质量验收'],
            'next_actions': ['负责人核对交付与原始需求'],
        }

    def test_all_twelve_registered_nodes_complete_queue_and_use_actual_skill_model(self):
        self.calls = []
        ModelSettings(self.store).save_custom({'base_url': 'https://fixture.example/v1',
            'model': 'fixture-selected-model', 'protocol': 'responses', 'effort': 'high',
            'api_key': 'fixture-only'})
        registry = AdapterRegistry().load_modules()
        queue = DepartmentExecutionQueue(self.store, registry)
        with patch('server.codex_model.CodexModel.request_json', side_effect=self.document_fixture):
            for department in ('product', 'design', 'development'):
                for index in range(4):
                    node = department + ':' + str(index)
                    with self.subTest(node=node):
                        body = {'revision': 0, 'inputs': 'fixture-source ' + node}
                        if index == 1:
                            body['skill'] = '# Imported fixture Skill\n遵循当前节点输入并保留证据。'
                        workspace = Workspaces(self.store).save(self.studio, self.project, node, body)
                        job = queue.enqueue(self.studio, self.project, node, workspace['revision'])
                        queue.run_once()
                        finished = queue.get(self.studio, self.project, job['id'])
                        self.assertEqual(finished['status'], 'completed', finished['error'])
                        result = finished['result']
                        self.assertEqual(result['workspace']['status'], 'waiting_user')
                        self.assertEqual(result['workspace']['revision'], workspace['revision'] + 1)
                        self.assertEqual(result['quality']['source_quotes_checked'], 1)
                        self.assertFalse(result['quality']['fact_checked'])
                        self.assertTrue(result['gaps'])
                        payload, selection = self.calls[-1]
                        self.assertEqual(payload['node'], node)
                        self.assertEqual(payload['skill'], workspace['skill']['content'].strip())
                        self.assertEqual(selection['model'], 'fixture-selected-model')
                        self.assertEqual(selection['source'], 'custom')
                        self.assertEqual(selection['effort'], 'high')
        self.assertEqual(len(self.calls), 12)
        self.assertEqual(len({value[0]['contract']['id'] for value in self.calls}), 12)

    def test_real_department_contracts_in_custom_chain_preserve_snapshot_and_sources(self):
        self.calls = []
        builder = Builder(self.store)
        nodes = ('product:3', 'design:1', 'development:0')
        originals = [Workspaces(self.store).get(self.studio, self.project, node) for node in nodes]
        flow = builder.save_flow(self.studio, self.project, {'revision': 0, 'name': '跨部门隔离契约验证',
            'blocks': [{'id': 'stage' + str(i), 'type': 'node', 'config': {
                'node': node, 'auto_next': True, 'inputs': 'fixture stage ' + str(i),
                'skill': '# Flow snapshot Skill\n严格标注来源，当前实例 ' + str(i)}}
                for i, node in enumerate(nodes)]})
        runs = Runs(self.store, AdapterRegistry().load_modules())
        run = runs.start(self.studio, self.project, {'flow': flow['id'],
            'revision': flow['revision'], 'input': 'fixture initial source'})
        # The in-flight run must continue using its frozen local instance Skill.
        changed = json.loads(json.dumps(flow))
        changed['blocks'][0]['config']['skill'] = '# Changed Skill\n不应进入历史运行'
        builder.save_flow(self.studio, self.project, changed)
        with patch('server.codex_model.CodexModel.request_json', side_effect=self.document_fixture):
            for _ in range(4):
                runs.tick()
        result = runs.get(self.studio, self.project, run['id'])
        self.assertEqual(result['status'], 'completed', result.get('error'))
        self.assertEqual(len(self.calls), 3)
        for index, step in enumerate(result['steps']):
            self.assertIn('quality', step)
            self.assertTrue(step['evidence'])
            self.assertTrue(step['gaps'])
            self.assertIn('当前实例 ' + str(index), self.calls[index][0]['skill'])
            self.assertNotIn('Changed Skill', self.calls[index][0]['skill'])
        self.assertIn('PRD', self.calls[1][0]['inputs'])
        for node, before in zip(nodes, originals):
            self.assertEqual(Workspaces(self.store).get(self.studio, self.project, node), before)

    def test_registered_document_result_cannot_overwrite_newer_input_revision(self):
        self.calls = []
        workspaces = Workspaces(self.store)
        original = workspaces.save(self.studio, self.project, 'product:0',
                                   {'revision': 0, 'inputs': 'fixture original input'})
        queue = DepartmentExecutionQueue(self.store, AdapterRegistry().load_modules())
        job = queue.enqueue(self.studio, self.project, 'product:0', original['revision'])
        def changed_while_generating(prompt):
            workspaces.save(self.studio, self.project, 'product:0',
                            {'revision': original['revision'], 'inputs': 'newer user input'})
            return self.document_fixture(prompt)
        with patch('server.codex_model.CodexModel.request_json', side_effect=changed_while_generating):
            queue.run_once()
        current = queue.get(self.studio, self.project, job['id'])
        self.assertEqual(current['status'], 'failed')
        self.assertIn('节点已变化', current['error'])
        latest = workspaces.get(self.studio, self.project, 'product:0')
        self.assertEqual(latest['inputs'], 'newer user input')
        self.assertEqual(latest['deliverable'], '')

    def test_custom_ai_missing_evidence_is_explicit_gap_in_output_and_result(self):
        blueprint = Builder(self.store).save_blueprint(self.studio, self.project, 'product:0', {
            'revision': 0, 'blocks': [{'id': 'ai', 'type': 'ai', 'config': {'prompt': '分析输入'}}]})
        runs = Runs(self.store)
        run = runs.start(self.studio, self.project, {'node': 'product:0',
            'revision': blueprint['revision'], 'input': '资料'})
        with patch('server.codex_model.CodexModel.request_json',
                   return_value={'deliverable': '未经证实的模型判断'}):
            runs.tick()
        current = runs.get(self.studio, self.project, run['id'])
        self.assertTrue(current['steps'][0]['gaps'])
        self.assertIn('未核验', current['steps'][0]['output'])
        self.assertIn('未经证实的模型判断', current['steps'][0]['output'])


if __name__ == '__main__':
    unittest.main()
