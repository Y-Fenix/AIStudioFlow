"""Two local data directories and a real central password HTTP service."""
import json
import unittest
from unittest.mock import patch
from tests import test_public_area_http as http_tests
from server.store import Store
from server.studio_workspaces import Workspaces
from server.core.public_area.local import LocalPublic
from server.core.public_area.client import RemoteError, validate_url
from server.core.public_area.service import Conflict

class PublicClientTests(unittest.TestCase):
    setUp=http_tests.PublicHttpTests.setUp
    tearDown=http_tests.PublicHttpTests.tearDown
    req=http_tests.PublicHttpTests.req
    def local(self,name):
        store=Store(self.tmp.name+'/'+name+'/db.sqlite');s=store.studios()[0]['id'];p=store.create_project(name,s)['id']
        w=Workspaces(store);w.save(s,p,'product:0',{'revision':0,'deliverable':'Reviewed result '+name,'inputs':'PRIVATE requirement '+name})
        c=LocalPublic(store);c.connect({'server_url':'http://127.0.0.1:'+str(self.server.server_port),'allow_lan_http':True,'username':'owner','password':'Owner-test-1234'})
        version=self.req(f'/api/studios/{self.studio}/projects/{self.project}/public/versions')[1]['items'][0]['id']
        c.bind(s,p,{'studio_id':self.studio,'project_id':self.project,'version_id':version})
        return store,s,p,c
    def version(self):self.req(f'/api/studios/{self.studio}/projects/{self.project}/public/versions',{'name':'1.0'})
    def test_source_picker_uses_stable_node_definitions(self):
        self.version();a,s,p,c=self.local('picker')
        sources=c.sources(s,p)
        self.assertTrue(any(n['node']=='product:0' and n['department']=='product' and n['title'] for n in sources['nodes']))
        self.assertEqual(sources['tasks'],[])

    def test_two_installations_only_explicit_selected_data_is_shared(self):
        self.version();a,s,p,ca=self.local('a');b,sb,pb,cb=self.local('b')
        preview=ca.preview(s,p,{'source':{'type':'node','node':'product:0'},'title':'A result','description':''})
        self.assertNotIn('PRIVATE',json.dumps(preview));self.assertEqual(ca.remote(s,p,'items')['total'],0)
        result=ca.publish(s,p,preview['id'],True)
        self.assertEqual(result['status'],'published');self.assertEqual(ca.publish(s,p,preview['id'],True),result)
        self.assertEqual(cb.remote(sb,pb,'items')['total'],1)
        copied=cb.copy(sb,pb,result['id'],1)
        self.assertEqual(copied['package']['content'],'Reviewed result a')
        self.assertEqual(Workspaces(b).get(sb,pb,'product:0')['deliverable'],'Reviewed result b')
        Workspaces(a).save(s,p,'product:0',{'revision':1,'deliverable':'New personal result'})
        self.assertEqual(cb.remote(sb,pb,'items/'+result['id'])['package']['content'],'Reviewed result a')
        self.assertNotIn('session',json.dumps(ca.connection()))
    def test_source_change_requires_new_preview_and_offline_is_never_success(self):
        self.version();a,s,p,c=self.local('a')
        draft=c.preview(s,p,{'source':{'type':'node','node':'product:0'},'title':'Draft'})
        with self.assertRaises(ValueError):c.publish(s,p,draft['id'],False)
        Workspaces(a).save(s,p,'product:0',{'revision':1,'deliverable':'Changed'})
        with self.assertRaises(Conflict):c.publish(s,p,draft['id'],True)
        draft=c.preview(s,p,{'source':{'type':'node','node':'product:0'},'title':'Draft'})
        with patch('server.core.public_area.client.Remote.request',side_effect=RemoteError('offline')):
            result=c.publish(s,p,draft['id'],True)
            self.assertEqual(result['status'],'unknown')
        self.assertEqual(c.remote(s,p,'items')['total'],0)
        self.assertEqual(c.publish(s,p,draft['id'],True)['status'],'published')
    def test_lost_commit_response_is_resolved_without_duplicate_revision(self):
        from server.core.public_area.client import Remote
        self.version();a,s,p,c=self.local('a');draft=c.preview(s,p,{'source':{'type':'node','node':'product:0'},'title':'Draft'})
        original=Remote.request
        def lose(remote,path,body=None):
            result=original(remote,path,body)
            if path.endswith('/commit'):raise RemoteError('response lost')
            return result
        with patch.object(Remote,'request',lose):self.assertEqual(c.publish(s,p,draft['id'],True)['status'],'unknown')
        self.assertEqual(c.publish(s,p,draft['id'],True)['status'],'published')
        self.assertEqual(c.remote(s,p,'items')['total'],1)
    def test_opt_in_inputs_and_skill_are_independent(self):
        self.version();a,s,p,c=self.local('a')
        draft=c.preview(s,p,{'source':{'type':'node','node':'product:0'},'title':'With input','include_requirements':True})
        self.assertEqual(draft['package']['includes'],['requirements'])
        self.assertIn('PRIVATE requirement a',json.dumps(draft))
        self.assertNotIn('SKILL.md',json.dumps(draft))

    def test_workflow_preserves_task_instructions_and_opt_in_effective_skills(self):
        from server.core.node_blocks.service import Builder
        self.version();a,s,p,c=self.local('workflow')
        flow=Builder(a).save_flow(s,p,{'name':'Review flow','revision':0,'blocks':[
            {'id':'reference','type':'node','config':{'node':'product:0','inputs':'PRIVATE REF INPUT'}},
            {'id':'custom','type':'task','config':{'inputs':'PRIVATE TASK INPUT','skill':'PRIVATE RULE',
                'blocks':[{'id':'analyse','type':'ai','config':{'prompt':'Review evidence carefully'}}]}}]})
        source={'type':'workflow','node':'product:0','flow_id':flow['id']}
        exported=json.loads(c.snapshot(s,p,source,{})['content'])
        self.assertEqual(exported['blocks'][1]['config']['blocks'][0]['config']['prompt'],'Review evidence carefully')
        self.assertNotIn('PRIVATE',json.dumps(exported));self.assertNotIn('skills',exported)
        opted=json.loads(c.snapshot(s,p,source,{'include_requirements':True,'include_skill':True})['content'])
        self.assertEqual(opted['blocks'][0]['config']['inputs'],'PRIVATE REF INPUT')
        self.assertEqual(opted['skills'][0]['content'],Workspaces(a).get(s,p,'product:0')['skill']['content'])
        self.assertEqual(opted['skills'][1]['content'],'PRIVATE RULE')

    def test_workflow_requires_export_permission_on_each_referenced_node(self):
        from server.core.node_blocks.service import Builder
        self.version();a,s,p,c=self.local('workflow-permission')
        f=Builder(a).save_flow(s,p,{'name':'Cross-node','revision':0,'blocks':[
            {'id':'reference','type':'node','config':{'node':'design:0'}}]})
        original=c.policy.require
        def require(resource,action,**scope):
            if resource=='node' and action=='export' and scope.get('node')=='design:0':raise PermissionError('export denied')
            return original(resource,action,**scope)
        with patch.object(c.policy,'require',side_effect=require):
            with self.assertRaises(PermissionError):c.snapshot(s,p,{'type':'workflow','node':'product:0','flow_id':f['id']},{})

    def test_skill_only_export_has_no_inputs_or_deliverable(self):
        self.version();a,s,p,c=self.local('skill')
        result=c.snapshot(s,p,{'type':'skill','node':'product:0'},{})
        self.assertIn(Workspaces(a).get(s,p,'product:0')['skill']['content'].strip(),result['content'])
        self.assertEqual(result['includes'],['skill']);self.assertNotIn('PRIVATE requirement',result['content'])
        self.assertNotIn('Reviewed result',result['content'])
    def test_qa_exports_selected_result_without_raw_code_or_publication_requests(self):
        self.version();a,s,p,c=self.local('qa')
        task={'id':'batch','revision':3,'requirements':[], 'node_skills':{'1':{'content':'PRIVATE SKILL'}},
              'artifacts':{'1':{'method':'static_code_review','results':[{'id':'R1','status':'failed',
                  'assertions':[{'call_chain':[{'file':'Assets/Game.cs','line':9,'quote':'PRIVATE CODE'}]}]}],
                  'publication_plan':{'requests':['PRIVATE REQUEST']},'unexpected_future_field':'PRIVATE FUTURE',
                  'logs':['PRIVATE LOG'],'scope':'Static only'}}}
        with patch.object(a,'task',return_value=task):
            result=c.snapshot(s,p,{'type':'testing','node':'testing:1','task_id':'batch'},{})
        self.assertIn('Assets/Game.cs',result['content']);self.assertIn('Static only',result['content'])
        self.assertNotIn('PRIVATE',result['content']);self.assertNotIn('quote',result['content'])

    def test_second_approved_account_permissions_and_logged_out_session(self):
        self.version();a,s,p,ca=self.local('author');b,sb,pb,cb=self.local('reader')
        code,registered,_=self.req('/api/auth/register',{'username':'reader','name':'Reader','password':'Reader-test-1234'})
        self.assertEqual(code,201);uid=registered['user']['id']
        self.assertEqual(self.req('/api/admin/members',{'studio_id':self.studio,'project_id':self.project,'department':'product','user_id':uid,'role':'member'})[0],200)
        rules={}
        for action in ('view','export'):
            code,value,_=self.req('/api/admin/rules',{'studio_id':self.studio,'project_id':self.project,'department':'product','node':'',
                'subject_type':'user','subject_id':uid,'resource':'publication','action':action,'effect':'allow'})
            self.assertEqual(code,200);rules[action]=value['id']
        cb.connect({'server_url':'http://127.0.0.1:'+str(self.server.server_port),'allow_lan_http':True,'username':'reader','password':'Reader-test-1234'})
        with self.assertRaises(ValueError):cb.binding(sb,pb) # Switching accounts clears prior mapping.
        cb.bind(sb,pb,{'studio_id':self.studio,'project_id':self.project,'version_id':self.req(f'/api/studios/{self.studio}/projects/{self.project}/public/versions')[1]['items'][0]['id']})
        d=ca.preview(s,p,{'source':{'type':'node','node':'product:0'},'title':'Shared'})
        published=ca.publish(s,p,d['id'],True);item=published['id']
        self.assertEqual(cb.remote(sb,pb,'items')['total'],1)
        self.assertTrue(cb.copy(sb,pb,item,1)['inert'])
        denied=cb.preview(sb,pb,{'source':{'type':'node','node':'product:0'},'title':'Denied'})
        self.assertEqual(cb.publish(sb,pb,denied['id'],True)['status'],'failed')
        self.req('/api/admin/rules/'+rules['view']+'/revoke',{})
        self.assertEqual(cb.remote(sb,pb,'items')['total'],0)
        with self.assertRaises(RemoteError):cb.remote(sb,pb,'items/'+item)
        self.req('/api/admin/rules/'+rules['export']+'/revoke',{})
        with self.assertRaises(RemoteError):cb.copy(sb,pb,item,1)
        cb.client().request('/api/auth/logout',{})
        with self.assertRaises(RemoteError):cb.remote(sb,pb,'items')

    def test_expired_session_preserves_unpublished_local_preview(self):
        self.version();a,s,p,c=self.local('expiry')
        draft=c.preview(s,p,{'source':{'type':'node','node':'product:0'},'title':'Pending'})
        with self.store.connection() as db:db.execute('UPDATE auth_sessions SET expires=0')
        result=c.publish(s,p,draft['id'],True)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(c.draft(s,p,draft['id'])['package']['content'],'Reviewed result expiry')
        with self.store.connection() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM public_items').fetchone()[0],0)
    def test_url_safety_and_server_switch_clears_binding(self):
        for url in ('http://example.com','https://u:p@example.com','https://example.com/path','http://169.254.169.254','file:///tmp/a','https://example.com:99999'):
            with self.subTest(url=url),self.assertRaises(ValueError):validate_url(url,True)
        with self.assertRaises(ValueError):validate_url('http://127.0.0.1:1234',False)
        self.version();a,s,p,c=self.local('a');c.disconnect()
        self.assertFalse(c.connection()['connected'])
        with self.assertRaises(ValueError):c.binding(s,p)
