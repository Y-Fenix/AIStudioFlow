import unittest
from server.bugs import build_drafts, prepare_drafts


class BugDraftTests(unittest.TestCase):
    def test_publication_request_binds_current_preview_and_one_root_per_request(self):
        from server.bugs import preview_field_mapping, prepare_publication
        import copy
        target = {'verified': True, 'base_token': 'base', 'table_id': 'tbl',
                  'fields': [{'id': 'description', 'type': 'text', 'name': '描述'}]}
        drafts = [{'draft_key': key, 'root_cause_id': key, 'title': '真实断言候选',
                   'steps': ['操作'], 'actual': '错误', 'expected': '正确', 'missing': []}
                  for key in ('a', 'b')]
        preview = preview_field_mapping(drafts, target, {'description': 'full_description'})
        artifact = {'drafts': drafts, 'field_preview': preview}
        plan = prepare_publication(artifact, target, preview['preview_hash'])
        self.assertEqual(len(plan['requests']), 2)
        self.assertTrue(all(len(r['payload']['create_records']) == 1 for r in plan['requests']))
        self.assertNotEqual(plan['requests'][0]['request_hash'], plan['requests'][1]['request_hash'])
        self.assertFalse(plan['external_write_performed'])
        changed = copy.deepcopy(artifact)
        changed['drafts'][0]['actual'] = '新结果'
        with self.assertRaisesRegex(ValueError, '重新预览'):
            prepare_publication(changed, target, preview['preview_hash'])
        with self.assertRaises(ValueError):
            prepare_publication(artifact, {**target, 'table_id': 'other'}, preview['preview_hash'])
        incomplete = copy.deepcopy(artifact)
        incomplete['drafts'][0]['missing'] = ['构建版本']
        incomplete['field_preview'] = preview_field_mapping(incomplete['drafts'], target, preview['mapping'])
        with self.assertRaisesRegex(ValueError, '缺口'):
            prepare_publication(incomplete, target, incomplete['field_preview']['preview_hash'])

    def test_manual_reproduction_does_not_replace_runner_evidence(self):
        results = [{'id':'a','status':'failed','detail':'原始断言失败','evidence':'run.json'}]
        groups = [{'root_cause_id':'r','title':'原因','result_ids':['a'],'root_evidence':['code:12']}]
        notes = [{'result_id':'a','preconditions':['账号条件'], 'steps':['点击领取'],
                  'expected':'次数加一','actual':'次数为零'}]
        result = prepare_drafts(groups, results, notes, {'project':'A','code_fingerprint':'hash'})
        draft = result['drafts'][0]
        self.assertEqual(draft['reproduction_provenance'], 'user_supplied')
        self.assertEqual(draft['failure_evidence'], ['run.json'])
        self.assertIn('构建版本', draft['missing'])
        self.assertFalse(result['publication_complete'])
        self.assertNotIn('steps', results[0])
        with self.assertRaises(ValueError):
            prepare_drafts(groups, results, [{**notes[0], 'result_id':'unknown'}], {})

    def test_root_group_produces_one_traceable_draft(self):
        group = {'root_cause_id':'root', 'title':'共享状态错误', 'result_ids':['a','b'], 'root_evidence':['code:10']}
        failures = [{'id':id, 'status':'failed', 'evidence':'run.json', 'steps':['打开设置','点击开关'],
                     'expected':'切换状态', 'actual':'状态未变化', 'preconditions':['开关开启']} for id in ['a','b']]
        drafts = build_drafts([group], failures, {'project':'GagaSort','code_fingerprint':'sha','build':'test-build'})
        self.assertEqual(len(drafts),1)
        self.assertEqual(drafts[0]['related_result_ids'],['a','b'])
        self.assertTrue(drafts[0]['ready_for_review'])
        self.assertEqual(drafts[0]['actual'],'状态未变化')

    def test_missing_reproduction_is_blocked_not_invented(self):
        draft = build_drafts([{'root_cause_id':'r','title':'候选','result_ids':['a'],'root_evidence':['code']}],
            [{'id':'a','status':'failed','evidence':'run'}], {'project':'A'})[0]
        self.assertFalse(draft['ready_for_review'])
        self.assertIsNone(draft['actual'])
        self.assertIn('复现步骤',draft['missing'])

    def test_field_preview_uses_real_ids_and_never_publishes(self):
        from server.bugs import preview_field_mapping
        target = {'verified':True,'base_token':'base','table_id':'tblReal','fields':[
            {'field_id':k,'field_name':k,'type':'text'} for k in ['f1','f2','f3','f4']]}
        draft = {'draft_key':'key','title':'标题','steps':['打开','点击'],'expected':'成功','actual':'失败','missing':[]}
        mapping = dict(zip(['f1','f2','f3','f4'],['title','steps','expected','actual']))
        result = preview_field_mapping([draft],target,mapping)
        self.assertEqual(result['records'][0]['fields']['f2'],'1. 打开\n2. 点击')
        self.assertTrue(result['records'][0]['ready_for_review'])
        self.assertFalse(result['external_write_performed'])
        changed = preview_field_mapping([{**draft,'actual':'另一个失败'}],target,mapping)
        self.assertNotEqual(result['preview_hash'],changed['preview_hash'])
        for invalid in [{'unknown':'title'}, {'f1':'unknown'}]:
            with self.assertRaises(ValueError): preview_field_mapping([draft],target,invalid)
        with self.assertRaises(ValueError):
            preview_field_mapping([draft],{**target,'verified':False},mapping)
        unsupported = {**target,'fields':[{'field_id':'f1','type':'select'}]}
        with self.assertRaises(ValueError): preview_field_mapping([draft],unsupported,{'f1':'title'})

    def test_preview_keeps_reproduction_gaps_and_missing_mappings(self):
        from server.bugs import preview_field_mapping
        target = {'verified':True,'base_token':'b','table_id':'tbl','fields':[{'field_id':'f','type':'text'}]}
        result=preview_field_mapping([{'draft_key':'k','title':'标题','missing':['构建版本']}],target,{'f':'title'})
        record=result['records'][0]
        self.assertFalse(record['ready_for_review'])
        self.assertIn('构建版本',record['missing'])
        self.assertIn('复现步骤',record['unmapped'])

    def test_existing_bug_confirmation_requires_complete_fresh_unique_links(self):
        from datetime import datetime, timezone, timedelta
        from server.bugs import confirm_existing_records
        target={'verified':True,'base_token':'b','table_id':'tblA'}
        check={'record_id':'recA','table_id':'tblA','checked_at':datetime.now(timezone.utc).isoformat()}
        draft={'draft_key':'k','root_cause_id':'r','missing':[]}
        artifact={'drafts':[draft],'remote_checks':{'k':check},'publication_complete':False}
        result=confirm_existing_records(artifact,target)
        self.assertTrue(result['publication_complete'])
        self.assertFalse(result['external_write_performed'])
        self.assertEqual(result['linked_records'][0]['record_id'],'recA')
        self.assertFalse(artifact['publication_complete'])
        bad=[{**artifact,'remote_checks':{}},
             {**artifact,'drafts':[{**draft,'missing':['复现步骤']}]},
             {**artifact,'remote_checks':{'k':{**check,'table_id':'tblWrong'}}},
             {**artifact,'remote_checks':{'k':{**check,'checked_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}}},
             {**artifact,'drafts':[draft,{**draft,'draft_key':'k2','root_cause_id':'r2'}], 'remote_checks':{'k':check,'k2':check}}]
        for invalid in bad:
            with self.assertRaises(ValueError):confirm_existing_records(invalid,target)

    def test_export_preserves_one_root_per_row_and_escapes_csv_formulas(self):
        import csv, io, json
        from server.bugs import export_bug_preview
        record={'draft_key':'k','rows':[{'field_id':'f','field_name':'标题','value':'=1+1'}],
                'fields':{'f':'=1+1'},'missing':['复现步骤'],'unmapped':[]}
        artifact={'field_preview':{'scope':'预览','preview_hash':'hash','records':[record]}}
        raw,mime,ext=export_bug_preview(artifact,'csv')
        rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1][0],"'=1+1")
        self.assertEqual(rows[1][-1],'未发布的字段预览')
        data=json.loads(export_bug_preview(artifact,'json')[0])
        self.assertEqual(data['records'][0]['fields']['f'],'=1+1')
        self.assertFalse(data['external_write_performed'])
        with self.assertRaises(ValueError):export_bug_preview({},'csv')
        with self.assertRaises(ValueError):export_bug_preview(artifact,'xlsx')

    def test_actual_table_description_layout_and_existing_select_values(self):
        from server.bugs import preview_field_mapping
        target={'verified':True,'base_token':'b','table_id':'tbl','fields':[
            {'id':'description','name':'缺陷描述','type':'text','style':{'type':'plain'}},
            {'id':'status','name':'缺陷状态','type':'select','multiple':False,'options':[{'name':'未解决'},{'name':'⚠️待验证'}]}]}
        draft={'draft_key':'k','title':'次数错误','preconditions':['账号已满足条件'],'steps':['领取奖励'],
               'expected':'次数为1','actual':'次数为0','root_evidence':['code:12'],'failure_evidence':['run.json'],'missing':[]}
        mapping={'description':'full_description','status':{'literal':'未解决'}}
        result=preview_field_mapping([draft],target,mapping)['records'][0]
        self.assertTrue(result['ready_for_review'])
        self.assertIn('复现步骤：\n领取奖励',result['fields']['description'])
        self.assertIn('实际结果：\n次数为0',result['fields']['description'])
        self.assertEqual(result['fields']['status'],'未解决')
        for value in ['待验证','不存在']:
            with self.assertRaises(ValueError):preview_field_mapping([draft],target,{**mapping,'status':{'literal':value}})

    def test_logic_bug_can_be_reviewed_without_fabricated_client_build(self):
        from server.bugs import preview_field_mapping
        group={'root_cause_id':'root','title':'逻辑错误','result_ids':['failure']}
        result={'id':'failure','status':'failed','preconditions':['逻辑输入'],
                'steps':['运行生产方法断言'],'expected':'1','actual':'0','evidence':'actual.log'}
        environment={'project':'GagaSort','code_fingerprint':'hash','build':None,
                     'method':'production_suite_with_stubs'}
        draft=build_drafts([group],[result],environment)[0]
        self.assertEqual(draft['missing'],[])
        self.assertIsNone(draft['environment']['build'])
        self.assertIn('未执行Unity客户端',draft['verification_scope'])
        target={'verified':True,'table_id':'tbl','base_token':'base',
                'fields':[{'id':'description','type':'text','name':'缺陷描述'}]}
        preview=preview_field_mapping([draft],target,{'description':'full_description'})
        value=preview['records'][0]['fields']['description']
        self.assertIn('hash',value)
        self.assertIn('production_suite_with_stubs',value)
        self.assertIn('未验证客户端构建',value)
        self.assertTrue(preview['records'][0]['ready_for_review'])
        runtime=build_drafts([group],[result],{**environment,'method':'client_runtime'})[0]
        self.assertIn('构建版本',runtime['missing'])
