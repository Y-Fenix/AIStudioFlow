"""Fixed model fixtures; these tests do not contact a live model or external tools."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from departments.product.adapter import create_adapter

PRODUCT_SECTIONS = [['scope', 'audience', 'market', 'opportunities', 'validation', 'handoff'], ['scope', 'comparison', 'loops', 'implementation', 'differentiation', 'handoff'], ['core_loop', 'progression', 'economy', 'monetization', 'experiments', 'handoff'], ['scope', 'requirements', 'states', 'flows', 'acceptance', 'handoff']]


class PRODUCT_ExecutorTests(unittest.TestCase):
    def PRODUCT_response(self, index):
        return {
            'sections': [{'id': identity, 'content': 'fixture 内容 ' + identity}
                         for identity in PRODUCT_SECTIONS[index]],
            'claims': [{'statement': '项目基线为 fixture-baseline。', 'kind': 'fact',
                        'quote': 'fixture-baseline'}],
            'risks': ['未取得真实工具证据'],
            'next_actions': ['由负责人核对输入资料与建议'],
        }

    def PRODUCT_context(self, index=0, **overrides):
        values = dict(input_revision=7, node_id='product:' + str(index),
                      inputs='项目 baseline: fixture-baseline；目标平台 Android；需求为关卡游戏。',
                      skill_content='# Imported fixture Skill\n当前规则：保留来源，缺失写待确认。',
                      model=Mock(request_json=Mock(return_value=self.PRODUCT_response(index))),
                      gm=Mock())
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_all_four_nodes_generate_node_specific_documents_with_boundaries(self):
        for index in range(4):
            with self.subTest(index=index):
                context = self.PRODUCT_context(index)
                result = create_adapter().execute(context)
                self.assertIn('fixture 内容', result['deliverable'])
                for identity in PRODUCT_SECTIONS[index]:
                    self.assertIn('fixture 内容 ' + identity, result['deliverable'])
                self.assertIn('未执行外部调研', result['deliverable'])
                self.assertEqual(result['quality']['sections_checked'], 6)
                self.assertFalse(result['quality']['fact_checked'])
                self.assertTrue(result['gaps'])
                prompt = context.model.request_json.call_args_list[0].args[0]
                payload = json.loads(prompt.split('\n', 1)[1])
                self.assertEqual(payload['skill'], context.skill_content)
                self.assertEqual(payload['inputs'], context.inputs)
                context.gm.call_read.assert_not_called()

    def test_invalid_and_other_department_nodes_fail_before_model_access(self):
        for node in ('product:4', 'product:-1', 'product:custom-a',
                     'product:00', 'product:0:extra', 'testing:0', '', None):
            with self.subTest(node=node):
                context = self.PRODUCT_context(node_id=node)
                with self.assertRaises(ValueError):
                    create_adapter().execute(context)
                context.model.request_json.assert_not_called()

    def test_empty_input_or_missing_skill_fails_before_model_access(self):
        for field in ('inputs', 'skill_content'):
            for value in ('', '  ', None):
                with self.subTest(field=field, value=value):
                    context = self.PRODUCT_context(**{field: value})
                    with self.assertRaises(ValueError):
                        create_adapter().execute(context)
                    context.model.request_json.assert_not_called()

    def test_manifest_enables_document_executor_without_claiming_tool_connection(self):
        manifest = json.loads((Path(__file__).resolve().parents[1] /
                               'departments/product/manifest.json').read_text())
        self.assertEqual(manifest['execution']['adapter'], 'adapter')
        self.assertIs(manifest['execution']['automatic'], True)
        self.assertEqual(len(manifest['nodes']), 4)
        for index, fields in {0: [(3, '输入资料'), (5, '文字')], 1: [(3, '不执行反编译'), (5, '已提供'), (6, '缺口')], 3: [(3, '文字原型'), (6, '文本线框')]}.items():
            for field, wording in fields:
                self.assertIn(wording, manifest['nodes'][index][field])
        wording = json.dumps(manifest['nodes'], ensure_ascii=False)
        for unsupported in ['产出低保真设计图', '可读取的包体实现']:
            self.assertNotIn(unsupported, wording)
        for tool in manifest.get('tool_adapters', []):
            self.assertNotEqual(tool['status'], 'connected')

    def test_real_service_uses_imported_skill_and_keeps_result_pending_review(self):
        from server.core.integrations import AdapterRegistry, ExecutionService
        from server.store import Store
        from server.studio_workspaces import Workspaces
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory + '/fixture.sqlite')
            studio = store.studios()[0]['id']
            project = store.create_project('Executor fixture', studio)['id']
            service = Workspaces(store)
            workspace = service.get(studio, project, 'product:0')
            imported = '# Imported fixture rules\n只分析 fixture 输入；不得冒充真实工具证据。'
            workspace = service.save(studio, project, 'product:0', {
                'revision': workspace['revision'], 'inputs': 'fixture-baseline', 'skill': imported,
            })
            registry = AdapterRegistry()
            registry.register('product', create_adapter())
            with patch('server.codex_model.CodexModel.request_json',
                       return_value=self.PRODUCT_response(0)) as model:
                result = ExecutionService(store, registry).execute(
                    studio, project, 'product:0', workspace['revision'])
            self.assertEqual(json.loads(model.call_args.args[0].split('\n', 1)[1])['skill'], imported)
            self.assertIn('fixture 内容', result['workspace']['deliverable'])
            self.assertEqual(result['workspace']['status'], 'waiting_user')

    def test_service_rejects_execute_denial_before_calling_model(self):
        from server.core.admin import Administration
        from server.core.identity import current_user
        from server.core.integrations import AdapterRegistry, ExecutionService
        from server.store import Store
        from server.studio_workspaces import Workspaces
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory + '/fixture.sqlite')
            studio = store.studios()[0]['id']
            project = store.create_project('Denied fixture', studio)['id']
            with store.connection() as db:
                db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) "
                           "VALUES('fixture-user','fixture','fixture-user','Fixture','active')")
            admin = Administration(store)
            admin.member({'user_id': 'fixture-user', 'studio_id': studio,
                          'project_id': project, 'department': 'product'})
            admin.rule({'subject_type': 'user', 'subject_id': 'fixture-user',
                        'studio_id': studio, 'project_id': project, 'department': 'product',
                        'node': 'product:0', 'resource': 'node', 'action': 'execute',
                        'effect': 'deny'})
            registry = AdapterRegistry()
            registry.register('product', create_adapter())
            workspace = Workspaces(store).get(studio, project, 'product:0')
            token = current_user.set('fixture-user')
            try:
                with patch('server.codex_model.CodexModel.request_json') as model:
                    with self.assertRaises(PermissionError):
                        ExecutionService(store, registry).execute(
                            studio, project, 'product:0', workspace['revision'])
                    model.assert_not_called()
            finally:
                current_user.reset(token)
