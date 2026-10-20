import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.core.admin import Administration
from server.core.identity import current_user


class ProjectContentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite');self.studio=self.store.studios()[0]['id'];self.project=self.store.create_project('内容')['id']
        from server.core.project_content import ProjectContent
        self.service=ProjectContent(self.store)

    def add(self,kind='note',**fields):
        current=self.service.get(self.studio,self.project)
        return self.service.change(self.studio,self.project,{'revision':current['revision'],'action':'create','department':'product','kind':kind,'title':'真实内容','body':'明确来源的内容',**fields})

    def test_create_archive_and_reload_are_project_scoped_with_stable_ids(self):
        current=self.add();item=current['items'][0]
        current=self.service.change(self.studio,self.project,{'revision':current['revision'],'action':'delete','id':item['id']})
        self.assertTrue(current['items'][0]['archived'])
        self.assertEqual(current['items'][0]['body'],'明确来源的内容')
        other=self.store.create_project('独立')['id']
        self.assertFalse(self.service.get(self.studio,other)['items'])
        self.assertEqual(type(self.service)(Store(self.store.path)).get(self.studio,self.project),current)

    def test_default_member_has_no_content_create_delete_but_explicit_grant_and_revoke_work(self):
        with self.store.connection() as db:db.execute("INSERT INTO users VALUES('member','t','m','成员','active','member',CURRENT_TIMESTAMP)")
        admin=Administration(self.store);admin.member({'user_id':'member','studio_id':self.studio,'project_id':self.project,'department':'product','role':'lead'})
        token=current_user.set('member')
        try:
            with self.assertRaises(PermissionError):self.add()
        finally:current_user.reset(token)
        rule=admin.rule({'subject_type':'department','subject_id':'product','studio_id':self.studio,'project_id':self.project,'department':'product','resource':'content','action':'create','effect':'allow'})
        token=current_user.set('member')
        try:
            current=self.add()
            with self.assertRaises(PermissionError):self.service.change(self.studio,self.project,{'revision':current['revision'],'action':'delete','id':current['items'][0]['id']})
        finally:current_user.reset(token)
        admin.revoke(rule['id']);token=current_user.set('member')
        try:
            with self.assertRaises(PermissionError):self.add()
        finally:current_user.reset(token)

    def test_tools_accept_only_credential_free_https_and_catalog_reflects_overrides(self):
        for url in ('javascript:alert(1)','http://example.test','https://u:p@example.test'):
            with self.assertRaises(ValueError):self.add('tool',url=url)
        self.add('tool',url='https://example.test/design')
        from server.core.project_nodes import ProjectNodes
        d=next(d for d in ProjectNodes(self.store).catalog(self.studio,self.project)['departments'] if d['id']=='product')
        self.assertIn('https://example.test/design',[t['url'] for t in d['tools']])

    def test_stale_revision_and_active_department_disable_are_rejected(self):
        self.add()
        with self.assertRaisesRegex(ValueError,'版本'):self.service.change(self.studio,self.project,{'revision':0,'action':'create','department':'product','kind':'note','title':'过期','body':'旧'})
        with self.store.connection() as db:db.execute("INSERT INTO department_jobs VALUES('active',?,?,'product:0','local',0,'running',NULL,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(self.studio,self.project))
        with self.assertRaisesRegex(ValueError,'任务'):self.service.change(self.studio,self.project,{'revision':1,'action':'disable','department':'product'})

    def test_create_cannot_hide_defaults_and_create_grant_can_restore_hidden_default(self):
        with self.assertRaises(ValueError):self.add('hidden',target='focus:0')
        current=self.service.change(self.studio,self.project,{'revision':0,'action':'hide','department':'product','target':'focus:0'})
        hidden=current['items'][0]
        with self.store.connection() as db:db.execute("INSERT INTO users VALUES('creator','t','c','创建者','active','member',CURRENT_TIMESTAMP)")
        admin=Administration(self.store);admin.member({'user_id':'creator','studio_id':self.studio,'project_id':self.project,'department':'product','role':'member'})
        admin.rule({'subject_type':'user','subject_id':'creator','studio_id':self.studio,'project_id':self.project,'department':'product','resource':'content','action':'create','effect':'allow'})
        token=current_user.set('creator')
        try:
            current=self.service.change(self.studio,self.project,{'revision':current['revision'],'action':'unhide','id':hidden['id']})
            self.assertTrue(current['items'][0]['archived'])
        finally:current_user.reset(token)

    def test_disabled_department_retains_history_but_blocks_workspace_writes_and_new_batches(self):
        from server.studio_workspaces import Workspaces
        work=Workspaces(self.store);work.save(self.studio,self.project,'product:0',{'revision':0,'inputs':'历史'})
        current=self.service.change(self.studio,self.project,{'revision':0,'action':'disable','department':'product'})
        self.assertEqual(work.get(self.studio,self.project,'product:0')['inputs'],'历史')
        with self.assertRaisesRegex(ValueError,'停用'):work.save(self.studio,self.project,'product:0',{'revision':1,'inputs':'不能保存'})
        self.service.change(self.studio,self.project,{'revision':current['revision'],'action':'disable','department':'testing'})
        with self.assertRaisesRegex(ValueError,'停用'):self.store.create_task(self.project,'新测试批次')
