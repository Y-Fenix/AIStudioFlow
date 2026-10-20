"""本地协议替身验证生成链路，不评估真实模型质量。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import unittest
from tests import test_api


class GenerationTests(unittest.TestCase):
    setUp = test_api.ApiTests.setUp
    tearDown = test_api.ApiTests.tearDown
    request = test_api.ApiTests.request
    def test_generation_roundtrip_and_invalid_quote(self):
        _, project = self.request('/api/projects', {'name': '生成项目'})
        route = '/api/projects/' + project['id'] + '/tasks'
        _, task = self.request(route, {'title': '生成集成验证'})
        route += '/' + task['id']
        _, task = self.request(route + '/requirements', {'source': '设置需求', 'content': '关闭后保存状态'})
        requirement_id = task['requirements'][0]['id']
        output = {'points': [{'id': 'p1', 'title': '保存状态', 'requirement_id': requirement_id,
                              'quote': '关闭后保存状态'}],
                  'cases': [{'id': 'c1', 'title': '关闭后重启', 'point_ids': ['p1'],
                             'preconditions': ['初始开关开启'],
                             'steps': [{'action': '关闭并重启', 'expected': '开关保持关闭'}]}],
                  'gaps': [], 'ambiguities': []}

        class ModelHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if request['messages'][0]['role'] != 'user':
                    self.send_error(400)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                for event in [
                    {'choices':[{'delta':{'content':json.dumps(output)},'finish_reason':None}]},
                    {'choices':[{'delta':{},'finish_reason':'stop'}]}]:
                    self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
                self.wfile.flush()

        model = ThreadingHTTPServer(('127.0.0.1', 0), ModelHandler)
        thread = threading.Thread(target=model.serve_forever, daemon=True)
        thread.start()
        try:
            code, configured = self.request('/api/ai-models/custom', {
                'base_url':f'http://127.0.0.1:{model.server_port}/v1',
                'protocol':'chat','api_key':'test-key','model':'protocol-fixture'})
            self.assertEqual(code,200,configured)
            with patch.dict('os.environ', {'TESTFLOW_MODEL_PROVIDER':'api'}):
                code, generated = self.request(route + '/generate', {})
                self.assertEqual(code, 200)
                self.assertEqual(generated['artifacts']['0']['cases'][0]['title'], '关闭后重启')
                output['points'][0]['quote'] = '虚构正文'
                code, result = self.request(route + '/generate', {})
                self.assertEqual(code, 400)
                self.assertIn('引用不存在', result['error'])
                saved = self.request(route)[1]
                self.assertEqual(saved['revision'], generated['revision'])
                code, reviewed = self.request(route + '/case-review', {'revision':generated['revision'], 'decisions':[], 'decomposition_confirmed':True})
                self.assertEqual(code, 200)
                code, confirmed = self.request(route + '/decisions',
                    {'action': 'confirm', 'revision': reviewed['revision']})
                self.assertEqual(code, 200)
                self.assertEqual(confirmed['stage'], 1)
        finally:
            model.shutdown()
            model.server_close()
            thread.join()
