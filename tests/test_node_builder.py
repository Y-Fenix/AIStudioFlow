import copy
import tempfile
import unittest
from unittest.mock import patch
from server.store import Store
from server.core.identity import current_user
from server.core.admin import Administration


def block(kind, id=None, **config):
    return {'id': id or kind, 'type': kind, 'config': config}


class NodeBuilderFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name+'/db.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('积木项目', self.studio)['id']
        from server.core.node_blocks.service import Builder
        self.builder = Builder(self.store)

    def blueprint(self, blocks, node='product:0'):
        return self.builder.save_blueprint(self.studio, self.project, node, {'revision': 0, 'blocks': blocks})

    def start_run(self, blocks):
        from server.core.node_blocks.runtime import Runs
        b = self.blueprint(blocks)
        service = Runs(self.store)
        return service, service.start(self.studio, self.project, {'node': 'product:0', 'revision': b['revision'], 'input': '真实资料'})



class NodeBuilderTests(NodeBuilderFixture,unittest.TestCase):
    def test_unknown_type_duplicate_ids_scripts_and_forward_references_rejected(self):
        from server.core.node_blocks.schema import validate_blocks
        for blocks in ([block('shell')], [block('input'),block('input')],
                       [block('tool', url='javascript:alert(1)')],
                       [block('template', text='{{unknown}}')]):
            with self.subTest(blocks=blocks), self.assertRaises(ValueError): validate_blocks(blocks)

    def test_blueprint_persists_with_revision_and_does_not_change_other_projects(self):
        first = self.blueprint([block('input', label='需求', required=True)])
        self.assertEqual(first['revision'], 1)
        other = self.store.create_project('隔离', self.studio)['id']
        self.assertEqual(self.builder.blueprint(self.studio, other, 'product:0')['blocks'], [])
        with self.assertRaisesRegex(ValueError, '版本'):
            self.blueprint([])

    def test_shared_template_versions_snapshot_and_scope(self):
        body={'department':'product','name':'研究模板','blocks':[block('input',label='资料')],'revision':0}
        first=self.builder.save_template(self.studio,body)
        body.update(id=first['id'],revision=1,blocks=[block('review',label='审核')])
        second=self.builder.save_template(self.studio,body)
        self.assertEqual(second['revision'],2)
        self.assertEqual(self.builder.template(self.studio,'product',first['id'],1)['blocks'],first['blocks'])
        with self.assertRaises(KeyError): self.builder.template(self.studio,'design',first['id'])

    def test_manual_input_checklist_template_review_run_to_completion(self):
        runs, run=self.start_run([block('input',label='资料',required=True),block('checklist',items=['来源可靠']),
            block('template',text='报告：{{previous}}'),block('review',label='负责人确认')])
        runs.tick();run=runs.get(self.studio,self.project,run['id']);self.assertEqual(run['status'],'waiting_user')
        with self.assertRaises(ValueError):runs.act(self.studio,self.project,run['id'],{'revision':run['revision'],'action':'submit','value':''})
        run=runs.act(self.studio,self.project,run['id'],{'revision':run['revision'],'action':'submit','value':'来源 A'})
        runs.tick();run=runs.get(self.studio,self.project,run['id'])
        with self.assertRaises(ValueError):runs.act(self.studio,self.project,run['id'],{'revision':run['revision'],'action':'submit','value':[]})
        runs.act(self.studio,self.project,run['id'],{'revision':run['revision'],'action':'submit','value':[True]})
        runs.tick();runs.tick();run=runs.get(self.studio,self.project,run['id'])
        self.assertEqual(run['cursor'],3);self.assertIn('报告',run['steps'][2]['output'])
        runs.act(self.studio,self.project,run['id'],{'revision':run['revision'],'action':'submit','value':'证据已核对'})
        runs.tick();self.assertEqual(runs.get(self.studio,self.project,run['id'])['status'],'completed')

    def test_cross_department_flow_passes_output_and_pins_blueprints(self):
        from server.core.node_blocks.runtime import Runs
        self.blueprint([block('template',text='产品报告 {{input}}')])
        self.blueprint([block('template',text='设计交付 {{previous}}')], 'design:0')
        flow=self.builder.save_flow(self.studio,self.project,{'revision':0,'name':'产品到设计','blocks':[
            block('node','one',node='product:0'),block('node','two',node='design:0')]})
        runs=Runs(self.store);run=runs.start(self.studio,self.project,{'flow':flow['id'],'revision':1,'input':'版本1'})
        self.builder.save_blueprint(self.studio,self.project,'design:0',{'revision':1,'blocks':[block('template',text='不应出现')]})
        for _ in range(8): runs.tick()
        result=runs.get(self.studio,self.project,run['id'])
        self.assertEqual(result['status'],'completed');self.assertIn('产品报告',result['output']);self.assertNotIn('不应出现',result['output'])

    def test_model_failure_is_retryable_and_does_not_advance(self):
        runs,run=self.start_run([block('ai',prompt='整理真实输入')])
        with patch('server.codex_model.CodexModel.request_json',side_effect=ValueError('测试模型失败')): runs.tick()
        run=runs.get(self.studio,self.project,run['id']);self.assertEqual(run['status'],'failed');self.assertEqual(run['cursor'],0)
        run=runs.act(self.studio,self.project,run['id'],{'revision':run['revision'],'action':'retry'})
        with patch('server.codex_model.CodexModel.request_json',return_value={'deliverable':'真实调用替身输出','evidence':[],'gaps':[]}): runs.tick()
        runs.tick();result=runs.get(self.studio,self.project,run['id']);self.assertEqual(result['status'],'completed')

    def test_permission_is_required_and_revoked_before_result_save(self):
        runs,run=self.start_run([block('ai',prompt='整理')])
        with self.store.connection() as db: db.execute("INSERT INTO users VALUES('worker','t','worker','成员','active','member',CURRENT_TIMESTAMP)")
        Administration(self.store).member({'user_id':'worker','studio_id':self.studio,'project_id':self.project,'department':'product'})
        token=current_user.set('worker')
        try:
            with self.assertRaises(PermissionError):self.builder.save_template(self.studio,{'department':'product','revision':0,'name':'非法','blocks':[]})
        finally:current_user.reset(token)
        # Cancellation during a model call must not resurrect the run or save its output.
        def model(*args):
            current=runs.get(self.studio,self.project,run['id'])
            runs.act(self.studio,self.project,run['id'],{'revision':current['revision'],'action':'cancel'})
            return {'deliverable':'过时输出'}
        with patch('server.codex_model.CodexModel.request_json',side_effect=model):runs.tick()
        final=runs.get(self.studio,self.project,run['id']);self.assertEqual(final['status'],'cancelled');self.assertNotIn('过时输出',final['output'])

