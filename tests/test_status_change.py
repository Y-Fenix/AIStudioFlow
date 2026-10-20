"""最终状态变更契约：隔离数据库及飞书替身，不改真实记录。"""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.status_change import StatusChanges


class Client:
    def __init__(self, target):
        self.target=target;self.value='待验证';self.updates=[];self.fail=False
    def inspect_bug_target(self,url):return copy.deepcopy(self.target)
    def read_bug_status(self,target,record,field,pending):
        from datetime import datetime,timezone
        return {'record_id':record,'table_id':target['table_id'],'field_id':field,'value':self.value,
                'pending_value':pending,'pending':self.value==pending,'checked_at':datetime.now(timezone.utc).isoformat(),'remote_state_changed':False}
    def update_bug_status(self,request):
        self.updates.append(request)
        if self.fail: raise ValueError('模拟发送超时')
        self.value=request['target_value'];return {}


class StatusChangeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite')
        self.project=self.store.create_project('隔离样例')['id'];self.task=self.store.create_task(self.project,'非真实Bug')['id']
        self.target={'verified':True,'url':'https://example.feishu.cn/base/base','base_token':'base','table_id':'tblFixture',
                     'fields':[{'id':'status','name':'状态','type':'select','multiple':False,'options':[{'name':'待验证'},{'name':'验证通过'}]}]}
        self.binding={'repository':'/fixture','branch':'master','commit':'sha','code_fingerprint':'code'}
        self.result={'id':'C1','case_id':'C1','test_name':'用例','status':'passed','evidence':'fixture.json'}
        self.regression={'execution':{**self.binding,'method':'static_code_review','case_input_hash':'cases','requirements_hash':'requirements'},'roots':[{'root_cause_id':'R','title':'缺陷',
            'verdict':'logic_assertions_passed','required_test_names':['C1'],'results':[self.result],'missing_test_names':[]}]}
        self.artifacts={'1':{'method':'static_code_review','case_input_hash':'cases','requirements_hash':'requirements','results':[{'id':'C1','case_id':'C1','status':'failed'}]},
            '4':{'drafts':[{'draft_key':'D','root_cause_id':'R','related_result_ids':['C1']}],
                 'linked_records':[{'draft_key':'D','root_cause_id':'R','record_id':'recFixture','table_id':'tblFixture','base_token':'base',
                                    'status_snapshot':{'field_id':'status','pending_value':'待验证'}}]},
            '5':{'ready_for_review':True,'code_fingerprint':'code','decisions':[{'root_cause_id':'R','action':'accept_logic_only','reason':'已审阅静态证据'}]}}
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET stage=5,status='waiting_user',binding=?,regression=?,artifacts=?,bug_target=? WHERE id=?",
                tuple(json.dumps(v,ensure_ascii=False) for v in (self.binding,self.regression,self.artifacts,self.target))+(self.task,))
        self.service=StatusChanges(self.store);self.client=Client(self.target)
        self.inspect=lambda path,branch:copy.deepcopy(self.binding)
    def prepare(self):
        return self.service.prepare(self.project,self.task,'R','验证通过',1,self.client,self.inspect)
    def confirm(self,preview,**kwargs):
        return self.service.confirm(self.project,self.task,preview['identity'],preview['preview_hash'],1,
            kwargs.get('confirmed',True),kwargs.get('acknowledged',True),self.client,self.inspect)

    def test_prepare_never_writes_and_confirmation_needs_explicit_ack(self):
        preview=self.prepare()
        self.assertEqual(self.client.updates,[])
        for kwargs in ({'confirmed':False},{'acknowledged':False}):
            with self.assertRaises(ValueError):self.confirm(preview,**kwargs)
        self.assertEqual(self.client.updates,[])

    def test_only_one_status_field_written_and_readback_required(self):
        p=self.prepare();result=self.confirm(p)
        self.assertEqual(result['status'],'confirmed')
        self.assertEqual(self.client.updates[0]['payload'],{'update_records':{'recFixture':{'status':'验证通过'}}})
        with self.assertRaises(ValueError):self.confirm(p)
        self.assertEqual(len(self.client.updates),1)
        self.assertEqual(len(self.service.list(self.project,self.task)),1)

    def test_remote_conflict_or_changed_code_never_writes(self):
        p=self.prepare();self.client.value='处理中'
        with self.assertRaises(ValueError):self.confirm(p)
        self.assertEqual(self.client.updates,[])
        self.client.value='待验证'
        p=self.prepare();self.binding['code_fingerprint']='changed'
        with self.assertRaises(ValueError):self.confirm(p)
        self.assertEqual(self.client.updates,[])

    def test_timeout_becomes_uncertain_and_never_retries(self):
        p=self.prepare();self.client.fail=True
        with self.assertRaises(ValueError):self.confirm(p)
        self.assertEqual(self.service.list(self.project,self.task)[0]['status'],'uncertain')
        with self.assertRaises(ValueError):self.confirm(p)
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(len(self.client.updates),1)

    def test_failed_or_unreviewed_regression_cannot_prepare(self):
        with self.store.connection() as db:
            self.artifacts['5']['decisions'][0]['action']='keep_open'
            db.execute('UPDATE tasks SET artifacts=? WHERE id=?',(json.dumps(self.artifacts),self.task))
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.client.updates,[])

    def test_ignored_field_or_readback_mismatch_is_not_success(self):
        p=self.prepare()
        def update(request):self.client.updates.append(request);return {'ignored_fields':['status']}
        self.client.update_bug_status=update
        with self.assertRaises(ValueError):self.confirm(p)
        self.assertEqual(self.service.list(self.project,self.task)[0]['status'],'uncertain')

    def test_uncertain_can_be_readonly_reconciled_without_resend(self):
        p=self.prepare();self.client.fail=True
        with self.assertRaises(ValueError):self.confirm(p)
        self.client.value='验证通过'
        result=self.service.reconcile(self.project,self.task,p['identity'],self.client)
        self.assertEqual(result['status'],'reconciled')
        self.assertEqual(len(self.client.updates),1)

    def test_lark_connector_sends_only_validated_status_payload_via_private_file(self):
        from server.connectors.lark import LarkClient
        from unittest.mock import patch
        p=self.prepare();request=p['request'];client=LarkClient()
        def invoke(arguments):
            self.assertIn('+record-batch-update',arguments)
            path=Path(arguments[arguments.index('--json')+1][1:])
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(path.read_text()),request['payload'])
            return {}
        with patch.object(client,'_read',side_effect=invoke) as call:
            self.assertEqual(client.update_bug_status(request),{})
            bad=copy.deepcopy(request);bad['payload']['update_records']['recFixture']['another']='bad'
            with self.assertRaises(ValueError):client.update_bug_status(bad)
            self.assertEqual(call.call_count,1)

    def test_interrupted_sending_recovers_to_uncertain(self):
        p=self.prepare()
        with self.store.connection() as db:
            db.execute("UPDATE status_changes SET status='sending',attempt='fixture' WHERE identity=?",(p['identity'],))
        self.service.recover_interrupted()
        self.assertEqual(self.service.list(self.project,self.task)[0]['status'],'uncertain')
        with self.assertRaises(ValueError):self.confirm(p)
        self.assertEqual(self.client.updates,[])

    def test_http_confirmation_and_ledger_survive_reload(self):
        import threading
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from unittest.mock import patch
        from server.app import create_server
        server=create_server('127.0.0.1',0,str(self.store.path),local_development=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join()))
        route=f'http://127.0.0.1:{server.server_port}/api/projects/{self.project}/tasks/{self.task}'
        def call(endpoint,body=None):
            req=Request(route+endpoint,data=json.dumps(body).encode() if body is not None else None,
                        headers={'Content-Type':'application/json'})
            try:r=urlopen(req)
            except HTTPError as e:r=e
            with r:return r.status,json.load(r)
        with patch('server.app.LarkClient',return_value=self.client),patch('server.app.inspect_project',side_effect=self.inspect):
            status,p=call('/prepare-status-change',{'root_cause_id':'R','target_value':'验证通过','revision':1})
            self.assertEqual(status,200,p)
            body={'identity':p['identity'],'preview_hash':p['preview_hash'],'revision':1,'confirmed':True}
            self.assertEqual(call('/confirm-status-change',body)[0],400)
            self.assertEqual(self.client.updates,[])
            body['static_scope_acknowledged']=True
            status,result=call('/confirm-status-change',body)
            self.assertEqual(status,200,result)
            self.assertEqual(result['status'],'confirmed')
            self.assertEqual(call('/confirm-status-change',body)[0],400)
            self.assertEqual(len(self.client.updates),1)
            status,snapshot=call('')
            self.assertEqual(snapshot['status_changes'][0]['status'],'confirmed')
            self.assertEqual(snapshot['revision'],1)
            self.assertEqual(snapshot['stage'],5)

    def test_two_concurrent_confirmations_write_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        p=self.prepare();barrier=Barrier(2)
        def inspect_target(url):barrier.wait(timeout=5);return copy.deepcopy(self.target)
        self.client.inspect_bug_target=inspect_target
        def confirm():
            try:return self.confirm(p)['status']
            except ValueError:return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:confirm(),range(2)))
        self.assertEqual(sorted(results),['confirmed','rejected'])
        self.assertEqual(len(self.client.updates),1)

    def test_success_response_without_matching_readback_is_uncertain(self):
        p=self.prepare()
        def update(request):self.client.updates.append(request);return {}
        self.client.update_bug_status=update
        with self.assertRaises(ValueError):self.confirm(p)
        self.assertEqual(self.service.list(self.project,self.task)[0]['status'],'uncertain')
        with self.assertRaises(ValueError):self.service.reconcile(self.project,self.task,p['identity'],self.client)
        self.assertEqual(len(self.client.updates),1)

    def test_final_state_rejects_changed_regression_expectations(self):
        for key in ('case_input_hash','requirements_hash'):
            regression=copy.deepcopy(self.regression)
            regression['execution'][key]='changed'
            with self.store.connection() as db:
                db.execute('UPDATE tasks SET regression=? WHERE id=?',(json.dumps(regression),self.task))
            with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.client.updates,[])
