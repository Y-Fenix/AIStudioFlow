import json
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server.app import create_server
from server.core.integrations import AdapterRegistry


class DepartmentJobsHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.started = threading.Event()
        self.release = threading.Event()
        registry = AdapterRegistry()

        class SlowAdapter:
            def execute(inner, context):
                self.started.set()
                if not self.release.wait(5):
                    raise ValueError('fixture release timed out')
                return {'deliverable': 'HTTP 调研结果'}

        registry.register('product', SlowAdapter())
        self.server = create_server('127.0.0.1', 0, self.temp.name + '/platform.sqlite', registry=registry, local_development=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, session=None):
        request = Request(self.url + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json',
                                   **({'Cookie': 'studioflow_session='+session} if session else {})})
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_http_execution_returns_quickly_then_exposes_running_and_completed_states(self):
        _, studios = self.request('/api/studios')
        studio = studios['items'][0]['id']
        _, project = self.request(f'/api/studios/{studio}/projects', {'name': 'HTTP 队列'})
        route = f"/api/studios/{studio}/projects/{project['id']}"
        _, workspace = self.request(route + '/workspace?node=product:0')

        code, job = self.request(route + '/workspace/execute?node=product:0', {'revision': workspace['revision']})
        self.assertEqual(code, 202)
        self.assertEqual(job['status'], 'queued')
        self.assertTrue(self.started.wait(2))

        code, running = self.request(route + '/workspace/job?node=product:0')
        self.assertEqual(code, 200)
        self.assertEqual(running['status'], 'running')

        self.release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            _, current = self.request(route + '/department-jobs/' + job['id'])
            if current['status'] == 'completed':
                break
            time.sleep(.02)
        self.assertEqual(current['status'], 'completed')
        self.assertEqual(current['result']['workspace']['deliverable'], 'HTTP 调研结果')

    def test_job_responses_redact_skill_content_using_current_node_permissions(self):
        from server.core.admin import Administration
        from server.core.auth import digest
        from server.store import Store
        store = Store(self.temp.name + '/platform.sqlite')
        studio = store.studios()[0]['id']
        project = store.create_project('受限 Skill', studio)['id']
        admin = Administration(store)
        with store.connection() as db:
            db.execute('''INSERT INTO users(id,tenant_key,open_id,name,status)
                VALUES('reviewer','tenant','reviewer','审核员','active')''')
            db.execute('INSERT INTO auth_sessions(token_hash,user_id,expires) VALUES(?,?,?)',
                       (digest('reviewer-cookie'), 'reviewer', time.time()+3600))
        admin.member({'user_id': 'reviewer', 'studio_id': studio,
                      'project_id': project, 'department': 'product'})
        route = f'/api/studios/{studio}/projects/{project}'
        _, workspace = self.request(route + '/workspace?node=product:0')
        private_skill = '# Private policy\nThis body must not appear in a job response.'
        self.request(route + '/workspace?node=product:0', {'revision': workspace['revision'], 'skill': private_skill})
        _, job = self.request(route + '/workspace/execute?node=product:0', {'revision': 1})
        self.assertTrue(self.started.wait(2))
        self.release.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            code, completed = self.request(route + '/department-jobs/' + job['id'])
            if completed['status'] == 'completed':
                break
            time.sleep(.02)
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(completed['result']['workspace']['skill']['content'], private_skill)
        admin.rule({'subject_type': 'user', 'subject_id': 'reviewer', 'studio_id': studio,
                    'project_id': project, 'department': 'product', 'node': 'product:0',
                    'resource': 'skill', 'action': 'view', 'effect': 'deny'})
        for endpoint in ('/department-jobs/'+job['id'], '/workspace/job?node=product:0'):
            code, value = self.request(route + endpoint, session='reviewer-cookie')
            self.assertEqual(code, 200)
            self.assertEqual(value['result']['workspace']['skill']['content'], '')
            self.assertNotIn(private_skill, json.dumps(value, ensure_ascii=False))
        code, owner_value = self.request(route + '/department-jobs/' + job['id'])
        self.assertEqual(owner_value['result']['workspace']['skill']['content'], private_skill)


if __name__ == '__main__':
    unittest.main()
