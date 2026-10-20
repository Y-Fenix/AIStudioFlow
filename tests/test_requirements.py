import tempfile
import unittest
from pathlib import Path
from server.store import Store


class RequirementTests(unittest.TestCase):
    def test_import_preserves_source_and_invalidates_old_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db')
            project = store.create_project('A')
            task = store.create_task(project['id'], '需求测试')
            first = store.import_requirement(project['id'], task['id'], '需求.md', '关闭开关后保存状态')
            self.assertEqual(first['requirements'][0]['source'], '需求.md')
            self.assertEqual(len(first['requirements'][0]['sha256']), 64)
            same = store.import_requirement(project['id'], task['id'], '需求.md', '关闭开关后保存状态')
            self.assertEqual(same['revision'], first['revision'])
            produced = store.record_artifact(project['id'], task['id'], 0, {'cases': [1]})
            changed = store.import_requirement(project['id'], task['id'], '需求.md', '打开开关后保存状态')
            self.assertEqual(changed['artifacts'], {})
            self.assertGreater(changed['revision'], produced['revision'])
            self.assertEqual(changed['requirements'][0]['version'], 2)
            self.assertEqual(Store(Path(folder) / 'db').task(project['id'], task['id'])['requirements'], changed['requirements'])
            with self.assertRaises(ValueError):
                store.import_requirement(project['id'], task['id'], '空文档', ' ')


class ReviewTests(unittest.TestCase):
    def test_gaps_require_explicit_scope_decisions_and_hash_tracks_changes(self):
        from server.requirements import case_review_items, review_cases, case_review_hash
        output={'points':[], 'cases':[], 'gaps':[{'point_id':'p','reason':'未覆盖'}], 'ambiguities':['奖励规则未明确']}
        sources=[{'id':'r','source':'需求.xlsx','sha256':'hash','metadata':{'source_gaps':['未读取图片']}}]
        items=case_review_items(output,sources)
        self.assertEqual(len(items),3)
        with self.assertRaises(ValueError):review_cases(output,sources,[],True)
        decisions=[{'id':i['id'],'action':'accept_scope_gap','reason':'本批次排除，另行补需求'} for i in items]
        reviewed=review_cases(output,sources,decisions,True)
        self.assertTrue(reviewed['ready_for_execution'])
        self.assertEqual(reviewed['review_hash'],case_review_hash({**output,'user_review':reviewed},sources))
        self.assertNotEqual(reviewed['review_hash'],case_review_hash({**output,'ambiguities':[]},sources))
        decisions[0]['action']='needs_revision'
        self.assertFalse(review_cases(output,sources,decisions,True)['ready_for_execution'])
        with self.assertRaises(ValueError):review_cases(output,sources,decisions,False)

    def test_imported_resources_clear_only_reading_gaps_for_current_parent(self):
        from server.requirements import resolve_source_gaps,case_review_hash
        import copy
        parent={'id':'p','source':'https://example.feishu.cn/wiki/parent','sha256':'hash','content':'父正文',
                'metadata':{'revision_id':1,'source_gaps':['引用文档未展开：引用','尚未完整读取资源：source','尚未完整读取资源：img'],
                            'resources':[{'kind':'cite','type':'doc','file-type':'wiki','doc-id':'child','title':'引用'},
                                         {'kind':'source','token':'attachment'}]}}
        children=[{'id':'c','source':'https://example.feishu.cn/wiki/child','sha256':'c','content':'引用正文',
                   'metadata':{'referenced_by':parent['source'],'parent_sha256':'hash','parent_revision_id':1}},
                  {'id':'a','source':parent['source']+'#attachment=attachment','sha256':'a','content':'附件正文',
                   'metadata':{'referenced_by':parent['source'],'parent_sha256':'hash','parent_revision_id':1,
                               'file_token':'attachment','source_gaps':['页眉页脚未读取']}}]
        sources=[parent,*children];resolved=resolve_source_gaps(sources)
        self.assertEqual(resolved[0]['metadata']['effective_source_gaps'],['尚未完整读取资源：img'])
        self.assertEqual(len(parent['metadata']['source_gaps']),3)
        self.assertEqual(resolved[2]['metadata']['source_gaps'],['页眉页脚未读取'])
        self.assertEqual(case_review_hash({},sources),case_review_hash({},resolved))
        old=copy.deepcopy(sources);old[0]['metadata']['revision_id']=2
        self.assertEqual(len(resolve_source_gaps(old)[0]['metadata']['effective_source_gaps']),3)
        partial=resolve_source_gaps([parent,children[0]])
        self.assertIn('尚未完整读取资源：source',partial[0]['metadata']['effective_source_gaps'])
