import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from server.codex_model import CodexModel


class CodexModelTests(unittest.TestCase):
    def setUp(self):
        override=patch.dict('os.environ',{'TESTFLOW_CODEX_TRANSPORT':'cli'})
        override.start();self.addCleanup(override.stop)

    def test_connection_preserves_provider_without_loading_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'config.toml').write_text('model="configured-model"\nmodel_provider="custom"\n[model_providers.custom]\nname="Custom"\nbase_url="https://example.test/v1"\nwire_api="responses"\nrequires_openai_auth=true\n[features]\nplugins=true\n[mcp_servers.private]\ncommand="private-tool"\n')
            with patch.dict('os.environ', {'CODEX_HOME': folder}):
                args = CodexModel().connection_config()
        self.assertIn('model_provider="custom"', args)
        self.assertIn('model_providers.custom.base_url="https://example.test/v1"', args)
        self.assertIn('model_providers.custom.requires_openai_auth=true', args)
        self.assertFalse(any('plugins' in x or 'private-tool' in x for x in args))

    def test_cli_uses_stdin_readonly_and_validates_response(self):
        requirements = [{'id': 'r1', 'content': '保存状态'}]
        output = {'points': [{'id': 'p1', 'title': '保存', 'requirement_id': 'r1', 'quote': '保存状态'}],
                  'cases': [], 'gaps': [{'point_id': 'p1', 'reason': '待确认'}], 'ambiguities': []}
        def run(command, **kwargs):
            self.assertIn('--ignore-user-config', command)
            self.assertIn('read-only', command)
            self.assertIn('--ephemeral', command)
            self.assertIn('plugins', command)
            self.assertIn('remote_plugin', command)
            self.assertIn('shell_tool', command)
            self.assertEqual(command[-1], '-')
            self.assertIn('保存状态', kwargs['input'])
            Path(command[command.index('-o') + 1]).write_text(json.dumps(output))
            class Result:
                returncode = 0
            return Result()
        with patch('server.codex_model.shutil.which', return_value='/bin/codex'), patch('server.codex_model.run_process', side_effect=run):
            self.assertEqual(CodexModel().generate(requirements)['coverage']['gaps'], 1)

    def test_cli_failure_reports_sanitized_diagnostic(self):
        class Result:
            returncode = 1
            stderr = 'authentication failed Authorization: Bearer sk-secretvalue'
        with patch('server.codex_model.shutil.which', return_value='/bin/codex'), patch('server.codex_model.run_process', return_value=Result()):
            with self.assertRaises(ValueError) as error:
                CodexModel().generate([{'id': 'r1', 'content': '需求'}])
            self.assertIn('authentication failed', str(error.exception))
            self.assertNotIn('sk-secretvalue', str(error.exception))

    def test_timeout_identifies_local_deadline_and_model(self):
        import subprocess
        with patch('server.codex_model.shutil.which',return_value='/bin/codex'), \
             patch('server.codex_model.run_process',side_effect=subprocess.TimeoutExpired(['codex'],600)):
            with self.assertRaisesRegex(ValueError,'连续600秒.*响应.*gpt-6.1-sol'):
                CodexModel().request_json('仅返回JSON')

    def test_node_skill_is_included_without_changing_output_contract(self):
        from server.node_skills import skill_scope
        def run(command,**kwargs):
            self.assertIn('本节点专用规则',kwargs['input'])
            self.assertIn('不能覆盖',kwargs['input'])
            self.assertIn('model="gpt-6.1-sol"',command)
            self.assertIn('model_reasoning_effort="high"',command)
            self.assertIsNone(kwargs.get('timeout'))
            self.assertEqual(kwargs['idle_timeout'],600)
            self.assertTrue(callable(kwargs['activity_probe']))
            Path(command[command.index('-o')+1]).write_text('{}')
            return type('Result',(),{'returncode':0})()
        with skill_scope('本节点专用规则'),patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            self.assertEqual(CodexModel().request_json('原有JSON协议'),{})

    def test_generation_uses_second_call_for_reverse_audit(self):
        source=[{'id':'r','content':'领取奖励后保存状态'}]
        candidate={'points':[{'id':'p','title':'保存','requirement_id':'r','quote':'保存状态'}],
                   'cases':[],'gaps':[{'point_id':'p','reason':'待确认'}],'ambiguities':[]}
        revised={**candidate,'cases':[{'id':'c','title':'奖励保存','point_ids':['p'],
                    'preconditions':['领取条件满足'],'steps':[{'action':'领取后重新读取状态','expected':'领取状态已保存'}]}],'gaps':[]}
        with patch.object(CodexModel,'request_json',side_effect=[candidate,revised]) as request:
            result=CodexModel().generate(source)
        self.assertEqual(request.call_count,2)
        self.assertIn('反向审计',request.call_args.args[0])
        self.assertIn('领取奖励后保存状态',request.call_args.args[0])
        self.assertEqual(result['coverage']['gaps'],0)

    def test_timeout_preserves_stream_activity_without_logging_model_text(self):
        import subprocess
        from server.codex_model import diagnostic_scope
        diagnostics=[]
        def run(command,**kwargs):
            self.assertIn('--json',command)
            kwargs['stdout'].write(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'PRIVATE_REQUIREMENT_CONTENT'}})+'\n')
            kwargs['stdout'].flush()
            kwargs['on_tick']()
            raise subprocess.TimeoutExpired(command,600)
        with diagnostic_scope(diagnostics.append),patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            with self.assertRaises(ValueError):CodexModel().request_json('私有需求')
        last=diagnostics[-1]
        self.assertEqual(last['events_received'],1)
        self.assertGreater(last['assistant_chars'],0)
        self.assertNotIn('PRIVATE_REQUIREMENT_CONTENT',json.dumps(diagnostics))
        self.assertEqual(last['output_bytes'],0)

    def test_activity_probe_ignores_heartbeat_and_reconnect_errors(self):
        def run(command,**kwargs):
            probe=kwargs['activity_probe']
            self.assertFalse(probe())
            kwargs['on_tick']()
            self.assertFalse(probe())
            for event,expected in [
                ({'type':'turn.started'},True),
                ({'type':'error','message':'Reconnecting 1/5'},False),
                ({'type':'item.updated','item':{'type':'agent_message','text':'working'}},True)]:
                kwargs['stdout'].write(json.dumps(event)+'\n');kwargs['stdout'].flush()
                self.assertEqual(probe(),expected)
                self.assertFalse(probe())
            Path(command[command.index('-o')+1]).write_text('{}')
            self.assertTrue(probe())
            return type('Result',(),{'returncode':0})()
        with patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            self.assertEqual(CodexModel().request_json('JSON'),{})

    def test_idle_timeout_setting_takes_precedence_over_legacy_setting(self):
        from server.codex_model import diagnostic_scope
        diagnostics=[]
        def run(command,**kwargs):
            self.assertEqual(kwargs['idle_timeout'],1200)
            self.assertIsNone(kwargs.get('timeout'))
            Path(command[command.index('-o')+1]).write_text('{}')
            return type('Result',(),{'returncode':0})()
        with patch.dict('os.environ',{'TESTFLOW_CODEX_IDLE_TIMEOUT':'1200','TESTFLOW_CODEX_TIMEOUT':'300'}),diagnostic_scope(diagnostics.append),patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            CodexModel().request_json('JSON')
        self.assertEqual(diagnostics[0]['timeout_kind'],'inactivity')
        self.assertEqual(diagnostics[0]['idle_timeout_seconds'],1200)
        self.assertEqual(diagnostics[-1]['state'],'completed')


