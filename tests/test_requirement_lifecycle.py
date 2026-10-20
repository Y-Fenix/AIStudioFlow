import unittest
import tempfile
from pathlib import Path
from server.store import Store
from server.core.identity import current_user
from server.core.admin import Administration
from server.core.gateway import Gateway

class RequirementLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db.sqlite');self.studio=self.store.studios()[0]['id']
        self.project=self.store.create_project('资料生命周期')['id'];self.task=self.store.create_task(self.project,'测试')

    def test_archive_retains_versions_excludes_generation_input_and_restore_is_explicit(self):
        task=self.store.import_requirement(self.project,self.task['id'],'需求.md','原始资料')
        source=task['requirements'][0]
        task=self.store.archive_requirement(self.project,task['id'],source['id'],task['revision'],True)
        self.assertEqual(task['requirements'],[])
        self.assertEqual(task['archived_requirements'][0]['content'],'原始资料')
        with self.assertRaisesRegex(ValueError,'归档'):self.store.import_requirement(self.project,task['id'],'需求.md','覆盖内容')
        task=self.store.archive_requirement(self.project,task['id'],source['id'],task['revision'],False)
        self.assertEqual(task['requirements'][0]['id'],source['id'])
        self.assertFalse(task['archived_requirements'])

    def test_downstream_reference_busy_and_stale_requests_block_archive(self):
        t=self.store.import_requirement(self.project,self.task['id'],'需求.md','原始资料');r=t['requirements'][0]
        with self.assertRaisesRegex(ValueError,'版本'):self.store.archive_requirement(self.project,t['id'],r['id'],0,True)
        with self.store.connection() as db:db.execute("UPDATE tasks SET artifacts=? WHERE id=?",('{"0":{"cases":[]}}',t['id']))
        with self.assertRaisesRegex(ValueError,'下游'):self.store.archive_requirement(self.project,t['id'],r['id'],t['revision'],True)
        with self.store.connection() as db:
            db.execute("UPDATE tasks SET artifacts='{}' WHERE id=?",(t['id'],))
            db.execute("INSERT INTO jobs(id,project_id,task_id,revision,status,actor) VALUES('busy',?,?,?,'queued','local')",(self.project,t['id'],t['revision']))
        with self.assertRaisesRegex(ValueError,'任务'):self.store.archive_requirement(self.project,t['id'],r['id'],t['revision'],True)

    def test_node_import_does_not_imply_content_creation_and_revocation_is_immediate(self):
        with self.store.connection() as db:db.execute("INSERT INTO users VALUES('m','t','m','成员','active','member',CURRENT_TIMESTAMP)")
        admin=Administration(self.store);admin.member({'user_id':'m','studio_id':self.studio,'project_id':self.project,'department':'testing','role':'lead'})
        gateway=Gateway(self.store);parts=['api','studios',self.studio,'projects',self.project,'tasks',self.task['id'],'requirements']
        token=current_user.set('m')
        try:
            with self.assertRaises(PermissionError):gateway.authorize(parts,'',{'source':'新需求'},True)
        finally:current_user.reset(token)
        grant=admin.rule({'subject_type':'user','subject_id':'m','studio_id':self.studio,'project_id':self.project,'department':'testing','resource':'content','action':'create','effect':'allow'})
        token=current_user.set('m')
        try:self.assertTrue(gateway.authorize(parts,'',{},True))
        finally:current_user.reset(token)
        admin.revoke(grant['id']);token=current_user.set('m')
        try:
            with self.assertRaises(PermissionError):gateway.authorize(parts,'',{},True)
        finally:current_user.reset(token)
