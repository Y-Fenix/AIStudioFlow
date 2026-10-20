import tempfile
import unittest

from server.core.integrations import AdapterRegistry
from server.department_jobs import DepartmentExecutionQueue
from server.store import Store
from server.studio_workspaces import Workspaces


class DepartmentExecutionQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name + '/platform.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('游戏', self.studio)['id']
        self.registry = AdapterRegistry()
        self.workspaces = Workspaces(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_execution_is_queued_and_persisted_before_adapter_runs(self):
        calls = []

        class Adapter:
            def execute(self, context):
                calls.append(context.node_id)
                return {'deliverable': '调研简报', 'evidence': ['来源A'], 'gaps': []}

        self.registry.register('product', Adapter())
        workspace = self.workspaces.get(self.studio, self.project, 'product:0')
        queue = DepartmentExecutionQueue(self.store, self.registry)
        job = queue.enqueue(self.studio, self.project, 'product:0', workspace['revision'])
        self.assertEqual(job['status'], 'queued')
        self.assertEqual(calls, [])
        self.assertEqual(queue.get(self.studio, self.project, job['id'])['status'], 'queued')

    def test_worker_saves_adapter_output_and_persists_terminal_status(self):
        class Adapter:
            def execute(self, context):
                return {'deliverable': '调研简报', 'evidence': ['来源A'], 'gaps': ['数据待补']}

        self.registry.register('product', Adapter())
        workspace = self.workspaces.get(self.studio, self.project, 'product:0')
        queue = DepartmentExecutionQueue(self.store, self.registry)
        job = queue.enqueue(self.studio, self.project, 'product:0', workspace['revision'])
        self.assertTrue(queue.run_once())
        latest = queue.get(self.studio, self.project, job['id'])
        self.assertEqual(latest['status'], 'completed')
        self.assertEqual(latest['result']['workspace']['deliverable'], '调研简报')
        self.assertEqual(latest['result']['evidence'], ['来源A'])

    def test_worker_records_failure_without_faking_a_deliverable(self):
        class Adapter:
            def execute(self, context):
                raise ValueError('外部模型连接失败')

        self.registry.register('product', Adapter())
        workspace = self.workspaces.get(self.studio, self.project, 'product:0')
        queue = DepartmentExecutionQueue(self.store, self.registry)
        job = queue.enqueue(self.studio, self.project, 'product:0', workspace['revision'])
        queue.run_once()
        latest = queue.get(self.studio, self.project, job['id'])
        self.assertEqual(latest['status'], 'failed')
        self.assertEqual(latest['error'], '外部模型连接失败')
        self.assertEqual(self.workspaces.get(self.studio, self.project, 'product:0')['deliverable'], '')

    def test_restart_marks_running_job_interrupted_without_retry(self):
        self.registry.register('product', type('Adapter', (), {'execute': lambda self, context: {'deliverable': 'x'}})())
        workspace = self.workspaces.get(self.studio, self.project, 'product:0')
        queue = DepartmentExecutionQueue(self.store, self.registry)
        job = queue.enqueue(self.studio, self.project, 'product:0', workspace['revision'])
        queue.claim()
        recovered = DepartmentExecutionQueue(self.store, self.registry)
        recovered.recover()
        self.assertEqual(recovered.get(self.studio, self.project, job['id'])['status'], 'interrupted')
        self.assertFalse(recovered.run_once())

    def test_execution_permission_is_rechecked_after_a_job_is_queued(self):
        from server.core.admin import Administration
        from server.core.identity import current_user

        with self.store.connection() as db:
            db.execute('INSERT INTO users(id,tenant_key,open_id,name,status) VALUES(?,?,?,?,?)',
                       ('researcher', 'tenant-a', 'open-researcher', '研究员', 'active'))
        admin = Administration(self.store)
        admin.member({'user_id': 'researcher', 'studio_id': self.studio,
                      'project_id': self.project, 'department': 'product'})
        self.registry.register('product', type('Adapter', (), {
            'execute': lambda self, context: {'deliverable': 'must not save'}})())
        workspace = self.workspaces.get(self.studio, self.project, 'product:0')
        identity = current_user.set('researcher')
        try:
            queue = DepartmentExecutionQueue(self.store, self.registry)
            job = queue.enqueue(self.studio, self.project, 'product:0', workspace['revision'])
        finally:
            current_user.reset(identity)
        admin.rule({'subject_type': 'user', 'subject_id': 'researcher',
                    'studio_id': self.studio, 'project_id': self.project,
                    'department': 'product', 'node': 'product:0', 'resource': 'node',
                    'action': 'execute', 'effect': 'deny'})
        queue.run_once()
        self.assertEqual(queue.get(self.studio, self.project, job['id'], actor='researcher')['status'], 'failed')
        self.assertEqual(self.workspaces.get(self.studio, self.project, 'product:0')['deliverable'], '')

    def test_worker_survives_a_transient_queue_storage_error(self):
        import threading
        from server.department_jobs import DepartmentExecutionWorker

        class Queue:
            def __init__(self):
                self.calls = 0

            def run_once(inner):
                inner.calls += 1
                if inner.calls == 1:
                    raise OSError('temporary database I/O error')
                worker.stop.set()
                return False

        worker = object.__new__(DepartmentExecutionWorker)
        worker.queue = Queue()
        worker.stop = threading.Event()
        worker.run()
        self.assertEqual(worker.queue.calls, 2)


if __name__ == '__main__':
    unittest.main()
