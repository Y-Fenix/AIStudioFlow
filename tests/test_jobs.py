import tempfile
import unittest
from pathlib import Path
from server.store import Store


class JobTests(unittest.TestCase):
    def test_execute_and_attribution_persist_at_correct_destinations(self):
        task = self.store.task(self.p, self.t)
        task = self.store.record_artifact(self.p, self.t, 0, {'cases':[]})
        task = self.store.decide(self.p, self.t, 'confirm', task['revision'])
        task = self.store.bind_execution(self.p, self.t, {'repository':'/fixture','branch':'master'}, task['revision'])
        job = self.store.enqueue_operation(self.p, self.t, 'execute')
        self.assertEqual(job['id'], self.store.enqueue_operation(self.p, self.t, 'execute')['id'])
        self.assertEqual(job['stage'], 1)
        claimed = self.store.claim_generation()
        self.store.finish_generation(claimed, {'results':[]})
        task = self.store.task(self.p, self.t)
        self.assertEqual(task['artifacts']['1'], {'results':[]})
        task = self.store.decide(self.p, self.t, 'confirm', task['revision'])
        self.store.enqueue_operation(self.p, self.t, 'attribution')
        claimed = self.store.claim_generation()
        self.store.finish_generation(claimed, {'suggestions':[]})
        task = self.store.task(self.p, self.t)
        self.assertEqual(task['attribution'], {'suggestions':[]})
        self.assertNotIn('2', task['artifacts'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'jobs.sqlite')
        self.p = self.store.create_project('队列')['id']
        self.t = self.store.create_task(self.p, '批次')['id']
        self.store.import_requirement(self.p, self.t, '需求', '保存音量')

    def test_duplicate_and_changed_requirement_discard_result(self):
        job = self.store.enqueue_generation(self.p, self.t)
        self.assertEqual(job['id'], self.store.enqueue_generation(self.p, self.t)['id'])
        claimed = self.store.claim_generation()
        self.assertIsNone(self.store.claim_generation())
        self.store.import_requirement(self.p, self.t, '需求', '保存语言')
        self.store.finish_generation(claimed, {'cases': ['过时产物']})
        task = self.store.task(self.p, self.t)
        self.assertEqual(task['artifacts'], {})
        self.assertEqual(task['jobs'][0]['status'], 'superseded')

    def test_completion_and_restart_recovery(self):
        self.store.enqueue_generation(self.p, self.t)
        job = self.store.claim_generation()
        self.store.finish_generation(job, {'cases': []})
        self.assertEqual(self.store.task(self.p, self.t)['jobs'][0]['status'], 'completed')
        self.store.enqueue_generation(self.p, self.t)
        self.store.claim_generation()
        self.store.recover_generations()
        self.assertEqual(self.store.task(self.p, self.t)['jobs'][0]['status'], 'failed')
        self.assertIsNone(self.store.claim_generation())

    def test_cancelled_task_cannot_save_running_result(self):
        self.store.enqueue_generation(self.p, self.t)
        job = self.store.claim_generation()
        task = self.store.task(self.p, self.t)
        self.store.decide(self.p, self.t, 'cancel', task['revision'])
        self.store.finish_generation(job, {'cases': []})
        task = self.store.task(self.p, self.t)
        self.assertEqual(task['artifacts'], {})
        self.assertEqual(task['jobs'][0]['status'], 'superseded')

    def test_worker_cancellation_interrupts_live_child(self):
        import sys
        import threading
        import time
        from unittest.mock import patch
        from server.jobs import GenerationWorker
        from server.processes import run
        ready = Path(self.temp.name)/'worker-ready'
        ended = threading.Event()
        def generate(_client, requirements):
            try:
                run([sys.executable, '-c', 'from pathlib import Path; import time; Path('+repr(str(ready))+').touch(); time.sleep(30)'], timeout=40)
            finally:
                ended.set()
        with patch('server.jobs.CodexModel.generate', generate):
            worker = GenerationWorker(self.store)
            try:
                self.store.enqueue_generation(self.p, self.t)
                deadline = time.monotonic()+5
                while not ready.exists() and time.monotonic()<deadline:
                    threading.Event().wait(.02)
                self.assertTrue(ready.exists(), '运行器未启动')
                task = self.store.task(self.p, self.t)
                self.store.decide(self.p, self.t, 'cancel', task['revision'])
                self.assertTrue(ended.wait(3), '取消后子进程仍在运行')
            finally:
                worker.stop.set()
                worker.thread.join(5)
            self.assertFalse(worker.thread.is_alive())
            task = self.store.task(self.p, self.t)
            self.assertEqual(task['artifacts'], {})
            self.assertEqual(task['jobs'][0]['status'], 'superseded')

    def test_pending_refresh_queues_only_pending_roots_and_is_atomic(self):
        import json
        task=self.store.task(self.p,self.t)
        for stage in range(4):
            task=self.store.record_artifact(self.p,self.t,stage,{'ready_for_review':True})
            task=self.store.decide(self.p,self.t,'confirm',task['revision'])
        links=[{'draft_key':'a','root_cause_id':'r1','record_id':'recA','table_id':'tbl'},
               {'draft_key':'b','root_cause_id':'r2','record_id':'recB','table_id':'tbl'}]
        task=self.store.record_artifact(self.p,self.t,4,{'drafts':[{'root_cause_id':'r1'},{'root_cause_id':'r2'}],
                                                        'linked_records':links,'publication_complete':True})
        task=self.store.decide(self.p,self.t,'confirm',task['revision'])
        with self.store.connection() as db:
            db.execute('UPDATE tasks SET binding=? WHERE id=?',(json.dumps({'repository':'/fixture','branch':'master'}),self.t))
        checks={'a':{'record_id':'recA','table_id':'tbl','pending':False},
                'b':{'record_id':'recB','table_id':'tbl','pending':False}}
        r=self.store.refresh_pending_bugs(self.p,self.t,checks,task['revision'])
        self.assertIsNone(r['job'])
        self.assertEqual(r['task']['artifacts']['4']['remote_checks'],checks)
        checks['b']['pending']=True
        before=r['task']
        with self.assertRaises(ValueError):self.store.refresh_pending_bugs(self.p,self.t,{'a':checks['a']},before['revision'])
        self.assertEqual(self.store.task(self.p,self.t)['revision'],before['revision'])
        r=self.store.refresh_pending_bugs(self.p,self.t,checks,before['revision'])
        self.assertEqual(r['job']['revision'],r['task']['revision'])
        self.assertEqual(json.loads(r['job']['context'])['root_cause_ids'],['r2'])
        with self.assertRaises(ValueError):self.store.refresh_pending_bugs(self.p,self.t,checks,r['task']['revision'])

    def test_worker_keeps_one_source_snapshot_despite_switch_and_legacy_env(self):
        import threading,time
        from unittest.mock import patch
        from server.jobs import GenerationWorker
        from server.ai_models import ModelSettings,current_selection
        settings=ModelSettings(self.store)
        settings.write('catalog',{'models':[{'id':'relay-model','efforts':[],'usable':True}]})
        settings.save_custom({'base_url':'https://custom.example/v1','model':'custom-model'})
        started=threading.Event();release=threading.Event();finished=threading.Event();seen=[]
        def generate(client,requirements):
            seen.append(dict(current_selection()));started.set()
            if not release.wait(3):raise ValueError('测试等待超时')
            seen.append(dict(current_selection()));finished.set()
            return {'cases':[]}
        with patch.dict('os.environ',{'TESTFLOW_MODEL_PROVIDER':'legacy'}),patch('server.jobs.CodexModel.generate',generate):
            worker=GenerationWorker(self.store)
            try:
                self.store.enqueue_generation(self.p,self.t)
                self.assertTrue(started.wait(3),'后台未使用界面选择的模型')
                settings.save({'model':'relay-model'})
                release.set();self.assertTrue(finished.wait(3))
            finally:
                release.set();worker.stop.set();worker.thread.join(5)
        self.assertEqual([s['source'] for s in seen],['custom','custom'])
        self.assertEqual(settings.runtime_selection()['source'],'relay')
