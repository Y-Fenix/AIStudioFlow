import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.core.integrations import AdapterRegistry
from server.core.production_runs import ProductionRuns


class ProductionRunsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'db.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('Production', self.studio)['id']
        self.registry = AdapterRegistry()
        class Adapter:
            def execute(self, context):
                return {'deliverable': 'Verified structure '+context.node_id, 'gaps':['external research unavailable']}
        for d in ('product','design','development'):self.registry.register(d, Adapter())
        class QaModel:
            def request_json(self, prompt):
                return {'points':[{'id':'P1','title':'Playable','requirement_id':'production-requirement','quote':'A playable game'}], 'cases':[{'id':'C1','title':'Start','preconditions':['installed'],'point_ids':['P1'],'steps':[{'action':'start','expected':'board'}]}],'gaps':[],'ambiguities':[]}
        self.service = ProductionRuns(self.store, self.registry, builder=self.build, model_factory=lambda node:QaModel(),source_reviewer=lambda *a,**kw:{'findings':[],'checks':[],'gaps':['fixture review only']})
    def tearDown(self):self.tmp.cleanup()
    def build(self, output_root, brief, **kw):
        root=Path(output_root);root.mkdir(parents=True,exist_ok=True)
        p=root/'project.zip';p.write_bytes(b'fixture project')
        return {'artifacts':[{'path':str(p),'kind':'source','name':p.name}], 'project_path':str(root), 'checks':[{'name':'fixture runtime check','passed':True,'evidence':'fixture only'}], 'gaps':['device untested']}
    def create(self):return self.service.create(self.studio,self.project,{'brief':'A playable game','delegation':True})
    def test_production_brief_is_not_overridden_by_memory_template(self):
        run=self.service.create(self.studio,self.project,{'brief':'制作Loop闭环解谜游戏','delegation':True})
        self.service.advance(self.studio,self.project,run['id'])
        from server.studio_workspaces import Workspaces
        current=self.service.get(self.studio,self.project,run['id'])
        workspace=Workspaces(self.store).get(self.studio,self.project,'product:0',flow=current['steps'][0]['flow_id'])
        self.assertNotIn('构建可玩的记忆配对游戏MVP',workspace['inputs'])
        self.assertIn('制作Loop闭环解谜游戏',workspace['inputs'])

    def test_loop_test_generation_does_not_invent_memory_or_timer_requirements(self):
        prompts=[]
        class Model:
            def request_json(inner,prompt):
                prompts.append(prompt)
                return {'points':[{'id':'P1','title':'Playable','requirement_id':'production-requirement','quote':'A playable game'}], 'cases':[{'id':'C1','title':'Rotate','preconditions':['installed'],'point_ids':['P1'],'steps':[{'action':'rotate','expected':'closed loop'}]}],'gaps':[],'ambiguities':[]}
        original=self.service.builder
        def build(*args,**kw):
            result=original(*args,**kw);result['spec']={'game_type':'loop'};return result
        self.service.builder=build
        self.service.model_factory=lambda node:Model()
        run=self.create()
        while self.service.run_once():pass
        self.assertTrue(prompts)
        self.assertNotIn('覆盖开始、配对成功/不成功、倒计时',prompts[0])
        self.assertIn('旋转',prompts[0])

    def test_requires_explicit_delegation(self):
        with self.assertRaises(ValueError):self.service.create(self.studio,self.project,{'brief':'idea'})
    def test_persistent_isolated_chain_and_artifact(self):
        run=self.create()
        while self.service.run_once():pass
        run=self.service.get(self.studio,self.project,run['id'])
        self.assertEqual(run['status'],'completed')
        self.assertEqual(len([s for s in run['steps'] if s['status']=='completed']),18)
        self.assertIn('device untested',run['gaps'])
        path=self.service.artifact(self.studio,self.project,run['id'],run['artifacts'][0]['id'])
        self.assertTrue(path.is_file())
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM studio_workspaces WHERE project_id=?',(self.project,)).fetchone()[0],0)
        restored=ProductionRuns(self.store,self.registry,builder=self.build)
        self.assertEqual(restored.get(self.studio,self.project,run['id'])['status'],'completed')
    def test_pause_cancel_and_resume(self):
        run=self.create();run=self.service.action(self.studio,self.project,run['id'],'pause')
        self.assertEqual(run['status'],'paused');self.assertFalse(self.service.run_once())
        self.service.action(self.studio,self.project,run['id'],'resume')
        self.assertTrue(self.service.run_once())
        run=self.service.action(self.studio,self.project,run['id'],'cancel')
        self.assertEqual(run['status'],'cancelled')
    def test_failure_resume_preserves_completed_steps(self):
        run=self.create()
        self.service.run_once()
        self.service.recover()
        run=self.service.get(self.studio,self.project,run['id'])
        self.assertEqual(run['status'],'paused')
        self.assertEqual(run['steps'][0]['status'],'completed')
        self.service.action(self.studio,self.project,run['id'],'resume')
        while self.service.run_once():pass
        self.assertEqual(self.service.get(self.studio,self.project,run['id'])['status'],'completed')
    def test_cross_project_cannot_read(self):
        run=self.create();p=self.store.create_project('Other',self.studio)['id']
        with self.assertRaises(KeyError):self.service.get(self.studio,p,run['id'])
    def test_no_checks_is_failure(self):
        self.service.builder=lambda *a,**kw:{'artifacts':[], 'checks':[]}
        run=self.create()
        while self.service.run_once():pass
        run=self.service.get(self.studio,self.project,run['id'])
        self.assertEqual(run['status'],'failed')

    def test_builder_progress_shows_message_without_private_log_path(self):
        observed=[]
        run=self.create()
        def builder(root,brief,**kwargs):
            kwargs['progress']({'stage':'compile','message':'正在编译 Android 工程','log_path':'PRIVATE LOG PATH'})
            observed.append(self.service.get(self.studio,self.project,run['id'])['summary'])
            return self.build(root,brief,**kwargs)
        self.service.builder=builder
        for _ in range(13):
            self.assertTrue(self.service.run_once())
        self.assertEqual(observed,['正在编译 Android 工程'])

    def test_request_id_is_idempotent(self):
        value={'brief':'A playable game','delegation':True,'request_id':'same-request'}
        first=self.service.create(self.studio,self.project,value)
        second=self.service.create(self.studio,self.project,value)
        self.assertEqual(first['id'],second['id'])
    def test_pause_during_adapter_never_approves_or_advances(self):
        run=self.create();service=self.service;studio=self.studio;project=self.project
        class Adapter:
            def execute(self, context):
                service.action(studio,project,run['id'],'pause')
                return {'deliverable':'saved but not delegated yet'}
        self.registry._adapters['product']=Adapter()
        service.run_once()
        result=service.get(studio,project,run['id'])
        self.assertEqual(result['status'],'paused')
        self.assertEqual(result['steps'][0]['status'],'running')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM flow_workspaces WHERE node=?',('product:0',)).fetchone()[0],'waiting_user')
        service.action(studio,project,run['id'],'resume');service.run_once()
        self.assertEqual(service.get(studio,project,run['id'])['steps'][0]['status'],'completed')
    def test_revoked_actor_prevents_next_execution(self):
        run=self.create()
        with self.store.connection() as db:db.execute("UPDATE users SET status='disabled' WHERE id='local'")
        self.service.run_once()
        with self.store.connection() as db:
            row=db.execute('SELECT status,error FROM production_runs WHERE id=?',(run['id'],)).fetchone()
            self.assertEqual(row['status'],'failed')
            self.assertIn('权限',row['error'])
            self.assertEqual(db.execute('SELECT count(*) FROM flow_workspaces').fetchone()[0],0)
    def test_artifact_tamper_is_rejected(self):
        run=self.create()
        while self.service.run_once():pass
        run=self.service.get(self.studio,self.project,run['id'])
        artifact=run['artifacts'][0]
        path=self.service.artifact(self.studio,self.project,run['id'],artifact['id'])
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):self.service.artifact(self.studio,self.project,run['id'],artifact['id'])
    def test_qa_defect_creates_internal_draft_and_does_not_fake_regression(self):
        self.service.source_reviewer=lambda *a,**kw:{'findings':[{'status':'failed','title':'Fixture defect','evidence':[{'file':'fixture.java','line':1,'quote':'fixture'}]}],'gaps':[]}
        run=self.create()
        while self.service.run_once():pass
        run=self.service.get(self.studio,self.project,run['id'])
        self.assertEqual(run['status'],'completed')
        self.assertEqual(run['qa']['bugs']['drafts'][0]['status'],'internal_draft')
        self.assertFalse(run['qa']['bugs']['drafts'][0]['published'])
        self.assertEqual(run['qa']['regression']['status'],'awaiting_fix')
        self.assertIsNone(run['qa']['regression']['passed'])
        self.assertTrue(any('尚未修复' in g for g in run['gaps']))
    def test_qa_invalid_requirement_quote_cannot_complete_cases(self):
        class InvalidModel:
            def request_json(self,prompt):
                return {'points':[{'id':'P','title':'bad','requirement_id':'production-requirement','quote':'fabricated absent source text'}],'cases':[],'gaps':[{'point_id':'P','reason':'gap'}],'ambiguities':[]}
        self.service.model_factory=lambda n:InvalidModel()
        run=self.create()
        while self.service.run_once():pass
        run=self.service.get(self.studio,self.project,run['id'])
        self.assertEqual(run['status'],'failed')
        self.assertEqual(run['steps'][13]['status'],'failed')
        self.assertIn('引用不存在',run['error'])
    def test_concurrent_idempotent_creates_have_one_persistent_run(self):
        from concurrent.futures import ThreadPoolExecutor
        value={'brief':'A playable game','delegation':True,'request_id':'concurrent'}
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda _:self.service.create(self.studio,self.project,value),range(3)))
        self.assertEqual(len({r['id'] for r in results}),1)
        self.assertEqual(len(self.service.listing(self.studio,self.project)['runs']),1)
    def test_production_notifications_pin_scope_and_recover_to_run_link(self):
        import json
        from server.core.notification_settings import NotificationSettings
        from server.core.notifications import card_for
        NotificationSettings(self.store).save(self.studio,'',{'enabled':True,'webhook':'https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000001'})
        run=self.create();self.service.run_once();self.service.recover()
        with self.store.connection() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM node_notifications ORDER BY id')]
        self.assertEqual([r['event'] for r in rows],['completed','interrupted'])
        for row in rows:
            payload=json.loads(row['payload'])
            self.assertEqual(payload['origin'],'production')
            self.assertEqual(payload['production_run_id'],run['id'])
            self.assertIn('步骤完成 1/18',payload['summary'])
            self.assertNotIn('webhook',row['payload'])
            card=card_for(row,{'public_url':'https://studio.example'})
            url=next(e for e in card['elements'] if e['tag']=='action')['actions'][0]['url']
            self.assertIn('production_run='+run['id'],url)
    def test_public_advance_only_dispatches_selected_run(self):
        first=self.create();second=self.create()
        self.assertTrue(self.service.advance(self.studio,self.project,second['id']))
        one=self.service.get(self.studio,self.project,first['id'])
        two=self.service.get(self.studio,self.project,second['id'])
        self.assertEqual(one['status'],'queued')
        self.assertEqual(one['steps'][0]['status'],'pending')
        self.assertEqual(two['steps'][0]['status'],'completed')
    def test_model_progress_is_human_readable_and_uses_only_observed_metrics(self):
        run=self.create();self.service.advance(self.studio,self.project,run['id'])
        self.service._model_progress({'id':run['id']},{'name':'市场调研'},{'state':'running','elapsed_seconds':125.5,'assistant_chars':1234,'tool_calls':3,'commands_completed':2,'transport':'codex_cli','prompt':'PRIVATE PROMPT','api_key':'PRIVATE KEY'})
        summary=self.service.get(self.studio,self.project,run['id'])['summary']
        self.assertIn('市场调研',summary)
        self.assertIn('2分5秒',summary)
        self.assertIn('已接收 1234 字',summary)
        self.assertIn('工具调用 3 次',summary)
        self.assertIn('命令完成 2 次',summary)
        for raw in ('{','state','codex_cli','PRIVATE','%'):self.assertNotIn(raw,summary)
    def test_qa_progress_describes_verified_counts_and_validation_repair(self):
        run=self.create();self.service.advance(self.studio,self.project,run['id'])
        self.service._qa_progress({'id':run['id']},{'state':'case_completed','completed':7,'total':12,'reviewed_count':5,'checkpoint_reused_count':2,'title':'计时归零','raw':'PRIVATE DATA'})
        summary=self.service.get(self.studio,self.project,run['id'])['summary']
        self.assertIn('已校验 7/12 条',summary)
        self.assertIn('本次审查 5 条',summary)
        self.assertIn('复用 2 条',summary)
        self.assertNotIn('{',summary);self.assertNotIn('PRIVATE',summary)
        self.service._qa_progress({'id':run['id']},{'state':'validation_repair','validation_attempt':1,'validation_max_attempts':3,'validation_error':'PRIVATE RAW RESPONSE'})
        summary=self.service.get(self.studio,self.project,run['id'])['summary']
        self.assertIn('修正输出格式',summary);self.assertIn('1/3',summary)
        self.assertNotIn('PRIVATE',summary)
    def test_progress_does_not_invent_metrics_from_invalid_values_or_unknown_states(self):
        run=self.create();self.service.advance(self.studio,self.project,run['id'])
        self.service._model_progress({'id':run['id']},{'name':'测试执行'},{'state':['PRIVATE STATE'],'elapsed_seconds':float('nan'),'assistant_chars':-1,'tool_calls':True,'commands_completed':'nine'})
        summary=self.service.get(self.studio,self.project,run['id'])['summary']
        self.assertIn('正在执行',summary)
        for fabricated in ('PRIVATE','nan','已接收','工具调用','命令完成','%','{'):self.assertNotIn(fabricated,summary)
