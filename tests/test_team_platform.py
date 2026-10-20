"""Team identities and authorization use isolated databases and explicit OAuth fakes."""
import http.cookiejar
import json
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, urlopen
from unittest.mock import patch
from server.store import Store
from server.core.permissions import Policy, AccessDenied
from server.core.admin import Administration
from server.core.auth import Authentication, digest
from server.core.identity import current_user
from server.app import create_server


class TeamPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name+'/db.sqlite');self.p=Policy(self.store)
        self.studio=self.store.studios()[0]['id'];self.project=self.store.create_project('游戏',self.studio)['id'];self.other=self.store.create_project('其他游戏',self.studio)['id']
        with self.store.connection() as db:
            for key,tenant in (('qa1','tenant-a'),('qa2','tenant-b'),('artist','tenant-a')):
                db.execute('INSERT INTO users(id,tenant_key,open_id,name,status) VALUES(?,?,?,?,?)',(key,tenant,key,key,'active'))
        self.admin=Administration(self.store)
        for key,dept in (('qa1','testing'),('qa2','testing'),('artist','design')):
            self.admin.member({'user_id':key,'studio_id':self.studio,'project_id':self.project,'department':dept})

    def tearDown(self):self.temp.cleanup()
    def rule(self,**kw):
        v={'subject_type':'user','subject_id':'qa1','studio_id':self.studio,'project_id':self.project,'department':'testing','node':'testing:0','resource':'node','action':'edit','effect':'deny'};v.update(kw);return self.admin.rule(v)
    def allowed(self,actor,resource='node',action='view',project=None,node='testing:0'):
        return self.p.allowed(resource,action,self.studio,project or self.project,node=node,actor=actor)

    def test_home_preference_never_grants_owner_permissions(self):
        self.store.save_preferences({'active_studio_id':self.studio,'role':'studio_owner'},'qa1')
        self.assertFalse(self.p.allowed('project','create',self.studio,actor='qa1'))
        self.assertFalse(self.p.allowed('studio','create',actor='qa1'))
        self.assertFalse(self.p.allowed('project','create',self.studio,actor='qa1'))
        self.assertFalse(self.allowed('qa1',node='design:0'))
        self.assertTrue(self.allowed('qa1'))

    def test_studio_owner_must_explicitly_delegate_project_lifecycle_permissions(self):
        studio=self.store.create_studio('受控工作室','qa1')['id']
        project=self.store.create_project('受控项目',studio,'qa1')['id']
        self.assertFalse(self.p.allowed('project','create',studio,actor='qa1'))
        self.assertFalse(self.p.allowed('project','delete',studio,project,actor='qa1'))
        self.assertFalse(self.p.allowed('studio','delete',studio,actor='qa1'))
        self.assertFalse(self.p.allowed('gm','execute',studio,project,node='product:0',actor='qa1'))
        self.admin.member({'user_id':'qa2','studio_id':studio,'department':'testing'})
        token=current_user.set('qa1')
        try:
            rule=self.admin.rule({'subject_type':'user','subject_id':'qa2','studio_id':studio,'resource':'project','action':'create','effect':'allow'})
        finally:current_user.reset(token)
        self.assertTrue(self.p.allowed('project','create',studio,actor='qa2'))
        self.admin.revoke(rule['id'])
        self.assertFalse(self.p.allowed('project','create',studio,actor='qa2'))

    def test_project_lead_lifecycle_permissions_stay_inside_assigned_project(self):
        self.admin.member({'user_id':'qa1','studio_id':self.studio,'project_id':self.project,'department':'testing','role':'project_lead'})
        self.assertTrue(self.p.allowed('project','delete',self.studio,self.project,actor='qa1'))
        self.assertFalse(self.p.allowed('project','delete',self.studio,self.other,actor='qa1'))
        self.assertFalse(self.p.allowed('project','create',self.studio,actor='qa1'))
        self.assertFalse(self.p.allowed('studio','create',actor='qa1'))
        self.assertFalse(self.p.allowed('studio','delete',self.studio,actor='qa1'))
        self.assertFalse(self.p.allowed('gm','execute',self.studio,self.project,node='testing:0',actor='qa1'))

    def test_project_membership_does_not_leak_into_other_project(self):
        self.assertFalse(self.allowed('qa1',project=self.other))
        self.assertEqual(self.store.projects(studio_id=self.studio,user_id='qa1')['total'],1)

    def test_explicit_deny_wins_and_revoke_restores_inheritance(self):
        rule=self.rule();self.assertFalse(self.allowed('qa1',action='edit'))
        self.rule(effect='allow');self.assertFalse(self.allowed('qa1',action='edit'))
        self.admin.revoke(rule['id']);self.assertTrue(self.allowed('qa1',action='edit'))

    def test_department_grant_updates_all_current_department_members(self):
        rule=self.rule(subject_type='department',subject_id='testing',resource='skill',action='import',effect='allow')
        self.assertTrue(self.allowed('qa1','skill','import'));self.assertTrue(self.allowed('qa2','skill','import'))
        self.assertFalse(self.allowed('artist','skill','import'))
        self.admin.revoke(rule['id']);self.assertFalse(self.allowed('qa1','skill','import'))

    def test_department_grant_at_studio_scope_covers_department_across_projects(self):
        self.admin.member({'user_id':'qa2','studio_id':self.studio,'project_id':self.other,'department':'testing'})
        rule=self.admin.rule({'subject_type':'department','subject_id':'testing','studio_id':self.studio,
            'department':'testing','resource':'skill','action':'import','effect':'allow'})
        self.assertTrue(self.p.allowed('skill','import',self.studio,self.project,node='testing:2',actor='qa1'))
        self.assertTrue(self.p.allowed('skill','import',self.studio,self.other,node='testing:2',actor='qa2'))
        self.assertFalse(self.p.allowed('skill','import',self.studio,self.other,node='design:0',actor='qa2'))
        self.admin.revoke(rule['id'])
        self.assertFalse(self.p.allowed('skill','import',self.studio,self.other,node='testing:2',actor='qa2'))

    def test_skill_rules_do_not_grant_node_edits(self):
        self.rule(resource='skill',action='import',effect='allow');self.rule(action='edit',effect='deny')
        self.assertTrue(self.allowed('qa1','skill','import'));self.assertFalse(self.allowed('qa1',action='edit'))

    def test_explicit_resource_grants_do_not_leak_between_department_node_and_skill(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) VALUES('auditor','tenant-a','auditor','审计员','active')")
            db.execute('INSERT INTO studio_memberships VALUES(?,?,?)',(self.studio,'auditor','member'))
        value={'subject_type':'user','subject_id':'auditor','studio_id':self.studio,'project_id':self.project,
               'department':'testing','node':'testing:0','resource':'node','action':'edit','effect':'allow'}
        node_rule=self.admin.rule(value)
        self.assertTrue(self.allowed('auditor','node','edit'))
        self.assertFalse(self.allowed('auditor','skill','edit'))
        self.admin.revoke(node_rule['id'])
        self.admin.rule({**value,'node':'','resource':'department'})
        self.assertFalse(self.allowed('auditor','node','edit'))

    def test_member_cannot_promote_self_or_grant_what_they_do_not_have(self):
        token=current_user.set('qa1')
        try:
            with self.assertRaises(PermissionError):self.rule(effect='allow',action='manage',resource='permission')
            with self.assertRaises(PermissionError):self.admin.member({'user_id':'qa1','studio_id':self.studio,'department':'testing','role':'project_lead'})
        finally:current_user.reset(token)

    def test_remove_department_revokes_defaults(self):
        self.admin.member({'user_id':'qa1','studio_id':self.studio,'project_id':self.project,'department':'testing','remove':True})
        self.assertFalse(self.allowed('qa1'))

    def test_first_approval_sets_the_assigned_department_homepage(self):
        with self.store.connection() as db:db.execute('INSERT INTO users(id,tenant_key,open_id,name,status) VALUES(?,?,?,?,?)',('new-designer','tenant-z','designer','新设计师','pending'))
        self.admin.member({'user_id':'new-designer','studio_id':self.studio,'project_id':self.project,'department':'design'})
        prefs=self.store.preferences('new-designer')
        self.assertEqual((prefs['active_role'],prefs['default_workspace']),('design','design'))
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT status FROM users WHERE id=?',('new-designer',)).fetchone()['status'],'active')

    def test_project_lead_admin_data_stays_inside_the_current_project(self):
        with self.store.connection() as db:db.execute('INSERT INTO users(id,tenant_key,open_id,name,status) VALUES(?,?,?,?,?)',('other-user','tenant-a','private-open-id','其他项目成员','active'))
        self.admin.member({'user_id':'other-user','studio_id':self.studio,'project_id':self.other,'department':'design'})
        self.admin.member({'user_id':'qa1','studio_id':self.studio,'project_id':self.project,'department':'testing','role':'project_lead'})
        token=current_user.set('qa1')
        try:overview=self.admin.overview(self.studio,self.project)
        finally:current_user.reset(token)
        self.assertNotIn('other-user',{u['id'] for u in overview['users']})
        self.assertFalse(any('other-user' in row['detail'] for row in overview['audit']))
        self.assertNotIn('open_id',overview['users'][0])

    def test_only_platform_lead_can_initially_assign_pending_accounts(self):
        studio=self.store.create_studio('新团队','qa1')['id']
        with self.store.connection() as db:db.execute('INSERT INTO users(id,tenant_key,open_id,name,status) VALUES(?,?,?,?,?)',('pending-new','tenant-z','pending','待审批','pending'))
        token=current_user.set('qa1')
        try:
            with self.assertRaisesRegex(PermissionError,'平台负责人首次审批'):
                self.admin.member({'user_id':'pending-new','studio_id':studio,'department':'testing'})
        finally:current_user.reset(token)
        self.admin.member({'user_id':'pending-new','studio_id':studio,'department':'testing'})

    def test_disabled_user_loses_grants_immediately(self):
        self.rule(effect='allow');self.admin.user_status({'user_id':'qa1','status':'disabled'})
        self.assertFalse(self.allowed('qa1'))

    def test_department_assignment_never_reactivates_a_disabled_account(self):
        self.admin.user_status({'user_id':'artist','status':'disabled'})
        self.admin.member({'user_id':'qa1','studio_id':self.studio,'project_id':self.project,
                           'department':'testing','role':'project_lead'})
        token=current_user.set('qa1')
        try:
            with self.assertRaisesRegex(ValueError,'禁用'):
                self.admin.member({'user_id':'artist','studio_id':self.studio,
                                   'project_id':self.project,'department':'design'})
        finally:current_user.reset(token)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM users WHERE id='artist'").fetchone()['status'],'disabled')

    def test_even_platform_lead_must_use_account_status_action_to_reactivate(self):
        self.admin.user_status({'user_id':'artist','status':'disabled'})
        with self.assertRaisesRegex(ValueError,'禁用'):
            self.admin.member({'user_id':'artist','studio_id':self.studio,
                               'project_id':self.project,'department':'design'})
        self.admin.user_status({'user_id':'artist','status':'active'})
        self.admin.member({'user_id':'artist','studio_id':self.studio,
                           'project_id':self.project,'department':'design'})

    def test_disabled_account_membership_can_still_be_removed(self):
        self.admin.user_status({'user_id':'artist','status':'disabled'})
        self.admin.member({'user_id':'artist','studio_id':self.studio,
                           'project_id':self.project,'department':'design','remove':True})
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT status FROM users WHERE id='artist'").fetchone()['status'],'disabled')
            self.assertIsNone(db.execute("SELECT 1 FROM team_members WHERE user_id='artist'").fetchone())

    def test_scope_mismatch_rejected(self):
        with self.assertRaises(ValueError):self.rule(department='design')
        # A Skill rule without a node applies to every node in its selected scope.
        self.rule(resource='skill',node='')
        with self.assertRaisesRegex(ValueError,'GM MCP 仅可授权到明确项目'):
            self.rule(resource='gm',action='execute',node='')

    def test_archive_keeps_history_and_refuses_running_jobs(self):
        task=self.store.create_task(self.project,'旧任务')
        with self.store.connection() as db:db.execute("INSERT INTO jobs(id,project_id,task_id,revision,status) VALUES('running',?,?,1,'running')",(self.project,task['id']))
        with self.assertRaises(ValueError):self.admin.archive(self.studio,self.project,True,'游戏')
        with self.store.connection() as db:db.execute("UPDATE jobs SET status='cancelled'")
        self.admin.archive(self.studio,self.project,True,'游戏')
        self.assertEqual(self.store.projects(studio_id=self.studio)['total'],1)
        self.assertEqual(self.store.task(self.project,task['id'])['id'],task['id'])

    def test_archive_refuses_queued_and_running_department_jobs(self):
        for status in ('queued','running'):
            with self.subTest(status=status):
                with self.store.connection() as db:
                    db.execute('''INSERT INTO department_jobs
                        (id,studio_id,project_id,node,actor,revision,status)
                        VALUES(?,?,?,'product:0','local',0,?)''',
                               ('dept-'+status,self.studio,self.project,status))
                for project,name in ((self.project,'游戏'),('',self.store.studios()[0]['name'])):
                    with self.subTest(project=project),self.assertRaisesRegex(ValueError,'运行中任务'):
                        self.admin.archive(self.studio,project,True,name)
                with self.store.connection() as db:
                    self.assertEqual(db.execute('SELECT archived FROM projects WHERE id=?',(self.project,)).fetchone()['archived'],0)
                    db.execute("UPDATE department_jobs SET status='completed'")
        self.admin.archive(self.studio,self.project,True,'游戏')

    def test_department_adapter_registry_validates_contract_and_duplicates(self):
        from server.core.integrations import AdapterRegistry
        registry=AdapterRegistry()
        self.assertEqual(registry.load_modules().status()[0]['adapter'], 'not_connected')
        class Adapter:
            def execute(self,context):return {'gaps':['fake adapter for contract test']}
        registry.register('product',Adapter());self.assertIsNotNone(registry.get('product:0'))
        self.assertIsNone(registry.get('design:0'))
        with self.assertRaises(ValueError):registry.register('product',Adapter())
        with self.assertRaises(TypeError):registry.register('design',object())


