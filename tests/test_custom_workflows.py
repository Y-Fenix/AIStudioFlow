"""Behavioral tests for business-node flows, independent snapshots and real gates."""
import json
import unittest
from unittest.mock import patch
from tests.test_node_builder import NodeBuilderFixture, block
from server.core.node_blocks.runtime import Runs
from server.core.identity import current_user
from server.core.admin import Administration


def task(identity, text, **config):
    return block('task', identity, label=identity, blocks=[block('template', 'report', text=text)], **config)


class CustomWorkflowTests(NodeBuilderFixture, unittest.TestCase):
    def flow(self, blocks, **extra):
        return self.builder.save_flow(self.studio, self.project, {'name':'质量验收', 'description':'独立业务节点', 'revision':0, 'blocks':blocks, **extra})

    def detail(self, flow):
        return self.builder.flow(self.studio, self.project, flow['id'])

    def test_legacy_contiguous_blocks_are_grouped_without_rewriting_storage(self):
        original=[block('input','source'),block('template','report',text='{{previous}}'),block('node','qa',node='testing:1'),block('review','accept')]
        f=self.flow(original);detail=self.detail(f)
        self.assertEqual([n['id'] for n in detail['nodes']], ['source','qa','accept'])
        self.assertEqual([b['id'] for b in detail['nodes'][0]['blocks']], ['source','report'])
        with self.store.connection() as db:
            self.assertEqual(json.loads(db.execute('SELECT blocks FROM custom_flows WHERE id=?',(f['id'],)).fetchone()[0]),original)
        self.assertEqual(self.detail(f)['nodes'],detail['nodes'])

    def test_custom_node_schema_rejects_nested_flows_and_wrong_property_types(self):
        invalid=[block('task','a',blocks=[block('task','nested',blocks=[])]),block('task','a',blocks=[block('node','n',node='product:0')]),task('a','X',auto_next='yes')]
        for blocks in invalid:
            with self.subTest(block=blocks),self.assertRaises(ValueError):self.flow([blocks])

    def test_manual_boundary_really_pauses_and_continue_preserves_output(self):
        f=self.flow([task('one','第一份交付',auto_next=False),task('two','第二份 {{previous}}')])
        runs=Runs(self.store);r=runs.start(self.studio,self.project,{'flow':f['id'],'revision':1})
        runs.tick();runs.tick();r=runs.get(self.studio,self.project,r['id'])
        self.assertEqual(r['status'],'waiting_user');self.assertEqual(r['steps'][r['cursor']]['type'],'boundary')
        self.assertEqual(r['output'],'第一份交付')
        with self.assertRaises(ValueError):runs.act(self.studio,self.project,r['id'],{'revision':r['revision'],'action':'submit','value':'不可冒充审核'})
        r=runs.act(self.studio,self.project,r['id'],{'revision':r['revision'],'action':'continue'})
        runs.tick();runs.tick();r=runs.get(self.studio,self.project,r['id'])
        self.assertEqual(r['status'],'completed');self.assertEqual(r['output'],'第二份 第一份交付')
        self.assertEqual([n['id'] for n in r['groups']],['one','two'])

    def test_automatic_transition_cannot_skip_review_and_edits_do_not_change_snapshot(self):
        f=self.flow([block('task','first',label='审核',blocks=[block('review','review')],auto_next=True),task('second','原报告',auto_next=True)])
        runs=Runs(self.store);r=runs.start(self.studio,self.project,{'flow':f['id'],'revision':1})
        self.builder.save_flow(self.studio,self.project,{**f,'blocks':[task('first','修改后',auto_next=False),task('second','新报告')]})
        runs.tick();r=runs.get(self.studio,self.project,r['id']);self.assertEqual(r['status'],'waiting_user');self.assertEqual(r['steps'][0]['type'],'review')
        runs.act(self.studio,self.project,r['id'],{'revision':r['revision'],'action':'submit','value':'核对原证据'})
        runs.tick();runs.tick();r=runs.get(self.studio,self.project,r['id'])
        self.assertEqual(r['output'],'原报告');self.assertTrue(r['groups'][0]['auto_next'])

    def test_repeated_source_nodes_keep_local_skill_input_and_results_independent(self):
        from server.studio_workspaces import Workspaces
        self.blueprint([block('ai','analyze',prompt='根据资料输出')])
        before=Workspaces(self.store).get(self.studio,self.project,'product:0')
        f=self.flow([block('node','a',node='product:0',skill='规则 A',inputs='资料 A',auto_next=True),block('node','b',node='product:0',skill='规则 B',inputs='资料 B',auto_next=True)])
        runs=Runs(self.store);r=runs.start(self.studio,self.project,{'flow':f['id'],'revision':1,'input':'起始'})
        prompts=[]
        def answer(prompt,*args,**kwargs):
            from server.node_skills import current_skill
            prompts.append(current_skill()+'\n'+str(prompt));return {'deliverable':'结果 '+str(len(prompts))}
        with patch('server.codex_model.CodexModel.request_json',side_effect=answer):
            for _ in range(3):runs.tick()
        r=runs.get(self.studio,self.project,r['id'])
        self.assertEqual(r['status'],'completed');self.assertEqual([s['group'] for s in r['steps']],['a','b'])
        self.assertIn('规则 A',prompts[0]);self.assertIn('资料 A',prompts[0]);self.assertIn('规则 B',prompts[1]);self.assertIn('资料 B',prompts[1])
        after=Workspaces(self.store).get(self.studio,self.project,'product:0');self.assertEqual(before,after)
        self.assertNotIn('规则 A',str(r));self.assertNotIn('规则 B',str(r))

    def test_run_listing_filter_does_not_lose_older_selected_flows(self):
        first=self.flow([task('a','旧记录')]);second=self.flow([task('a','另一流程')])
        runs=Runs(self.store)
        for f in (first,second):
            r=runs.start(self.studio,self.project,{'flow':f['id'],'revision':1});runs.tick();runs.tick()
        self.assertEqual([r['flow_id'] for r in runs.listing(self.studio,self.project,flow=first['id'])['items']],[first['id']])

    def test_logs_are_operations_for_this_run_only(self):
        f=self.flow([task('a','交付中的私有正文')]);runs=Runs(self.store)
        r=runs.start(self.studio,self.project,{'flow':f['id'],'revision':1});runs.tick();runs.tick()
        result=runs.get(self.studio,self.project,r['id'])
        self.assertTrue(result['events']);self.assertNotIn('交付中的私有正文',str(result['events']))
        self.assertTrue(all(e['detail']['run']==r['id'] for e in result['events']))

    def test_workflow_edit_does_not_grant_node_or_skill_permissions(self):
        f=self.flow([task('a','报告',skill='独立私有 Skill')])
        with self.store.connection() as db:db.execute("INSERT INTO users VALUES('flow-member','t','fm','成员','active','member',CURRENT_TIMESTAMP)")
        admin=Administration(self.store);admin.member({'user_id':'flow-member','studio_id':self.studio,'project_id':self.project,'department':'product'})
        for resource,actions in [('workflow',['view','edit','execute']),('workflow_node',['view','edit','execute'])]:
            for action in actions:admin.rule({'subject_type':'user','subject_id':'flow-member','studio_id':self.studio,'project_id':self.project,'resource':resource,'action':action,'effect':'allow'})
        token=current_user.set('flow-member')
        try:
            d=self.detail(f);self.assertNotIn('独立私有 Skill',str(d))
            with self.assertRaises(PermissionError):self.builder.save_flow(self.studio,self.project,{**f,'blocks':[task('a','报告',skill='越权规则')]})
            with self.assertRaises(PermissionError):Runs(self.store).start(self.studio,self.project,{'flow':f['id'],'revision':1})
        finally:current_user.reset(token)

    def test_node_specific_deny_is_effective_in_api_and_worker(self):
        f=self.flow([task('a','报告',auto_next=False),task('b','后续')])
        with self.store.connection() as db:db.execute("INSERT INTO users VALUES('flow-owner','t','fo','项目负责人','active','member',CURRENT_TIMESTAMP)")
        admin=Administration(self.store);admin.member({'user_id':'flow-owner','studio_id':self.studio,'project_id':self.project,'department':'product','role':'project_lead'})
        token=current_user.set('flow-owner')
        try:r=Runs(self.store).start(self.studio,self.project,{'flow':f['id'],'revision':1})
        finally:current_user.reset(token)
        admin.rule({'subject_type':'user','subject_id':'flow-owner','studio_id':self.studio,'project_id':self.project,'resource':'workflow_node','node':'wf:'+f['id']+':b','action':'execute','effect':'deny'})
        Runs(self.store).tick()
        with self.store.connection() as db:row=db.execute('SELECT status,results FROM block_runs WHERE id=?',(r['id'],)).fetchone()
        self.assertEqual(row['status'],'failed');self.assertEqual(json.loads(row['results']),[])

    def test_prepared_node_inputs_survive_manual_input_before_ai(self):
        f=self.flow([block('task','a',inputs='预先准备资料',blocks=[block('input','in',required=True),block('ai','analysis',prompt='整理')])])
        runs=Runs(self.store);r=runs.start(self.studio,self.project,{'flow':f['id'],'revision':1});runs.tick();r=runs.get(self.studio,self.project,r['id'])
        runs.act(self.studio,self.project,r['id'],{'revision':r['revision'],'action':'submit','value':'补充输入'})
        seen=[]
        with patch('server.codex_model.CodexModel.request_json',side_effect=lambda prompt:(seen.append(prompt) or {'deliverable':'报告'})):runs.tick()
        self.assertIn('预先准备资料',seen[0]);self.assertIn('补充输入',seen[0])

    def test_input_only_save_preserves_hidden_skill_without_edit_permission(self):
        f=self.flow([task('a','报告',skill='不能读取的既存规则')])
        with self.store.connection() as db:db.execute("INSERT INTO users VALUES('writer','t','writer','成员','active','member',CURRENT_TIMESTAMP)")
        admin=Administration(self.store);admin.member({'user_id':'writer','studio_id':self.studio,'project_id':self.project,'department':'product'})
        for resource in ('workflow','workflow_node'):
            for action in ('view','edit'):admin.rule({'subject_type':'user','subject_id':'writer','studio_id':self.studio,'project_id':self.project,'resource':resource,'action':action,'effect':'allow'})
        token=current_user.set('writer')
        try:
            value=self.detail(f);value['blocks'][0]['config']['inputs']='有权修改资料'
            self.builder.save_flow(self.studio,self.project,value)
        finally:current_user.reset(token)
        saved=self.detail(f);self.assertEqual(saved['nodes'][0]['skill']['content'],'不能读取的既存规则');self.assertEqual(saved['nodes'][0]['inputs'],'有权修改资料')

    def test_visible_skill_can_be_explicitly_reset_to_default(self):
        f=self.flow([task('a','报告',skill='自定义规则')])
        value=self.detail(f);value['blocks'][0]['config'].pop('skill')
        saved=self.builder.save_flow(self.studio,self.project,value)
        self.assertEqual(saved['nodes'][0]['skill']['source'],'default')

    def test_legacy_run_without_groups_enforces_instance_denies(self):
        for legacy_field in ('group','instance'):
            with self.subTest(field=legacy_field):
                f=self.flow([block('task','a',blocks=[block('input','source',required=True)])])
                with self.store.connection() as db:
                    db.execute("INSERT OR IGNORE INTO users VALUES('legacy-owner','t','legacy','负责人','active','member',CURRENT_TIMESTAMP)")
                admin=Administration(self.store);admin.member({'user_id':'legacy-owner','studio_id':self.studio,'project_id':self.project,'department':'product','role':'project_lead'})
                runs=Runs(self.store);token=current_user.set('legacy-owner')
                try:
                    r=runs.start(self.studio,self.project,{'flow':f['id'],'revision':1});runs.tick()
                    r=runs.get(self.studio,self.project,r['id'])
                    with self.store.connection() as db:
                        snapshot=json.loads(db.execute('SELECT snapshot FROM block_runs WHERE id=?',(r['id'],)).fetchone()[0])
                        snapshot.pop('groups')
                        for step in snapshot['steps']:
                            step.pop('group',None);step.pop('instance',None);step[legacy_field]='a'
                        db.execute('UPDATE block_runs SET snapshot=? WHERE id=?',(json.dumps(snapshot),r['id']))
                    admin.rule({'subject_type':'user','subject_id':'legacy-owner','studio_id':self.studio,'project_id':self.project,'resource':'workflow_node','node':'wf:'+f['id']+':a','action':'execute','effect':'deny'})
                    with self.assertRaises(PermissionError):
                        runs.act(self.studio,self.project,r['id'],{'revision':r['revision'],'action':'submit','value':'不能绕过'})
                    with self.store.connection() as db:
                        self.assertEqual(db.execute('SELECT cursor FROM block_runs WHERE id=?',(r['id'],)).fetchone()[0],0)
                finally:current_user.reset(token)

    def test_legacy_root_and_expanded_instance_scopes_are_normalized(self):
        # Old top-level primitives used instance=root; expanded references
        # used the source block ID plus a trailing hyphen.
        f=self.flow([block('input','source'),block('template','report',text='交付'),block('node','ref',node='product:0')])
        snapshot={'flow':f['id'],'steps':[
            {'id':'source','node':'','instance':'root'},
            {'id':'report','node':'','instance':'root'},
            {'id':'ref-ai','node':'product:0','instance':'ref-'}]}
        runs=Runs(self.store)
        with patch.object(runs.policy,'require') as require:
            from server.core.identity import user_id
            runs._permissions(self.studio,self.project,snapshot,user_id(),'execute')
        scopes=[call.kwargs['node'] for call in require.call_args_list if call.args[0]=='workflow_node']
        self.assertEqual(scopes,['wf:'+f['id']+':source','wf:'+f['id']+':ref'])