class NodeBuilderHardeningTests(NodeBuilderFixture,unittest.TestCase):
    def test_completed_run_can_publish_only_to_unchanged_source_workspace(self):
        runs,run=self.start_run([block('template',text='可追溯交付 {{input}}')]);runs.tick();runs.tick()
        current=runs.get(self.studio,self.project,run['id'])
        result=runs.publish(self.studio,self.project,run['id'],{'revision':current['revision']})
        self.assertEqual(result['status'],'waiting_user');self.assertIn('可追溯交付',result['deliverable'])
        with self.assertRaises(ValueError):runs.publish(self.studio,self.project,run['id'],{'revision':current['revision']})

    def test_partial_checklist_draft_survives_reload_without_advancing(self):
        runs,run=self.start_run([block('checklist',items=['A','B'])]);runs.tick();r=runs.get(self.studio,self.project,run['id'])
        r=runs.act(self.studio,self.project,run['id'],{'revision':r['revision'],'action':'save-draft','value':[True,False]})
        self.assertEqual(runs.get(self.studio,self.project,run['id'])['draft'],[True,False]);self.assertEqual(r['cursor'],0)

    def test_recovery_marks_live_execution_interrupted_and_keeps_results(self):
        runs,run=self.start_run([block('template','a',text='第一步'),block('template','b',text='第二步 {{previous}}')]);runs.tick()
        with self.store.connection() as db:db.execute("UPDATE block_runs SET status='running' WHERE id=?",(run['id'],))
        runs.recover();r=runs.get(self.studio,self.project,run['id']);self.assertEqual(r['status'],'interrupted');self.assertEqual(r['output'],'第一步')
        runs.act(self.studio,self.project,r['id'],{'revision':r['revision'],'action':'retry'});runs.tick();runs.tick()
        self.assertEqual(runs.get(self.studio,self.project,r['id'])['output'],'第二步 第一步')

    def test_revoke_execute_while_model_runs_discards_output(self):
        runs,run=self.start_run([block('ai',prompt='整理')])
        with self.store.connection() as db:db.execute("INSERT INTO users VALUES('revoked','t','revoked','成员','active','member',CURRENT_TIMESTAMP)")
        admin=Administration(self.store);admin.member({'user_id':'revoked','studio_id':self.studio,'project_id':self.project,'department':'product'})
        with self.store.connection() as db:db.execute('UPDATE block_runs SET actor=? WHERE id=?',('revoked',run['id']))
        def answer(*a):
            token=current_user.set('local')
            try:admin.rule({'subject_type':'user','subject_id':'revoked','studio_id':self.studio,'project_id':self.project,'department':'product','node':'product:0','resource':'node','action':'execute','effect':'deny'})
            finally:current_user.reset(token)
            return {'deliverable':'撤权之后的输出'}
        with patch('server.codex_model.CodexModel.request_json',side_effect=answer):runs.tick()
        r=runs.get(self.studio,self.project,run['id']);self.assertEqual(r['status'],'failed');self.assertEqual(r['output'],'')

    def test_malformed_schema_types_raise_validation_errors(self):
        from server.core.node_blocks.schema import validate_blocks
        for value in ([{'id':'x','type':[],'config':{}}], [block('input',required=1)], [block('ai',prompt='X',shell='bad')]):
            with self.assertRaises(ValueError):validate_blocks(value)

    def test_trusted_department_extension_runs_through_public_model_contract(self):
        from server.core.node_blocks.contracts import register, unregister
        register('product.fixture',label='部门摘要',fields={'label':'text','prefix':'text'},execute=lambda context,config,previous:{'deliverable':config['prefix']+previous})
        self.addCleanup(lambda:unregister('product.fixture'))
        runs,run=self.start_run([block('product.fixture','fixture',prefix='部门处理：')]);runs.tick();runs.tick()
        self.assertEqual(runs.get(self.studio,self.project,run['id'])['output'],'部门处理：真实资料')


