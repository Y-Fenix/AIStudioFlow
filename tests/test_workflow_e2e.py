"""隔离数据库的六步HTTP契约；模型/执行/飞书均为明确样例替身。"""
import time
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
from tests.test_api import ApiTests
from server.requirements import validate_cases


class WorkflowE2ETests(unittest.TestCase):
    setUp=ApiTests.setUp
    tearDown=ApiTests.tearDown
    request=ApiTests.request

    def wait_job(self, route):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            task=self.request(route)[1]
            if task['jobs'][0]['status'] not in ('queued','running'):
                self.assertEqual(task['jobs'][0]['status'],'completed',task['jobs'][0])
                return task
            time.sleep(.02)
        self.fail('隔离后台操作未在5秒内完成')

    def test_two_failures_one_root_one_record_then_pending_regression(self):
        self.run_workflow(False)

    def test_static_cases_one_root_draft_then_static_regression(self):
        self.run_workflow(True)

    def run_workflow(self, static):
        _,project=self.request('/api/projects',{'name':'隔离流程样例'})
        _,task=self.request('/api/projects/'+project['id']+'/tasks',{'title':'非真实Bug'})
        route='/api/projects/'+project['id']+'/tasks/'+task['id']
        def update(endpoint,body=None,code=200):
            nonlocal task
            status,task=self.request(route+'/'+endpoint,{**(body or {}),'revision':task['revision']})
            self.assertEqual(status,code,task)
            return task
        update('requirements',{'source':'测试样例','content':'规则样例：计数加一'},201)
        def generate(requirements):
            return validate_cases({'points':[{'id':'p','title':'计数','requirement_id':requirements[0]['id'],'quote':'计数加一'}],
                'cases':[{'id':identifier,'title':'样例计数'+identifier,'point_ids':['p'],'preconditions':['隔离样例'],
                          'steps':[{'action':'样例调用'+identifier,'expected':'计数加一'}]} for identifier in (['0','1'] if static else ['c'])],
                'gaps':[],'ambiguities':[]},requirements)
        with patch('server.jobs.CodexModel.generate',side_effect=generate):
            self.assertEqual(self.request(route+'/operation-jobs',{'kind':'generate'})[0],202)
            task=self.wait_job(route)
        update('case-review',{'decisions':[],'decomposition_confirmed':True})
        update('decisions',{'action':'confirm'})
        binding={'repository':'/fixture','branch':'master','commit':'fixture-sha','code_fingerprint':'old'}
        with patch('server.app.inspect_project',return_value=binding):
            update('execution-binding',{'path':'/fixture','branch':'master','suite':'static' if static else 'streakgroup'})
        original={'method':'production_suite_with_stubs','branch':'master','commit':'fixture-sha','code_fingerprint':'old',
                  'build':None,'results':[{'id':str(i),'test_name':'fixture-'+str(i),'status':'failed',
                                         'detail':'样例断言失败','evidence':'fixture-only.log'} for i in range(2)]}
        if static:
            from server.static_review import input_hash
            original.update(method='static_code_review', case_input_hash=input_hash(task['artifacts']['0']['cases']), requirements_hash='fixture-requirements')
            for row in original['results']:
                row.update(case_id=row['id'], preconditions=['静态样例条件'], steps=['调用计数入口'],
                           expected='1', actual='静态推导：0',
                           assertions=[{'step_index':0,'expected':'计数加一','status':'failed'}])
        with patch('server.jobs.execute_logic',return_value=original):
            self.assertEqual(self.request(route+'/operation-jobs',{'kind':'execute'})[0],202)
            task=self.wait_job(route)
        if not static:
            update('execution-mapping',{'mappings':[{'case_id':'c','result_ids':['0','1'],'reason':'样例映射'}]})
        with patch('server.app.inspect_project',return_value=binding):
            update('decisions',{'action':'confirm'})
        update('triage',{'roots':[{'id':'root','title':'同一个样例根因','confirmed':True,'evidence':['fixture evidence']}],
                         'assignments':[{'result_id':str(i),'root_cause_id':'root'} for i in range(2)]})
        update('decisions',{'action':'confirm'})
        update('filter',{'selected':['root'],'excluded':{}})
        update('decisions',{'action':'confirm'})
        update('bug-drafts',{'observations':[] if static else [{'result_id':'0','preconditions':['样例条件'],
                                            'steps':['执行样例'],'expected':'1','actual':'0'}]})
        self.assertEqual(len(task['artifacts']['4']['drafts']),1)
        self.assertEqual(task['artifacts']['4']['drafts'][0]['missing'],[])
        if static:
            self.assertEqual(task['artifacts']['4']['drafts'][0]['reproduction_provenance'],'static_inference')
        target={'verified':True,'url':'https://example.feishu.cn/base/base','base_token':'base','table_id':'tblFixture',
                'fields':[{'id':'description','type':'text','name':'描述'},{'id':'status','type':'select','multiple':False,
                           'name':'状态','options':[{'name':'未解决'},{'name':'待验证'}]}]}
        with patch('server.app.LarkClient.inspect_bug_target',return_value=target):
            update('bug-target',{'url':target['url']})
            update('bug-preview',{'mapping':{'description':'full_description','status':{'literal':'未解决'}}})
            preview=task['artifacts']['4']['field_preview']
            update('prepare-bug-publication',{'preview_hash':preview['preview_hash']})
            publication=task['artifacts']['4']['publication_plan']['requests']
            self.assertEqual(len(publication),1)
            with patch('server.app.LarkClient.create_bug_record',return_value={'record_id_list':['recFixture']}) as create:
                update('publish-bug',{'confirmed':True,'preview_hash':preview['preview_hash'],'request_hash':publication[0]['request_hash']})
                self.assertEqual(create.call_count,1)
        draft=task['artifacts']['4']['drafts'][0]
        def status(value):
            return {'record_id':'recFixture','table_id':'tblFixture','field_id':'status','field_name':'状态',
                    'value':value,'pending_value':'待验证','pending':value=='待验证',
                    'checked_at':datetime.now(timezone.utc).isoformat(),'remote_state_changed':False}
        with patch('server.app.LarkClient.read_bug_status',return_value=status('未解决')):
            update('bug-status',{'draft_key':draft['draft_key'],'record_id':'recFixture','field_id':'status','pending_value':'待验证'})
        update('confirm-existing-bugs',{'confirmed':True})
        update('decisions',{'action':'confirm'})
        self.assertEqual(task['stage'],5)
        current={**original,'code_fingerprint':'new','results':[{**r,'status':'passed','detail':'样例断言通过'} for r in original['results']]}
        with patch('server.app.LarkClient.read_bug_status',return_value=status('待验证')), \
             patch('server.jobs.inspect_project',return_value={**binding,'code_fingerprint':'new'}), \
             patch('server.jobs.execute_logic',return_value=current):
            response=self.request(route+'/check-pending-regression',{'revision':task['revision']})
            self.assertEqual(response[0],202,response[1])
            task=self.wait_job(route)
        self.assertEqual(len(task['regression']['roots']),1)
        self.assertEqual(task['regression']['roots'][0]['verdict'],'logic_assertions_passed')
        self.assertIsNone(task['regression']['roots'][0]['repair_probability'])
        with patch('server.app.inspect_project',return_value={**binding,'code_fingerprint':'new'}):
            update('regression-review',{'decisions':[{'root_cause_id':'root','action':'accept_logic_only','reason':'仅接受样例逻辑，不表示客户端通过'}]})
        update('decisions',{'action':'confirm'})
        self.assertEqual(task['status'],'completed')
        self.assertFalse(task['artifacts']['5']['client_verified'])
        self.assertFalse(task['artifacts']['5']['remote_state_changed'])

# 只复用HTTP测试工具，不重复发现导入类中的测试。
del ApiTests
