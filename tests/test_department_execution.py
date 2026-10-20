import tempfile
import unittest
from unittest.mock import patch

from server.ai_models import ModelSettings, current_selection
from server.core.integrations import AdapterRegistry, ExecutionService
from server.node_skills import current_skill
from server.node_skills import validate
from server.studio_workspaces import Workspaces
from server.store import Store


class DepartmentExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name + '/db.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('Adapter contract', self.studio)['id']
        self.workspaces = Workspaces(self.store)
        self.registry = AdapterRegistry()

    def tearDown(self):
        self.temp.cleanup()

    def test_execute_permission_revoked_during_execution_prevents_saving_output(self):
        from server.core.admin import Administration
        from server.core.identity import current_user
        admin = Administration(self.store)
        with self.store.connection() as db:
            db.execute('''INSERT INTO users(id,tenant_key,open_id,name,status)
                VALUES('researcher','tenant','researcher','研究员','active')''')
        admin.member({'user_id': 'researcher', 'studio_id': self.studio,
                      'project_id': self.project, 'department': 'product'})
        studio, project = self.studio, self.project

        class Adapter:
            def execute(inner, context):
                token = current_user.set('local')
                try:
                    admin.rule({'subject_type': 'user', 'subject_id': 'researcher',
                                'studio_id': studio, 'project_id': project,
                                'department': 'product', 'node': 'product:0',
                                'resource': 'node', 'action': 'execute', 'effect': 'deny'})
                finally:
                    current_user.reset(token)
                return {'deliverable': 'revoked output must not be saved'}

        self.registry.register('product', Adapter())
        token = current_user.set('researcher')
        try:
            with self.assertRaises(PermissionError):
                ExecutionService(self.store, self.registry).execute(self.studio, self.project, 'product:0', 0)
            self.assertEqual(self.workspaces.get(self.studio, self.project, 'product:0')['deliverable'], '')
        finally:
            current_user.reset(token)

    def test_adapter_receives_the_current_imported_skill_content(self):
        node = 'product:0'
        workspace = self.workspaces.get(self.studio, self.project, node)
        content = validate('# Product research\nUse source-backed evidence only.')
        workspace = self.workspaces.save(self.studio, self.project, node, {
            'revision': workspace['revision'], 'skill': content,
        })
        captured = {}

        class Adapter:
            def execute(self, context):
                captured['skill_content'] = context.skill_content
                return {'deliverable': 'Research brief'}

        self.registry.register('product', Adapter())
        result = ExecutionService(self.store, self.registry).execute(
            self.studio, self.project, node, workspace['revision'])

        self.assertEqual(captured['skill_content'], content)
        self.assertEqual(result['workspace']['deliverable'], 'Research brief')

    def test_adapter_receives_the_default_skill_content(self):
        node = 'design:0'
        workspace = self.workspaces.get(self.studio, self.project, node)
        captured = {}

        class Adapter:
            def execute(self, context):
                captured['skill_content'] = context.skill_content
                return {'deliverable': 'Visual direction'}

        self.registry.register('design', Adapter())
        ExecutionService(self.store, self.registry).execute(
            self.studio, self.project, node, workspace['revision'])

        self.assertEqual(captured['skill_content'], workspace['skill']['content'])

    def test_adapter_model_call_uses_the_saved_model_and_skill_snapshot(self):
        settings = ModelSettings(self.store)
        settings.save_custom({
            'base_url': 'https://models.example.test/v1', 'protocol': 'responses',
            'model': 'studio-model-v1', 'effort': 'high', 'api_key': 'test-key',
        })
        node = 'product:0'
        workspace = self.workspaces.get(self.studio, self.project, node)
        skill = validate('# Snapshot\nUse the accepted project rules.')
        workspace = self.workspaces.save(self.studio, self.project, node, {
            'revision': workspace['revision'], 'skill': skill,
        })
        captured = {}

        def fake_model_call(_client, prompt):
            captured['prompt'] = prompt
            captured['selection'] = current_selection()
            captured['skill'] = current_skill()
            return {'deliverable': 'AI research brief'}

        class Adapter:
            def execute(self, context):
                answer = context.model.request_json('Create a research brief from these inputs.')
                return {'deliverable': answer['deliverable']}

        self.registry.register('product', Adapter())
        with patch('server.codex_model.CodexModel.request_json', fake_model_call):
            result = ExecutionService(self.store, self.registry).execute(
                self.studio, self.project, node, workspace['revision'])

        self.assertEqual(captured['selection']['model'], 'studio-model-v1')
        self.assertEqual(captured['selection']['source'], 'custom')
        self.assertEqual(captured['skill'], skill)
        self.assertEqual(result['workspace']['deliverable'], 'AI research brief')

    def test_gm_capability_requires_scoped_grant_and_explicit_test_environment(self):
        from server.core.admin import Administration
        from server.core.integrations import GmCapability
        from server.core.permissions import AccessDenied, Policy

        user = 'department-member'
        with self.store.connection() as db:
            db.execute('INSERT INTO users(id,tenant_key,open_id,name,status) VALUES(?,?,?,?,?)',
                       (user, 'tenant-a', 'member-open-id', '部门成员', 'active'))
        admin = Administration(self.store)
        admin.member({'user_id': user, 'studio_id': self.studio, 'project_id': self.project,
                      'department': 'product'})
        cap = GmCapability(self.store, user, self.studio, self.project, 'product:0')
        self.assertFalse(Policy(self.store).allowed('gm', 'execute', self.studio, self.project,
                                                   node='product:0', actor=user))
        with self.assertRaises(AccessDenied):
            cap.call_read('gm_query_game_list', {'env': 'test'})

        grant = admin.rule({'subject_type': 'user', 'subject_id': user, 'studio_id': self.studio,
                            'project_id': self.project, 'department': 'product', 'node': 'product:0',
                            'resource': 'gm', 'action': 'execute', 'effect': 'allow'})
        with patch('server.connectors.gm.GmClient.call_read', return_value={'games': []}) as call:
            self.assertEqual(cap.call_read('gm_query_game_list', {'env': 'test'}), {'games': []})
            call.assert_called_once_with('gm_query_game_list', {'env': 'test'})
        with self.assertRaisesRegex(ValueError, '必须明确指定 env=test'):
            cap.call_read('gm_query_game_list', {})
        with self.assertRaisesRegex(ValueError, '必须明确指定 env=test'):
            cap.call_read('gm_query_game_list', {'env': 'release'})

        other_node = GmCapability(self.store, user, self.studio, self.project, 'product:1')
        with self.assertRaises(AccessDenied):
            other_node.call_read('gm_query_game_list', {'env': 'test'})
        admin.revoke(grant['id'])
        with self.assertRaises(AccessDenied):
            cap.call_read('gm_query_game_list', {'env': 'test'})

    def test_gm_grant_is_exact_resource_and_never_inherited_from_node(self):
        from server.core.admin import Administration
        from server.core.permissions import Policy
        user = 'node-member'
        with self.store.connection() as db:
            db.execute('INSERT INTO users(id,tenant_key,open_id,name,status) VALUES(?,?,?,?,?)',
                       (user, 'tenant-a', 'node-open-id', '节点成员', 'active'))
        Administration(self.store).member({'user_id': user, 'studio_id': self.studio,
                                             'project_id': self.project, 'department': 'product'})
        policy = Policy(self.store)
        self.assertTrue(policy.allowed('node', 'execute', self.studio, self.project,
                                       node='product:0', actor=user))
        self.assertFalse(policy.allowed('gm', 'execute', self.studio, self.project,
                                        node='product:0', actor=user))


if __name__ == '__main__':
    unittest.main()
