import tempfile
import unittest
from pathlib import Path
from server.store import Store


class StoreTests(unittest.TestCase):
    def test_edit_case_invalidates_execution_and_rejects_empty_assertions(self):
        p = self.store.create_project('编辑')
        t = self.store.create_task(p['id'], '评审')
        t = self.store.import_requirement(p['id'], t['id'], '需求', '保存音量')
        output = {'points': [{'id':'p','title':'保存','requirement_id':t['requirements'][0]['id'],'quote':'保存音量'}],
                  'cases':[{'id':'c','title':'保存','point_ids':['p'],'preconditions':['已启动'],
                            'steps':[{'action':'保存','expected':'保持音量'}]}], 'gaps':[], 'ambiguities':[]}
        from server.requirements import review_cases
        output['user_review'] = review_cases(output, t['requirements'], [], True)
        t = self.store.record_artifact(p['id'], t['id'], 0, output)
        t = self.store.decide(p['id'], t['id'], 'confirm', t['revision'])
        t = self.store.record_artifact(p['id'], t['id'], 1, {'results':['旧结果']})
        changes = {'title':'重新保存','preconditions':['已启动'],'steps':[{'action':'点击保存','expected':''}]}
        with self.assertRaises(ValueError):
            self.store.edit_case(p['id'], t['id'], 'c', changes, t['revision'])
        self.assertIn('1', self.store.task(p['id'], t['id'])['artifacts'])
        changes['steps'][0]['expected'] = '音量保持'
        updated = self.store.edit_case(p['id'], t['id'], 'c', changes, t['revision'])
        self.assertEqual(updated['stage'], 0)
        self.assertEqual(set(updated['artifacts']), {'0'})
        self.assertEqual(updated['artifacts']['0']['cases'][0]['point_ids'], ['p'])
        with self.assertRaises(ValueError):
            self.store.edit_case(p['id'], t['id'], 'c', changes, t['revision'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.sqlite'
        self.store = Store(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_projects_survive_restart_and_names_are_unique(self):
        project = self.store.create_project(' GagaSort ')
        self.assertEqual(Store(self.path).projects()['items'][0]['id'], project['id'])
        with self.assertRaises(ValueError):
            self.store.create_project('gagasort')
        with self.assertRaises(ValueError):
            self.store.create_project(' ')

    def test_task_isolation_and_no_unverified_advance(self):
        a = self.store.create_project('A')
        b = self.store.create_project('B')
        task = self.store.create_task(a['id'], '版本测试')
        with self.assertRaises(KeyError):
            self.store.task(b['id'], task['id'])
        with self.assertRaises(ValueError):
            self.store.decide(a['id'], task['id'], 'confirm', 1)
        self.assertEqual(self.store.task(a['id'], task['id'])['stage'], 0)

    def test_artifact_revision_prevents_stale_confirmation(self):
        p = self.store.create_project('A')
        t = self.store.create_task(p['id'], '测试')
        t = self.store.record_artifact(p['id'], t['id'], 0, {'coverage': 'reviewed'})
        with self.assertRaises(ValueError):
            self.store.decide(p['id'], t['id'], 'confirm', t['revision'] - 1)
        t = self.store.decide(p['id'], t['id'], 'confirm', t['revision'])
        self.assertEqual(t['stage'], 1)
        t = self.store.invalidate(p['id'], t['id'], '需求变更')
        self.assertEqual(t['stage'], 0)
        self.assertEqual(t['artifacts'], {})
        self.assertGreaterEqual(len(t['events']), 4)

    def test_stale_generation_cannot_replace_new_requirements(self):
        p = self.store.create_project('A')
        t = self.store.create_task(p['id'], '测试')
        old_revision = t['revision']
        self.store.import_requirement(p['id'], t['id'], '需求', '新正文')
        with self.assertRaises(ValueError):
            self.store.record_artifact(p['id'], t['id'], 0, {'cases': []}, expected_revision=old_revision)

    def test_project_search_pagination_treats_wildcards_literally(self):
        for i in range(12):
            self.store.create_project(f'项目{i:02d}')
        self.store.create_project('项目%特殊')
        self.assertEqual(len(self.store.projects(page=3, size=5)['items']), 3)
        self.assertEqual(self.store.projects(query='%')['total'], 1)
        self.assertEqual(self.store.projects(query='项目')['total'], 13)

    def test_existing_bug_confirmation_advances_and_target_change_invalidates(self):
        from datetime import datetime, timezone
        from server.bugs import confirm_existing_records
        p=self.store.create_project('已有单据')['id']
        t=self.store.create_task(p,'回归批次')
        for stage in range(4):
            t=self.store.record_artifact(p,t['id'],stage,{'ready_for_review':True})
            t=self.store.decide(p,t['id'],'confirm',t['revision'])
        target={'verified':True,'base_token':'b','table_id':'tblA'}
        t=self.store.save_bug_target(p,t['id'],target,t['revision'])
        a={'drafts':[{'draft_key':'k','root_cause_id':'r','missing':[]}],
           'remote_checks':{'k':{'record_id':'recA','table_id':'tblA','checked_at':datetime.now(timezone.utc).isoformat()}},
           'publication_complete':False}
        t=self.store.record_artifact(p,t['id'],4,a)
        with self.assertRaises(ValueError):self.store.decide(p,t['id'],'confirm',t['revision'])
        t=self.store.record_artifact(p,t['id'],4,confirm_existing_records(a,target),t['revision'])
        t=self.store.save_bug_target(p,t['id'],target,t['revision'])
        self.assertFalse(t['artifacts']['4']['publication_complete'])
        self.assertNotIn('linked_records',t['artifacts']['4'])
        with self.assertRaises(ValueError):self.store.decide(p,t['id'],'confirm',t['revision'])
        t=self.store.record_artifact(p,t['id'],4,confirm_existing_records(a,target),t['revision'])
        t=self.store.decide(p,t['id'],'confirm',t['revision'])
        self.assertEqual(t['stage'],5)

    def test_regression_review_preserves_execution_and_new_run_invalidates_review(self):
        p=self.store.create_project('回归决策')['id']
        t=self.store.create_task(p,'测试')
        for stage in range(5):
            t=self.store.record_artifact(p,t['id'],stage,{'ready_for_review':True,'publication_complete':True})
            t=self.store.decide(p,t['id'],'confirm',t['revision'])
        r={'roots':[{'root_cause_id':'r','verdict':'still_reproducible'}], 'execution':{'code_fingerprint':'hash'}}
        t=self.store.save_logic_regression(p,t['id'],r,t['revision'])
        t=self.store.record_artifact(p,t['id'],5,{'ready_for_review':True,'decisions':['keep_open']},t['revision'])
        self.assertEqual(t['regression'],r)
        t=self.store.save_logic_regression(p,t['id'],r,t['revision'])
        self.assertNotIn('5',t['artifacts'])
        with self.assertRaises(ValueError):self.store.decide(p,t['id'],'confirm',t['revision'])
        t=self.store.record_artifact(p,t['id'],5,{'ready_for_review':True,'decisions':['keep_open']},t['revision'])
        t=self.store.decide(p,t['id'],'confirm',t['revision'])
        self.assertEqual(t['status'],'completed')

class NoBugBatchTests(unittest.TestCase):
    def test_empty_submission_can_finish_without_fake_regression(self):
        import tempfile,json
        from pathlib import Path
        from server.store import Store
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db.sqlite');p=store.create_project('无单据')['id'];t=store.create_task(p,'无缺陷批次')['id']
            artifacts={'1':{'results':[{'id':'C1','status':'insufficient_evidence','detail':'调用链未闭合'}]},
                       '3':{'groups':[],'excluded':{}},'4':{'drafts':[],'publication_complete':True}}
            with store.connection() as db:
                db.execute("UPDATE tasks SET stage=4,artifacts=? WHERE id=?",(json.dumps(artifacts),t))
            result=store.decide(p,t,'confirm',1)
            self.assertEqual(result['stage'],5)
            self.assertTrue(result['artifacts']['5']['ready_for_review'])
            self.assertEqual(result['artifacts']['5']['unresolved_results'][0]['id'],'C1')
            self.assertFalse(result['artifacts']['5']['client_verified'])
            self.assertFalse(result['artifacts']['5']['remote_state_changed'])
            finished=store.decide(p,t,'confirm',result['revision'])
            self.assertEqual(finished['status'],'completed')
            self.assertIn('不代表全部测试通过',finished['artifacts']['5']['scope'])

    def test_selected_root_cannot_be_hidden_by_empty_drafts(self):
        import tempfile,json
        from pathlib import Path
        from server.store import Store
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'db.sqlite');p=store.create_project('有根因')['id'];t=store.create_task(p,'不允许空草稿')['id']
            with store.connection() as db:
                db.execute('UPDATE tasks SET stage=4,artifacts=? WHERE id=?',(json.dumps({'3':{'groups':[{'root_cause_id':'R'}]},'4':{'drafts':[],'publication_complete':True}}),t))
            with self.assertRaisesRegex(ValueError,'筛选仍有提单根因'):store.decide(p,t,'confirm',1)
            self.assertEqual(store.task(p,t)['stage'],4)
