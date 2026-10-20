import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

class ResponsesTests(unittest.TestCase):
    def test_custom_provider_selected_without_exposing_key(self):
        from server.responses_model import configured_connection
        with tempfile.TemporaryDirectory() as d:
            Path(d,'config.toml').write_text('model_provider="custom"\n[model_providers.custom]\nbase_url="https://example.test/v1"\nwire_api="responses"\nrequires_openai_auth=true\n')
            Path(d,'auth.json').write_text('{"OPENAI_API_KEY":"private-key"}')
            with patch.dict('os.environ',{'CODEX_HOME':d}):
                connection=configured_connection()
            self.assertEqual(connection.endpoint,'https://example.test/v1/responses')
            self.assertNotIn('private-key',repr(connection))

    def test_local_codex_relay_allows_loopback_http_but_rejects_remote_http(self):
        from server.responses_model import configured_connection
        with tempfile.TemporaryDirectory() as d:
            config=Path(d,'config.toml');auth=Path(d,'auth.json');auth.write_text('{"OPENAI_API_KEY":"relay-key"}')
            with patch.dict('os.environ',{'CODEX_HOME':d}):
                config.write_text('model_provider="relay"\n[model_providers.relay]\nbase_url="http://127.0.0.1:9010/v1"\nwire_api="responses"\n')
                self.assertEqual(configured_connection().endpoint,'http://127.0.0.1:9010/v1/responses')
                config.write_text('model_provider="relay"\n[model_providers.relay]\nbase_url="http://relay.example/v1"\nwire_api="responses"\n')
                with self.assertRaisesRegex(ValueError,'HTTP仅允许本机回环地址'):configured_connection()

    def test_stream_completion_uses_only_final_assistant_text(self):
        from server.responses_model import request_json,Connection
        def run(command,**kwargs):
            self.assertNotIn('private-key',' '.join(command))
            self.assertNotIn('private requirement',' '.join(command))
            f=Path(command[command.index('--output')+1])
            events=[{'type':'response.created'},{'type':'response.output_text.delta','delta':'{"ok":'},
                    {'type':'response.output_text.delta','delta':'true}'},
                    {'type':'response.completed','response':{'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{"ok":true}'}]}]}}]
            f.write_text(''.join('data: '+json.dumps(e)+'\n\n' for e in events))
            self.assertTrue(kwargs['activity_probe']())
            kwargs['stdout'].write('200');kwargs['stdout'].flush()
            return type('Result',(),{'returncode':0})()
        with patch('server.responses_model.run_process',side_effect=run):
            self.assertEqual(request_json(Connection('https://example.test/v1/responses','private-key'),'private requirement','gpt-6.1-sol','high',600,None),{'ok':True})

    def test_partial_response_is_never_accepted(self):
        from server.responses_model import request_json,Connection
        def run(command,**kwargs):
            Path(command[command.index('--output')+1]).write_text('data: {"type":"response.output_text.delta","delta":"{}"}\n\n')
            kwargs['stdout'].write('200');kwargs['stdout'].flush()
            return type('Result',(),{'returncode':0})()
        with patch('server.responses_model.run_process',side_effect=run):
            with self.assertRaisesRegex(ValueError,'未完成'):request_json(Connection('https://example.test/v1/responses','key'),'JSON','gpt-6.1-sol','high',600,None)


    def test_transport_failure_after_http_headers_is_retryable(self):
        from server.responses_model import request_json,Connection
        from server.codex_model import GatewayFailure
        def run(command,**kwargs):
            kwargs['stdout'].write('200\n000\n');kwargs['stdout'].flush()
            return type('Result',(),{'returncode':1})()
        with patch('server.responses_model.run_process',side_effect=run):
            with self.assertRaises(GatewayFailure) as error:
                request_json(Connection('https://example.test/v1/responses','key'),'JSON','gpt-6.1-sol','high',600,None)
        self.assertTrue(error.exception.retryable)

    def test_http_auth_error_is_not_retryable_or_leaked(self):
        from server.responses_model import request_json,Connection
        from server.codex_model import GatewayFailure
        def run(command,**kwargs):
            kwargs['stdout'].write('401');kwargs['stdout'].flush()
            return type('Result',(),{'returncode':1})()
        with patch('server.responses_model.run_process',side_effect=run):
            with self.assertRaises(GatewayFailure) as error:request_json(Connection('https://example.test/v1/responses','private-key'),'JSON','gpt-6.1-sol','high',600,None)
        self.assertFalse(error.exception.retryable)
        self.assertNotIn('private-key',str(error.exception))

    def test_auto_routes_custom_gateway_without_starting_cli(self):
        from server.codex_model import CodexModel
        from server.responses_model import Connection
        with patch.dict('os.environ',{'TESTFLOW_CODEX_TRANSPORT':'auto'}),patch('server.responses_model.configured_connection',return_value=Connection('https://example.test/v1/responses','key')),patch('server.responses_model.request_json',return_value={'ok':True}) as request,patch('server.codex_model.shutil.which') as cli:
            self.assertEqual(CodexModel().request_json('JSON'),{'ok':True})
        cli.assert_not_called()
        self.assertEqual(request.call_args.args[2:4],('gpt-6.1-sol','high'))

    def test_real_http_worker_reads_stream_and_returns_final_json(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from server.responses_model import request_json,Connection
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for event in [{'type':'response.created'}, {'type':'response.output_text.delta','delta':'{"ok":true}'},
                    {'type':'response.completed','response':{'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{"ok":true}'}]}]}}]:
                    self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            value=request_json(Connection('http://127.0.0.1:'+str(server.server_port)+'/responses','test-key'),'test requirement','gpt-6.1-sol','high',5,None)
        finally:server.shutdown();server.server_close();thread.join()
        self.assertEqual(value,{'ok':True})
        self.assertEqual(seen[0]['model'],'gpt-6.1-sol')
        self.assertEqual(seen[0]['input'],'test requirement')
        self.assertNotIn('tools',seen[0])

    def test_real_http_wait_is_cancelled_without_waiting_for_socket_timeout(self):
        import threading,time
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from server.responses_model import request_json,Connection
        from server.processes import cancellation_scope
        started=threading.Event();release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']));started.set();release.wait(5)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();before=time.monotonic()
        try:
            with cancellation_scope(started.is_set):
                with self.assertRaisesRegex(ValueError,'取消'):
                    request_json(Connection('http://127.0.0.1:'+str(server.server_port)+'/responses','test-key'),'JSON','gpt-6.1-sol','high',600,None)
            self.assertLess(time.monotonic()-before,3)
        finally:release.set();server.shutdown();server.server_close();thread.join()

    def test_final_completion_without_trailing_newline_is_read_at_eof(self):
        from server.responses_model import request_json,Connection
        def run(command,**kwargs):
            event={'type':'response.completed','response':{'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'{"ok":true}'}]}]}}
            Path(command[command.index('--output')+1]).write_text('data: '+json.dumps(event))
            kwargs['stdout'].write('200');kwargs['stdout'].flush()
            return type('Result',(),{'returncode':0})()
        with patch('server.responses_model.run_process',side_effect=run):
            self.assertEqual(request_json(Connection('https://example.test/v1/responses','key'),'JSON','gpt-6.1-sol','high',600,None),{'ok':True})
