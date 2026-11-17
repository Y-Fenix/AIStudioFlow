"""Production-to-native-Agent integration; child/model outputs are explicit fixtures."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server.store import Store
from server.ai_models import current_selection
from server.node_skills import current_skill
from server.core.integrations import AdapterRegistry, ModelCapability
from server.core.production_runs import ProductionRuns

SOURCE='class MemoryRules {\n int pairs() { return 6; }\n}\n'
FILE='src/game/MemoryRules.java'


class ProductionSourceBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite')
        self.studio=self.store.studios()[0]['id'];self.project=self.store.create_project('Source bridge',self.studio)['id']
        registry=AdapterRegistry()
        class Adapter:
            def execute(self,context):return {'deliverable':'fixture documentation '+context.node_id}
        for department in ('product','design','development'):registry.register(department,Adapter())
        class TextClient:
            def request_json(self,prompt):
                return {'points':[{'id':'P1','title':'Pair count','requirement_id':'production-requirement','quote':'six pairs'}],
                    'cases':[{'id':'C1','title':'Pair count','preconditions':['new game'],'point_ids':['P1'],'steps':[{'action':'start game','expected':'six pairs'}]}],'gaps':[],'ambiguities':[]}
        self.selection={'source':'custom','protocol':'responses','model':'fixture-pinned-model','effort':'high','base_url':'https://fixture.invalid/v1','api_key':'fixture-secret'}
        self.capability=ModelCapability(TextClient(),self.selection,'EXACT PRODUCTION QA SKILL')
        self.service=ProductionRuns(self.store,registry,builder=self.build,model_factory=lambda node:self.capability)
        self.calls=[]
    def build(self,output_root,brief,**options):
        root=Path(output_root);(root/FILE).parent.mkdir(parents=True);(root/FILE).write_text(SOURCE)
        apk=root/'fixture.apk';apk.write_bytes(b'fixture APK, not a real build')
        self.source=root/FILE
        return {'project_path':str(root),'spec':{'pairs':6},'artifacts':[{'path':str(apk),'kind':'fixture'}],
            'checks':[{'name':'fixture_check','passed':True,'evidence':'fixture only'}],'gaps':['fixture builder only']}
    def output(self,status='passed',quote=' int pairs() { return 6; }'):
        assertion={'step_index':0,'status':status,'reasoning':'fixture source inference','precondition_analysis':'new game reachable',
            'call_chain':[{'file':FILE,'line':2,'quote':quote}],'counterexample_search':'checked pair count','gap':'','next_action':'','counterexample':None}
        if status=='failed':assertion['counterexample']={'preconditions':['new game'],'steps':['start'],'expected':'six pairs','actual':'fixture defect','reachability':'fixture path reachable'}
        return {'shared_analysis':'fixture shared investigation','results':[{'case_id':'C1','assertions':[assertion]}]}
    def agent(self,prompt,root,schema,**options):
        self.calls.append({'selection':current_selection(),'skill':current_skill(),'prompt':prompt,'root':Path(root)})
        return self.output()
    def run_chain(self,side_effect=None):
        run=self.service.create(self.studio,self.project,{'brief':'memory match with six pairs','delegation':True})
        with patch('server.core.codex_agent.CodexAgent.request_json',side_effect=side_effect or self.agent), \
             patch('server.gagasort.inspect_project',side_effect=AssertionError('Generated production has no fake Git/Unity binding')):
            while self.service.run_once():pass
        return self.service.get(self.studio,self.project,run['id'])
    def test_real_bridge_preserves_capability_selection_skill_and_readonly_results(self):
        run=self.run_chain()
        self.assertEqual(run['status'],'completed')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0]['selection'],self.selection)
        self.assertEqual(self.calls[0]['skill'],'EXACT PRODUCTION QA SKILL')
        self.assertIn('EXACT PRODUCTION QA SKILL',self.calls[0]['prompt'])
        self.assertEqual(run['qa']['execution']['source_review']['results'][0]['status'],'passed')
        self.assertEqual(run['qa']['execution']['source_review']['runtime_status'],'not_run')
        self.assertEqual(run['qa']['regression']['status'],'not_applicable')
        self.assertEqual(self.source.read_text(),SOURCE)
        evidence=run['qa']['execution']['source_review']['results'][0]['evidence']
        self.assertTrue(Path(evidence).is_file())
        artifact=next(a for a in run['artifacts'] if a['name']=='qa-source-evidence.zip')
        archive=self.service.artifact(self.studio,self.project,run['id'],artifact['id'])
        import zipfile
        with zipfile.ZipFile(archive) as bundle:
            self.assertIn('case-0001.json',bundle.namelist())
            self.assertIn('package-001.json',bundle.namelist())
            self.assertFalse(any(name.endswith('.jsonl') for name in bundle.namelist()))
        self.assertNotIn('fixture-secret',json.dumps(run))
    def test_real_bridge_validates_defect_evidence_before_internal_draft(self):
        run=self.run_chain(lambda *a,**kw:self.output('failed'))
        self.assertEqual(run['status'],'completed')
        finding=run['qa']['attribution']['findings'][0]
        self.assertEqual(finding['evidence'][0]['file'],FILE)
        self.assertEqual(finding['evidence'][0]['line'],2)
        self.assertEqual(run['qa']['bugs']['drafts'][0]['reproduction_provenance'],'static_inference')
        self.assertEqual(run['qa']['regression']['status'],'awaiting_fix')
    def test_real_bridge_rejects_fabricated_source_quote(self):
        run=self.run_chain(lambda *a,**kw:self.output(quote='fabricated missing source'))
        self.assertEqual(run['status'],'completed')
        self.assertEqual(next(s for s in run['steps'] if s['id']=='testing:1')['status'],'completed')
        result=run['qa']['execution']['source_review']['results'][0]
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertEqual(result['assertions'][0]['call_chain'],[])
        self.assertEqual(run['qa']['attribution']['findings'],[])
        self.assertEqual(run['qa']['bugs']['drafts'],[])
        self.assertEqual(self.source.read_text(),SOURCE)
    def test_text_only_model_capability_never_falls_back_to_default_agent(self):
        class TextOnly:
            def request_json(inner,prompt):return self.capability.request_json(prompt)
        self.service.model_factory=lambda node:TextOnly()
        run=self.service.create(self.studio,self.project,{'brief':'memory match with six pairs','delegation':True})
        with patch('server.core.codex_agent.CodexAgent.request_json') as agent:
            while self.service.run_once():pass
        run=self.service.get(self.studio,self.project,run['id'])
        self.assertEqual(run['status'],'failed')
        self.assertIn('不能切换',run['error']);agent.assert_not_called()
