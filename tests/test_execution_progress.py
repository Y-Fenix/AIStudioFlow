"""Diagnostic fixtures exercise durable queues, not a real provider."""
import json
import tempfile
import unittest
from unittest.mock import patch
from server.store import Store
from server.core.integrations import AdapterRegistry
from server.department_jobs import DepartmentExecutionQueue
from server.core.node_blocks.runtime import Runs
from server.core.node_blocks.service import Builder
from server.codex_model import current_diagnostic


class ExecutionProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name + '/platform.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('隔离诊断', self.studio)['id']
        self.registry = AdapterRegistry()

    def test_department_progress_is_durable_safe_and_does_not_change_workspace(self):
        queue = DepartmentExecutionQueue(self.store, self.registry)
        observed = []
        late = []
        test = self
        class Fixture:
            def execute(self, context):
                callback = current_diagnostic()
                test.assertTrue(callable(callback), 'department queue must install diagnostics')
                late.append(callback)
                callback({'state': 'running', 'assistant_chars': 234, 'events_received': 18,
                          'seconds_since_response': 80, 'idle_timeout_seconds': 600,
                          'api_key': 'NEVER-PERSIST', 'reason': 'NEVER-PERSIST',
                          'last_event': 'NEVER-PERSIST', 'prompt': 'NEVER-PERSIST'})
                current = queue.get(test.studio, test.project, job['id'])
                observed.append(current)
                with test.store.connection() as db:
                    test.assertEqual(db.execute("SELECT revision FROM studio_workspaces WHERE project_id=? AND node='product:0'", (test.project,)).fetchone()[0] if db.execute("SELECT 1 FROM studio_workspaces WHERE project_id=? AND node='product:0'", (test.project,)).fetchone() else 0, 0)
                return {'deliverable': '替身交付'}
        self.registry.register('product', Fixture())
        job = queue.enqueue(self.studio, self.project, 'product:0', 0)
        queue.run_once()
        value = observed[0]['progress']
        self.assertEqual(value['assistant_chars'], 234)
        self.assertEqual(value['state'], 'running')
        self.assertGreater(value['progress_updated_at'], 0)
        self.assertNotIn('NEVER-PERSIST', json.dumps(value))
        latest = DepartmentExecutionQueue(Store(str(self.store.path)), self.registry).get(self.studio, self.project, job['id'])
        self.assertEqual(latest['progress'], value)
        late[0]({'state': 'running', 'assistant_chars': 999})
        self.assertEqual(queue.get(self.studio, self.project, job['id'])['progress'], value)

    def test_custom_flow_progress_is_scoped_to_current_step_without_revision_churn(self):
        test = self
        observations = []
        callbacks = []
        class Fixture:
            def execute(self, context):
                callback = current_diagnostic()
                test.assertTrue(callable(callback), 'custom runner must install diagnostics')
                before = runs.get(test.studio, test.project, run['id'])
                test.assertEqual(before['progress']['state'], 'preparing')
                test.assertEqual(before['progress']['cursor'], before['cursor'])
                test.assertNotIn('assistant_chars', before['progress'])
                callback({'state': 'retrying', 'attempt': 2, 'max_attempts': 3, 'reason': 'secret'})
                after = runs.get(test.studio, test.project, run['id'])
                if callbacks:
                    callbacks[0]({'state': 'running', 'assistant_chars': 999})
                    test.assertEqual(runs.get(test.studio, test.project, run['id'])['progress'], after['progress'])
                callbacks.append(callback)
                test.assertEqual(before['revision'], after['revision'])
                observations.append(after['progress'])
                return {'deliverable': '替身流程交付'}
        self.registry.register('product', Fixture())
        builder = Builder(self.store)
        flow = builder.save_flow(self.studio, self.project, {'revision': 0, 'name': '进度验证', 'blocks': [
            {'id': 'one', 'type': 'node', 'config': {'node': 'product:0', 'auto_next': True}},
            {'id': 'two', 'type': 'node', 'config': {'node': 'product:1', 'auto_next': True}}]})
        runs = Runs(self.store, self.registry)
        run = runs.start(self.studio, self.project, {'flow': flow['id'], 'revision': flow['revision'], 'input': '隔离资料'})
        runs.tick();runs.tick();runs.tick()
        self.assertEqual([x['cursor'] for x in observations], [0, 1])
        self.assertTrue(all(x['state'] == 'retrying' for x in observations))
        self.assertNotIn('secret', json.dumps(observations))
        self.assertEqual(runs.get(self.studio, self.project, run['id'])['status'], 'completed')

    def test_bad_diagnostics_are_dropped_and_new_request_resets_old_counters(self):
        from server.core.execution_progress import ExecutionProgress
        queue = DepartmentExecutionQueue(self.store, self.registry)
        self.registry.register('product', type('Fixture', (), {'execute': lambda self, ctx: {'deliverable': 'fixture'}})())
        job = queue.enqueue(self.studio, self.project, 'product:0', 0)
        queue.claim()
        progress = ExecutionProgress(self.store, 'department_jobs', job['id'], {'model': 'actual-model', 'effort': 'high', 'source': 'relay'})
        progress.publish({'state': 'running', 'assistant_chars': 900, 'events_received': 2})
        progress.publish({'state': 'retrying', 'attempt': 2, 'max_attempts': 3})
        progress.publish({'state': 'started', 'requested_model': 'wrong-model', 'assistant_chars': float('nan'), 'events_received': -8})
        value = queue.get(self.studio, self.project, job['id'])['progress']
        self.assertEqual(value['requested_model'], 'actual-model')
        self.assertEqual(value['attempt'], 2)
        self.assertNotIn('assistant_chars', value)
        self.assertNotIn('events_received', value)

    def test_custom_flow_clears_actor_when_diagnostic_setup_fails(self):
        from server.core.identity import current_user
        from server.core.execution_progress import ExecutionProgress
        builder = Builder(self.store)
        flow = builder.save_flow(self.studio, self.project, {'revision': 0, 'name': '上下文清理', 'blocks': [
            {'id': 'one', 'type': 'template', 'config': {'text': '{{input}}'}}]})
        runs = Runs(self.store, self.registry)
        runs.start(self.studio, self.project, {'flow': flow['id'], 'revision': flow['revision'], 'input': '资料'})
        outer_token = current_user.set('worker-context-sentinel')
        self.addCleanup(current_user.reset, outer_token)
        before = current_user.get()
        with patch.object(ExecutionProgress, '__init__', side_effect=RuntimeError('setup failure')):
            with self.assertRaisesRegex(RuntimeError, 'setup failure'):
                runs.tick()
        self.assertEqual(current_user.get(), before)