class GrowthReplacementTests(NodeBuilderFixture,unittest.TestCase):
    def test_default_cross_department_chain_ends_at_testing_and_growth_is_historical(self):
        from server.core.node_continuation import NodeContinuation
        edges=NodeContinuation(self.store).get(self.studio,self.project,'__project__')['edges']
        self.assertFalse(any(e['source'].startswith('growth:') or e['target'].startswith('growth:') for e in edges))

class BuilderScopeTests(NodeBuilderFixture,unittest.TestCase):
    def member(self,user='member'):
        with self.store.connection() as db:db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)',(user,'tenant',user,'部门成员','active','member'))
        Administration(self.store).member({'user_id':user,'studio_id':self.studio,'project_id':self.project,'department':'product'})
        return user

    def test_cross_studio_template_and_cross_project_runs_are_inaccessible(self):
        t=self.builder.save_template(self.studio,{'department':'product','name':'共享','revision':0,'blocks':[block('review',label='核对')]})
        other=self.store.create_studio('另一个工作室')['id']
        with self.assertRaises(KeyError):self.builder.template(other,'product',t['id'])
        runs,r=self.start_run([block('template',text='私有交付')])
        project=self.store.create_project('另一项目',self.studio)['id']
        with self.assertRaises(KeyError):runs.get(self.studio,project,r['id'])
        # Same department in the same studio can use the template from another project.
        self.assertEqual(self.builder.template(self.studio,'product',t['id'])['blocks'],t['blocks'])

    def test_plain_edit_permission_cannot_add_or_remove_structure(self):
        self.member();b=self.blueprint([block('input',label='资料')]);token=current_user.set('member')
        try:
            with self.assertRaises(PermissionError):self.builder.save_blueprint(self.studio,self.project,'product:0',{'revision':b['revision'],'blocks':b['blocks']+[block('review')]})
            with self.assertRaises(PermissionError):self.builder.save_blueprint(self.studio,self.project,'product:0',{'revision':b['revision'],'blocks':[]})
            allowed=self.builder.save_blueprint(self.studio,self.project,'product:0',{'revision':b['revision'],'blocks':[block('input',label='已编辑')]})
            self.assertEqual(allowed['blocks'][0]['config']['label'],'已编辑')
        finally:current_user.reset(token)

    def test_project_template_grant_cannot_escalate_to_department_shared_content(self):
        user=self.member();admin=Administration(self.store)
        with self.assertRaises(ValueError):admin.rule({'subject_type':'user','subject_id':user,'studio_id':self.studio,'project_id':self.project,'department':'product','resource':'block','action':'create','effect':'allow'})
        rule=admin.rule({'subject_type':'user','subject_id':user,'studio_id':self.studio,'department':'product','resource':'block','action':'create','effect':'allow'})
        token=current_user.set(user)
        try:
            t=self.builder.save_template(self.studio,{'department':'product','name':'授权模板','revision':0,'blocks':[]})
            self.assertEqual(t['name'],'授权模板')
        finally:current_user.reset(token)
        admin.revoke(rule['id']);token=current_user.set(user)
        try:
            with self.assertRaises(PermissionError):self.builder.save_template(self.studio,{'department':'product','name':'已撤权','revision':0,'blocks':[]})
        finally:current_user.reset(token)

    def test_fixed_testing_node_cannot_be_overridden_and_unverified_batch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'专用'):self.blueprint([block('ai',prompt='绕过静态证据')],'testing:1')
        from server.core.node_blocks.runtime import Runs
        flow=self.builder.save_flow(self.studio,self.project,{'name':'测试核验','revision':0,'blocks':[block('node',node='testing:1')]})
        runs=Runs(self.store);r=runs.start(self.studio,self.project,{'flow':flow['id'],'revision':1})
        runs.tick();r=runs.get(self.studio,self.project,r['id']);task=self.store.create_task(self.project,'未完成测试')
        with self.assertRaisesRegex(ValueError,'尚未完成'):runs.act(self.studio,self.project,r['id'],{'revision':r['revision'],'action':'submit','value':task['id']})

    def test_changed_model_configuration_blocks_retry_instead_of_switching_mid_run(self):
        from server.ai_models import ModelSettings
        runs,r=self.start_run([block('ai',prompt='整理')]);ModelSettings(self.store).save_custom({'base_url':'https://example.com/v1','model':'new','api_key':'private-key'})
        with patch('server.codex_model.CodexModel.request_json') as call:runs.tick()
        call.assert_not_called();r=runs.get(self.studio,self.project,r['id']);self.assertEqual(r['status'],'failed');self.assertNotIn('private-key',str(r))

