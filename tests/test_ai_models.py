import json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from server.store import Store

class AIModelTests(unittest.TestCase):
 def test_discovery_capabilities_save_and_scope(self):
  from server.ai_models import ModelSettings,selection_scope,current_selection
  from server.responses_model import Connection
  with tempfile.TemporaryDirectory() as d:
   settings=ModelSettings(Store(Path(d)/'db'))
   response={'data':[{'id':'reasoner','supported_reasoning_efforts':['low','medium','high']},{'id':'plain'}]}
   with patch('server.ai_models.configured_connection',return_value=Connection('https://example.test/v1/responses','secret')),patch('server.ai_models.fetch_models',return_value=response):
    catalog=settings.discover()
    self.assertEqual(catalog['models'][0]['efforts'],['low','medium','high'])
    self.assertEqual(catalog['models'][1]['efforts'],[])
    self.assertNotIn('secret',json.dumps(catalog))
    selected=settings.save({'model':'reasoner','effort':'medium'})
    self.assertEqual(ModelSettings(Store(Path(d)/'db')).selection(),selected)
    with selection_scope(selected):self.assertEqual(current_selection()['effort'],'medium')
    self.assertIsNone(current_selection())
    with self.assertRaises(ValueError):settings.save({'model':'plain','effort':'high'})
    with self.assertRaises(ValueError):settings.save({'model':'invented','effort':None})
 def test_selected_model_and_effort_reach_actual_transport(self):
  from server.ai_models import selection_scope
  from server.codex_model import CodexModel
  from server.responses_model import Connection
  with selection_scope({'model':'selected-model','effort':'medium'}),patch('server.responses_model.configured_connection',return_value=Connection('https://example.test/v1/responses','key')),patch('server.responses_model.request_json',return_value={'ok':True}) as request:
   self.assertEqual(CodexModel().request_json('test'),{'ok':True})
   self.assertEqual(request.call_args.args[2:4],('selected-model','medium'))
 def test_discovery_marks_protocol_fallback_and_disables_images(self):
  from server.ai_models import ModelSettings
  from server.responses_model import Connection
  with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'CODEX_HOME':d}):
   settings=ModelSettings(Store(Path(d)/'db'))
   with patch('server.ai_models.configured_connection',return_value=Connection('https://example.test/v1/responses','key')),patch('server.ai_models.fetch_models',return_value={'data':[{'id':'text-model','supported_endpoint_types':['openai-response']},{'id':'gpt-image-2','supported_endpoint_types':['openai-response']}]}):
    rows=settings.discover()['models']
    self.assertEqual(rows[0]['efforts'],['low','medium','high'])
    self.assertIn('未确认',rows[0]['capability_source'])
    with self.assertRaises(ValueError):settings.save({'model':'gpt-image-2'})
 def test_custom_file_persistence_redaction_and_runtime_connection(self):
  from server.ai_models import ModelSettings
  with tempfile.TemporaryDirectory() as d:
   settings=ModelSettings(Store(Path(d)/'db'))
   result=settings.save_custom({'base_url':'http://127.0.0.1:9999/v1','api_key':'private-token','model':'my-model','effort':'high','protocol':'responses'})
   self.assertTrue(Path(result['config_file']).exists())
   self.assertEqual(Path(result['config_file']).stat().st_mode & 0o777,0o600)
   self.assertNotIn('private-token',json.dumps(settings.status()))
   self.assertEqual(settings.runtime_selection()['api_key'],'private-token')
   settings.save_custom({'base_url':'http://127.0.0.1:9999/v1','api_key':'','model':'other','effort':None,'protocol':'responses'})
   self.assertEqual(settings.runtime_selection()['api_key'],'private-token')
   with self.assertRaises(ValueError):settings.save_custom({'base_url':'http://public.example/v1','model':'x'})
 def test_custom_chat_transport_with_real_local_http(self):
  import threading
  from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
  from server.codex_model import CodexModel
  from server.ai_models import selection_scope
  seen=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    seen.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
    self.send_response(200);self.end_headers()
    for event in [{'choices':[{'delta':{'content':'{"ok":true}'},'finish_reason':None}]},{'choices':[{'delta':{},'finish_reason':'stop'}]}]:self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with selection_scope({'source':'custom','base_url':'http://127.0.0.1:'+str(server.server_port)+'/v1','protocol':'chat','api_key':'test-secret','model':'custom-chat','effort':'low'}):
    self.assertEqual(CodexModel().request_json('return JSON'),{'ok':True})
   self.assertEqual(seen[0][0],'/v1/chat/completions');self.assertEqual(seen[0][1]['reasoning_effort'],'low');self.assertEqual(seen[0][1]['model'],'custom-chat')
  finally:server.shutdown();server.server_close();thread.join()
 def test_sources_are_exclusive_and_running_snapshot_does_not_change(self):
  from server.ai_models import ModelSettings,selection_scope,current_selection
  from server.codex_model import CodexModel,GatewayFailure
  from server.responses_model import Connection
  with tempfile.TemporaryDirectory() as d:
   settings=ModelSettings(Store(Path(d)/'db'))
   settings.write('catalog',{'models':[{'id':'relay-model','efforts':['high'],'usable':True}]})
   settings.save({'model':'relay-model','effort':'high'})
   settings.save_custom({'base_url':'https://custom.example/v1','api_key':'test-key','model':'custom-model','protocol':'chat'})
   snapshot=settings.runtime_selection()
   with selection_scope(snapshot),patch('server.responses_model.configured_connection') as relay,patch('server.responses_model.request_json',return_value={'ok':True}) as request:
    settings.save({'model':'relay-model','effort':'high'})
    self.assertEqual(current_selection()['source'],'custom')
    CodexModel().request_json('JSON')
    relay.assert_not_called()
    self.assertEqual(request.call_count,1)
    self.assertEqual(request.call_args.args[0].endpoint,'https://custom.example/v1/chat/completions')
   next_selection=settings.runtime_selection()
   self.assertEqual(next_selection['source'],'relay')
   with selection_scope(next_selection),patch('server.responses_model.configured_connection',return_value=Connection('https://relay.example/v1/responses','relay-key')),patch('server.responses_model.request_json',return_value={'ok':True}) as request:
    CodexModel().request_json('JSON')
    self.assertEqual(request.call_count,1)
    self.assertEqual(request.call_args.args[0].endpoint,'https://relay.example/v1/responses')
   with selection_scope(snapshot),patch('server.responses_model.configured_connection') as relay,patch('server.responses_model.request_json',side_effect=GatewayFailure('认证失败',retryable=False)) as request:
    with self.assertRaisesRegex(ValueError,'认证失败'):CodexModel().request_json('JSON')
    relay.assert_not_called();self.assertEqual(request.call_count,1)
 def test_missing_custom_and_invalid_source_fail_without_fallback(self):
  from server.ai_models import ModelSettings
  with tempfile.TemporaryDirectory() as d:
   settings=ModelSettings(Store(Path(d)/'db'))
   settings.write('active_source','custom')
   with self.assertRaisesRegex(ValueError,'配置文件不存在'):settings.runtime_selection()
   settings.write('active_source','unknown')
   with self.assertRaisesRegex(ValueError,'模型来源'):settings.runtime_selection()
 def test_saved_ui_choice_has_priority_over_legacy_provider(self):
  from server.ai_models import ModelSettings
  from server.codex_model import CodexModel
  with tempfile.TemporaryDirectory() as d,patch.dict('os.environ',{'TESTFLOW_MODEL_PROVIDER':'legacy'}):
   settings=ModelSettings(Store(Path(d)/'db'))
   settings.save_custom({'base_url':'https://custom.example/v1','model':'custom-model'})
   self.assertIsInstance(settings.generation_client(),CodexModel)
