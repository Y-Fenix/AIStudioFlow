"""Real password/session HTTP workflows against isolated SQLite, no external login."""
import http.client
import json
import tempfile
import threading
import unittest

from server.app import create_server
from server.store import Store


class LocalAccountHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = self.temp.name + '/platform.sqlite'
        self.store = Store(self.path)
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('原有项目', self.studio)['id']
        self.server = create_server('127.0.0.1', 0, self.path)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = '127.0.0.1:' + str(self.server.server_port)
        self.password = 'Owner-example-2026'
        self.owner = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, cookie='', headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        request_headers = {'Host': self.host, 'Content-Type': 'application/json'}
        if cookie:
            request_headers['Cookie'] = cookie
        request_headers.update(headers or {})
        client.request('POST' if body is not None else 'GET', path,
                       json.dumps(body) if body is not None else None, request_headers)
        response = client.getresponse()
        status, cookies = response.status, response.getheader('Set-Cookie', '')
        result = json.loads(response.read())
        client.close()
        return status, result, cookies

    def setup_owner(self):
        code, result, cookie = self.request('/api/auth/setup', {
            'username': 'Studio.Owner', 'name': '工作室负责人', 'password': self.password})
        self.assertEqual(code, 201, result)
        self.owner = cookie.split(';')[0]
        return result

    def register(self, username='tester', password='Tester-example-2026', **extra):
        return self.request('/api/auth/register', {
            'username': username, 'name': '测试同事', 'password': password, **extra})

    def test_default_requires_login_and_setup_is_only_available_on_direct_loopback(self):
        self.assertEqual(self.request('/api/studios')[0], 401)
        code, public, _ = self.request('/api/auth/public')
        self.assertEqual(code, 200)
        self.assertEqual(public['mode'], 'password')
        self.assertTrue(public['setup_required'])
        self.assertTrue(public['setup_available'])
        for headers in ({'Host': 'studio.example.com'}, {'X-Forwarded-For': '10.1.2.3'},
                        {'Forwarded': 'for=10.1.2.3'}, {'X-Forwarded-Host': self.host},
                        {'X-Forwarded-Proto': 'https'}):
            with self.subTest(headers=headers):
                self.assertFalse(self.request('/api/auth/public', headers=headers)[1]['setup_available'])
                self.assertEqual(self.request('/api/auth/setup', {'username': 'hijack',
                    'name': 'hijack', 'password': self.password}, headers=headers)[0], 403)
        self.assertEqual(self.register()[0], 400, 'registration waits for owner setup')

    def test_setup_preserves_owner_identity_data_and_cannot_be_replayed(self):
        result = self.setup_owner()
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result['user']['id'], 'local')
        self.assertEqual(result['user']['global_role'], 'project_lead')
        self.assertEqual(self.request('/api/studios', cookie=self.owner)[1]['items'][0]['id'], self.studio)
        self.assertEqual(self.request(f'/api/studios/{self.studio}/projects/{self.project}', cookie=self.owner)[0], 200)
        self.assertEqual(self.request('/api/auth/setup', {'username': 'hijack', 'name': 'hijack', 'password': self.password})[0], 400)
        self.assertFalse(self.request('/api/auth/public')[1]['setup_required'])
        self.assertEqual(self.request('/api/studios')[0], 401, 'loopback cannot bypass password after setup')

    def test_register_pending_approval_then_login_homepage_and_permissions(self):
        self.setup_owner()
        code, registered, _ = self.register(global_role='project_lead', status='active', user_id='local')
        self.assertEqual(code, 201, registered)
        actor = registered['user']['id']
        self.assertNotEqual(actor, 'local')
        self.assertEqual(registered['user']['status'], 'pending')
        self.assertEqual(registered['user']['global_role'], 'member')
        code, session, cookie = self.request('/api/auth/login', {'username': 'TESTER', 'password': 'Tester-example-2026'})
        self.assertEqual(code, 200, session)
        member = cookie.split(';')[0]
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Lax', cookie)
        self.assertEqual(self.request('/api/studios', cookie=member)[0], 403)
        self.assertEqual(self.request('/api/admin/overview', cookie=member)[0], 403)
        code, approved, _ = self.request('/api/admin/members', {'user_id': actor,
            'studio_id': self.studio, 'project_id': self.project, 'department': 'testing'}, self.owner)
        self.assertEqual(code, 200, approved)
        self.assertEqual(self.request('/api/auth/session', cookie=member)[1]['user']['status'], 'active')
        self.assertEqual(self.request('/api/me/preferences', cookie=member)[1]['default_workspace'], 'testing')
        self.assertEqual(self.request('/api/studios', cookie=member)[0], 200)
        self.assertEqual(self.request('/api/admin/auth', {}, member)[0], 403)
        self.assertEqual(self.request('/api/auth/logout', {}, member)[0], 200)
        self.assertEqual(self.request('/api/auth/session', cookie=member)[0], 401)

    def test_password_hash_salts_duplicates_and_generic_login_errors(self):
        self.setup_owner()
        self.assertEqual(self.register()[0], 201)
        self.assertEqual(self.register(username='TESTER')[0], 400)
        self.assertEqual(self.register(username='tester-two')[0], 201)
        with self.store.connection() as db:
            rows = db.execute('SELECT * FROM local_credentials').fetchall()
            dump = '\n'.join(db.iterdump())
        self.assertEqual(len(rows), 3)
        self.assertNotIn(self.password, dump)
        self.assertNotIn('Tester-example-2026', dump)
        self.assertEqual(len({r['password_hash'] for r in rows}), 3)
        wrong = self.request('/api/auth/login', {'username': 'tester', 'password': 'wrong-password'})
        missing = self.request('/api/auth/login', {'username': 'nobody', 'password': 'wrong-password'})
        self.assertEqual(wrong[0], 401)
        self.assertEqual(wrong[1], missing[1])
        code, overview, _ = self.request(f'/api/admin/overview?studio={self.studio}', cookie=self.owner)
        self.assertEqual(code, 200)
        self.assertNotIn('password_hash', json.dumps(overview))

    def test_invalid_registration_and_cross_site_setup_are_rejected(self):
        self.assertEqual(self.request('/api/auth/setup', {'username': 'owner', 'name': 'Owner', 'password': self.password},
            headers={'Origin': 'https://evil.example'})[0], 403)
        self.setup_owner()
        for username, password in [('ab', self.password), ('../../bad', self.password),
                                   ('tester', 'short'), ('tester', 'x' * 129)]:
            with self.subTest(username=username, size=len(password)):
                self.assertEqual(self.register(username, password)[0], 400)
        self.assertEqual(self.request('/api/auth/register',
            {'username': 'tester', 'name': '', 'password': self.password})[0], 400)
        self.assertEqual(self.request('/auth/feishu/login')[0], 400, 'password mode disables OAuth')

    def test_rate_limit_survives_service_instances_and_never_creates_session(self):
        self.setup_owner()
        responses = [self.request('/api/auth/login', {'username': 'studio.owner', 'password': 'wrong-password'})[0]
                     for _ in range(11)]
        self.assertEqual(responses[-1], 429)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM auth_sessions').fetchone()[0], 1)
        from server.core.local_accounts import LocalAccounts, LoginThrottled
        with self.assertRaises(LoginThrottled):
            LocalAccounts(Store(self.path)).login({'username': 'studio.owner', 'password': self.password}, '127.0.0.1')

    def test_change_password_admin_reset_disable_and_session_expiry(self):
        self.setup_owner()
        actor = self.register()[1]['user']['id']
        member = self.request('/api/auth/login', {'username': 'tester', 'password': 'Tester-example-2026'})[2].split(';')[0]
        self.assertEqual(self.request('/api/auth/password', {'current_password': 'wrong-password', 'password': 'New-password-2026'}, member)[0], 401)
        self.assertEqual(self.request('/api/auth/password', {'current_password': 'Tester-example-2026', 'password': 'New-password-2026'}, member)[0], 200)
        self.assertEqual(self.request('/api/auth/session', cookie=member)[0], 401)
        member = self.request('/api/auth/login', {'username': 'tester', 'password': 'New-password-2026'})[2].split(';')[0]
        self.assertEqual(self.request('/api/admin/users/password', {'user_id': 'local', 'password': 'Hijack-password-2026'}, member)[0], 403)
        self.assertEqual(self.request('/api/admin/users/password', {'user_id': actor, 'password': 'Reset-password-2026'}, self.owner)[0], 200)
        self.assertEqual(self.request('/api/auth/session', cookie=member)[0], 401)
        self.assertEqual(self.request('/api/auth/login', {'username': 'tester', 'password': 'New-password-2026'})[0], 401)
        member = self.request('/api/auth/login', {'username': 'tester', 'password': 'Reset-password-2026'})[2].split(';')[0]
        self.assertEqual(self.request('/api/admin/users/status', {'user_id': actor, 'status': 'disabled'}, self.owner)[0], 200)
        self.assertEqual(self.request('/api/auth/session', cookie=member)[0], 401)
        self.assertEqual(self.request('/api/auth/login', {'username': 'tester', 'password': 'Reset-password-2026'})[0], 401)
        with self.store.connection() as db:
            db.execute('UPDATE auth_sessions SET expires=0')
        self.assertEqual(self.request('/api/auth/session', cookie=self.owner)[0], 401)

    def test_registration_switch_secure_cookie_and_terminal_recovery(self):
        self.setup_owner()
        code, result, _ = self.request('/api/admin/auth', {'mode': 'password',
            'public_url': 'https://studio.mygame.dev', 'registration_open': False}, self.owner)
        self.assertEqual(code, 200, result)
        self.assertEqual(self.register()[0], 403)
        self.assertFalse(self.request('/api/auth/public')[1]['registration_open'])
        login = self.request('/api/auth/login', {'username': 'studio.owner', 'password': self.password})
        self.assertEqual(login[0], 200)
        self.assertIn('Secure', login[2])
        from tools.local_account_admin import recover_password
        recover_password(self.store, 'STUDIO.OWNER', 'Recovered-password-2026')
        self.assertEqual(self.request('/api/auth/session', cookie=self.owner)[0], 401)
        self.assertEqual(self.request('/api/auth/login', {'username': 'studio.owner', 'password': self.password})[0], 401)
        recovered = self.request('/api/auth/login', {'username': 'studio.owner', 'password': 'Recovered-password-2026'})
        self.assertEqual(recovered[0], 200)
        self.assertEqual(recovered[1]['user']['global_role'], 'project_lead')
        with self.assertRaises(ValueError):
            recover_password(self.store, 'not-created', 'Recovered-password-2026')

    def test_concurrent_owner_setup_can_only_succeed_once(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.request, '/api/auth/setup', {
                'username': username, 'name': username, 'password': self.password})
                for username in ('owner-one', 'owner-two')]
            codes = [f.result()[0] for f in futures]
        self.assertEqual(sorted(codes), [201, 400])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM local_credentials').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM auth_sessions').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
