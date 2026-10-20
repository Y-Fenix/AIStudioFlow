import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server.codex_model import CodexModel

class GenerationBatchTests(unittest.TestCase):
    def test_html_payload_keeps_text_quotes_but_not_ids_and_resource_urls(self):
        from server.generation_batches import chunks
        requirements=[{'id':'r','source':'doc','content':'<h1 id="huge-id">奖励</h1><p style="font-size:14px">领取后保存</p><del>重复发奖</del>',
                       'metadata':{'kind':'feishu','source_gaps':['图片未读取'],'reference_map':{'unused':'secret-url'}}}]
        rows=chunks(requirements)
        encoded=json.dumps(rows,ensure_ascii=False)
        self.assertIn('领取后保存',encoded)
        self.assertIn('图片未读取',encoded)
        for noise in ('huge-id','font-size','secret-url','重复发奖'):self.assertNotIn(noise,encoded)

    def test_default_batches_bound_gateway_work_without_losing_requirement_text(self):
        from server.generation_batches import chunks
        text='明确规则。'*700
        rows=chunks([{'id':'r','content':text}])
        self.assertTrue(all(len(r['content'])<=1000 for r in rows))
        self.assertEqual(''.join(r['content'] for r in rows),text)

    def test_large_source_is_split_without_dropping_tail_or_source(self):
        from server.generation_batches import chunks
        value='完整规则。'*8000+'尾部必须结算'
        rows=chunks([{'id':'r','content':value},{'id':'other','content':'另一份需求'}],limit=8000)
        self.assertGreater(len(rows),2)
        self.assertTrue(all(len(row['content'])<=8000 for row in rows))
        self.assertEqual(''.join(row['content'] for row in rows if row['id']=='r'),value)
        self.assertEqual(rows[-1]['id'],'other')

    def test_failed_audit_resumes_design_checkpoint_and_rejects_fabricated_quotes(self):
        from server.generation_batches import generation_scope
        requirements=[{'id':'r','content':'保存状态'}]
        candidate={'points':[{'id':'p','title':'保存','requirement_id':'r','quote':'保存状态'}],
                   'cases':[],'gaps':[{'point_id':'p','reason':'待确认'}],'ambiguities':[]}
        with tempfile.TemporaryDirectory() as directory:
            with generation_scope(Path(directory)),patch.object(CodexModel,'request_json',side_effect=[candidate,ValueError('超时')]):
                with self.assertRaises(ValueError):CodexModel().generate(requirements)
            with generation_scope(Path(directory)),patch.object(CodexModel,'request_json',return_value=candidate) as call:
                result=CodexModel().generate(requirements)
            self.assertEqual(call.call_count,1)
            self.assertEqual(len(result['points']),1)
            with generation_scope(Path(directory)),patch.object(CodexModel,'request_json') as call:
                self.assertEqual(CodexModel().generate(requirements)['points'],result['points'])
                call.assert_not_called()
            changed=[{'id':'r','content':'需求变化'}]
            with generation_scope(Path(directory)),patch.object(CodexModel,'request_json',return_value=candidate):
                with self.assertRaises(ValueError):CodexModel().generate(changed)

    def test_independent_batches_overlap_and_preserve_context_and_result_order(self):
        import threading
        from server.generation_batches import generate
        from server.node_skills import skill_scope,current_skill
        from server.codex_model import diagnostic_scope,current_diagnostic
        diagnostics=[]
        barrier=threading.Barrier(2)
        def response(prompt):
            self.assertEqual(current_skill(),'rules-context')
            row=json.loads(prompt.split('需求数据：\n',1)[1].split('\n反向审计：',1)[0])[0]
            current_diagnostic()({'state':'running','input_source_id':row['id']})
            barrier.wait(timeout=2)
            return {'points':[{'id':'p','title':'规则','requirement_id':row['id'],'quote':row['content']}],
                    'cases':[],'gaps':[{'point_id':'p','reason':'执行条件未提供'}],'ambiguities':[]}
        client=type('Client',(),{'request_json':staticmethod(response)})()
        with patch.dict('os.environ',{'TESTFLOW_GENERATION_WORKERS':'2'}),skill_scope('rules-context'),diagnostic_scope(diagnostics.append):
            result=generate(client,[{'id':'r1','content':'保存'},{'id':'r2','content':'领取'}])
        self.assertEqual([p['requirement_id'] for p in result['points']],['r1','r2'])
        self.assertEqual(len(diagnostics),4)
        for value in diagnostics:
            self.assertEqual(value['batch'],int(value['input_source_id'][1:]))
            self.assertIn(value['phase'],('design','audit'))

    def test_failed_batch_cancels_other_inflight_process_and_saves_no_artifact(self):
        import threading,time,sys
        from server.generation_batches import generate
        from server.processes import run
        barrier=threading.Barrier(2)
        def response(prompt):
            row=json.loads(prompt.split('需求数据：\n',1)[1].split('\n反向审计：',1)[0])[0]
            barrier.wait(timeout=2)
            if row['id']=='r1':raise ValueError('真实设计失败')
            run([sys.executable,'-c','import time;time.sleep(30)'],check=True)
            self.fail('取消后不应继续生成')
        client=type('Client',(),{'request_json':staticmethod(response)})()
        started=time.monotonic()
        with patch.dict('os.environ',{'TESTFLOW_GENERATION_WORKERS':'2'}):
            with self.assertRaisesRegex(ValueError,'真实设计失败'):
                generate(client,[{'id':'r1','content':'保存'},{'id':'r2','content':'领取'}])
        self.assertLess(time.monotonic()-started,3)

    def test_merge_renames_duplicate_ids_and_checks_all_sources(self):
        from server.generation_batches import generate
        def response(prompt):
            data=json.loads(prompt.split('需求数据：\n',1)[1].split('\n反向审计：',1)[0])
            r=data[0]
            return {'points':[{'id':'p','title':'规则','requirement_id':r['id'],'quote':r['content']}],
                    'cases':[{'id':'c','title':'检查','point_ids':['p'],'preconditions':['满足资格'],
                              'steps':[{'action':'操作','expected':r['content']+'状态已满足'}]}],'gaps':[],'ambiguities':[]}
        client=type('Client',(),{'request_json':staticmethod(response)})()
        result=generate(client,[{'id':'r1','content':'保存'},{'id':'r2','content':'领取'}])
        self.assertEqual(len({p['id'] for p in result['points']}),2)
        self.assertEqual({p['requirement_id'] for p in result['points']},{'r1','r2'})
        self.assertEqual(len({c['id'] for c in result['cases']}),2)