class BuilderFinalBoundaryTests(NodeBuilderFixture,unittest.TestCase):
    member=BuilderScopeTests.member
    def test_denied_template_read_never_commits_a_write(self):
        user=self.member();admin=Administration(self.store)
        for action,effect in [('create','allow'),('view','deny')]:
            admin.rule({'subject_type':'user','subject_id':user,'studio_id':self.studio,'department':'product','resource':'block','action':action,'effect':effect})
        token=current_user.set(user)
        try:
            with self.assertRaises(PermissionError):self.builder.save_template(self.studio,{'department':'product','name':'不得写入','revision':0,'blocks':[]})
        finally:current_user.reset(token)
        self.assertEqual(self.builder.templates(self.studio,'product')['items'],[])

    def test_replacing_block_type_requires_structural_permissions(self):
        self.member();b=self.blueprint([block('input','same',label='资料')]);token=current_user.set('member')
        try:
            with self.assertRaises(PermissionError):self.builder.save_blueprint(self.studio,self.project,'product:0',{'revision':b['revision'],'blocks':[block('review','same',label='审批')]})
        finally:current_user.reset(token)

    def test_malformed_write_bodies_are_validation_errors(self):
        for body in (None,[],1,'bad'):
            for call in (lambda:self.builder.save_template(self.studio,body),lambda:self.builder.save_flow(self.studio,self.project,body),lambda:self.builder.archive_template(self.studio,body),lambda:self.builder.archive_flow(self.studio,self.project,body)):
                with self.assertRaises(ValueError):call()

    def test_flow_template_round_trip_and_node_template_validation(self):
        t=self.builder.save_template(self.studio,{'department':'product','name':'跨部门组合','revision':0,'kind':'flow','blocks':[block('node',node='design:0')]})
        self.assertEqual(t['kind'],'flow');self.assertEqual(t['blocks'][0]['config']['node'],'design:0')
        with self.assertRaises(ValueError):self.builder.save_template(self.studio,{'department':'product','name':'不可嵌套','revision':0,'blocks':t['blocks']})

    def test_results_expose_evidence_gaps_and_manual_actor(self):
        runs,r=self.start_run([block('ai','a',prompt='整理'),block('review','r',label='审核')])
        with patch('server.codex_model.CodexModel.request_json',return_value={'deliverable':'报告','evidence':['fixture evidence'],'gaps':['fixture gap']}):runs.tick()
        runs.tick();r=runs.get(self.studio,self.project,r['id'])
        self.assertEqual(r['steps'][0]['evidence'],['fixture evidence']);self.assertEqual(r['steps'][0]['gaps'],['fixture gap'])
        r=runs.act(self.studio,self.project,r['id'],{'revision':r['revision'],'action':'submit','value':'已核对'})
        self.assertEqual(r['steps'][1]['actor'],'local');self.assertEqual(r['steps'][1]['acknowledgement'],'已核对')

    def test_department_modules_load_idempotently(self):
        from pathlib import Path
        from server.core.node_blocks.contracts import load_modules,unregister
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'product';target.mkdir()
            (target/'PRODUCT_blocks.py').write_text("def PRODUCT_register_blocks(register):\n register('product.fixture_load',label='示例',fields={},execute=lambda context,config,previous:{'deliverable':previous})\n")
            self.addCleanup(lambda:unregister('product.fixture_load'))
            with patch('server.studio_catalog.MODULE_ROOT',Path(folder)):load_modules();load_modules()

