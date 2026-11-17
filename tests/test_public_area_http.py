"""Real HTTP/password deployment boundaries; all data in temporary installations."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from server.app import create_server
from server.store import Store

class PublicHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=self.tmp.name+'/central/db.sqlite'
        self.store=Store(self.path);self.studio=self.store.studios()[0]['id']
        self.project=self.store.create_project('Central',self.studio)['id']
        with ExitStack() as guards:
            for name in ('server.app.GenerationWorker','server.department_jobs.DepartmentExecutionWorker','server.core.node_blocks.runtime.BlockWorker','server.core.node_continuation.ContinuationWorker','server.core.testing_automation.TestingAutomationWorker','server.core.skill_library.SkillCleanupWorker'):
                guards.enter_context(patch(name,side_effect=AssertionError('public started execution worker')))
            self.server=create_server(port=0,database=self.path,runtime_mode='public')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        code,data,self.cookie=self.req('/api/auth/setup',{'username':'owner','name':'Owner','password':'Owner-test-1234'})
        self.assertEqual(code,201,data)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def req(self,path,body=None,cookie=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        conn.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),
            {'Content-Type':'application/json','Cookie':cookie if cookie is not None else getattr(self,'cookie','')})
        r=conn.getresponse();result=(r.status,json.loads(r.read()),r.getheader('Set-Cookie','').split(';')[0]);conn.close();return result
    def test_no_execution_or_private_routes_even_for_owner(self):
        for path,body in [('/api/ai-models',None),('/api/codex-handoff/redeem',{}),
            (f'/api/studios/{self.studio}/projects/{self.project}/summary',None),
            (f'/api/studios/{self.studio}/projects/{self.project}/workspace',{}),
            ('/api/gagasort/inspect',{}),('/api/admin/project-connection',{}),('/api/integrations',None)]:
            with self.subTest(path=path):self.assertEqual(self.req(path,body)[0],403)
        self.assertEqual(self.req('/api/runtime')[1]['mode'],'public')
        self.assertEqual(self.req('/api/studios')[0],200)
        self.assertEqual(self.req('/api/ai-models',cookie='')[0],403)
    def test_public_versions_routes_and_registration_are_separate(self):
        base=f'/api/studios/{self.studio}/projects/{self.project}/public'
        self.assertEqual(self.req(base+'/versions',{'name':'1.0'})[0],201)
        self.assertEqual(len(self.req(base+'/versions')[1]['items']),1)
        self.assertEqual(self.req(base+'/items')[1]['total'],0)
        code,data,_=self.req('/api/auth/register',{'username':'member','name':'Member','password':'Member-test-1234'})
        self.assertEqual(code,201,data);self.assertEqual(data['user']['status'],'pending')
        _,_,cookie=self.req('/api/auth/login',{'username':'member','password':'Member-test-1234'})
        self.assertEqual(self.req(base+'/items',cookie=cookie)[0],403)
    def test_public_cannot_disable_password_auth(self):
        self.assertEqual(self.req('/api/admin/auth',{'mode':'local'})[0],403)
        self.assertEqual(self.req('/api/admin/auth')[1]['mode'],'password')

    def test_personal_never_starts_notification_sender(self):
        with patch('server.core.notifications.NotificationWorker',side_effect=AssertionError('personal started sender')):
            personal=create_server(port=0,database=self.tmp.name+'/personal/db.sqlite',runtime_mode='personal')
            personal.server_close()

    def test_runtime_defaults_use_three_separate_databases(self):
        root=Path(self.tmp.name)/'defaults'
        for mode,relative in [('personal','data/personal/platform.sqlite'),('public','data/public-area/platform.sqlite'),('team','data/platform.sqlite')]:
            with self.subTest(mode=mode),patch('server.app.ROOT',root):
                service=create_server(port=0,runtime_mode=mode)
                try:
                    self.assertTrue((root/relative).is_file())
                finally:service.server_close()

    def test_personal_rejects_non_loopback_and_public_rejects_local_bypass(self):
        with self.assertRaises(ValueError):create_server(host='0.0.0.0',port=0,database=self.tmp.name+'/p/db.sqlite',runtime_mode='personal')
        with self.assertRaises(ValueError):create_server(port=0,database=self.tmp.name+'/q/db.sqlite',runtime_mode='public',local_development=True)

if __name__=='__main__':unittest.main()
