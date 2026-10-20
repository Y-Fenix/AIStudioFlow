"""Real SQLite tests; adapters are explicit local fixtures, never external tools."""
import tempfile
import unittest
from unittest.mock import patch
from server.store import Store
from server.studio_workspaces import Workspaces
from server.core.identity import current_user
from server.core.admin import Administration
from server.core.integrations import AdapterRegistry


class NodeContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name+'/db.sqlite')
        self.studio=self.store.studios()[0]['id']
        self.project=self.store.create_project('续接')['id']
        self.other=self.store.create_project('隔离')['id']
        self.w=Workspaces(self.store);self.registry=AdapterRegistry()
        self.registry.register('product',type('FixtureAdapter',(),{'execute':lambda s,c:{'deliverable':'fixture'}})())

    def service(self):
        from server.core.node_continuation import NodeContinuation
        return NodeContinuation(self.store,self.registry)

    def enable(self,source='product:0',target='product:1',enabled=True):
        service=self.service();value=service.get(self.studio,self.project,source.split(':')[0])
        return service.save(self.studio,self.project,source.split(':')[0],
            {'revision':value['revision'],'source':source,'target':target,'enabled':enabled})

    def approve(self):
        self.w.save(self.studio,self.project,'product:1',{'revision':0,'inputs':'真实准备资料'})
        self.w.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'已核实上游交付'})
        return self.w.decide(self.studio,self.project,'product:0',{'revision':1,'action':'approve','reason':'人工核对'})

    def rows(self,table):
        with self.store.connection() as db:return [dict(r) for r in db.execute('SELECT * FROM '+table)]

    def test_defaults_persistence_scope_and_conflicts(self):
        service=self.service();before=service.get(self.studio,self.project,'product')
        self.assertEqual(len(before['edges']),3);self.assertFalse(any(e['enabled'] for e in before['edges']))
        saved=self.enable();self.assertTrue(saved['edges'][0]['enabled'])
        self.assertFalse(service.get(self.studio,self.other,'product')['edges'][0]['enabled'])
        from server.core.node_continuation import NodeContinuation
        self.assertTrue(NodeContinuation(Store(self.store.path)).get(self.studio,self.project,'product')['edges'][0]['enabled'])
        with self.assertRaisesRegex(ValueError,'变化'):
            service.save(self.studio,self.project,'product',{'revision':before['revision'],'source':'product:0','target':'product:1','enabled':False})
        for value in (1,'true',None):
            with self.assertRaises(ValueError):self.enable(enabled=value)

    def test_invalid_edges_and_reorder_are_not_enabled(self):
        with self.assertRaises(ValueError):self.enable(target='design:1')
        with self.assertRaises(ValueError):self.enable(target='product:2')
        self.enable()
        from server.core.project_nodes import ProjectNodes
        manager=ProjectNodes(self.store);config=manager.get(self.studio,self.project,'product')
        config['nodes'].reverse();config=manager.save(self.studio,self.project,'product',config)
        self.assertFalse(any(e['enabled'] for e in self.service().get(self.studio,self.project,'product')['edges']))
        config['nodes'].reverse();config=manager.save(self.studio,self.project,'product',config)
        self.assertFalse(any(e['enabled'] for e in self.service().get(self.studio,self.project,'product')['edges']))
        config=manager.get(self.studio,self.project,'testing');config['nodes'][1],config['nodes'][2]=config['nodes'][2],config['nodes'][1];manager.save(self.studio,self.project,'testing',config)
        edge=self.service().get(self.studio,self.project,'testing')['edges'][0]
        self.assertFalse(edge['available']);self.assertIn('依赖',edge['reason'])

    def test_no_job_before_approval_then_dispatch_once_with_persistence(self):
        self.enable();self.assertFalse(self.service().run_once())
        self.approve();self.assertEqual(len(self.rows('node_continuation_events')),1)
        self.assertEqual(self.rows('department_jobs'),[])
        self.assertTrue(self.service().run_once());self.assertFalse(self.service().run_once())
        self.assertEqual(len(self.rows('department_jobs')),1)
        job=self.rows('department_jobs')[0];self.assertEqual((job['node'],job['actor'],job['status']),('product:1','local','queued'))
        from server.core.node_continuation import NodeContinuation
        self.assertFalse(NodeContinuation(Store(self.store.path),self.registry).run_once())
        self.assertEqual(len(self.rows('department_jobs')),1)

    def test_default_off_and_enabling_after_approval_do_not_replay(self):
        self.approve();self.assertFalse(self.service().run_once());self.enable()
        self.assertFalse(self.service().run_once());self.assertEqual(self.rows('department_jobs'),[])

    def test_disabling_pending_or_modifying_evidence_stops(self):
        self.enable();self.approve();self.enable(enabled=False)
        self.assertTrue(self.service().run_once());self.assertEqual(self.rows('department_jobs'),[])
        self.assertIn('关闭',self.rows('node_continuation_events')[0]['detail'])

    def test_target_changes_and_missing_adapter_are_blocked(self):
        self.enable();self.approve()
        self.w.save(self.studio,self.project,'product:1',{'revision':1,'inputs':'并发修改'})
        self.service().run_once();self.assertEqual(self.rows('department_jobs'),[])
        self.assertIn('变化',self.rows('node_continuation_events')[0]['detail'])

    def test_missing_inputs_stop_truthfully(self):
        self.enable('design:0','design:1')
        self.registry.register('design',type('Fixture',(),{'execute':lambda s,c:{'deliverable':'x'}})())
        self.w.save(self.studio,self.project,'design:0',{'revision':0,'deliverable':'设计依据'})
        self.w.decide(self.studio,self.project,'design:0',{'revision':1,'action':'approve','reason':'核查'})
        self.service().run_once();self.assertEqual(self.rows('department_jobs'),[])
        self.assertIn('缺少输入',self.rows('node_continuation_events')[-1]['detail'])

    def test_source_reject_and_failure_never_dispatch(self):
        self.enable();self.w.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'待审核'})
        self.w.decide(self.studio,self.project,'product:0',{'revision':1,'action':'reject','reason':'未通过'})
        self.assertFalse(self.service().run_once());self.assertEqual(self.rows('department_jobs'),[])

    def test_permission_denied_even_direct_service_and_rechecked_on_dispatch(self):
        with self.store.connection() as db:db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) VALUES('worker','t','w','成员','active')")
        admin=Administration(self.store);admin.member({'user_id':'worker','studio_id':self.studio,'project_id':self.project,'department':'product','role':'lead'})
        admin.rule({'subject_type':'user','subject_id':'worker','studio_id':self.studio,'project_id':self.project,'department':'product','node':'product:0','resource':'node','action':'edit','effect':'deny'})
        token=current_user.set('worker')
        try:
            with self.assertRaises(PermissionError):self.enable()
        finally:current_user.reset(token)
        self.enable()
        self.w.save(self.studio,self.project,'product:1',{'revision':0,'inputs':'资料'})
        self.w.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'交付'})
        token=current_user.set('worker')
        try:self.w.decide(self.studio,self.project,'product:0',{'revision':1,'action':'approve','reason':'人工确认'})
        finally:current_user.reset(token)
        admin.rule({'subject_type':'user','subject_id':'worker','studio_id':self.studio,'project_id':self.project,'department':'product','node':'product:1','resource':'node','action':'execute','effect':'deny'})
        self.service().run_once();self.assertEqual(self.rows('department_jobs'),[])
        self.assertIn('权限',self.rows('node_continuation_events')[0]['detail'])

    def test_testing_approval_missing_binding_pauses_without_bypassing_review(self):
        self.enable('testing:0','testing:1')
        task=self.store.create_task(self.project,'原六步')
        with self.store.connection() as db:db.execute("UPDATE tasks SET artifacts='{\"0\":{\"legacy_fixture\":true}}' WHERE id=?",(task['id'],))
        task=self.store.task(self.project,task['id']);self.store.decide(self.project,task['id'],'confirm',task['revision'])
        self.service().run_once();self.assertEqual(self.rows('jobs'),[])
        self.assertIn('绑定',self.rows('node_continuation_events')[0]['detail'])

    def test_testing_safe_static_execution_is_queued_once(self):
        self.enable('testing:0','testing:1');task=self.store.create_task(self.project,'静态样例')
        binding={'repository':'/fixture','branch':'main','commit':'one','code_fingerprint':'fingerprint','execution_suite':'static'}
        import json
        with self.store.connection() as db:db.execute('UPDATE tasks SET artifacts=?,binding=? WHERE id=?',(json.dumps({'0':{'legacy_fixture':True}}),json.dumps(binding),task['id']))
        self.store.decide(self.project,task['id'],'confirm',task['revision'])
        with patch('server.gagasort.inspect_project',return_value=binding):self.service().run_once()
        self.assertEqual(len(self.rows('jobs')),1);self.assertEqual(self.rows('jobs')[0]['kind'],'execute')
        self.assertEqual(self.store.task(self.project,task['id'])['stage'],1)

    def test_atomic_confirmation_rollback_and_unique_events(self):
        self.enable();self.approve()
        row=self.rows('node_continuation_events')[0]
        from server.core.node_continuation import record_completion
        with self.store.connection() as db:
            record_completion(self.store,db,self.studio,self.project,'product:0',2)
        self.assertEqual(len(self.rows('node_continuation_events')),1)
        with self.assertRaises(RuntimeError):
            with self.store.connection() as db:
                record_completion(self.store,db,self.studio,self.project,'product:0',3)
                raise RuntimeError('rollback fixture')
        self.assertEqual(len(self.rows('node_continuation_events')),1)

    def test_disable_then_reenable_does_not_revive_a_pending_event(self):
        self.enable();self.approve();self.enable(enabled=False);self.enable()
        self.service().run_once();self.assertEqual(self.rows('department_jobs'),[])

    def test_approval_atomic_rollback_leaves_no_approval_or_intent(self):
        self.enable();self.w.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'待审核证据'})
        with patch('server.core.node_continuation.record_completion',side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):self.w.decide(self.studio,self.project,'product:0',{'revision':1,'action':'approve','reason':'核实'})
        self.assertEqual(self.w.get(self.studio,self.project,'product:0')['status'],'waiting_user')
        self.assertEqual(self.rows('node_continuation_events'),[])

    def test_dispatch_fault_rolls_back_insert_and_event_then_can_resume_once(self):
        self.enable();self.approve()
        from server.department_jobs import DepartmentExecutionQueue
        original=DepartmentExecutionQueue.enqueue
        def fail_after_insert(queue,*args,**kwargs):
            original(queue,*args,**kwargs)
            raise OSError('fixture storage fault')
        with patch.object(DepartmentExecutionQueue,'enqueue',fail_after_insert):
            with self.assertRaises(OSError):self.service().run_once()
        self.assertEqual(self.rows('department_jobs'),[])
        self.assertEqual(self.rows('node_continuation_events')[0]['status'],'pending')
        self.service().run_once();self.assertEqual(len(self.rows('department_jobs')),1)

    def test_no_adapter_stops_without_fake_delivery(self):
        self.enable('design:0','design:1')
        self.w.save(self.studio,self.project,'design:1',{'revision':0,'inputs':'设计资料'})
        self.w.save(self.studio,self.project,'design:0',{'revision':0,'deliverable':'设计依据'})
        self.w.decide(self.studio,self.project,'design:0',{'revision':1,'action':'approve','reason':'核实'})
        self.service().run_once();self.assertIn('执行器',self.rows('node_continuation_events')[0]['detail'])
        self.assertEqual(self.w.get(self.studio,self.project,'design:1')['deliverable'],'')

    def test_manual_testing_stages_do_not_publish_or_regress_automatically(self):
        import json
        for stage in (2,3,4):
            self.enable(f'testing:{stage}',f'testing:{stage+1}')
            task=self.store.create_task(self.project,'人工门禁'+str(stage))
            with self.store.connection() as db:
                db.execute('UPDATE tasks SET stage=? WHERE id=?',(stage+1,task['id']))
                from server.core.node_continuation import record_completion
                record_completion(self.store,db,self.studio,self.project,f'testing:{stage}',1,task['id'])
            self.service().run_once()
        self.assertEqual(self.rows('jobs'),[])
        self.assertTrue(all(e['status']=='stopped' for e in self.rows('node_continuation_events')))

    def test_two_workers_race_dispatches_once(self):
        import concurrent.futures
        self.enable();self.approve()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.service().run_once(),range(2)))
        self.assertEqual(sorted(results),[False,True]);self.assertEqual(len(self.rows('department_jobs')),1)

    def test_completed_target_output_stays_waiting_for_human_approval(self):
        self.enable();self.enable('product:1','product:2');self.approve();self.service().run_once()
        from server.department_jobs import DepartmentExecutionQueue
        queue=DepartmentExecutionQueue(self.store,self.registry)
        self.assertTrue(queue.run_once())
        self.assertEqual(self.w.get(self.studio,self.project,'product:1')['status'],'waiting_user')
        self.assertFalse(self.service().run_once())
        self.assertEqual(len(self.rows('department_jobs')),1)


    def test_legacy_task_without_skill_snapshot_uses_existing_default_rules(self):
        self.enable('testing:0','testing:1')
        task=self.store.create_task(self.project,'旧数据')
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET node_skills='{}',stage=1 WHERE id=?",(task['id'],))
            from server.core.node_continuation import record_completion
            record_completion(self.store,db,self.studio,self.project,'testing:0',task['revision'],task['id'])
        expected=self.store.task(self.project,task['id'])['node_skills']['1']['sha256']
        self.assertEqual(self.rows('node_continuation_events')[0]['skill_sha256'],expected)