class BuilderSnapshotTests(NodeBuilderFixture,unittest.TestCase):
    def test_template_origin_pinned_without_live_dependency(self):
        t=self.builder.save_template(self.studio,{'department':'product','name':'源模板','revision':0,'blocks':[block('template',text='v1')]})
        origin={'id':t['id'],'department':'product','revision':1}
        b=self.builder.save_blueprint(self.studio,self.project,'product:0',{'revision':0,'blocks':t['blocks'],'sources':[origin]})
        self.builder.save_template(self.studio,{'department':'product','id':t['id'],'name':'新版','revision':1,'blocks':[block('template',text='v2')]})
        saved=self.builder.blueprint(self.studio,self.project,'product:0');self.assertEqual(saved['sources'],[origin]);self.assertEqual(saved['blocks'][0]['config']['text'],'v1')

    def test_relay_connection_changes_fail_before_model_call(self):
        from server.responses_model import Connection
        with patch('server.responses_model.configured_connection',return_value=Connection('https://first.example/responses','secret')):
            runs,r=self.start_run([block('ai',prompt='整理')])
        with patch('server.responses_model.configured_connection',return_value=Connection('https://second.example/responses','secret')),patch('server.codex_model.CodexModel.request_json') as call:runs.tick()
        call.assert_not_called();self.assertEqual(runs.get(self.studio,self.project,r['id'])['status'],'failed')

class BuilderHTTPTests(unittest.TestCase):
    from tests.test_api import ApiTests
    setUp=ApiTests.setUp
    tearDown=ApiTests.tearDown
    request=ApiTests.request

    def test_real_http_queue_with_explicit_model_substitute(self):
        import time
        studio=self.request('/api/studios')[1]['items'][0]['id']
        project=self.request('/api/studios/'+studio+'/projects',{'name':'HTTP 积木验收'})[1]['id']
        root='/api/studios/'+studio+'/projects/'+project
        payload={'revision':0,'blocks':[block('ai',prompt='返回摘要') ]}
        self.assertEqual(self.request(root+'/node-blueprint?node=product:0',payload)[0],200)
        with patch('server.codex_model.CodexModel.request_json',return_value={'deliverable':'明确模型替身','evidence':['fixture'],'gaps':['未调用外部模型']}) as model:
            code,r=self.request(root+'/block-runs',{'node':'product:0','revision':1,'input':'HTTP 资料'})
            self.assertEqual(code,200,r)
            deadline=time.monotonic()+5
            while r['status'] in ('queued','running') and time.monotonic()<deadline:
                time.sleep(.05);r=self.request(root+'/block-runs/'+r['id'])[1]
            self.assertEqual(r['status'],'completed',r);model.assert_called_once()
        self.assertEqual(r['steps'][0]['evidence'],['fixture']);self.assertEqual(r['output'],'明确模型替身')
        code,w=self.request(root+'/block-runs/'+r['id']+'/publish',{'revision':r['revision']})
        self.assertEqual(code,200,w);self.assertEqual(w['status'],'waiting_user')
        self.assertNotIn('skill_hash',str(r));self.assertNotIn('api_key',str(r))
        self.assertEqual(self.request(root+'/node-blueprint?node=product:0',payload)[0],400)
        self.assertIn(self.request(root+'/block-runs/'+r['id']+'/unknown',{'revision':r['revision']})[0],(403,404))

