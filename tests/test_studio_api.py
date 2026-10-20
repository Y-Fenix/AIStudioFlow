import json
import base64
import io
import zipfile
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from server.app import create_server


class StudioApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = create_server('127.0.0.1', 0, self.temp.name+'/db.sqlite', local_development=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)
        self.first = self.request('/api/studios')[1]['items'][0]['id']

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def request(self, path, body=None):
        req = Request(self.url+path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type':'application/json'})
        try: response = urlopen(req)
        except HTTPError as error: response = error
        with response: return response.status, json.load(response)

    def test_scoped_task_reads_and_writes_reject_wrong_studio(self):
        _, second = self.request('/api/studios', {'name':'第二工作室'})
        _, p = self.request('/api/studios/'+self.first+'/projects', {'name':'游戏'})
        route = '/api/studios/'+self.first+'/projects/'+p['id']
        code, t = self.request(route+'/tasks', {'title':'旧流程'})
        self.assertEqual(code, 201)
        other = '/api/studios/'+second['id']+'/projects/'+p['id']
        self.assertEqual(self.request(other+'/tasks')[0], 404)
        self.assertEqual(self.request(other+'/tasks/'+t['id'])[0], 404)
        self.assertEqual(self.request(other+'/tasks', {'title':'非法写入'})[0], 404)
        self.assertEqual(self.request(other+'/summary')[0], 404)
        self.request('/api/studios/'+second['id']+'/enter', {})
        self.assertEqual(self.request('/api/projects/'+p['id']+'/tasks')[0], 404)
        self.assertEqual(self.request(route+'/tasks/'+t['id'])[0], 200)

    def test_catalog_and_persistent_node_decision(self):
        catalog = self.request('/api/studio-catalog')[1]
        self.assertEqual(sum(len(x['nodes']) for x in catalog['departments']), 22)
        _, p = self.request('/api/studios/'+self.first+'/projects', {'name':'工作区'})
        route = '/api/studios/'+self.first+'/projects/'+p['id']
        code, value = self.request(route+'/workspace?node=product:0', {'revision':0,'inputs':'输入','deliverable':'已核对'})
        self.assertEqual(code, 200)
        code, decided = self.request(route+'/workspace/decision?node=product:0',
            {'revision':value['revision'],'action':'approve','reason':'来源已检查'})
        self.assertEqual(code, 200)
        self.assertEqual(decided['status'],'approved')
        self.assertEqual(self.request(route+'/summary')[1]['nodes'][0]['status'],'approved')
        self.assertEqual(self.request(route+'/workspace?node=product:0', {'revision':0})[0], 400)

    def test_project_node_configuration_http_and_custom_skill_handoff(self):
        _,p=self.request('/api/studios/'+self.first+'/projects',{'name':'可配置节点'})
        route='/api/studios/'+self.first+'/projects/'+p['id']
        path=route+'/nodes?department=design'
        code,value=self.request(path);self.assertEqual(code,200)
        value['nodes'].append({'definition':['额外评审','检查交付证据','评审报告','评审证据','人工确认','输入资料','证据和缺口']})
        code,saved=self.request(path,value);self.assertEqual(code,200)
        key=saved['nodes'][-1]['id']
        self.assertEqual(self.request(path,value)[0],400)
        catalog=self.request(route+'/node-catalog')[1]
        self.assertEqual(next(d for d in catalog['departments'] if d['id']=='design')['node_keys'][-1],key)
        self.assertEqual(self.request(route+'/workspace?node='+key,{'revision':0,'deliverable':'已检查'})[0],200)
        code,preview=self.request(route+'/workspace/codex-handoff?node='+key,{'origin':self.url,'preview':True})
        self.assertEqual(code,200);self.assertIn('人工',preview['prompt'])
        self.assertEqual(self.request(route+'/workspace/execute?node='+key,{'revision':1})[0],400)
        _,other=self.request('/api/studios/'+self.first+'/projects',{'name':'另一个配置'})
        self.assertEqual(self.request('/api/studios/'+self.first+'/projects/'+other['id']+'/workspace?node='+key)[0],403)

    def test_skill_library_http_import_history_and_recycle_lifecycle(self):
        _,p=self.request('/api/studios/'+self.first+'/projects',{'name':'Skill 界面真实 API'})
        root='/api/studios/'+self.first+'/projects/'+p['id'];path=root+'/skills?node=product:0'
        code,initial=self.request(path);self.assertEqual(code,200)
        code,item=self.request(path,{'id':initial['id'],'revision':initial['revision'],'name':'HTTP规则','content':'HTTP正文','note':'API实际导入'})
        self.assertEqual(code,200);self.assertEqual(item['uploader'],'本机负责人')
        self.assertEqual(self.request(root+'/skills')[0],200)
        self.assertEqual(self.request(root+'/skills/'+item['id']+'/export?version=1')[1]['content'],'HTTP正文')
        code,removed=self.request(root+'/skills/trash?node=product:0',{'revision':item['revision'],'confirmed':True})
        self.assertEqual(code,200);self.assertEqual(self.request(path)[1]['status'],'trashed')
        self.assertEqual(len(self.request(root+'/skills/recycle-bin')[1]['items']),1)
        code,restored=self.request(root+'/skills/'+item['id']+'/restore',{'revision':removed['revision']})
        self.assertEqual(code,200);self.assertEqual(restored['skill']['content'],'HTTP正文')
        _,removed=self.request(root+'/skills/trash?node=product:0',{'revision':restored['revision'],'confirmed':True})
        self.assertEqual(self.request(root+'/skills/'+item['id']+'/purge',{'revision':removed['revision'],'confirmed':True})[0],200)
        self.assertEqual(self.request(root+'/skills/'+item['id']+'/export')[0],404)

    def test_department_execution_job_endpoint_reports_idle_and_hides_unknown_jobs(self):
        _, project = self.request('/api/studios/'+self.first+'/projects', {'name':'执行状态'})
        route='/api/studios/'+self.first+'/projects/'+project['id']
        self.assertEqual(self.request(route+'/workspace/job?node=product:0')[1],None)
        self.assertEqual(self.request(route+'/department-jobs/not-a-job')[0],404)

    def test_department_static_route_serves_only_declared_ui_modules(self):
        for department in ('product','design','development','testing','growth'):
            with self.subTest(department=department),urlopen(self.url+f'/departments/{department}/ui.js') as response:
                source=response.read().decode()
                self.assertEqual(response.status,200)
                self.assertTrue(response.headers['Content-Type'].startswith('text/javascript'))
                self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertIn('renderHome',source)
        for path in ('/departments/unknown/ui.js','/departments/product/manifest.json',
                     '/departments/product/../testing/ui.js','/departments/product/ui.js/extra'):
            with self.subTest(path=path),self.assertRaises(HTTPError) as error:
                urlopen(self.url+path)
            self.assertEqual(error.exception.code,404)
            error.exception.close()

    def test_enter_and_identity_restore(self):
        _, p = self.request('/api/studios/'+self.first+'/projects', {'name':'首页'})
        self.assertEqual(self.request('/api/studios/'+self.first+'/projects/'+p['id']+'/enter', {})[0], 200)
        self.request('/api/me/preferences', {'active_studio_id':self.first,'role':'qa'})
        pref = self.request('/api/me/preferences')[1]
        self.assertEqual((pref['default_workspace'],pref['project_id']), ('testing',p['id']))
        self.assertEqual(self.request('/api/me/preferences',{'active_studio_id':self.first,'role':'fake'})[0],400)

    def test_node_input_readers_are_scoped_read_only_and_keep_partial_success(self):
        _, p = self.request('/api/studios/'+self.first+'/projects', {'name':'资料读取'})
        _, other = self.request('/api/studios', {'name':'其他工作室'})
        route = '/api/studios/'+self.first+'/projects/'+p['id']
        wrong = '/api/studios/'+other['id']+'/projects/'+p['id']
        with patch('server.app.LarkClient.requirement', side_effect=[
                ('真实正文', {'revision_id':3, 'source_gaps':[]}), ValueError('无权限')]) as read:
            self.assertEqual(self.request(wrong+'/read-sources', {'links':['https://example.feishu.cn/wiki/good']})[0],404)
            read.assert_not_called()
            code,result=self.request(route+'/read-sources', {'links':[
                'https://example.feishu.cn/wiki/good','https://example.feishu.cn/wiki/good',
                'https://example.feishu.cn/wiki/bad']})
        self.assertEqual(code,200)
        self.assertEqual(read.call_count,2)
        self.assertEqual([r['status'] for r in result['results']],['imported','failed'])
        self.assertEqual(result['results'][0]['content'],'真实正文')
        self.assertEqual(self.request(route+'/summary')[1],{'nodes':[],'tasks':[]})
        self.assertEqual(self.request(route+'/read-sources',{'links':[]})[0],400)
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>文件正文</w:t></w:r></w:p></w:body></w:document>')
        body={'name':'资料.docx','data':base64.b64encode(data.getvalue()).decode()}
        self.assertEqual(self.request(wrong+'/parse-file',body)[0],404)
        code,result=self.request(route+'/parse-file',body)
        self.assertEqual(code,200)
        self.assertIn('文件正文',result['content'])

    def test_project_lookup_restores_a_saved_project_beyond_first_hundred(self):
        from server.store import Store
        store=Store(self.temp.name+'/db.sqlite')
        for i in range(105):
            project=store.create_project('项目'+str(i),self.first)
        store.enter_project(self.first,project['id'])
        route='/api/studios/'+self.first+'/projects/'+project['id']
        self.assertEqual(self.request(route)[1]['id'],project['id'])
        self.assertEqual(self.request('/api/me/preferences')[1]['project_id'],project['id'])
        self.assertEqual(len(self.request('/api/studios/'+self.first+'/projects?size=5&page=2')[1]['items']),5)

    def test_project_picker_search_and_page_api(self):
        from server.store import Store
        store=Store(self.temp.name+'/db.sqlite')
        for i in range(12):store.create_project('常规项目 '+str(i),self.first)
        store.create_project('筛选目标 GagaSort',self.first)
        route='/api/studios/'+self.first+'/projects'
        results=self.request(route+'?size=5&page=1&q='+quote('GagaSort'))[1]
        self.assertEqual(results['total'],1)
        self.assertEqual(results['items'][0]['name'],'筛选目标 GagaSort')
        page=self.request(route+'?size=5&page=2')[1]
        self.assertEqual((page['total'],page['page'],page['size'],len(page['items'])),(13,2,5,5))

    def test_source_switch_can_restore_cli_defaults_without_a_remote_catalog(self):
        self.assertEqual(self.request('/api/ai-models/source',{'source':'custom'})[0],400)
        self.assertEqual(self.request('/api/ai-models/source',{'source':'invalid'})[0],400)
        code,status=self.request('/api/ai-models/custom',{'base_url':'https://example.com/v1',
                    'model':'text-model','api_key':'secret-test-value'})
        self.assertEqual(code,200)
        self.assertNotIn('secret-test-value',json.dumps(status))
        self.assertEqual(status['active_source'],'custom')
        self.assertEqual(self.request('/api/ai-models/source',{'source':'relay'})[1]['active_source'],'relay')
        self.assertEqual(self.request('/api/ai-models/source',{'source':'custom'})[1]['active_source'],'custom')

    def test_frontend_shell_and_test_workbench_are_served(self):
        for path,marker in [('/',b'/studio.js'),('/testing.html',b'/app.js')]:
            with urlopen(self.url+path) as response:
                self.assertEqual(response.status,200)
                self.assertIn(marker,response.read())

    def test_content_management_and_requirement_archive_http(self):
        _,project=self.request('/api/studios/'+self.first+'/projects',{'name':'内容生命周期 HTTP'})
        root='/api/studios/'+self.first+'/projects/'+project['id']
        code,content=self.request(root+'/content',{'revision':0,'action':'create','department':'testing','kind':'note','title':'来源规范','body':'核对版本'})
        self.assertEqual(code,200)
        self.assertEqual(self.request(root+'/content',{'revision':0,'action':'delete','id':content['items'][0]['id']})[0],400)
        _,task=self.request(root+'/tasks',{'title':'来源管理'})
        _,task=self.request(root+'/tasks/'+task['id']+'/requirements',{'source':'来源.txt','content':'真实测试资料'})
        path=root+'/tasks/'+task['id']+'/archive-requirement'
        code,archived=self.request(path,{'requirement_id':task['requirements'][0]['id'],'revision':task['revision'],'archived':True})
        self.assertEqual(code,200);self.assertFalse(archived['requirements'])
        self.assertEqual(archived['archived_requirements'][0]['content'],'真实测试资料')
        code,restored=self.request(path,{'requirement_id':archived['archived_requirements'][0]['id'],'revision':archived['revision'],'archived':False})
        self.assertEqual(code,200);self.assertEqual(len(restored['requirements']),1)
        code,value=self.request(root+'/content',{'revision':content['revision'],'action':'disable','department':'testing'})
        self.assertEqual(code,200)
        self.assertEqual(self.request(root+'/tasks',{'title':'停用后不能新建'})[0],400)
        self.assertEqual(self.request(root+'/tasks/'+task['id'])[0],200,'existing batch still readable')