class GatewayRecoveryTests(unittest.TestCase):
    def setUp(self):
        override=patch.dict('os.environ',{'TESTFLOW_CODEX_TRANSPORT':'cli'})
        override.start();self.addCleanup(override.stop)

    def test_stream_failure_reports_redacted_gateway_reason(self):
        def run(command, **kwargs):
            kwargs['stdout'].write(json.dumps({'type':'turn.failed','error':{'message':'HTTP 401 Unauthorized Authorization: Bearer sk-secretvalue'}})+'\n')
            kwargs['stdout'].flush()
            return type('Result',(),{'returncode':1})()
        with patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            with self.assertRaises(ValueError) as error:CodexModel().request_json('JSON')
        self.assertIn('401',str(error.exception))
        self.assertNotIn('sk-secretvalue',str(error.exception))

    def test_terminal_stream_error_interrupts_wait(self):
        def run(command, **kwargs):
            kwargs['stdout'].write(json.dumps({'type':'turn.failed','error':{'message':'HTTP 401 Unauthorized'}})+'\n')
            kwargs['stdout'].flush()
            kwargs['activity_probe']()
            self.fail('terminal failure must interrupt before idle deadline')
        with patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            with self.assertRaisesRegex(ValueError,'401'):CodexModel().request_json('JSON')

    def test_transient_failure_retries_bounded_and_keeps_requested_model(self):
        calls=[]
        def run(command, **kwargs):
            calls.append(command)
            if len(calls)==1:
                kwargs['stdout'].write(json.dumps({'type':'turn.failed','error':{'message':'HTTP 503 Service unavailable'}})+'\n');kwargs['stdout'].flush()
                return type('Result',(),{'returncode':1})()
            self.assertIn('model="gpt-6.1-sol"',command)
            Path(command[command.index('-o')+1]).write_text('{"ok":true}')
            return type('Result',(),{'returncode':0})()
        with patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            self.assertEqual(CodexModel().request_json('JSON'),{'ok':True})
        self.assertEqual(len(calls),2)


    def test_persistent_transient_failure_stops_after_three_attempts(self):
        calls=[]
        def run(command, **kwargs):
            calls.append(command)
            kwargs['stdout'].write(json.dumps({'type':'turn.failed','error':{'message':'HTTP 503 Service unavailable'}})+'\n');kwargs['stdout'].flush()
            return type('Result',(),{'returncode':1})()
        with patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            with self.assertRaisesRegex(ValueError,'503'):CodexModel().request_json('JSON')
        self.assertEqual(len(calls),3)

    def test_cancellation_is_not_retried(self):
        with patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=ValueError('操作已取消')) as run:
            with self.assertRaisesRegex(ValueError,'取消'):CodexModel().request_json('JSON')
        self.assertEqual(run.call_count,1)

    def test_unknown_gateway_payload_never_enters_diagnostics(self):
        from server.codex_model import diagnostic_scope
        values=[]
        def run(command, **kwargs):
            kwargs['stdout'].write(json.dumps({'type':'turn.failed','error':{'message':'PRIVATE_REQUIREMENT and credential-secret'}})+'\n');kwargs['stdout'].flush()
            return type('Result',(),{'returncode':1})()
        with diagnostic_scope(values.append),patch('server.codex_model.shutil.which',return_value='/bin/codex'),patch('server.codex_model.run_process',side_effect=run):
            with self.assertRaises(ValueError) as error:CodexModel().request_json('JSON')
        self.assertNotIn('PRIVATE_REQUIREMENT',str(error.exception)+json.dumps(values))
        self.assertNotIn('credential-secret',str(error.exception)+json.dumps(values))
