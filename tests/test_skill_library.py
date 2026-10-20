import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.studio_workspaces import Workspaces
from server.core.admin import Administration
from server.core.identity import current_user


class SkillLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite');self.studio=self.store.studios()[0]['id']
        self.project=self.store.create_project('技能版本')['id'];self.now=1000000000
        from server.core.skill_library import SkillLibrary
        self.library=SkillLibrary(self.store,clock=lambda:self.now)

    def detail(self,node='product:0'):
        return self.library.detail(self.studio,self.project,node)

    def upload(self,text='---\nname: sample\ndescription: 真实规则\n---\n# 规则\n核对来源。',node='product:0'):
        current=self.detail(node)
        return self.library.import_skill(self.studio,self.project,node,{'id':current['id'],'revision':current['revision'],
            'content':text,'name':'样例规则','note':'补充来源检查'})

    def remove(self,item):
        return self.library.trash(self.studio,self.project,item['id'],{'revision':item['revision'],'confirmed':True})

    def test_import_versions_are_actual_rules_with_actor_time_note_and_export(self):
        first=self.upload();second=self.upload('第二版规则')
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(second['uploader'],'本机负责人')
        self.assertEqual(second['updated_at'],self.now)
        self.assertEqual(second['history'][-1]['note'],'补充来源检查')
        self.assertEqual(Workspaces(self.store).get(self.studio,self.project,'product:0')['skill']['content'],'第二版规则')
        old=self.library.export(self.studio,self.project,first['id'],version=first['revision'])
        self.assertEqual(old['content'],first['skill']['content'])

    def test_legacy_uploader_and_update_time_are_not_invented(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO studio_workspaces(project_id,node,skill) VALUES(?,'product:0',?)",(self.project,'{"name":"旧规则","content":"旧上传规则","source_kind":"imported","sha256":"old"}'))
        item=self.detail()
        self.assertEqual(item['uploader'],'未记录');self.assertIsNone(item['updated_at'])

    def test_soft_delete_restore_and_30_day_cleanup_boundary(self):
        item=self.upload();removed=self.remove(item)
        self.assertEqual(self.detail()['status'],'trashed')
        self.assertEqual(self.detail()['skill']['content'],'')
        self.assertEqual(len(self.library.recycle_bin(self.studio,self.project)['items']),1)
        self.now+=30*86400-1;self.assertEqual(self.library.purge_expired(),0)
        self.library.restore(self.studio,self.project,item['id'],{'revision':removed['revision']})
        self.assertTrue(self.detail()['skill']['content'])
        removed=self.remove(self.detail());self.now+=30*86400
        self.assertEqual(self.library.purge_expired(),1)
        self.assertFalse(self.library.recycle_bin(self.studio,self.project)['items'])
        with self.store.connection() as db:
            self.assertIsNone(db.execute('SELECT skill FROM skill_library WHERE id=?',(item['id'],)).fetchone()[0])
            self.assertEqual(db.execute('SELECT count(*) FROM skill_versions WHERE skill_id=?',(item['id'],)).fetchone()[0],0)

    def test_new_upload_after_trash_does_not_overwrite_the_recycle_item(self):
        old=self.upload();old=self.remove(old);new=self.upload('全新规则')
        self.assertNotEqual(old['id'],new['id'])
        self.assertEqual(self.library.recycle_bin(self.studio,self.project)['items'][0]['id'],old['id'])
        with self.assertRaisesRegex(ValueError,'已有'):self.library.restore(self.studio,self.project,old['id'],{'revision':old['revision']})

    def test_member_import_permission_cannot_delete_restore_or_purge(self):
        item=self.upload()
        with self.store.connection() as db:db.execute("INSERT INTO users VALUES('member','t','m','成员','active','member',CURRENT_TIMESTAMP)")
        Administration(self.store).member({'user_id':'member','studio_id':self.studio,'project_id':self.project,'department':'product','role':'lead'})
        token=current_user.set('member')
        try:
            for operation in (self.library.trash,self.library.restore,self.library.purge):
                with self.assertRaises(PermissionError):operation(self.studio,self.project,item['id'],{'revision':item['revision'],'confirmed':True})
        finally:current_user.reset(token)

    def test_stale_import_missing_note_and_cross_project_delete_rejected(self):
        before=self.detail();item=self.upload()
        with self.assertRaisesRegex(ValueError,'版本'):self.library.import_skill(self.studio,self.project,'product:0',{'id':before['id'],'revision':before['revision'],'content':'过期内容','note':'更新'})
        with self.assertRaisesRegex(ValueError,'说明'):self.library.import_skill(self.studio,self.project,'product:0',{'id':item['id'],'revision':item['revision'],'content':'无说明'})
        other=self.store.create_project('其他项目')['id']
        with self.assertRaises(KeyError):self.library.trash(self.studio,other,item['id'],{'revision':item['revision'],'confirmed':True})

    def test_active_job_blocks_delete_and_new_execution_rejects_missing_skill(self):
        item=self.upload()
        with self.store.connection() as db:db.execute("INSERT INTO department_jobs VALUES('active',?,?,'product:0','local',0,'queued',NULL,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(self.studio,self.project))
        with self.assertRaisesRegex(ValueError,'任务'):self.remove(item)
        with self.store.connection() as db:db.execute("DELETE FROM department_jobs WHERE id='active'")
        self.remove(item)
        from server.core.integrations import ExecutionService,AdapterRegistry
        class Adapter:
            def execute(self,context):raise AssertionError('must not run')
        registry=AdapterRegistry();registry.register('product',Adapter())
        with self.assertRaisesRegex(ValueError,'Skill'):ExecutionService(self.store,registry).execute(self.studio,self.project,'product:0',0)

    def test_testing_batches_keep_rule_snapshot_when_library_changes(self):
        original=self.store.create_task(self.project,'旧批次')
        self.upload('项目级测试规则',node='testing:0')
        new=self.store.create_task(self.project,'新批次')
        self.assertEqual(new['node_skills']['0']['content'],'项目级测试规则')
        self.assertEqual(self.store.task(self.project,original['id'])['node_skills']['0'],original['node_skills']['0'])

    def test_trash_default_validates_revision_and_confirmation_before_materializing(self):
        for value in ({'revision':9,'confirmed':True},{'revision':0,'confirmed':False}):
            with self.assertRaises(ValueError):self.library.trash_node(self.studio,self.project,'product:0',value)
            self.assertIsNone(self.detail()['id'],'invalid request must not create a version')

    def test_archived_node_and_active_job_reject_library_import(self):
        from server.core.project_nodes import ProjectNodes
        service=ProjectNodes(self.store);config=service.get(self.studio,self.project,'product')
        config['nodes'].pop(0)
        service.save(self.studio,self.project,'product',config)
        with self.assertRaisesRegex(ValueError,'归档'):self.upload()
        with self.store.connection() as db:db.execute("INSERT INTO department_jobs VALUES('active',?,?,'design:0','local',0,'running',NULL,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(self.studio,self.project))
        with self.assertRaisesRegex(ValueError,'任务'):self.upload(node='design:0')
    def test_node_toolbar_import_cannot_bypass_active_job_guard(self):
        with self.store.connection() as db:db.execute("INSERT INTO department_jobs VALUES('active',?,?,'product:0','local',0,'running',NULL,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(self.studio,self.project))
        with self.assertRaisesRegex(ValueError,'任务'):
            Workspaces(self.store).save(self.studio,self.project,'product:0',{'revision':0,'skill':'不能旁路替换'})
    def test_trashing_and_restoring_default_does_not_invent_uploader_or_upload_time(self):
        original=self.detail()
        removed=self.library.trash_node(self.studio,self.project,'product:0',{'revision':original['revision'],'confirmed':True})
        restored=self.library.restore(self.studio,self.project,removed['id'],{'revision':removed['revision']})
        self.assertEqual(restored['uploader'],original['uploader'])
        self.assertEqual(restored['updated_at'],original['updated_at'])
        self.assertTrue(all(v['updated_at'] is None for v in restored['history']))
