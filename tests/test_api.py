import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from server.app import create_server


class ApiTests(unittest.TestCase):
    def test_feishu_batch_keeps_success_and_reports_failures(self):
        _, p = self.request('/api/projects', {'name': '飞书'})
        _, task = self.request('/api/projects/' + p['id'] + '/tasks', {'title': '需求'})
        route = '/api/projects/' + p['id'] + '/tasks/' + task['id']
        good = 'https://example.feishu.cn/wiki/good'
        bad = 'https://example.feishu.cn/wiki/bad'
        metadata = {'revision_id': 12, 'source_gaps': ['尚未完整读取资源：img']}
        with patch('server.app.LarkClient.requirement', side_effect=[('正文', metadata), ValueError('无权限')]) as fetch:
            code, result = self.request(route + '/feishu-requirements', {'links': [good, good, bad]})
        self.assertEqual(code, 200)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([r['status'] for r in result['results']], ['imported', 'failed'])
        saved = self.request(route)[1]['requirements']
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['source'], good)
        self.assertEqual(saved[0]['metadata'], metadata)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.http = create_server('127.0.0.1', 0, self.temp.name + '/db.sqlite', local_development=True)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.http.server_port)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None):
        request = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_projects_tasks_and_rejected_confirmation(self):
        code, p = self.request('/api/projects', {'name': 'A'})
        self.assertEqual(code, 201)
        _, b = self.request('/api/projects', {'name': 'B'})
        _, task = self.request('/api/projects/' + p['id'] + '/tasks', {'title': '测试'})
        self.assertEqual(self.request('/api/projects/' + b['id'] + '/tasks/' + task['id'])[0], 404)
        code, result = self.request('/api/projects/' + p['id'] + '/tasks/' + task['id'] + '/decisions',
                                    {'action': 'confirm', 'revision': 1})
        self.assertEqual(code, 409)
        self.assertIn('产物', result['error'])
        self.assertEqual(self.request('/api/projects?size=5')[1]['total'], 2)
        self.assertEqual(len(self.request('/api/projects/' + p['id'] + '/tasks')[1]['items']), 1)

    def test_requirement_import_over_http(self):
        _, p = self.request('/api/projects', {'name': '需求项目'})
        _, task = self.request('/api/projects/' + p['id'] + '/tasks', {'title': '导入测试'})
        route = '/api/projects/' + p['id'] + '/tasks/' + task['id']
        code, result = self.request(route + '/requirements', {'source': '需求.md', 'content': '首次切换须读取存档'})
        self.assertEqual(code, 201)
        self.assertEqual(result['requirements'][0]['content'], '首次切换须读取存档')
        self.assertEqual(self.request(route)[1]['revision'], result['revision'])
        self.assertEqual(self.request(route + '/requirements', {'source': '空', 'content': ''})[0], 400)

    def test_validation_and_unknown_route(self):
        self.assertEqual(self.request('/api/projects', {'name': ''})[0], 400)
        self.assertEqual(self.request('/api/projects?size=999')[0], 400)
        self.assertEqual(self.request('/api/unknown')[0], 404)

    def test_reviewed_publication_creates_once_and_persists_record_id(self):
        from server.store import Store
        from server.bugs import preview_field_mapping
        store=Store(self.temp.name+'/db.sqlite')
        p=store.create_project('发布测试')['id'];t=store.create_task(p,'提单')['id']
        target={'url':'https://example.feishu.cn/base/base?table=tblFixture','verified':True,
                'base_token':'base','table_id':'tblFixture','fields':[{'id':'description','name':'描述','type':'text'}]}
        drafts=[{'draft_key':'draft','root_cause_id':'root','title':'标题','steps':['操作'],
                 'expected':'正确','actual':'错误','missing':[]}]
        preview=preview_field_mapping(drafts,target,{'description':'full_description'})
        with store.connection() as db:
            db.execute('UPDATE tasks SET stage=4,bug_target=? WHERE id=?',(json.dumps(target),t))
        store.record_artifact(p,t,4,{'drafts':drafts,'field_preview':preview},1)
        route='/api/projects/'+p+'/tasks/'+t
        code,task=self.request(route+'/prepare-bug-publication',{'revision':2,'preview_hash':preview['preview_hash']})
        self.assertEqual(code,200)
        request=task['artifacts']['4']['publication_plan']['requests'][0]
        body={'revision':task['revision'],'preview_hash':preview['preview_hash'],
              'request_hash':request['request_hash'],'confirmed':True}
        with patch('server.app.LarkClient.inspect_bug_target',return_value=target), \
             patch('server.app.LarkClient.create_bug_record',return_value={'record_id_list':['recFixture']}) as create:
            self.assertEqual(self.request(route+'/publish-bug',{**body,'confirmed':False})[0],400)
            code,saved=self.request(route+'/publish-bug',body)
            self.assertEqual(code,200)
            self.assertEqual(saved['artifacts']['4']['publication_ledger'][0]['record_id'],'recFixture')
            self.assertEqual(self.request(route+'/publish-bug',body)[0],400)
            self.assertEqual(create.call_count,1)
        self.assertEqual(self.request(route)[1]['artifacts']['4']['publication_ledger'][0]['status'],'published')

    def test_sync_generation_obeys_saved_custom_choice(self):
        from server.ai_models import ModelSettings,current_selection
        from server.store import Store
        settings=ModelSettings(Store(self.temp.name+'/db.sqlite'))
        settings.save_custom({'base_url':'https://custom.example/v1','model':'custom-model','api_key':'test-key'})
        _,project=self.request('/api/projects',{'name':'选择互斥'})
        _,task=self.request('/api/projects/'+project['id']+'/tasks',{'title':'同步入口'})
        route='/api/projects/'+project['id']+'/tasks/'+task['id']
        def generate(requirements):
            self.assertEqual(current_selection()['source'],'custom')
            self.assertEqual(current_selection()['model'],'custom-model')
            return {'cases':[]}
        with patch.dict('os.environ',{'TESTFLOW_MODEL_PROVIDER':'legacy'}),patch('server.codex_model.CodexModel.generate',side_effect=generate) as model:
            code,result=self.request(route+'/generate',{})
        self.assertEqual(code,200,result)
        model.assert_called_once()
