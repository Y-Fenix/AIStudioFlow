"""Real SQLite lifecycle and authorization; no AI or external writes."""
import json
import tempfile
import unittest
from pathlib import Path
from server.store import Store
from server.requirements import validate_cases
from server.core.testing_library import TestingLibrary
from server.core.identity import current_user
from server.core.permissions import AccessDenied

class QA_CaseLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(Path(self.tmp.name)/'test.sqlite');self.studio=self.s.studios()[0]['id']
        self.p=self.s.create_project('案例库')['id'];self.lib=TestingLibrary(self.s)

    def generated(self,title='旧批次'):
        t=self.s.create_task(self.p,title);t=self.s.import_requirement(self.p,t['id'],'需求','奖励只能领取一次')
        rid=t['requirements'][0]['id']
        a=validate_cases({'points':[{'id':'P','title':'领取','requirement_id':rid,'quote':'奖励只能领取一次'}],
          'cases':[{'id':'C','title':'重复领取','point_ids':['P'],'preconditions':['已经领取'],
          'steps':[{'action':'再次领取','expected':'没有额外奖励'}]}],'gaps':[],'ambiguities':[]},t['requirements'])
        return self.s.record_artifact(self.p,t['id'],0,a)

    def test_generated_draft_automatically_saved_and_read_is_pure(self):
        t=self.generated();items=self.lib.listing(self.studio,self.p)['items']
        self.assertEqual(len(items),1);self.assertEqual(items[0]['case_status'],'draft')
        self.assertIsNone(items[0]['version_id']);self.assertEqual(items[0]['case_count'],1)
        before=self.s.task(self.p,t['id']);self.lib.listing(self.studio,self.p)
        self.assertEqual(before,self.s.task(self.p,t['id']))

    def test_versions_and_new_batch_leave_old_task_untouched(self):
        old=self.generated();before=self.s.task(self.p,old['id'])
        t=self.lib.create_batch(self.studio,self.p,{'title':'新版本','version_name':'1.1.0'})
        self.assertEqual(t['stage'],0);self.assertEqual(t['artifacts'],{});self.assertEqual(t['requirements'],[])
        self.assertEqual(t['version']['name'],'1.1.0');self.assertEqual(self.s.task(self.p,old['id']),before)
        self.assertEqual(self.s.task(self.p,t['id'])['version']['name'],'1.1.0')
        with self.assertRaises(ValueError):self.lib.create_version(self.studio,self.p,'1.1.0')

    def test_confirm_and_edit_produce_immutable_history(self):
        t=self.generated();original=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        # Production review gate remains in force, explicitly save review as API does.
        from server.requirements import review_cases
        a=t['artifacts']['0'];a['user_review']=review_cases(a,t['requirements'],[],True)
        t=self.s.record_artifact(self.p,t['id'],0,a)
        t=self.s.decide(self.p,t['id'],'confirm',t['revision'])
        entry=self.lib.listing(self.studio,self.p)['items'][0];self.assertEqual(entry['case_status'],'confirmed')
        confirmed=entry['snapshot_id']
        t=self.s.edit_case(self.p,t['id'],'C',{'title':'修改后的标题','preconditions':['已经领取'],
            'steps':[{'action':'再次领取','expected':'没有额外奖励'}]},t['revision'])
        self.assertEqual(self.lib.listing(self.studio,self.p)['items'][0]['case_status'],'draft')
        old=self.lib.detail(self.studio,self.p,confirmed)
        self.assertEqual(old['artifact']['cases'][0]['title'],'重复领取');self.assertEqual(old['case_status'],'confirmed')
        self.assertEqual(self.lib.detail(self.studio,self.p,original)['case_status'],'draft')

    def test_copy_is_independent_draft_with_remapped_sources_and_no_results(self):
        t=self.generated();snap=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        copied=self.lib.create_batch(self.studio,self.p,{'title':'复制版本','version_name':'1.2.0','snapshot_id':snap})
        self.assertEqual(set(copied['artifacts']),{'0'});self.assertEqual(copied['binding'],{})
        self.assertEqual(copied['attribution'],{});self.assertEqual(copied['regression'],{})
        self.assertEqual(copied['stage'],0);self.assertFalse(copied['automation']['enabled'])
        self.assertNotIn('user_review',copied['artifacts']['0'])
        self.assertNotEqual(copied['requirements'][0]['id'],t['requirements'][0]['id'])
        self.assertEqual(copied['artifacts']['0']['points'][0]['requirement_id'],copied['requirements'][0]['id'])
        self.assertEqual(self.lib.listing(self.studio,self.p,version_id=copied['version']['id'])['total'],1)

    def test_cross_project_and_version_mismatch_and_invalid_requests_rollback(self):
        t=self.generated();snap=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        p2=self.s.create_project('其他项目')['id'];v=self.lib.create_version(self.studio,p2,'2.0')
        for payload in ({'title':'非法','version_id':v['id']},{'title':'非法','version_name':'9.0','snapshot_id':'missing'}):
            with self.assertRaises((KeyError,ValueError)):self.lib.create_batch(self.studio,self.p,payload)
        self.assertEqual(self.lib.versions(self.studio,self.p)['items'],[])
        with self.assertRaises(KeyError):self.lib.detail(self.studio,p2,snap)
        with self.assertRaises(ValueError):self.lib.listing(self.studio,self.p,size=7)
        self.assertEqual(len(self.s.tasks(self.p)),1)

    def test_pagination_search_status_and_restart_persistence(self):
        for i in range(12):self.generated('边界 '+str(i))
        first=self.lib.listing(self.studio,self.p,size=10)
        self.assertEqual(first['total'],12);self.assertEqual(len(first['items']),10)
        self.assertEqual(len(self.lib.listing(self.studio,self.p,size=10,page=2)['items']),2)
        self.assertEqual(self.lib.listing(self.studio,self.p,q='边界 11')['total'],1)
        self.assertEqual(self.lib.listing(self.studio,self.p,status='confirmed')['total'],0)
        s=Store(self.s.path);self.assertEqual(TestingLibrary(s).listing(self.studio,self.p)['total'],12)

    def test_inactive_actor_and_viewer_cannot_write_or_copy(self):
        self.generated()
        with self.s.connection() as db:
            db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) VALUES('viewer','local','viewer','只读','active')")
            db.execute("INSERT INTO studio_memberships(studio_id,user_id,role) VALUES(?,'viewer','member')",(self.studio,))
        token=current_user.set('viewer')
        try:
            with self.assertRaises(AccessDenied):self.lib.listing(self.studio,self.p)
            with self.assertRaises(AccessDenied):self.lib.create_batch(self.studio,self.p,{'title':'不可创建','version_name':'1.0'})
        finally:current_user.reset(token)

    def test_migration_backfills_existing_cases_only_once(self):
        t=self.generated()
        with self.s.connection() as db:db.execute('DELETE FROM testing_case_snapshots');db.execute("DELETE FROM testing_library_meta WHERE key='backfilled'")
        restarted=Store(self.s.path);lib=TestingLibrary(restarted)
        self.assertEqual(lib.listing(self.studio,self.p)['total'],1)
        self.assertEqual(lib.detail(self.studio,self.p,lib.listing(self.studio,self.p)['items'][0]['snapshot_id'])['capture_kind'],'migration')
        before=self.s.task(self.p,t['id']);Store(self.s.path)
        self.assertEqual(before,self.s.task(self.p,t['id']))

    def test_version_assignment_changes_only_membership_and_snapshots_keep_old_version(self):
        t=self.generated();before=t['artifacts'];original=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        changed=self.lib.assign_version(self.studio,self.p,t['id'],{'version_name':'1.0.0','revision':t['revision']})
        self.assertEqual(changed['version']['name'],'1.0.0');self.assertEqual(changed['artifacts'],before)
        self.assertIsNone(self.lib.detail(self.studio,self.p,original)['version'])
        with self.assertRaises(ValueError):self.lib.assign_version(self.studio,self.p,t['id'],{'version_name':'bad','revision':t['revision']})
        self.assertEqual(len(self.lib.versions(self.studio,self.p)['items']),1)

    def test_finished_generation_saves_actual_skill_but_failed_or_stale_does_not(self):
        t=self.generated();snap=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id'];a=t['artifacts']['0']
        actual={'name':'生成时的 Skill','content':'captured execution skill'}
        queued=self.s.enqueue_generation(self.p,t['id']);job=self.s.claim_generation()
        self.assertEqual(job['id'],queued['id']);a['cases'][0]['title']='第二次生成'
        self.s.finish_generation(job,artifact=a,skill_snapshot=actual)
        newest=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        self.assertNotEqual(newest,snap);self.assertEqual(self.lib.detail(self.studio,self.p,newest)['skill'],actual)
        self.s.enqueue_generation(self.p,t['id']);job=self.s.claim_generation();self.s.finish_generation(job,error='失败样例')
        self.assertEqual(self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id'],newest)
        self.s.enqueue_generation(self.p,t['id']);job=self.s.claim_generation()
        self.s.import_requirement(self.p,t['id'],'需求','奖励只能领取两次')
        self.s.finish_generation(job,artifact=a,skill_snapshot=actual)
        self.assertEqual(self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id'],newest)

    def test_unknown_legacy_skill_requires_explicit_consent_and_copy_keeps_audit(self):
        t=self.generated()
        with self.s.connection() as db:db.execute('DELETE FROM testing_case_snapshots');db.execute("DELETE FROM testing_library_meta WHERE key='backfilled'")
        Store(self.s.path);snap=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        body={'title':'旧用例复用','version_name':'1.1.0','snapshot_id':snap}
        with self.assertRaisesRegex(ValueError,'明确同意'):self.lib.create_batch(self.studio,self.p,body)
        copied=self.lib.create_batch(self.studio,self.p,{**body,'use_current_skill':True})
        self.assertTrue(copied['node_skills']['0']['content']);self.assertEqual(copied['artifacts']['0']['copied_from_snapshot'],snap)
        with self.s.connection() as db:
            row=db.execute('SELECT uploader_id FROM skill_library WHERE task_id=?',(copied['id'],)).fetchone()
        self.assertEqual(row['uploader_id'],'local')

    def test_readonly_grants_filter_skill_and_baseline_and_deny_copy(self):
        t=self.generated();snap=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        with self.s.connection() as db:
            db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) VALUES('reader','local','reader','查看者','active')")
            db.execute("INSERT INTO studio_memberships(studio_id,user_id,role) VALUES(?,'reader','member')",(self.studio,))
            db.execute("INSERT INTO permission_rules(id,subject_type,subject_id,studio_id,project_id,department,node,resource,action,effect,created_by) VALUES('r','user','reader',?,?,'testing','testing:0','node','view','allow','local')",(self.studio,self.p))
        token=current_user.set('reader')
        try:
            self.assertEqual(self.lib.listing(self.studio,self.p)['total'],1)
            detail=self.lib.detail(self.studio,self.p,snap);self.assertEqual(detail['skill']['content'],'');self.assertEqual(detail['baseline'],{})
            with self.assertRaises(AccessDenied):self.lib.create_batch(self.studio,self.p,{'title':'不允许','version_name':'1','snapshot_id':snap})
            with self.assertRaises(AccessDenied):self.lib.delete_preview(self.studio,self.p,'batch',t['id'])
            with self.assertRaises(AccessDenied):self.lib.set_unassigned_version(self.studio,self.p,{'version_name':'越权'})
            with self.assertRaises(AccessDenied):self.lib.rename_batch(self.studio,self.p,t['id'],{'title':'越权','expected_title':t['title']})
            with self.assertRaises(AccessDenied):self.lib.rename_version(self.studio,self.p,'any',{'name':'越权','expected_name':'旧名称'})
        finally:current_user.reset(token)

    def test_http_routes_legacy_and_studio_scope_use_same_authentication(self):
        import threading
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        from server.app import create_server
        self.generated();server=create_server(port=0,database=self.s.path,local_development=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            root=f'http://127.0.0.1:{server.server_port}'
            def request(path,body=None):
                try:
                    with urlopen(Request(root+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})) as r:return r.status,json.load(r)
                except HTTPError as r:
                    with r:return r.code,json.load(r)
            legacy='/api/projects/'+self.p+'/testing-library'
            scoped='/api/studios/'+self.studio+'/projects/'+self.p+'/testing-library'
            self.assertEqual(request(legacy+'/cases')[1]['total'],1)
            self.assertEqual(request(scoped+'/cases')[1]['total'],1)
            code,t=request(scoped+'/batches',{'title':'新版本','version_name':'2.0.0'});self.assertEqual(code,200);self.assertEqual(t['version']['name'],'2.0.0')
            self.assertEqual(request(scoped+'/versions/'+t['version']['id']+'/rename',{'name':'2.0.1','expected_name':'2.0.0'})[1]['name'],'2.0.1')
            self.assertEqual(request(scoped+'/batches/'+t['id']+'/rename',{'title':'新版批次','expected_title':'新版本'})[1]['title'],'新版批次')
            self.assertEqual(request(scoped+'/batches?version='+t['version']['id'])[1]['items'][0]['title'],'新版批次')
            assigned=request(scoped+'/unassigned-version',{'version_id':t['version']['id']})
            self.assertEqual(assigned[0],200);self.assertEqual(assigned[1]['count'],1)
            preview=request(scoped+'/batches/'+t['id']+'/delete-preview')[1]
            self.assertEqual(request(scoped+'/batches/'+t['id']+'/delete',{'token':preview['token']})[0],400)
            self.assertEqual(request(scoped+'/batches/'+t['id']+'/delete',{'confirmed':True,'token':preview['token']})[0],200)
            self.assertEqual(request(scoped+'/batches/'+t['id']+'/rename',{'title':'复活','expected_title':'新版批次'})[0],404)
            self.assertEqual(request(scoped+'/cases?size=7')[0],400)
            self.assertEqual(request(scoped+'/cases/missing')[0],404)
            self.assertEqual(request(scoped+'/cases',{'pretend':'write'})[0],404)
        finally:server.shutdown();server.server_close();thread.join()

    def test_rename_version_updates_batches_but_never_rewrites_snapshot(self):
        v=self.lib.create_version(self.studio,self.p,'1.7.0')
        t=self.generated();t=self.lib.assign_version(self.studio,self.p,t['id'],{'version_id':v['id'],'revision':t['revision']})
        snap=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        empty=self.lib.create_batch(self.studio,self.p,{'title':'空批次','version_id':v['id']})
        result=self.lib.rename_version(self.studio,self.p,v['id'],{'name':'1.7.1','expected_name':'1.7.0'})
        self.assertEqual(result['name'],'1.7.1')
        self.assertEqual(self.s.task(self.p,t['id'])['version']['name'],'1.7.1')
        self.assertEqual(self.lib.detail(self.studio,self.p,snap)['version']['name'],'1.7.0')
        versions=self.lib.versions(self.studio,self.p)['items'];self.assertEqual(versions[0]['batch_count'],2)
        batches=self.lib.batches(self.studio,self.p,v['id'])['items'];self.assertEqual(len(batches),2)
        self.assertIn(empty['id'],[b['id'] for b in batches])
        with self.assertRaisesRegex(ValueError,'已变化'):self.lib.rename_version(self.studio,self.p,v['id'],{'name':'1.7.2','expected_name':'1.7.0'})
        self.lib.create_version(self.studio,self.p,'2.0')
        with self.assertRaisesRegex(ValueError,'已存在'):self.lib.rename_version(self.studio,self.p,v['id'],{'name':'2.0','expected_name':'1.7.1'})
        other=self.s.create_project('越权项目')['id']
        with self.assertRaises(KeyError):self.lib.rename_version(self.studio,other,v['id'],{'name':'x','expected_name':'1.7.1'})

    def test_batch_rename_is_metadata_only_and_optimistic(self):
        t=self.generated();before=self.s.task(self.p,t['id'])
        self.lib.rename_batch(self.studio,self.p,t['id'],{'title':'奖励回归 · 第 2 轮','expected_title':t['title']})
        after=self.s.task(self.p,t['id']);self.assertEqual(after['title'],'奖励回归 · 第 2 轮')
        for key in ('revision','artifacts','stage','binding','node_skills'):self.assertEqual(after[key],before[key])
        with self.assertRaisesRegex(ValueError,'已变化'):self.lib.rename_batch(self.studio,self.p,t['id'],{'title':'覆盖他人更新','expected_title':t['title']})
        with self.assertRaises(ValueError):self.lib.rename_batch(self.studio,self.p,t['id'],{'title':' ','expected_title':after['title']})

    def test_unassigned_project_version_does_not_depend_on_batch_title(self):
        t=self.generated();empty=self.s.create_task(self.p,'历史批次')
        result=self.lib.set_unassigned_version(self.studio,self.p,{'version_name':'v1.7.0'})
        self.assertEqual(result['count'],2)
        self.assertEqual(self.s.task(self.p,t['id'])['version']['name'],'v1.7.0')
        self.assertEqual(self.s.task(self.p,empty['id'])['title'],'历史批次')

    def test_delete_version_keeps_batches_unassigned_and_history_unchanged(self):
        t=self.generated();t=self.lib.assign_version(self.studio,self.p,t['id'],{'version_name':'1.0','revision':t['revision']})
        v=t['version']['id'];snap=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        preview=self.lib.delete_preview(self.studio,self.p,'version',v)
        with self.assertRaises(ValueError):self.lib.delete(self.studio,self.p,'version',v,{'token':preview['token']})
        self.lib.delete(self.studio,self.p,'version',v,{'confirmed':True,'token':preview['token']})
        self.assertEqual(self.lib.versions(self.studio,self.p)['items'],[])
        self.assertIsNone(self.s.task(self.p,t['id'])['version'])
        self.assertEqual(self.lib.detail(self.studio,self.p,snap)['version']['name'],'1.0')
        with self.assertRaises(KeyError):self.lib.create_batch(self.studio,self.p,{'title':'非法','version_id':v})
        self.assertEqual(self.lib.create_version(self.studio,self.p,'1.0')['name'],'1.0')

    def test_delete_batch_blocks_stale_busy_and_preserves_records(self):
        t=self.generated();snap=self.lib.listing(self.studio,self.p)['items'][0]['snapshot_id']
        preview=self.lib.delete_preview(self.studio,self.p,'batch',t['id'])
        self.s.enqueue_generation(self.p,t['id'])
        with self.assertRaisesRegex(ValueError,'运行|排队'):self.lib.delete(self.studio,self.p,'batch',t['id'],{'confirmed':True,'token':preview['token']})
        with self.s.connection() as db:db.execute("UPDATE jobs SET status='failed' WHERE task_id=?",(t['id'],))
        self.lib.rename_batch(self.studio,self.p,t['id'],{'title':'改名','expected_title':t['title']})
        with self.assertRaisesRegex(ValueError,'变化'):self.lib.delete(self.studio,self.p,'batch',t['id'],{'confirmed':True,'token':preview['token']})
        preview=self.lib.delete_preview(self.studio,self.p,'batch',t['id'])
        self.lib.delete(self.studio,self.p,'batch',t['id'],{'confirmed':True,'token':preview['token']})
        from server.studio_workspaces import Workspaces
        self.assertEqual(Workspaces(self.s).summary(self.studio,self.p)['tasks'],[])
        self.assertEqual(self.s.tasks(self.p),[]);self.assertEqual(self.lib.listing(self.studio,self.p)['total'],0)
        with self.assertRaises(KeyError):self.s.task(self.p,t['id'])
        with self.s.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM testing_case_snapshots WHERE id=?',(snap,)).fetchone()[0],1)

    def test_delete_version_rechecks_batch_scope_and_project(self):
        t=self.lib.create_batch(self.studio,self.p,{'title':'一','version_name':'1'})
        v=t['version']['id'];preview=self.lib.delete_preview(self.studio,self.p,'version',v)
        self.lib.create_batch(self.studio,self.p,{'title':'二','version_id':v})
        with self.assertRaisesRegex(ValueError,'变化'):self.lib.delete(self.studio,self.p,'version',v,{'confirmed':True,'token':preview['token']})
        other=self.s.create_project('其他')['id']
        with self.assertRaises(KeyError):self.lib.delete_preview(self.studio,other,'version',v)
        with self.assertRaises(KeyError):self.lib.delete_preview(self.studio,other,'batch',t['id'])

    def test_delete_permissions_do_not_require_create_permission(self):
        t=self.generated()
        with self.s.connection() as db:
            db.execute("INSERT INTO users(id,tenant_key,open_id,name,status) VALUES('deleter','local','deleter','删除者','active')")
            db.execute("INSERT INTO studio_memberships(studio_id,user_id,role) VALUES(?,'deleter','member')",(self.studio,))
            for n,(resource,action) in enumerate([('node','view'),('node','delete'),('content','delete')]):
                db.execute("INSERT INTO permission_rules(id,subject_type,subject_id,studio_id,project_id,department,node,resource,action,effect,created_by) VALUES(?,'user','deleter',?,?,'testing',?,?,?,'allow','local')",('delete'+str(n),self.studio,self.p,'testing:0' if resource=='node' else '',resource,action))
        token=current_user.set('deleter')
        try:
            with self.assertRaises(AccessDenied):self.lib.create_version(self.studio,self.p,'不能创建')
            preview=self.lib.delete_preview(self.studio,self.p,'batch',t['id'])
            self.lib.delete(self.studio,self.p,'batch',t['id'],{'confirmed':True,'token':preview['token']})
        finally:current_user.reset(token)
