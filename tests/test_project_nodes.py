import copy
import tempfile
import unittest
from pathlib import Path

from server.store import Store
from server.core.identity import current_user
from server.core.permissions import Policy
from server.core.admin import Administration
from server.studio_workspaces import Workspaces


class ProjectNodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'db.sqlite')
        self.studio = self.store.studios()[0]['id']
        self.project = self.store.create_project('节点配置')['id']
        self.other = self.store.create_project('独立项目')['id']
        from server.core.project_nodes import ProjectNodes
        self.nodes = ProjectNodes(self.store)

    def config(self, department='product', project=None):
        return self.nodes.get(self.studio, project or self.project, department)

    def save(self, value, department='product'):
        return self.nodes.save(self.studio, self.project, department, value)

    def add(self, department='product'):
        value = self.config(department)
        value['nodes'].append({'definition':['附加审查','核对证据','审查记录','检查真实证据','人工确认','已知资料','审查记录与缺口']})
        return self.save(value, department)

    def member(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO users VALUES('worker','t','worker','成员','active','member',CURRENT_TIMESTAMP)")
        Administration(self.store).member({'user_id':'worker','studio_id':self.studio,'project_id':self.project,'department':'product','role':'lead'})

    def grant(self, action, effect='allow', node=''):
        return Administration(self.store).rule({'subject_type':'user','subject_id':'worker','studio_id':self.studio,
            'project_id':self.project,'department':'product','node':node,'resource':'node','action':action,'effect':effect})

    def test_reorder_keeps_identity_skill_and_deliverable_and_other_project(self):
        w = Workspaces(self.store)
        w.save(self.studio,self.project,'product:0',{'revision':0,'deliverable':'原交付物','skill':'原规则'})
        value = self.config(); value['nodes'].reverse(); self.save(value)
        self.assertEqual(self.config()['nodes'][-1]['id'],'product:0')
        self.assertEqual(self.config(project=self.other)['nodes'][0]['id'],'product:0')
        self.assertEqual(w.get(self.studio,self.project,'product:0')['deliverable'],'原交付物')
        self.assertEqual(w.get(self.studio,self.project,'product:0')['skill']['content'],'原规则')
        self.assertEqual(self.config()['nodes'],type(self.nodes)(Store(self.store.path)).get(self.studio,self.project,'product')['nodes'])

    def test_new_nodes_in_all_departments_have_manual_workspaces_and_unique_ids(self):
        for department in ('product','design','development','testing','growth'):
            first = self.add(department)['nodes'][-1]
            self.assertTrue(first['id'].startswith(department+':custom-'))
            w = Workspaces(self.store).save(self.studio,self.project,first['id'],{'revision':0,'deliverable':'新增节点记录'})
            self.assertIn('人工', w['skill']['content'])
            self.assertEqual(w['deliverable'],'新增节点记录')
            from server.core.integrations import AdapterRegistry
            self.assertIsNone(AdapterRegistry().get(first['id'],store=self.store,project=self.project))

    def test_archive_retains_history_refuses_writes_and_never_reuses_id(self):
        value=self.add(); key=value['nodes'][-1]['id']; w=Workspaces(self.store)
        w.save(self.studio,self.project,key,{'revision':0,'deliverable':'历史证据'})
        value['nodes'].pop();self.save(value)
        self.assertEqual(w.get(self.studio,self.project,key)['deliverable'],'历史证据')
        with self.assertRaisesRegex(ValueError,'归档'):w.save(self.studio,self.project,key,{'revision':1,'deliverable':'覆盖'})
        self.assertNotEqual(self.add()['nodes'][-1]['id'],key)
        self.assertIn(key,{n['id'] for n in self.config()['archived']})

    def test_stale_versions_duplicate_keys_and_cross_project_keys_are_rejected(self):
        old=self.config(); self.add()
        with self.assertRaisesRegex(ValueError,'版本'):self.save(old)
        value=self.config();value['nodes'].append(copy.deepcopy(value['nodes'][0]))
        with self.assertRaises(ValueError):self.save(value)
        key=self.config()['nodes'][-1]['id']
        self.assertFalse(Policy(self.store).allowed('node','view',self.studio,self.other,node=key))

    def test_edit_and_lead_role_do_not_grant_node_lifecycle_or_reorder(self):
        self.member(); p=Policy(self.store)
        self.assertTrue(p.allowed('node','edit',self.studio,self.project,node='product:0',actor='worker'))
        for action in ('create','delete','reorder'):
            self.assertFalse(p.allowed('node',action,self.studio,self.project,department='product',actor='worker'))
        value=self.config();value['nodes'].reverse();token=current_user.set('worker')
        try:
            with self.assertRaises(PermissionError):self.save(value)
        finally:current_user.reset(token)

    def test_reorder_only_cannot_smuggle_create_delete_and_revoke_takes_effect(self):
        self.member();rule=self.grant('reorder');value=self.config();value['nodes'].reverse()
        token=current_user.set('worker')
        try:
            result=self.save(value)
            result['nodes'].pop()
            with self.assertRaises(PermissionError):self.save(result)
            result=self.config();result['nodes'].append({'definition':['新增']*7})
            with self.assertRaises(PermissionError):self.save(result)
        finally:current_user.reset(token)
        Administration(self.store).revoke(rule['id'])
        value=self.config();value['nodes'].reverse();token=current_user.set('worker')
        try:
            with self.assertRaises(PermissionError):self.save(value)
        finally:current_user.reset(token)

    def test_active_jobs_block_archive(self):
        value=self.config();value['nodes']=value['nodes'][1:]
        with self.store.connection() as db:
            db.execute("INSERT INTO department_jobs(id,studio_id,project_id,node,actor,revision,status) VALUES('job',?,?,'product:0','local',0,'queued')",(self.studio,self.project))
        with self.assertRaisesRegex(ValueError,'任务'):self.save(value)

    def test_testing_snapshot_survives_configuration_changes_but_missing_gate_blocks_new_batch(self):
        before=self.store.create_task(self.project,'原批次')
        value=self.config('testing');value['nodes'].reverse();self.save(value,'testing')
        self.assertEqual(self.store.task(self.project,before['id'])['workflow_nodes'],before['workflow_nodes'])
        after=self.store.create_task(self.project,'新顺序')
        self.assertEqual(after['workflow_nodes']['nodes'][0]['id'],'testing:5')
        value=self.config('testing');value['nodes']=[n for n in value['nodes'] if n['id']!='testing:1'];self.save(value,'testing')
        with self.assertRaisesRegex(ValueError,'必需节点'):self.store.create_task(self.project,'缺少检测')
        self.assertEqual(self.store.task(self.project,before['id'])['stage'],0)

    def test_management_permission_scope_requires_department_and_no_node_for_create_reorder(self):
        self.member()
        for action in ('create','reorder'):
            with self.assertRaises(ValueError):self.grant(action,node='product:0')
        self.grant('delete',node='product:0')

    def test_archive_restore_preserves_the_original_id_and_requires_create_permission(self):
        value=self.config();value['nodes']=value['nodes'][1:];value=self.save(value)
        archived=next(n for n in value['archived'] if n['id']=='product:0')
        value['nodes'].append({**archived,'restore':True})
        restored=self.save(value)
        self.assertEqual(restored['nodes'][-1]['id'],'product:0')
        self.assertFalse(restored['archived'])
