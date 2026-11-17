import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

class ResponsesTests(unittest.TestCase):
    def test_real_failed_stream_retries_when_macos_denies_process_group_cleanup(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from server.codex_model import CodexModel,diagnostic_scope
        from server.responses_model import Connection
        seen=[];release=threading.Event();diagnostics=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                event=({'error':{'message':'temporary stream failure'}} if len(seen)==1 else
                    {'choices':[{'delta':{'content':'{"ok":true}'},'finish_reason':'stop'}]})
                self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode());self.wfile.flush()
                if len(seen)==1:release.wait(5)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            connection=Connection('http://127.0.0.1:'+str(server.server_port)+'/chat/completions','fixture',protocol='chat')
            with patch.dict('os.environ',{'TESTFLOW_CODEX_TRANSPORT':'auto'}), \
                 patch('server.responses_model.configured_connection',return_value=connection), \
                 patch('server.processes.os.killpg',side_effect=PermissionError(1,'Operation not permitted')) as kill, \
                 diagnostic_scope(diagnostics.append):
                result=CodexModel().request_json('Return JSON')
            self.assertTrue(kill.called,'exercise cleanup of the real failed streaming worker')
        finally:release.set();server.shutdown();server.server_close();thread.join()
        self.assertEqual(result,{'ok':True})
        self.assertEqual(len(seen),2)
        self.assertTrue(any(d['state']=='retrying' for d in diagnostics))

    def test_malformed_gateway_envelope_is_a_classified_transport_failure(self):
        from server.responses_model import request_json, Connection
        from server.codex_model import GatewayFailure
        events = [
            {'type': 'response.completed', 'response': []},
            {'type': 'response.completed', 'response': ['private']},
            {'type': 'response.output_text.delta', 'delta': {'private': 'text'}},
            {'type': 'response.completed', 'response': {'status': 'completed', 'output': [None]}},
            {'type': 'response.completed', 'response': {'status': 'completed', 'output': [
                {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': {}}]}]}},
        ]
        for event in events:
            with self.subTest(event=event):
                def run(command, **kwargs):
                    Path(command[command.index('--output')+1]).write_text('data: '+json.dumps(event)+'\n\n')
                    kwargs['stdout'].write('200'); kwargs['stdout'].flush()
                    return type('Result', (), {'returncode': 0})()
                with patch('server.responses_model.run_process', side_effect=run):
                    with self.assertRaises(GatewayFailure) as failure:
                        request_json(Connection('https://example.test/responses', 'key'),
                            'JSON', 'gpt-6.1-sol', 'high', 600, None)
                self.assertTrue(failure.exception.retryable)
                self.assertNotIn('private', str(failure.exception))

    def test_real_http_completion_does_not_wait_for_server_to_close_connection(self):
        import threading, time
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from server.responses_model import request_json, Connection
        release = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                event = {'type': 'response.completed', 'response': {'status': 'completed', 'output': [
                    {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}}
                self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode()); self.wfile.flush()
                release.wait(3)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        started = time.monotonic()
        try:
            result = request_json(Connection('http://127.0.0.1:'+str(server.server_port)+'/responses', 'key'),
                'JSON', 'gpt-6.1-sol', 'high', 5, None)
            elapsed = time.monotonic()-started
        finally:
            release.set(); server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(result, {'ok': True})
        self.assertLess(elapsed, 1.5, '完成事件后不能继续等连接EOF')

    def test_completed_fenced_json_is_accepted_without_changing_values(self):
        from server.responses_model import request_json, Connection
        def run(command, **kwargs):
            event = {'type': 'response.completed', 'response': {'status': 'completed', 'output': [
                {'type': 'message', 'role': 'assistant', 'content': [
                    {'type': 'output_text', 'text': '```json\n{"quote":"exact text"}\n```'}]}]}}
            Path(command[command.index('--output')+1]).write_text('data: '+json.dumps(event)+'\n\n')
            kwargs['stdout'].write('200'); kwargs['stdout'].flush()
            return type('Result', (), {'returncode': 0})()
        with patch('server.responses_model.run_process', side_effect=run):
            self.assertEqual(request_json(Connection('https://example.test/responses', 'key'),
                'JSON', 'gpt-6.1-sol', 'high', 600, None), {'quote': 'exact text'})

    def test_complete_malformed_output_keeps_raw_for_recovery_without_logging_it(self):
        from server.responses_model import request_json, Connection
        from server.model_output import ModelOutputError
        raw = '{"private":"requirement text",}'
        diagnostics = []
        def run(command, **kwargs):
            event = {'type': 'response.completed', 'response': {'status': 'completed', 'output': [
                {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': raw}]}]}}
            Path(command[command.index('--output')+1]).write_text('data: '+json.dumps(event)+'\n\n')
            kwargs['stdout'].write('200'); kwargs['stdout'].flush()
            return type('Result', (), {'returncode': 0})()
        with patch('server.responses_model.run_process', side_effect=run):
            with self.assertRaises(ModelOutputError) as failure:
                request_json(Connection('https://example.test/responses', 'secret-key'),
                    'JSON', 'gpt-6.1-sol', 'high', 600, diagnostics.append)
        self.assertEqual(failure.exception.raw_text, raw)
        self.assertEqual(diagnostics[-1]['state'], 'invalid_json')
        self.assertNotIn('requirement text', json.dumps(diagnostics))
        self.assertNotIn('secret-key', str(failure.exception))

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
