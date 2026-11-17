"""Archived filter compatibility; real SQLite, no model or remote writes."""
import json
import tempfile
import unittest
from server.store import Store
from server.core.project_nodes import ProjectNodes
from server.triage import triage_report, filter_groups


class QA_MergedTriageTests(unittest.TestCase):
    def test_each_default_skill_has_a_content_fingerprint_for_continuation(self):
        import hashlib
        from server.node_skills import defaults
        for skill in defaults().values():
            self.assertEqual(skill.get('sha256'),hashlib.sha256(skill['content'].encode()).hexdigest())

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name+'/db.sqlite')
        self.project=self.store.create_project('五步兼容')['id']
        self.studio=self.store.studios()[0]['id']
        self.manager=ProjectNodes(self.store)
        config=self.manager.get(self.studio,self.project,'testing')
        config['nodes']=[n for n in config['nodes'] if n['id']!='testing:3']
        self.manager.save(self.studio,self.project,'testing',config)
        self.task=self.store.create_task(self.project,'人工根因审核')
        self.results=[{'id':'f1','status':'failed','evidence':'fixture-1'},
                      {'id':'f2','status':'failed','evidence':'fixture-2'}]
        self.triage=triage_report(self.results,
            [{'result_id':r['id'],'root_cause_id':r['id']} for r in self.results],
            [{'id':r['id'],'title':r['id'],'confirmed':True,'evidence':[r['evidence']]} for r in self.results],[])
        self.seed(self.triage)

    def seed(self,triage,stage=2):
        with self.store.connection() as db:
            db.execute('UPDATE tasks SET stage=?,artifacts=? WHERE id=?',
                (stage,json.dumps({'0':{'fixture':True},'1':{'results':self.results},'2':triage}),self.task['id']))

    def confirm(self):
        task=self.store.task(self.project,self.task['id'])
        return self.store.decide(self.project,task['id'],'confirm',task['revision'])

    def test_merged_scope_requires_explicit_selection_and_preserves_exclusion_reason(self):
        with self.assertRaisesRegex(ValueError,'提单范围'):self.confirm()
        scope=filter_groups(self.triage,['f1'],{'f2':'本次明确不提单'})
        self.seed({**self.triage,'filing_scope':scope})
        task=self.confirm()
        self.assertEqual(task['stage'],4)
        self.assertEqual(task['artifacts']['3'],scope)
        self.assertEqual(task['artifacts']['3']['excluded']['f2'],'本次明确不提单')
        self.assertEqual(task['events'][-2]['stage'],2)
        with self.assertRaises(ValueError):
            self.store.decide(self.project,task['id'],'confirm',task['revision']-1)

    def test_unresolved_or_forged_scope_cannot_skip_evidence(self):
        for triage in ({**self.triage,'ready_for_review':False},
                       {**self.triage,'filing_scope':{'groups':[],'excluded':{},'result_ids':[]}}):
            self.seed(triage)
            with self.assertRaises(ValueError):self.confirm()
            self.assertEqual(self.store.task(self.project,self.task['id'])['stage'],2)

    def test_old_filter_batch_can_resave_triage_without_restoring_deleted_node(self):
        self.seed(self.triage,stage=3)
        scope=filter_groups(self.triage,['f1','f2'],{})
        task=self.store.record_artifact(self.project,self.task['id'],2,{**self.triage,'filing_scope':scope},self.task['revision'])
        self.assertEqual(task['stage'],2)
        self.assertEqual(self.confirm()['stage'],4)

    def test_no_other_deleted_stage_becomes_automatically_skippable(self):
        config=self.manager.get(self.studio,self.project,'testing')
        config['nodes']=[n for n in config['nodes'] if n['id']!='testing:1']
        self.manager.save(self.studio,self.project,'testing',config)
        with self.store.connection() as db:db.execute('UPDATE tasks SET stage=0 WHERE id=?',(self.task['id'],))
        self.assertEqual(self.confirm()['stage'],1)

    def test_automatic_bridge_uses_legacy_skill_content_and_never_publishes(self):
        from server.core.node_continuation import NodeContinuation
        service=NodeContinuation(self.store)
        config=service.get(self.studio,self.project,'testing')
        service.save(self.studio,self.project,'testing',{'revision':config['revision'],'source':'testing:2','target':'testing:4','enabled':True})
        scope=filter_groups(self.triage,['f1'],{'f2':'本次不提单'})
        self.seed({**self.triage,'filing_scope':scope})
        with self.store.connection() as db:
            artifacts=json.loads(db.execute('SELECT artifacts FROM tasks WHERE id=?',(self.task['id'],)).fetchone()['artifacts'])
            artifacts['1'].update(method='static_code_review',code_fingerprint='fixture')
            db.execute('UPDATE tasks SET artifacts=?,node_skills=? WHERE id=?',
                (json.dumps(artifacts),json.dumps({'4':{'name':'旧规则','content':'旧批次保留规则'}}),self.task['id']))
        self.assertFalse(service.run_once())
        self.confirm();self.assertTrue(service.run_once());self.assertFalse(service.run_once())
        task=self.store.task(self.project,self.task['id'])
        self.assertEqual(len(task['artifacts'].get('4',{}).get('drafts',[])),1)
        self.assertEqual(task['stage'],4);self.assertFalse(task['artifacts']['4']['publication_complete'])
        self.assertEqual(task['artifacts']['4']['drafts'][0]['publication_status'],'internal_draft')
        self.assertIn('未发布',task['events'][-1]['detail'])

    def test_deleted_filter_permission_is_not_needed_or_exposed(self):
        from server.core.gateway import Gateway
        from server.core.identity import current_user
        from server.core.admin import Administration
        with self.store.connection() as db:
            db.execute("INSERT INTO users VALUES('qa','fixture','qa','测试员','active','member',CURRENT_TIMESTAMP)")
        admin=Administration(self.store)
        admin.member({'user_id':'qa','studio_id':self.studio,'project_id':self.project,'department':'testing','role':'lead'})
        for action in ('view','edit','approve'):
            admin.rule({'subject_type':'user','subject_id':'qa','studio_id':self.studio,'project_id':self.project,'department':'testing','node':'testing:3','resource':'node','action':action,'effect':'deny'})
        scope=filter_groups(self.triage,['f1'],{'f2':'不提单'})
        self.seed({**self.triage,'filing_scope':scope})
        task=self.confirm();token=current_user.set('qa')
        try:
            gateway=Gateway(self.store)
            response=gateway.filter_response(task,{'studio':self.studio,'project':self.project})
            self.assertNotIn('3',response['artifacts'])
            self.assertEqual(response['filing_scope'],scope)
            self.assertTrue(response['filter_merged'])
            gateway.authorize(['api','studios',self.studio,'projects',self.project,'tasks',task['id'],'reset-node'],'',{'stage':2},True)
        finally:current_user.reset(token)