class BuilderRuntimeContractTests(NodeBuilderFixture,unittest.TestCase):
    def test_real_registered_adapter_receives_workspace_revision_and_previous_output(self):
        from server.core.integrations import AdapterRegistry
        from server.studio_workspaces import Workspaces
        from server.core.node_blocks.runtime import Runs
        w=Workspaces(self.store).get(self.studio,self.project,'product:0')
        w=Workspaces(self.store).save(self.studio,self.project,'product:0',{'revision':w['revision'],'inputs':'节点原始资料'})
        w=Workspaces(self.store).save(self.studio,self.project,'product:0',{'revision':w['revision'],'inputs':'节点原始资料第二版'})
        seen=[]
        class Adapter:
            def execute(self,context):
                seen.append(context.input_revision)
                return {'deliverable':context.inputs+' → 执行器','evidence':['契约测试替身']}
        registry=AdapterRegistry();registry.register('product',Adapter())
        flow=self.builder.save_flow(self.studio,self.project,{'name':'真实执行器接口','revision':0,'blocks':[block('node','first',node='product:0'),block('node','second',node='product:0')]})
        runs=Runs(self.store,registry);r=runs.start(self.studio,self.project,{'flow':flow['id'],'revision':1,'input':'起始资料'})
        for _ in range(3):runs.tick()
        result=runs.get(self.studio,self.project,r['id']);self.assertEqual(result['status'],'completed');self.assertEqual(result['output'],'起始资料 → 执行器 → 执行器');self.assertEqual(seen,[w['revision'],w['revision']])
        self.assertEqual(Workspaces(self.store).get(self.studio,self.project,'product:0')['deliverable'],'')

    def test_source_change_while_preparing_run_rejected_before_queue_insert(self):
        from server.core.node_blocks.runtime import Runs
        b=self.blueprint([block('template',text='旧版本')])
        def changed(selection):
            self.builder.save_blueprint(self.studio,self.project,'product:0',{'revision':1,'blocks':[block('template',text='新版本')]})
            return 'fingerprint'
        with patch('server.core.node_blocks.runtime.model_fingerprint',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'版本'):Runs(self.store).start(self.studio,self.project,{'node':'product:0','revision':1})
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM block_runs').fetchone()[0],0)

class BuilderInputValidationTests(NodeBuilderFixture,unittest.TestCase):
    def test_bad_identity_and_kind_rejected_before_database(self):
        for bad in ([],{},1,True):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):self.builder.save_template(self.studio,{'department':'product','name':'bad','revision':0,'id':bad,'blocks':[]})
                with self.assertRaises(ValueError):self.builder.save_flow(self.studio,self.project,{'name':'bad','revision':0,'id':bad,'blocks':[]})
                with self.assertRaises(ValueError):self.builder.save_template(self.studio,{'department':'product','name':'bad','revision':0,'kind':bad,'blocks':[]})

    def test_extension_labels_use_public_text_field(self):
        from server.core.node_blocks.contracts import register,unregister
        register('product.labeltest',label='示例',fields={'heading':'text'},execute=lambda c,v,p:{'deliverable':p})
        self.addCleanup(lambda:unregister('product.labeltest'))
        b=self.blueprint([block('product.labeltest','l',label='可改展示名称',heading='标题')]);self.assertEqual(b['blocks'][0]['config']['label'],'可改展示名称')

class BuilderNotificationTests(NodeBuilderFixture,unittest.TestCase):
    def test_completed_node_queues_once_without_external_send_and_links_exact_run(self):
        from server.core.notification_settings import NotificationSettings
        from server.core.notifications import NotificationQueue,card_for
        from tests.test_notifications import HOOK
        NotificationSettings(self.store).save(self.studio,'',{'enabled':True,'webhook':HOOK,'public_url':'https://studio.example'})
        runs,r=self.start_run([block('template',text='通知验收')]);runs.tick();runs.tick();runs.tick()
        rows=NotificationQueue(self.store).listing(self.studio,self.project);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['event'],'completed')
        with self.store.connection() as db:row=dict(db.execute('SELECT * FROM node_notifications').fetchone())
        import json
        self.assertEqual(json.loads(row['payload'])['block_run'],r['id'])
        card=card_for(row,{'public_url':'https://studio.example'});self.assertIn('block_run='+r['id'],str(card))
