import tempfile
import unittest
from pathlib import Path
from server.store import Store

class NodeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'test.sqlite')
        self.project=self.store.create_project('样例')['id']
        self.task=self.store.create_task(self.project,'节点测试')['id']

    def test_logs_keep_operation_stage_when_task_advances(self):
        self.store.record_artifact(self.project,self.task,0,{'ready':True},1)
        current=self.store.task(self.project,self.task)
        self.store.decide(self.project,self.task,'confirm',current['revision'])
        current=self.store.task(self.project,self.task)
        self.assertEqual(current['stage'],1)
        self.assertEqual(current['events'][-1]['stage'],0)

    def test_six_skills_persist_independently_and_reject_stale_save(self):
        from server.node_skills import defaults
        initial=self.store.task(self.project,self.task)
        self.assertEqual(set(initial['node_skills']),set(map(str,range(6))))
        text='---\nname: sample\ndescription: 测试规则\n---\n# 测试\n只引用真实证据。'
        updated=self.store.save_node_skill(self.project,self.task,2,text,initial['revision'])
        self.assertEqual(updated['node_skills']['2']['content'],text)
        self.assertEqual(updated['node_skills']['0'],defaults()['0'])
        with self.assertRaises(ValueError):
            self.store.save_node_skill(self.project,self.task,1,text,initial['revision'])
        self.assertEqual(Store(self.store.path).task(self.project,self.task)['node_skills']['2']['content'],text)

    def test_empty_skill_and_active_job_edits_are_rejected(self):
        task=self.store.task(self.project,self.task)
        with self.assertRaises(ValueError):
            self.store.save_node_skill(self.project,self.task,0,'',task['revision'])
        with self.store.connection() as db:
            db.execute("INSERT INTO jobs(id,project_id,task_id,revision,status) VALUES('active',?,?,?,'running')",(self.project,self.task,task['revision']))
        with self.assertRaisesRegex(ValueError,'后台操作'):
            self.store.save_node_skill(self.project,self.task,0,'规则',task['revision'])

    def test_local_skills_are_full_defaults_and_imports_still_override(self):
        from unittest.mock import patch
        import hashlib
        from server.node_skills import defaults
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'CODEX_HOME':folder}):
            for stage,directory,name in [(0,'test-test-case','TEST_Test_Case'),(1,'test-testcase-codetest','TEST_Test_Codetest')]:
                path=Path(folder)/'skills'/directory/'SKILL.md';path.parent.mkdir(parents=True)
                text='---\nname: '+name+'\n---\n完整本地规则-'+str(stage)
                path.write_text(text)
                value=defaults()[str(stage)]
                self.assertEqual(value['content'],text)
                self.assertEqual(value['name'],name)
                self.assertEqual(value['source_path'],str(path.resolve()))
                self.assertEqual(value['source_kind'],'local')
                self.assertEqual(value['sha256'],hashlib.sha256(text.encode()).hexdigest())
            task=self.store.task(self.project,self.task)
            updated=self.store.save_node_skill(self.project,self.task,1,'用户替换规则',task['revision'])
            self.assertEqual(updated['node_skills']['1']['content'],'用户替换规则')
            self.assertEqual(updated['node_skills']['0']['content'],task['node_skills']['0']['content'])
            new=self.store.create_task(self.project,'读取新的本机默认')
            self.assertEqual(new['node_skills']['0']['content'],defaults()['0']['content'])

    def test_missing_local_skills_use_explicit_full_bundled_copies(self):
        from unittest.mock import patch
        from server.node_skills import defaults
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{'CODEX_HOME':folder}):
            skills=defaults()
            for stage,name in [('0','TEST_Test_Case'),('1','TEST_Test_Codetest')]:
                value=skills[stage]
                self.assertEqual(value['name'],name)
                self.assertEqual(value['source_kind'],'bundled')
                self.assertEqual(value['content'],Path(value['source_path']).read_text())
                self.assertGreater(len(value['content']),2000)

    def test_full_default_skill_reaches_generation_and_static_model_requests(self):
        from unittest.mock import patch
        from server.node_skills import defaults,skill_scope
        from server.ai_models import selection_scope
        from server.codex_model import CodexModel
        from server.static_review import SourceCatalog,review_case
        skills=defaults()
        selection={'source':'custom','base_url':'https://example.test/v1','protocol':'responses','api_key':'test','model':'test','effort':None}
        candidate={'points':[{'id':'p','title':'保存','requirement_id':'r','quote':'保存状态'}],
                   'cases':[],'gaps':[{'point_id':'p','reason':'执行条件未明确'}],'ambiguities':[]}
        with selection_scope(selection),skill_scope(skills['0']['content']),patch('server.responses_model.request_json',return_value=candidate) as transport:
            CodexModel().generate([{'id':'r','content':'保存状态'}])
            self.assertEqual(transport.call_count,2)
            for call in transport.call_args_list:self.assertIn(skills['0']['content'],call.args[1])
        case={'id':'c','title':'保存','preconditions':['可进入设置'],'steps':[{'action':'保存','expected':'状态保留'}]}
        with selection_scope(selection),skill_scope(skills['1']['content']),patch('server.responses_model.request_json',return_value={'read':[],'search':['Save']}) as transport:
            result,_=review_case(case,[],SourceCatalog(Path(self.temp.name)),CodexModel(),max_rounds=1)
            self.assertEqual(result['status'],'insufficient_evidence')
            self.assertIn(skills['1']['content'],transport.call_args.args[1])