class QuoteProvenanceTests(__import__('unittest').TestCase):
    def test_rendered_quote_maps_to_exact_original_span(self):
        from server.generation_batches import original_quote
        raw='<p>奖励<b>领取</b>后保存状态</p><del>旧规则</del>'
        self.assertEqual(original_quote('奖励\n领取\n后保存状态',raw),'奖励<b>领取</b>后保存状态')
        self.assertEqual(original_quote('领取',raw),'领取')
        with self.assertRaises(ValueError):original_quote('凭空规则',raw)

    def test_generation_accepts_traceable_html_quote_and_keeps_raw_evidence(self):
        from server.generation_batches import generate
        class Client:
            def request_json(self,prompt):return {'points':[{'id':'p','title':'保存','requirement_id':'r','quote':'奖励\n领取\n后保存状态'}],
                'cases':[],'gaps':[{'point_id':'p','reason':'需补充执行条件'}],'ambiguities':[]}
        result=generate(Client(),[{'id':'r','content':'<p>奖励<b>领取</b>后保存状态</p>','metadata':{'kind':'feishu'}}])
        self.assertEqual(result['points'][0]['quote'],'奖励<b>领取</b>后保存状态')


    def test_html_provenance_survives_checkpoint_resume_and_audit(self):
        from server.generation_batches import generate,generation_scope
        from unittest.mock import Mock
        requirements=[{'id':'r','content':'<p>奖励<b>领取</b>后保存状态</p>','metadata':{'kind':'feishu'}}]
        candidate={'points':[{'id':'p','title':'保存','requirement_id':'r','quote':'奖励\n领取\n后保存状态'}],
                   'cases':[],'gaps':[{'point_id':'p','reason':'执行条件待确认'}],'ambiguities':[]}
        with tempfile.TemporaryDirectory() as d:
            client=Mock();client.request_json.side_effect=[candidate,ValueError('连接中断')]
            with generation_scope(Path(d)):
                with self.assertRaises(ValueError):generate(client,requirements)
            canonical=json.loads(json.dumps(candidate));canonical['points'][0]['quote']='奖励<b>领取</b>后保存状态'
            client.request_json.side_effect=None;client.request_json.return_value=canonical;client.request_json.reset_mock()
            with generation_scope(Path(d)):result=generate(client,requirements)
            self.assertEqual(client.request_json.call_count,1)
            self.assertEqual(result['points'][0]['quote'],'奖励<b>领取</b>后保存状态')