class NodeContinuationHttpTests(unittest.TestCase):
    from tests.test_api import ApiTests as _Api
    setUp=_Api.setUp
    tearDown=_Api.tearDown
    request=_Api.request

    def test_real_routes_save_read_conflict_and_cross_scope(self):
        studio=self.request('/api/studios')[1]['items'][0]['id']
        project=self.request('/api/projects',{'name':'HTTP续接'})[1]['id']
        route=f'/api/studios/{studio}/projects/{project}/node-continuation?department=testing'
        code,value=self.request(route);self.assertEqual(code,200)
        payload={'revision':value['revision'],'source':'testing:0','target':'testing:1','enabled':True}
        code,value=self.request(route,payload);self.assertEqual(code,200);self.assertTrue(value['edges'][0]['enabled'])
        self.assertEqual(self.request(route,payload)[0],400)
        self.assertFalse(self.request(route.replace(project,'unknown-project'))[0]==200)
        other=self.request('/api/studios',{'name':'独立工作室'})[1]['id']
        self.assertNotEqual(self.request(route.replace(studio,other))[0],200)

    def test_real_http_worker_reports_missing_executor_in_operation_log(self):
        import time
        studio=self.request('/api/studios')[1]['items'][0]['id']
        project=self.request('/api/projects',{'name':'真实队列暂停'})[1]['id']
        root=f'/api/studios/{studio}/projects/{project}'
        settings=root+'/node-continuation?department=product'
        value=self.request(settings)[1]
        self.assertEqual(self.request(settings,{'revision':value['revision'],'source':'product:0','target':'product:1','enabled':True})[0],200)
        self.request(root+'/workspace?node=product:1',{'revision':0,'inputs':'真实准备资料'})
        self.request(root+'/workspace?node=product:0',{'revision':0,'deliverable':'已确认资料'})
        self.assertEqual(self.request(root+'/workspace/decision?node=product:0',{'revision':1,'action':'approve','reason':'人工核对'})[0],200)
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            workspace=self.request(root+'/workspace?node=product:0')[1]
            if any('尚未接通执行器' in event['detail'] for event in workspace['events']):break
            time.sleep(.02)
        else:self.fail('真实 HTTP 后台续接没有记录缺执行器原因')
        target=self.request(root+'/workspace?node=product:1')[1]
        self.assertEqual(target['deliverable'],'');self.assertNotEqual(target['status'],'approved')
