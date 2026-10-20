import json
import unittest
from unittest.mock import patch
from server.connectors.lark import LarkClient


class LarkTests(unittest.TestCase):
    def test_target_uses_resolved_table_not_query_parameter(self):
        client = LarkClient()
        url = 'https://example.feishu.cn/wiki/token?table=dashboard'
        with patch.object(client, 'resolve_base', return_value={'base_token':'base','table_id':'tblReal','block_type':'table'}), patch.object(client, '_read', return_value={'fields':[{'field_id':'fld1','field_name':'标题','type':'text'}]}) as read:
            target = client.inspect_bug_target(url)
        self.assertEqual(target['table_id'], 'tblReal')
        self.assertIn('tblReal', read.call_args.args[0])
        self.assertNotIn('dashboard', read.call_args.args[0])
        with patch.object(client, 'resolve_base', return_value={'base_token':'base','block_type':'dashboard'}):
            with self.assertRaises(ValueError): client.inspect_bug_target(url)

    def test_resource_placeholders_are_not_complete_content(self):
        document = {'document_id': 'doc1', 'revision_id': 3,
                    'content': '<p>需求</p><img token="image"/><sheet token="sheet"/>',
                    'reference_map': {'img': {'1': {'token': 'image'}}}}
        with patch.object(LarkClient, 'fetch_document', return_value={'document': document}):
            content, metadata = LarkClient().requirement('https://example.feishu.cn/wiki/token')
        self.assertEqual(content, document['content'])
        self.assertEqual(len(metadata['source_gaps']), 2)
        self.assertEqual(metadata['reference_map'], document['reference_map'])
        with patch.object(LarkClient, 'fetch_document', return_value={'document': {'content': ''}}):
            with self.assertRaisesRegex(ValueError, '正文为空'):
                LarkClient().requirement('https://example.feishu.cn/wiki/token')

    def test_fetch_uses_argument_array_and_user_identity(self):
        class Result:
            returncode=0
            stdout=json.dumps({'ok':True,'data':{'document':{'content':'需求','revision_id':1}}})
            stderr=''
        with patch('server.connectors.lark.subprocess.run',return_value=Result()) as run:
            result=LarkClient().fetch_document('https://example.feishu.cn/wiki/token')
            self.assertEqual(result['document']['revision_id'],1)
            command=run.call_args.args[0]
            self.assertIn('--as',command)
            self.assertIn('user',command)
            self.assertNotIn('shell',run.call_args.kwargs)

    def test_auth_failure_never_becomes_empty_success(self):
        class Result:
            returncode=3
            stdout=''
            stderr=json.dumps({'ok':False,'error':{'type':'authentication','subtype':'token_missing','message':'need authorization'}})
        with patch('server.connectors.lark.subprocess.run',return_value=Result()):
            with self.assertRaisesRegex(ValueError,'token_missing'):
                LarkClient().resolve_base('https://example.feishu.cn/wiki/token')

    def test_bug_status_requires_exact_record_and_real_field(self):
        target={'verified':True,'base_token':'base','table_id':'tblA','fields':[{'field_id':'fldStatus','field_name':'状态','type':'select','multiple':False}]}
        client=LarkClient()
        data={'records':[{'record_id':'recA','fields':{'状态':'待验证'}}]}
        with patch.object(client,'_read',return_value=data) as read:
            result=client.read_bug_status(target,'recA','fldStatus','待验证')
            self.assertTrue(result['pending'])
            self.assertFalse(result['remote_state_changed'])
            self.assertIn('--format',read.call_args.args[0])
            self.assertIn('--field-id',read.call_args.args[0])
            self.assertFalse(client.read_bug_status(target,'recA','fldStatus','已解决')['pending'])
        for invalid in [{'records':[]},{'records':[{'record_id':'recOther','fields':{'状态':'待验证'}}]},
                        {'records':[{'record_id':'recA','fields':{'状态':['待验证']}}]}]:
            with patch.object(client,'_read',return_value=invalid):
                with self.assertRaises(ValueError):client.read_bug_status(target,'recA','fldStatus','待验证')
        with patch.object(client,'_read') as read:
            with self.assertRaises(ValueError):client.read_bug_status(target,'recA','unknown','待验证')
            read.assert_not_called()

    def test_neutral_block_requires_directory_type_confirmation(self):
        client=LarkClient()
        resolved={'base_token':'base','block_id':'tblA'}
        with patch.object(client,'resolve_base',return_value=resolved), patch.object(client,'_read',side_effect=[{'blocks':[{'id':'tblA','type':'table'}]}, {'fields':[{'field_id':'f','type':'text'}]}]):
            self.assertEqual(client.inspect_bug_target('https://example.feishu.cn/wiki/x')['table_id'],'tblA')
        with patch.object(client,'resolve_base',return_value=resolved), patch.object(client,'_read',return_value={'blocks':[{'id':'tblA','type':'dashboard'}]}):
            with self.assertRaises(ValueError):client.inspect_bug_target('https://example.feishu.cn/wiki/x')

    def test_real_document_resource_shapes_remain_unverified_dependencies(self):
        content='<p>当前规则<del>历史规则</del></p><img id="i" alt="描述" src="token"/><cite doc-id="wiki" title="昵称库" file-type="wiki" type="doc"/><source name="机器人规则.docx" token="file"/>'
        with patch.object(LarkClient,'fetch_document',return_value={'document':{'content':content}}):
            actual,metadata=LarkClient().requirement('https://example.feishu.cn/wiki/x')
        self.assertEqual(actual,content)
        self.assertEqual(metadata['deleted_block_count'],1)
        self.assertEqual(len(metadata['resources']),3)
        self.assertTrue(all(r['read_status']=='reference_only' for r in metadata['resources']))
        self.assertTrue(any('昵称库' in gap for gap in metadata['source_gaps']))
        self.assertTrue(any('删除线' in gap for gap in metadata['source_gaps']))

    def test_reference_reader_uses_verified_host_and_reports_partial_failures(self):
        metadata={'resources':[
            {'kind':'cite','type':'doc','file-type':'wiki','doc-id':'good','title':'规则'},
            {'kind':'cite','type':'doc','file-type':'wiki','doc-id':'good','title':'重复'},
            {'kind':'cite','type':'doc','file-type':'docx','doc-id':'bad','title':'失败'},
            {'kind':'cite','type':'doc','file-type':'wiki','doc-id':'../../escape'},
            {'kind':'source','token':'attachment'}]}
        with patch.object(LarkClient,'requirement',side_effect=[('真实正文',{'kind':'feishu'}), ValueError('无权限')]) as read:
            r=LarkClient().referenced_requirements('https://example.feishu.cn/wiki/root',metadata)
        self.assertEqual(len(r),2)
        self.assertEqual(r[0]['metadata']['referenced_by'],'https://example.feishu.cn/wiki/root')
        self.assertEqual(r[1]['status'],'failed')
        self.assertEqual(read.call_args_list[0].args[0],'https://example.feishu.cn/wiki/good')

    def test_actual_status_matrix_is_strictly_projected_and_single_select(self):
        target={'verified':True,'base_token':'b','table_id':'tbl','fields':[{'id':'f','name':'缺陷状态','type':'select','multiple':False}]}
        matrix={'record_id_list':['recA'],'field_id_list':['f'],'data':[[['⚠️待验证']]]}
        with patch.object(LarkClient,'_read',return_value=matrix):
            result=LarkClient().read_bug_status(target,'recA','f','⚠️待验证')
            self.assertTrue(result['pending'])
        for bad in [{**matrix,'record_id_list':['recWrong']},{**matrix,'field_id_list':['wrong']},
                    {**matrix,'data':[[[]]]},{**matrix,'data':[[['⚠️待验证','未解决']]]}]:
            with patch.object(LarkClient,'_read',return_value=bad):
                with self.assertRaises(ValueError):LarkClient().read_bug_status(target,'recA','f','⚠️待验证')

    def test_create_uses_private_file_and_one_record_payload(self):
        from pathlib import Path
        client=LarkClient()
        payload={'create_records':[{'fldDescription':'测试样例，不是生产Bug'}]}
        captured=[]
        def invoke(args):
            self.assertEqual(args[:2],['base','+record-batch-create'])
            value=args[args.index('--json')+1]
            self.assertTrue(value.startswith('@'))
            path=Path(value[1:]);captured.append(path)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(path.read_text()),payload)
            return {'record_id_list':['recFixture']}
        with patch.object(client,'_read',side_effect=invoke):
            response=client.create_bug_record({'base_token':'base','table_id':'tblFixture','payload':payload})
        self.assertEqual(response['record_id_list'],['recFixture'])
        self.assertFalse(captured[0].exists())
        with self.assertRaises(ValueError):
            client.create_bug_record({'base_token':'base','table_id':'tblFixture','payload':{'create_records':[{},{}]}})

    def test_reconciliation_compares_projection_by_ids_not_column_order(self):
        client=LarkClient()
        target={'verified':True,'base_token':'base','table_id':'tbl','fields':[
            {'id':'description','type':'text'},{'id':'status','type':'select','multiple':False}]}
        request={'base_token':'base','table_id':'tbl','request_hash':'hash',
                 'payload':{'create_records':[{'description':'原文\n步骤','status':'未解决'}]}}
        matrix={'record_id_list':['recFixture'],'field_id_list':['status','description'],
                'data':[[['未解决'],'原文\n步骤']]}
        with patch.object(client,'_read',return_value=matrix):
            self.assertTrue(client.verify_bug_record(request,target,'recFixture')['matched'])
        with patch.object(client,'_read',return_value={**matrix,'data':[[['未解决'],'改动过的内容']]}):
            check=client.verify_bug_record(request,target,'recFixture')
            self.assertFalse(check['matched'])
            self.assertEqual(check['mismatched_field_ids'],['description'])
        for invalid in [{**matrix,'record_id_list':['recWrong']},
                        {**matrix,'field_id_list':['status','status']},
                        {**matrix,'data':[[['未解决']]]}]:
            with patch.object(client,'_read',return_value=invalid):
                with self.assertRaises(ValueError):client.verify_bug_record(request,target,'recFixture')

    def test_attachment_uses_fixed_local_path_and_verifies_reference_size(self):
        import io,zipfile
        from pathlib import Path
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>机器人规则样例</w:t></w:r></w:p></w:body></w:document>')
        raw=archive.getvalue()
        resource={'kind':'source','name':'../rules.docx','token':'fileToken','size':str(len(raw))}
        client=LarkClient();paths=[]
        def download(arguments,cwd=None):
            self.assertEqual(arguments[arguments.index('--output')+1],'attachment.docx')
            p=Path(cwd)/'attachment.docx';p.write_bytes(raw);paths.append(p)
            return {'file_token':'fileToken','selected_type':'source_file','status':'READY'}
        with patch.object(client,'_read',side_effect=download):
            content,metadata=client.attachment_requirement('https://example.feishu.cn/wiki/parent',resource)
            self.assertIn('机器人规则样例',content)
            self.assertEqual(metadata['file_token'],'fileToken')
            with self.assertRaisesRegex(ValueError,'大小'):
                client.attachment_requirement('https://example.feishu.cn/wiki/parent',{**resource,'size':'1'})
        self.assertTrue(all(not p.exists() for p in paths))
        with self.assertRaises(ValueError):
            client.attachment_requirement('https://example.feishu.cn/wiki/parent',{**resource,'size':'700001'})