class DepartmentManifestTests(unittest.TestCase):
    def test_each_department_has_codex_scope_rules_and_owned_prefix(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        prefixes = {'product': 'PRODUCT_', 'design': 'DESIGN_', 'development': 'DEV_',
                    'testing': 'QA_', 'growth': 'GROWTH_'}
        for department, prefix in prefixes.items():
            with self.subTest(department=department):
                guide = root / 'departments' / department / 'AGENTS.md'
                self.assertTrue(guide.is_file(), f'missing {guide}')
                text = guide.read_text(encoding='utf-8')
                self.assertIn(prefix, text)
                self.assertIn('不得修改其他部门', text)
                self.assertIn('server/core', text)
                self.assertIn('测试', text)

    def test_department_contract_rejects_missing_home_and_invalid_node_fields(self):
        from pathlib import Path
        from server.studio_catalog import load_departments, MODULE_ROOT
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for source in MODULE_ROOT.iterdir():
                if source.is_dir():
                    target=root/source.name;target.mkdir()
                    (target/'manifest.json').write_bytes((source/'manifest.json').read_bytes())
            manifest_path=root/'product'/'manifest.json'
            value=json.loads(manifest_path.read_text());value.pop('homepage')
            manifest_path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'homepage'):
                load_departments(root)
            value=json.loads((MODULE_ROOT/'product'/'manifest.json').read_text())
            value['nodes'][0][5]=''
            manifest_path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'节点输入输出契约'):
                load_departments(root)

    def test_frontend_entry_is_a_fixed_department_local_module(self):
        from pathlib import Path
        from server.studio_catalog import load_departments, MODULE_ROOT
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for source in MODULE_ROOT.iterdir():
                if source.is_dir():
                    target=root/source.name;target.mkdir()
                    (target/'manifest.json').write_bytes((source/'manifest.json').read_bytes())
            manifest_path=root/'product'/'manifest.json'
            value=json.loads(manifest_path.read_text())
            value['frontend']={'entry':'ui.js'}
            manifest_path.write_text(json.dumps(value))
            self.assertEqual(load_departments(root)[0]['frontend']['entry'],'ui.js')
            for entry in ('../server/app.py','/tmp/ui.js','adapter.py','ui.js?x=1'):
                value['frontend']={'entry':entry}
                manifest_path.write_text(json.dumps(value))
                with self.subTest(entry=entry),self.assertRaisesRegex(ValueError,'前端模块'):
                    load_departments(root)

    def test_department_tool_links_require_https_unique_ids_and_admin_adapter_scope(self):
        from pathlib import Path
        from server.studio_catalog import load_departments, MODULE_ROOT
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for source in MODULE_ROOT.iterdir():
                if source.is_dir():
                    target=root/source.name;target.mkdir()
                    (target/'manifest.json').write_bytes((source/'manifest.json').read_bytes())
            manifest_path=root/'design'/'manifest.json'
            value=json.loads(manifest_path.read_text())
            value['tools']=[{'id':'figma','label':'Figma','url':'https://www.figma.com/'}]
            value['tool_adapters']=[{'id':'figma_ai','label':'Figma AI','status':'unconfigured','credentials':'platform_admin'}]
            manifest_path.write_text(json.dumps(value))
            design=next(d for d in load_departments(root) if d['id']=='design')
            self.assertEqual(design['tools'][0]['url'],'https://www.figma.com/')
            self.assertEqual(design['tool_adapters'][0]['status'],'unconfigured')
            for bad_url in ('javascript:alert(1)','http://example.com','//example.com','https://user:pass@example.com'):
                value['tools'][0]['url']=bad_url
                manifest_path.write_text(json.dumps(value))
                with self.subTest(url=bad_url),self.assertRaisesRegex(ValueError,'工具入口'):
                    load_departments(root)
            value['tools'][0]['url']='https://www.figma.com/'
            value['tool_adapters'][0]['credentials']='browser'
            manifest_path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'工具适配器'):
                load_departments(root)
            value['tool_adapters'][0]['credentials']='platform_admin'
            value['tool_adapters'][0]['status']='connected'
            manifest_path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'工具适配器'):
                load_departments(root)

    def test_non_testing_departments_ship_executor_scaffolds_without_claiming_connection(self):
        from pathlib import Path
        from server.studio_catalog import MODULE_ROOT
        for department in ('product', 'design', 'development', 'growth'):
            with self.subTest(department=department):
                path = MODULE_ROOT / department / 'adapter.py'
                self.assertTrue(path.is_file())
                source = path.read_text(encoding='utf-8')
                self.assertIn('def create_adapter', source)
                self.assertIn('尚未接入', source)


class TeamAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name+'/db.sqlite');self.auth=Authentication(self.store)
        self.auth.save({'mode':'local','client_id':'test-app','client_secret':'fake-secret','public_url':'http://127.0.0.1:8766','allow_all_tenants':True})
    def tearDown(self):self.temp.cleanup()
    def login(self,tenant='enterprise-a',openid='same-app-user'):
        url,browser=self.auth.begin();state=parse_qs(urlsplit(url).query)['state'][0]
        with patch.object(self.auth,'request_json',side_effect=[{'access_token':'fake-access'}, {'data':{'tenant_key':tenant,'open_id':openid,'name':'真实协议替身'}}]):return self.auth.callback(state,'fake-code',browser)
    def test_two_tenants_with_same_open_id_are_distinct_and_pending(self):
        _,a=self.login();_,b=self.login('enterprise-b');self.assertNotEqual(a,b)
        self.assertEqual(self.auth.session(a)['user']['status'],'pending')
        self.assertEqual(self.auth.session(b)['user']['global_role'],'member')
    def test_state_is_browser_bound_single_use_and_expiring(self):
        url,browser=self.auth.begin();state=parse_qs(urlsplit(url).query)['state'][0]
        with self.assertRaises(ValueError):self.auth.callback(state,'fake-code','wrong-browser')
        with self.assertRaises(ValueError):self.auth.callback(state,'fake-code',browser)
        url,browser=self.auth.begin();state=parse_qs(urlsplit(url).query)['state'][0]
        with self.store.connection() as db:db.execute('UPDATE auth_states SET expires=0')
        with self.assertRaises(ValueError):self.auth.callback(state,'fake-code',browser)
    def test_local_fallback_rejects_remote_hosts_forwarding_and_remote_peers(self):
        self.assertEqual(self.auth.identity({'Host':'127.0.0.1:8766'},'127.0.0.1'),'local')
        for headers,peer in [({'Host':'127.0.0.1'},'10.0.0.2'),({'Host':'evil.example'},'127.0.0.1'),({'Host':'127.0.0.1','X-Forwarded-For':'10.0.0.2'},'127.0.0.1')]:
            with self.assertRaises(PermissionError):self.auth.identity(headers,peer)
    def test_credentials_not_exposed_and_private_file_permissions(self):
        self.assertNotIn('fake-secret',json.dumps(self.auth.status(True)))
        self.assertEqual(self.auth.path.stat().st_mode&0o777,0o600)
    def test_tenant_allow_list_is_enforced(self):
        self.auth.save({'client_id':'test-app','public_url':'http://127.0.0.1:8766','allowed_tenants':['only-this']})
        with self.assertRaises(PermissionError):self.login('not-allowed')
    def test_team_enable_requires_explicit_real_owner_and_https(self):
        with self.assertRaises(ValueError):self.auth.save({'mode':'team','client_id':'test-app','public_url':'http://127.0.0.1:8766','allow_all_tenants':True})
        _,actor=self.login();self.auth.promote_owner(actor,True)
        self.auth.save({'mode':'team','client_id':'test-app','public_url':'https://studio.example.com','allow_all_tenants':True})
        with self.assertRaises(PermissionError):self.auth.identity({'Host':'127.0.0.1:8766'},'127.0.0.1')
    def test_logout_and_user_disable_revoke_sessions(self):
        token,actor=self.login();headers={'Host':'studio.example.com','Cookie':'studioflow_session='+token}
        self.assertEqual(self.auth.identity(headers,'10.0.0.2'),actor)
        self.auth.logout(headers)
        with self.assertRaises(PermissionError):self.auth.identity(headers,'10.0.0.2')


class TeamHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=self.temp.name+'/db.sqlite'
        self.store=Store(self.path);self.studio=self.store.studios()[0]['id'];self.project=self.store.create_project('权限验证',self.studio)['id']
        self.task=self.store.create_task(self.project,'隔离任务')['id'];self.policy=Policy(self.store)
        with self.store.connection() as db:
            for key,status in [('qa','active'),('pending','pending')]:
                db.execute('INSERT INTO users(id,tenant_key,open_id,name,status) VALUES(?,?,?,?,?)',(key,'test-tenant',key,key,status))
                db.execute('INSERT INTO auth_sessions VALUES(?,?,?,CURRENT_TIMESTAMP)',(digest('test-session-'+key),key,time.time()+3600))
        Administration(self.store).member({'user_id':'qa','studio_id':self.studio,'project_id':self.project,'department':'testing'})
        self.server=create_server('127.0.0.1',0,self.path,local_development=True);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
        self.root=f'/api/studios/{self.studio}/projects/{self.project}'
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path,body=None,actor='qa'):
        r=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Cookie':'studioflow_session=test-session-'+actor})
        try:response=urlopen(r)
        except HTTPError as e:response=e
        with response:return response.status,json.load(response)
    def test_pending_account_can_read_own_status_but_no_project_or_catalog_data(self):
        self.assertEqual(self.request('/api/auth/session',actor='pending')[1]['user']['status'],'pending')
        for path in ['/api/studios','/api/studio-catalog',self.root+'/tasks']:
            self.assertEqual(self.request(path,actor='pending')[0],403)

    def test_codex_skill_handoff_uses_authenticated_one_time_ticket_without_bridge_cookie(self):
        from urllib.parse import parse_qs, urlsplit
        denied, _ = self.request(self.root+'/tasks/'+self.task+'/codex-handoff?stage=0', {'origin':'https://attacker.example'})
        self.assertEqual(denied, 403)
        preview_code, preview = self.request(self.root+'/tasks/'+self.task+'/codex-handoff?stage=0', {'origin': self.url, 'preview': True})
        self.assertEqual(preview_code, 200)
        self.assertNotIn('uri', preview)
        created, payload = self.request(self.root+'/tasks/'+self.task+'/codex-handoff?stage=0', {'origin': self.url})
        self.assertEqual(created, 200)
        handoff = urlsplit(payload['uri'])
        ticket = parse_qs(handoff.query)['ticket'][0]
        request = Request(self.url+'/api/codex-handoff/redeem', data=json.dumps({
            'ticket': ticket, 'origin': self.url
        }).encode(), headers={'Content-Type':'application/json'})
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)
            result = json.load(response)
        self.assertEqual(result['node'], 'testing:0')
        self.assertEqual(result['prompt'], preview['prompt'])
        self.assertIn('SKILL.md', result['prompt'])
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 403)

    def test_feishu_login_uses_fixed_https_callback_and_secure_state_cookie(self):
        from http.client import HTTPConnection
        auth=Authentication(self.store)
        auth.save({'mode':'local','client_id':'multi-tenant-app','client_secret':'placeholder-secret',
            'public_url':'https://studio.example.com','allow_all_tenants':True})
        connection=HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            connection.request('GET','/auth/feishu/login',headers={'Host':'studio.example.com'})
            response=connection.getresponse();location=response.getheader('Location');cookie=response.getheader('Set-Cookie')
            response.read()
        finally:connection.close()
        self.assertEqual(response.status,302)
        self.assertIn('accounts.feishu.cn/open-apis/authen/v1/authorize?',location)
        self.assertIn('client_id=multi-tenant-app',location)
        self.assertIn('redirect_uri=https%3A%2F%2Fstudio.example.com%2Fauth%2Ffeishu%2Fcallback',location)
        self.assertIn('studioflow_oauth=',cookie)
        for flag in ('HttpOnly','Secure','SameSite=Lax','Max-Age=600'):
            self.assertIn(flag,cookie)
    def test_ui_identity_change_does_not_elevate_old_or_new_endpoints(self):
        self.request('/api/me/preferences',{'active_studio_id':self.studio,'role':'studio_owner'})
        self.assertEqual(self.request('/api/studios',{'name':'不允许创建'})[0],403)
        self.assertEqual(self.request(f'/api/studios/{self.studio}/projects',{'name':'不允许项目'})[0],403)
        self.assertEqual(self.request('/api/projects',{'name':'旧接口也不行'})[0],403)
        self.assertEqual(self.request('/api/admin/overview?studio='+self.studio)[0],403)
        self.assertEqual(self.request(self.root+'/workspace?node=design:0',{'revision':0,'inputs':'越权'})[0],403)

    def test_project_lifecycle_api_enforces_lead_scope_not_ui_role(self):
        self.assertEqual(self.request('/api/studios',{'name':'普通成员不能建工作室'})[0],403)
        self.assertEqual(self.request(f'/api/studios/{self.studio}/projects',{'name':'普通成员不能建项目'})[0],403)
        self.assertEqual(self.request('/api/admin/archive',{'studio_id':self.studio,'project_id':self.project,
            'confirmed':True,'name':'权限验证'})[0],403)
        Administration(self.store).member({'user_id':'qa','studio_id':self.studio,'project_id':self.project,
            'department':'testing','role':'project_lead'})
        self.assertEqual(self.request(f'/api/studios/{self.studio}/projects',{'name':'项目负责人范围外不能建项目'})[0],403)
        self.assertEqual(self.request('/api/studios',{'name':'项目负责人不能建工作室'})[0],403)
        code,result=self.request('/api/admin/archive',{'studio_id':self.studio,'project_id':self.project,
            'confirmed':True,'name':'权限验证'})
        self.assertEqual((code,result['archived']),(200,True))
    def test_legacy_skill_endpoint_and_direct_task_urls_cannot_bypass_policy(self):
        a=self.root+'/tasks/'+self.task+'/node-skill?stage=0';b=f'/api/projects/{self.project}/tasks/{self.task}/node-skill?stage=0'
        for path in (a,b):self.assertEqual(self.request(path,{'revision':1,'content':'# 不允许修改 Skill'})[0],403)
        self.assertEqual(self.request(self.root+'/tasks/'+self.task+'/requirements',{'source':'需求','content':'范围'})[0],403)
        Administration(self.store).rule({'subject_type':'user','subject_id':'qa','studio_id':self.studio,'project_id':self.project,'department':'testing','resource':'content','action':'create','effect':'allow'})
        self.assertEqual(self.request(self.root+'/tasks/'+self.task+'/requirements',{'source':'需求','content':'范围'})[0],201)
    def test_node_revocation_redacts_task_response_and_events(self):
        Administration(self.store).rule({'subject_type':'user','subject_id':'qa','studio_id':self.studio,'project_id':self.project,'department':'testing','node':'testing:0','resource':'node','action':'view','effect':'deny'})
        code,value=self.request(self.root+'/tasks/'+self.task)
        self.assertEqual(code,200);self.assertNotIn('0',value['node_skills']);self.assertEqual(value['requirements'],[])
        self.assertEqual(self.request(self.root+'/tasks/'+self.task+'/requirements',{'source':'x','content':'x'})[0],403)
        # A revoked view also blocks mutation entry points.
    def test_disabled_account_cookie_stops_working(self):
        Administration(self.store).user_status({'user_id':'qa','status':'disabled'})
        # Local fallback is intentional for a local Mac operator, so use a nonlocal Host to verify session invalidation.
        headers={'Host':'studio.example','Cookie':'studioflow_session=test-session-qa'}
        with self.assertRaises(PermissionError):Authentication(self.store).identity(headers,'10.0.0.2')
