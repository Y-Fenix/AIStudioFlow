import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from server.store import Store


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'platform.sqlite'
        self.store = Store(self.path)
        self.first = self.store.studios()[0]['id']

    def tearDown(self):
        self.tmp.cleanup()

    def test_projects_with_same_name_are_independent_between_studios(self):
        second = self.store.create_studio('第二工作室')['id']
        one = self.store.create_project('同名游戏', self.first)
        two = self.store.create_project('同名游戏', second)
        self.assertNotEqual(one['id'], two['id'])
        self.assertEqual([x['id'] for x in self.store.projects(studio_id=self.first)['items']], [one['id']])
        self.assertEqual([x['id'] for x in self.store.projects(studio_id=second)['items']], [two['id']])
        with self.assertRaises(ValueError):
            self.store.create_project(' 同名游戏 ', second)

    def test_identity_decides_home_and_survives_reopening(self):
        for role, home in [('studio_owner','overview'),('product','product'),('design','design'),
                           ('development','development'),('qa','testing'),('growth','growth')]:
            self.store.save_preferences({'active_studio_id': self.first, 'role': role})
            value = Store(self.path).preferences()
            self.assertEqual((value['active_role'], value['default_workspace']), (role,home))
        with self.assertRaises(ValueError):
            self.store.save_preferences({'active_studio_id':self.first,'role':'admin'})
        with self.assertRaises(ValueError):
            self.store.save_preferences({'active_studio_id':self.first,'role':'qa','default_workspace':'overview'})
        with self.assertRaises(KeyError):
            self.store.save_preferences({'active_studio_id':'missing','role':'qa'})

    def test_workspaces_reject_wrong_studio_and_old_revision(self):
        from server.studio_workspaces import Workspaces
        p = self.store.create_project('游戏',self.first)
        second = self.store.create_studio('第二工作室')['id']
        workspace = Workspaces(self.store)
        original = workspace.get(self.first,p['id'],'product:0')
        saved = workspace.save(self.first,p['id'],'product:0',
                               {'revision':original['revision'],'inputs':'调研资料','deliverable':'调研结论'})
        self.assertEqual(saved['inputs'],'调研资料')
        self.assertEqual(workspace.get(self.first,p['id'],'product:1')['inputs'],'')
        with self.assertRaises(KeyError):
            workspace.get(second,p['id'],'product:0')
        with self.assertRaises(ValueError):
            workspace.save(self.first,p['id'],'product:0',{'revision':original['revision'],'inputs':'覆盖'})
        reread=Workspaces(Store(self.path)).get(self.first,p['id'],'product:0')
        self.assertEqual(reread['deliverable'],'调研结论')
        self.assertTrue(reread['events'])

    def test_skill_import_restore_and_human_decision_are_persistent(self):
        from server.studio_workspaces import Workspaces
        p=self.store.create_project('游戏',self.first); service=Workspaces(self.store)
        original=service.get(self.first,p['id'],'design:0')
        saved=service.save(self.first,p['id'],'design:0',{'revision':0,'skill':'# 团队规则','inputs':'风格要求','deliverable':'风格说明'})
        approved=service.decide(self.first,p['id'],'design:0',{'revision':saved['revision'],'action':'approve','reason':'已审核'})
        self.assertEqual(approved['status'],'approved')
        self.assertEqual(approved['skill']['content'],'# 团队规则')
        restored=service.save(self.first,p['id'],'design:0',{'revision':approved['revision'],'skill':None,'deliverable':''})
        self.assertEqual(restored['skill']['content'],original['skill']['content'])
        self.assertEqual(restored['status'],'draft')
        with self.assertRaises(ValueError):
            service.decide(self.first,p['id'],'design:1',{'revision':0,'action':'approve','reason':'无产物'})

    def test_partial_skill_save_keeps_inputs_and_deliverable(self):
        from server.studio_workspaces import Workspaces
        p=self.store.create_project('部分更新',self.first); service=Workspaces(self.store)
        saved=service.save(self.first,p['id'],'product:0',{'revision':0,'inputs':'来源','deliverable':'正文'})
        changed=service.save(self.first,p['id'],'product:0',{'revision':saved['revision'],'skill':'# 规则'})
        self.assertEqual((changed['inputs'],changed['deliverable']),('来源','正文'))
        self.assertEqual(changed['status'],'waiting_user')

    def test_catalog_default_skills_match_department_and_reject_unknown_nodes(self):
        from server.studio_workspaces import Workspaces
        p=self.store.create_project('节点校验',self.first); service=Workspaces(self.store)
        value=service.get(self.first,p['id'],'product:0')
        self.assertIn('市场调研',value['skill']['content'])
        self.assertNotIn('name: TEST_Test_Case',value['skill']['content'])
        with self.assertRaises(ValueError): service.get(self.first,p['id'],'product:99')
        with self.assertRaises(ValueError): service.save(self.first,p['id'],'typo:0',{'revision':0})

    def test_department_defaults_can_be_discovered_under_their_codex_install_names(self):
        import re
        from server.studio_catalog import DEPARTMENTS, default_skill
        for department in DEPARTMENTS:
            if department['id'] == 'testing':
                continue  # User-owned local testing Skills remain verbatim.
            for index in range(len(department['nodes'])):
                with self.subTest(department=department['id'], index=index):
                    skill = default_skill(f"{department['id']}:{index}")
                    name = re.search(r'^name: (.+)$', skill['content'], re.MULTILINE).group(1)
                    self.assertRegex(name, r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
                    self.assertEqual(name, f"studioflow-{department['id']}-{index+1}")
                    self.assertEqual(skill['name'], name)

    def test_visits_and_preferences_restore_project_in_each_studio(self):
        second=self.store.create_studio('另一个工作室')['id']
        p=self.store.create_project('项目一',self.first)
        q=self.store.create_project('项目二',second)
        self.store.enter_project(self.first,p['id'])
        self.store.enter_project(second,q['id'])
        self.store.enter_studio(self.first)
        self.assertEqual(Store(self.path).preferences()['project_id'],p['id'])
        with self.assertRaises(KeyError): self.store.enter_project(self.first,q['id'])
        with self.assertRaises(KeyError): self.store.check_project(self.first,q['id'])

    def test_legacy_migration_keeps_tasks_and_has_foreign_keys(self):
        legacy=Path(self.tmp.name)/'legacy.sqlite'
        with closing(sqlite3.connect(legacy)) as db, db:
            db.executescript("""CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,name_key TEXT NOT NULL UNIQUE,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                INSERT INTO projects(id,name,name_key) VALUES('old','GagaSort','gagasort');
                CREATE TABLE tasks(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),title TEXT NOT NULL,
                    stage INTEGER DEFAULT 0,status TEXT DEFAULT 'waiting_user',revision INTEGER DEFAULT 1,artifacts TEXT DEFAULT '{}');
                INSERT INTO tasks(id,project_id,title) VALUES('old-task','old','旧任务');""")
        migrated=Store(legacy)
        studio=migrated.studios()[0]['id']
        self.assertEqual(migrated.task('old','old-task')['title'],'旧任务')
        self.assertEqual(migrated.projects(studio_id=studio)['items'][0]['id'],'old')
        second=migrated.create_studio('其他工作室')['id']
        migrated.create_project('GagaSort',second)
        with migrated.connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO projects(id,name,name_key,studio_id) VALUES('bad','bad','bad',NULL)")
        self.assertTrue(list(legacy.parent.glob('legacy.before-studio-*.sqlite')))
        self.assertEqual(len(Store(legacy).studios()),2)


if __name__=='__main__': unittest.main()
