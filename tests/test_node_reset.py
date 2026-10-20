import json
import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.publication import PublicationLedger
from server.status_change import StatusChanges

class NodeResetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite')
        self.project=self.store.create_project('重置样例')['id']
        self.task=self.store.create_task(self.project,'节点重跑')
        self.task=self.store.import_requirement(self.project,self.task['id'],'需求','保存音量')
        self.original={str(i):{'ready_for_review':True,'marker':i} for i in range(6)}
        self.original['4']['linked_records']=[{'record_id':'recFixture','root_cause_id':'R'}]
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET stage=5,status='completed',artifacts=?,binding=?,attribution=?,regression=?,node_skills=? WHERE id=?",
                (json.dumps(self.original),'{"branch":"master"}','{"old":"candidate"}','{"old":"regression"}',
                 '{"0":{"name":"自定义","content":"自定义规则"}}',self.task['id']))
        self.task=self.store.task(self.project,self.task['id'])

    def test_all_six_resets_archive_and_invalidate_only_from_requested_stage(self):
        for stage in range(6):
            with self.subTest(stage=stage):
                with self.store.connection() as db:
                    db.execute("UPDATE tasks SET stage=5,status='completed',artifacts=? WHERE id=?",(json.dumps(self.original),self.task['id']))
                before=self.store.task(self.project,self.task['id'])
                current=self.store.reset_node(self.project,self.task['id'],stage,before['revision'],'修正范围',True)
                self.assertEqual(current['stage'],stage)
                self.assertEqual(current['status'],'waiting_user')
                self.assertEqual(set(current['artifacts']),{str(i) for i in range(stage)})
                self.assertEqual(current['requirements'],before['requirements'])
                self.assertEqual(current['node_skills'],before['node_skills'])
                self.assertEqual(current['binding'],before['binding'])
                self.assertEqual(current['regression'],{})
                self.assertEqual(current['events'][-1]['stage'],stage)
                self.assertEqual(current['reset_history'][-1]['remote_records'][0]['record_id'],'recFixture')
                with self.store.connection() as db:
                    archive=db.execute('SELECT snapshot FROM node_resets WHERE task_id=? ORDER BY id DESC LIMIT 1',(self.task['id'],)).fetchone()
                self.assertEqual(json.loads(archive['snapshot'])['artifacts'],self.original)
                with self.assertRaises(ValueError):
                    self.store.reset_node(self.project,self.task['id'],stage,before['revision'],'旧请求',True)

    def test_cancelled_task_can_resume_and_import_after_reset(self):
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET stage=0,status='cancelled',artifacts='{}' WHERE id=?",(self.task['id'],))
        task=self.store.task(self.project,self.task['id'])
        with self.assertRaises(ValueError):self.store.import_requirement(self.project,task['id'],'另一需求','正文')
        task=self.store.reset_node(self.project,task['id'],0,task['revision'],'重新开始',True)
        self.assertEqual(self.store.import_requirement(self.project,task['id'],'另一需求','正文')['status'],'waiting_user')

    def test_reject_unconfirmed_future_invalid_and_missing_previous_stage(self):
        for stage,confirmed in [(0,False),(True,True),(6,True)]:
            with self.assertRaises(ValueError):self.store.reset_node(self.project,self.task['id'],stage,self.task['revision'],'理由',confirmed)
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET stage=0,artifacts='{}' WHERE id=?",(self.task['id'],))
        with self.assertRaises(ValueError):self.store.reset_node(self.project,self.task['id'],1,self.task['revision'],'理由',True)
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET stage=5,artifacts='{}' WHERE id=?",(self.task['id'],))
        with self.assertRaises(ValueError):self.store.reset_node(self.project,self.task['id'],3,self.task['revision'],'理由',True)

    def test_active_job_and_remote_send_block_reset_and_ledgers_survive(self):
        PublicationLedger(self.store);StatusChanges(self.store)
        with self.store.connection() as db:
            db.execute("INSERT INTO jobs(id,project_id,task_id,revision,status) VALUES('job',?,?,?,'running')",(self.project,self.task['id'],self.task['revision']))
        with self.assertRaisesRegex(ValueError,'后台操作'):self.store.reset_node(self.project,self.task['id'],0,self.task['revision'],'理由',True)
        with self.store.connection() as db:
            db.execute("UPDATE jobs SET status='completed' WHERE id='job'")
            db.execute("INSERT INTO status_changes(identity,task_id,root_cause_id,preview_hash,request,status) VALUES('status',?,'R','hash','{}','sending')",(self.task['id'],))
        with self.assertRaisesRegex(ValueError,'发送'):self.store.reset_node(self.project,self.task['id'],0,self.task['revision'],'理由',True)
        with self.store.connection() as db:db.execute("UPDATE status_changes SET status='uncertain'")
        self.store.reset_node(self.project,self.task['id'],0,self.task['revision'],'理由',True)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM status_changes').fetchone()['status'],'uncertain')

    def test_http_cancelled_import_stops_before_feishu_and_reset_reopens(self):
        from server.app import create_server
        import threading
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from unittest.mock import patch
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET stage=0,status='cancelled',artifacts='{}' WHERE id=?",(self.task['id'],))
        server=create_server(port=0,database=self.store.path,local_development=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root=f'http://127.0.0.1:{server.server_address[1]}/api/projects/{self.project}/tasks/{self.task["id"]}'
            def post(path,body):
                with urlopen(Request(root+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})) as response:
                    return json.loads(response.read())
            with patch('server.app.LarkClient.requirement') as reader:
                with self.assertRaises(HTTPError) as error:
                    post('/feishu-requirements',{'links':['https://example.feishu.cn/wiki/fixture']})
                self.assertEqual(error.exception.code,400)
                self.assertIn('重置',json.loads(error.exception.read())['error'])
                error.exception.close()
                reader.assert_not_called()
            task=post('/reset-node',{'stage':0,'revision':self.task['revision'],'reason':'接口重置验证','confirmed':True})
            self.assertEqual(task['status'],'waiting_user')
            self.assertEqual(post('/requirements',{'source':'新需求','content':'保存音乐'})['requirements'][-1]['content'],'保存音乐')
        finally:
            server.shutdown();server.server_close()
