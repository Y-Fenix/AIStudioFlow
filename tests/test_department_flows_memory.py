"""Isolated fixtures; no external model or client execution."""
import tempfile
import threading
import unittest
from unittest.mock import patch
from server.store import Store
from server.studio_workspaces import Workspaces
from server.core.integrations import AdapterRegistry
from server.department_jobs import DepartmentExecutionQueue
from server.core.department_flows import DepartmentFlows
from server.core.node_memory import NodeMemory


class DepartmentFlowMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name+'/fixture.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('流程隔离',self.studio)['id']
        self.flows = DepartmentFlows(self.store)
        self.memory = NodeMemory(self.store)
        self.work = Workspaces(self.store)

    def create(self,name='A',department='product',**extra):
        return self.flows.create(self.studio,self.project,{'name':name,'department':department,**extra})

    def test_flow_read_releases_cursor_before_nested_permission_reads(self):
        import sqlite3
        from server.core.permissions import Policy
        f=self.create()
        original=Policy.allowed
        def checked(policy,resource,action,**kwargs):
            if resource=='node' and action=='view':
                # A different writer must commit while checking each node permission.
                with sqlite3.connect(self.store.path,timeout=.1) as writer:
                    writer.execute("UPDATE department_flows SET name=name WHERE id=?",(f['id'],))
            return original(policy,resource,action,**kwargs)
        with patch.object(Policy,'allowed',checked):
            self.assertEqual(len(self.flows.get(self.studio,self.project,f['id'])['nodes']),4)

    def test_flow_notification_links_open_the_exact_instance(self):
        from server.core.notification_settings import NotificationSettings
        from server.core.notifications import card_for
        NotificationSettings(self.store).save(self.studio,'',{'enabled':True,
            'webhook':'https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000001',
            'public_url':'https://studio.example.test','events':['manual','approved','completed']})
        a,b=self.create(),self.create('B')
        for f in (a,b):
            self.work.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'manual fixture'},flow=f['id'])
        with self.store.connection() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM node_notifications ORDER BY id')]
        self.assertEqual(len(rows),2,'same node/revision in different flows must not deduplicate')
        for row,f in zip(rows,(a,b)):
            card=card_for(row,{'public_url':'https://studio.example.test'})
            self.assertIn('flow='+f['id'],str(card))
        qa=self.create(department='testing')
        from server.core.notifications import testing_event
        with self.store.connection() as db:
            testing_event(self.store,db,qa['task_id'],1,'fixture-qa-event','completed')
            row=dict(db.execute('SELECT * FROM node_notifications ORDER BY id DESC LIMIT 1').fetchone())
        self.assertIn('flow='+qa['id'],str(card_for(row,{'public_url':'https://studio.example.test'})))

    def test_archived_flow_and_node_cannot_accept_questions(self):
        f=self.create()
        self.flows.archive(self.studio,self.project,f['id'])
        with self.assertRaisesRegex(ValueError,'归档'):
            self.memory.ask(self.studio,self.project,'product:0',{'question':'test'},flow=f['id'])
        from server.core.project_nodes import ProjectNodes
        service=ProjectNodes(self.store)
        # Archived nodes remain readable for history, but cannot start model work.
        config=service.get(self.studio,self.project,'product')
        config['nodes']=[n for n in config['nodes'] if n['id']!='product:0']
        service.save(self.studio,self.project,'product',config)
        with self.assertRaisesRegex(ValueError,'归档'):
            self.memory.ask(self.studio,self.project,'product:0',{'question':'test'})

    def test_qa_flow_uses_real_task_and_does_not_dispatch_default_continuation(self):
        f=self.create(department='testing')
        with self.assertRaisesRegex(ValueError,'测试批次'):
            self.work.save(self.studio,self.project,'testing:0',{'revision':0,'inputs':'phantom'},flow=f['id'])
        from server.core.node_continuation import record_completion
        with self.store.connection() as db, patch('server.core.node_continuation._edges') as edges:
            record_completion(self.store,db,self.studio,self.project,'testing:0',1,f['task_id'])
            edges.assert_not_called()

    def test_new_flows_isolate_data_skill_decisions_events_and_default(self):
        a,b=self.create(),self.create('B')
        w=self.work.save(self.studio,self.project,'product:0',{'revision':0,'inputs':'A only','deliverable':'A result'},flow=a['id'])
        self.work.decide(self.studio,self.project,'product:0',{'revision':w['revision'],'action':'approve','reason':'fixture'},flow=a['id'])
        self.assertEqual(self.work.get(self.studio,self.project,'product:0',flow=a['id'])['status'],'approved')
        for flow in ('',b['id']):
            w=self.work.get(self.studio,self.project,'product:0',flow=flow)
            self.assertEqual(w['inputs'],''); self.assertFalse(w['events'])
        with self.assertRaises(ValueError):self.work.get(self.studio,self.project,'design:0',flow=a['id'])
        other=self.store.create_project('other',self.studio)['id']
        with self.assertRaises(KeyError):self.work.get(self.studio,other,'product:0',flow=a['id'])

    def test_two_flow_jobs_can_run_concurrently_without_overwriting(self):
        a,b=self.create(),self.create('B'); barrier=threading.Barrier(2); seen=[]
        class Fixture:
            def execute(_,context):
                seen.append(context.inputs);barrier.wait(timeout=4)
                return {'deliverable':context.inputs}
        reg=AdapterRegistry();reg.register('product',Fixture());queue=DepartmentExecutionQueue(self.store,reg)
        for f in (a,b):
            w=self.work.save(self.studio,self.project,'product:0',{'revision':0,'inputs':f['name']},flow=f['id'])
            queue.enqueue(self.studio,self.project,'product:0',w['revision'],flow=f['id'])
            with self.assertRaisesRegex(ValueError,'已有执行'):queue.enqueue(self.studio,self.project,'product:0',w['revision'],flow=f['id'])
        ts=[threading.Thread(target=queue.run_once) for _ in range(2)]
        for t in ts:t.start()
        for t in ts:t.join(6)
        self.assertEqual(sorted(seen),['A','B'])
        for f in (a,b):self.assertIn(f['name'],self.work.get(self.studio,self.project,'product:0',flow=f['id'])['deliverable'])
        self.assertEqual(self.work.get(self.studio,self.project,'product:0')['deliverable'],'')

    def test_memory_sources_are_explicit_refreshed_bounded_and_cited(self):
        a,b=self.create(),self.create('B')
        source=self.work.save(self.studio,self.project,'product:0',{'revision':0,'inputs':'coins rule','deliverable':'Reward exactly 12 coins'},flow=a['id'])
        self.work.decide(self.studio,self.project,'product:0',{'revision':source['revision'],'action':'approve','reason':'fixture'},flow=a['id'])
        ctx=self.memory.context(self.studio,self.project,'design:0',question='coins')
        self.assertNotIn('12 coins',str(ctx))
        self.memory.link(self.studio,self.project,'design:0',{'node':'product:0','flow':a['id']})
        ctx=self.memory.context(self.studio,self.project,'design:0',question='coins')
        self.assertIn('12 coins',str(ctx)); self.assertNotIn(b['id'],str(ctx))
        self.assertTrue(all(x.get('sha256') and 'revision' in x for x in ctx['sources']))
        w=self.work.get(self.studio,self.project,'product:0',flow=a['id'])
        self.work.save(self.studio,self.project,'product:0',{'revision':w['revision'],'deliverable':'changed'},flow=a['id'])
        self.assertNotIn('12 coins',str(self.memory.context(self.studio,self.project,'design:0')))

    def test_question_queue_persists_and_uses_current_skill_and_context(self):
        flow=self.create()
        self.work.save(self.studio,self.project,'product:0',{'revision':0,'inputs':'source rule: 7 moves'},flow=flow['id'])
        message=self.memory.ask(self.studio,self.project,'product:1',{'question':'How many moves?'},flow=flow['id'])
        def model(prompt):
            self.assertIn('7 moves',prompt)
            return {'answer':'7 moves [S1]','citations':['S1']}
        with patch('server.codex_model.CodexModel.request_json',side_effect=model):self.memory.run_once()
        messages=NodeMemory(Store(str(self.store.path))).history(self.studio,self.project,'product:1',flow=flow['id'])['messages']
        self.assertEqual(messages[0]['id'],message['id']);self.assertEqual(messages[0]['status'],'completed')
        self.assertTrue(messages[0]['sources']);self.assertIn('7 moves',messages[0]['answer'])
        self.assertFalse(self.memory.history(self.studio,self.project,'product:1')['messages'])

    def test_qa_memory_recalls_only_bound_batch(self):
        a,b=self.create('QA A','testing'),self.create('QA B','testing')
        self.store.import_requirement(self.project,a['task_id'],'fixture','A rule: reward 99 coins')
        self.store.import_requirement(self.project,b['task_id'],'fixture','B secret unrelated')
        ctx=self.memory.context(self.studio,self.project,'testing:1',flow=a['id'],question='reward')
        self.assertIn('99 coins',str(ctx));self.assertNotIn('B secret',str(ctx))
        self.assertEqual(ctx['sources'][0]['task'],a['task_id'])

    def test_unknown_model_citation_is_not_saved_as_success(self):
        msg=self.memory.ask(self.studio,self.project,'product:0',{'question':'what?'})
        with patch('server.codex_model.CodexModel.request_json',return_value={'answer':'made up','citations':['imaginary']}):self.memory.run_once()
        row=self.memory.history(self.studio,self.project,'product:0')['messages'][0]
        self.assertEqual(row['id'],msg['id']);self.assertEqual(row['status'],'failed');self.assertEqual(row['answer'],'')

    def test_large_local_sources_do_not_starve_explicit_cross_department_link(self):
        flow=self.create('QA','testing')
        self.store.import_requirement(self.project,flow['task_id'],'huge','x'*60000)
        with self.store.connection() as db:
            db.execute('UPDATE tasks SET artifacts=? WHERE id=?',('{"0":{"cases":"'+('a'*60000)+'"},"1":{"review":"'+('b'*60000)+'"},"2":{"groups":"'+('c'*60000)+'"}}',flow['task_id']))
        w=self.work.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'PRD reward is 99 coins'})
        self.work.decide(self.studio,self.project,'product:0',{'revision':w['revision'],'action':'approve','reason':'fixture'})
        self.memory.link(self.studio,self.project,'testing:1',{'node':'product:0'},flow=flow['id'])
        ctx=self.memory.context(self.studio,self.project,'testing:1',flow=flow['id'])
        self.assertIn('PRD reward is 99 coins',str(ctx))
        self.assertLessEqual(ctx['used'],ctx['budget'])

    def test_unlink_works_after_source_no_longer_approved(self):
        w=self.work.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'rule'})
        w=self.work.decide(self.studio,self.project,'product:0',{'revision':w['revision'],'action':'approve','reason':'fixture'})
        self.memory.link(self.studio,self.project,'design:0',{'node':'product:0'})
        self.work.save(self.studio,self.project,'product:0',{'revision':w['revision'],'deliverable':'new draft'})
        self.memory.link(self.studio,self.project,'design:0',{'node':'product:0','remove':True})
        self.assertFalse(self.memory.links(self.studio,self.project,'design:0')['items'])

    def test_archive_blocks_queued_questions_on_bound_qa_task(self):
        f=self.create('QA','testing')
        self.memory.ask(self.studio,self.project,'testing:1',{'question':'what?'},flow=f['id'])
        with self.assertRaisesRegex(ValueError,'在途'):self.flows.archive(self.studio,self.project,f['id'])

    def test_invalid_payloads_are_validation_errors(self):
        f=self.create()
        for value in (None,[],42):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):self.flows.create(self.studio,self.project,value)
                with self.assertRaises(ValueError):self.work.save(self.studio,self.project,'product:0',value,flow=f['id'])
                with self.assertRaises(ValueError):self.memory.ask(self.studio,self.project,'product:0',value)

    def test_model_question_requires_execute_and_rechecks_revocation(self):
        from server.core.permissions import Policy,AccessDenied
        original=Policy.require
        def check(policy,resource,action,**kwargs):
            if resource=='node' and action=='execute':raise AccessDenied('fixture revoked')
            return original(policy,resource,action,**kwargs)
        with patch.object(Policy,'require',check):
            with self.assertRaises(PermissionError):self.memory.ask(self.studio,self.project,'product:0',{'question':'question'})
        self.memory.ask(self.studio,self.project,'product:0',{'question':'question'})
        with patch.object(Policy,'require',check),patch('server.codex_model.CodexModel.request_json') as model:
            self.memory.run_once();model.assert_not_called()
        self.assertEqual(self.memory.history(self.studio,self.project,'product:0')['messages'][0]['status'],'failed')

    def test_prior_answer_does_not_leak_after_source_unlinked_and_revoked(self):
        from server.core.permissions import Policy,AccessDenied
        w=self.work.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'private product rule'})
        self.work.decide(self.studio,self.project,'product:0',{'revision':w['revision'],'action':'approve','reason':'fixture'})
        self.memory.link(self.studio,self.project,'design:0',{'node':'product:0'})
        self.memory.ask(self.studio,self.project,'design:0',{'question':'first'})
        with patch('server.codex_model.CodexModel.request_json',return_value={'answer':'private product rule','citations':['S1']}):self.memory.run_once()
        self.memory.link(self.studio,self.project,'design:0',{'node':'product:0','remove':True})
        self.memory.ask(self.studio,self.project,'design:0',{'question':'second'})
        def no_leak(prompt):
            self.assertNotIn('private product rule',prompt)
            return {'answer':'no sources','citations':[]}
        with patch('server.codex_model.CodexModel.request_json',side_effect=no_leak):self.memory.run_once()
        original=Policy.require
        def deny(policy,resource,action,**kwargs):
            if kwargs.get('node')=='product:0':raise AccessDenied('revoked')
            return original(policy,resource,action,**kwargs)
        with patch.object(Policy,'require',deny):
            rows=self.memory.history(self.studio,self.project,'design:0')['messages']
            self.assertTrue(rows[0]['restricted'])
            self.assertNotIn('private product rule',str(rows))

    def test_failed_flow_creation_rolls_back_new_qa_task(self):
        with self.store.connection() as db:
            db.executescript("CREATE TRIGGER fixture_reject_flow BEFORE INSERT ON department_flows BEGIN SELECT RAISE(ABORT,'fixture reject');END;")
        before=len(self.store.tasks(self.project))
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):self.create('QA','testing')
        self.assertEqual(len(self.store.tasks(self.project)),before)
