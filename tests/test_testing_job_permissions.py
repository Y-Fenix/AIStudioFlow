"""QA legacy queue authorization uses explicit identities and model fixtures only."""
import tempfile
import threading
import time
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from server.core.admin import Administration
from server.core.identity import current_user
from server.jobs import GenerationWorker
from server.store import Store
from server.processes import run
from server.core.queued_operations import authorize_testing_job


class TestingJobPermissionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'queue.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('QA 权限', self.studio)['id']
        self.task = self.store.create_task(self.project, '用例生成')['id']
        self.store.import_requirement(self.project, self.task, 'fixture', '保存用户音量设置')
        with self.store.connection() as db:
            db.execute('''INSERT INTO users(id,tenant_key,open_id,name,status)
                VALUES('tester','tenant-a','tester','测试成员','active')''')
        self.admin = Administration(self.store)
        self.admin.member({'user_id': 'tester', 'studio_id': self.studio,
                           'project_id': self.project, 'department': 'testing'})

    def enqueue(self):
        token = current_user.set('tester')
        try:
            return self.store.enqueue_generation(self.project, self.task)
        finally:
            current_user.reset(token)

    def revoke(self):
        self.admin.rule({'subject_type': 'user', 'subject_id': 'tester',
                         'studio_id': self.studio, 'project_id': self.project,
                         'department': 'testing', 'node': 'testing:0',
                         'resource': 'node', 'action': 'execute', 'effect': 'deny'})

    def wait_finished(self, job):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            with self.store.connection() as db:
                row = dict(db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
            if row['status'] not in ('queued', 'running'):
                return row
            threading.Event().wait(.02)
        self.fail('fixture worker did not finish')

    def close_worker(self, worker):
        worker.stop.set()
        worker.thread.join(5)
        self.assertFalse(worker.thread.is_alive())

    def test_job_persists_the_enqueuing_actor(self):
        self.assertEqual(self.enqueue().get('actor'), 'tester')

    def test_revoked_queued_job_never_calls_the_model(self):
        job = self.enqueue()
        self.revoke()
        with patch('server.jobs.CodexModel.generate', return_value={'cases': []}) as generate:
            worker = GenerationWorker(self.store)
            try:
                result = self.wait_finished(job)
            finally:
                self.close_worker(worker)
        self.assertEqual(result['status'], 'failed')
        generate.assert_not_called()
        self.assertEqual(self.store.task(self.project, self.task)['artifacts'], {})

    def test_revocation_during_model_work_discards_output_and_preserves_actor_identity(self):
        started, release = threading.Event(), threading.Event()
        actors = []

        def generate(_client, _requirements):
            actors.append(current_user.get())
            started.set()
            if not release.wait(4):
                raise ValueError('fixture timed out')
            return {'cases': []}

        with patch('server.jobs.CodexModel.generate', generate):
            worker = GenerationWorker(self.store)
            try:
                job = self.enqueue()
                self.assertTrue(started.wait(3))
                self.revoke()
                release.set()
                result = self.wait_finished(job)
            finally:
                release.set()
                self.close_worker(worker)
        self.assertEqual(actors, ['tester'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.store.task(self.project, self.task)['artifacts'], {})

    def test_migration_does_not_run_legacy_pending_jobs_without_creator_identity(self):
        with self.store.connection() as db:
            db.execute('''INSERT INTO jobs(id,project_id,task_id,revision)
                VALUES('legacy',?,?,1)''', (self.project, self.task))
            db.execute('''INSERT INTO jobs(id,project_id,task_id,revision,status)
                VALUES('historical',?,?,1,'completed')''', (self.project, self.task))
        reopened = Store(self.store.path)
        with reopened.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM jobs WHERE id='legacy'").fetchone()['status'], 'failed')
            self.assertEqual(db.execute("SELECT status FROM jobs WHERE id='historical'").fetchone()['status'], 'completed')
        self.assertIsNone(reopened.claim_generation())

    def test_revocation_stops_a_real_running_subprocess(self):
        ready = Path(self.temp.name) / 'process-ready'
        def generate(_client, _requirements):
            script = ('import os,time; from pathlib import Path; '
                      f'Path({str(ready)!r}).write_text(str(os.getpid())); time.sleep(30)')
            run([sys.executable, '-c', script], capture_output=True, timeout=8)
            return {'cases': []}

        with patch('server.jobs.CodexModel.generate', generate):
            worker = GenerationWorker(self.store)
            try:
                job = self.enqueue()
                deadline = time.monotonic() + 3
                while not ready.exists() and time.monotonic() < deadline:
                    threading.Event().wait(.02)
                self.assertTrue(ready.exists(), 'real fixture process did not start')
                pid = int(ready.read_text())
                self.revoke()
                result = self.wait_finished(job)
            finally:
                self.close_worker(worker)
        self.assertEqual(result['status'], 'failed')
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertEqual(self.store.task(self.project, self.task)['artifacts'], {})

    def test_code_job_requires_current_project_repository_binding(self):
        repository = Path(self.temp.name) / 'authorized-code'
        repository.mkdir()
        task = self.store.task(self.project, self.task)
        self.store.bind_execution(self.project, self.task, {'repository': str(repository)}, task['revision'])
        job = {'actor': 'tester', 'kind': 'execute', 'project_id': self.project, 'task_id': self.task}
        with self.store.connection() as db:
            db.execute('INSERT INTO project_connections(project_id,repository,updated_by) VALUES(?,?,?)',
                       (self.project, str(repository), 'local'))
        authorize_testing_job(self.store, job)
        with self.store.connection() as db:
            db.execute('UPDATE project_connections SET repository=? WHERE project_id=?',
                       (str(repository.parent / 'different-code'), self.project))
        with self.assertRaisesRegex(PermissionError, '代码目录授权已变化'):
            authorize_testing_job(self.store, job)


if __name__ == '__main__':
    unittest.main()
