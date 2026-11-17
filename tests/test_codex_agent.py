import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from server.core.codex_agent import CodexAgent


class CodexAgentTests(unittest.TestCase):
    def test_agent_uses_real_project_readonly_shell_and_selected_model(self):
        with tempfile.TemporaryDirectory() as root:
            seen = []
            def run(command, **options):
                seen.append(command)
                Path(command[command.index('-o') + 1]).write_text('{"results": []}')
                return SimpleNamespace(returncode=0)
            with patch('server.core.codex_agent.shutil.which', return_value='/fixture/codex'), \
                 patch('server.core.codex_agent.run_process', side_effect=run), \
                 patch('server.codex_model.CodexModel.connection_config', return_value=[]):
                result = CodexAgent().request_json('read source only', root, {'type': 'object'},
                           selection={'model': 'gpt-6.1-sol', 'effort': 'high', 'source': 'relay'})
            cmd = seen[0]
            self.assertEqual(cmd[cmd.index('-C') + 1], str(Path(root).resolve()))
            self.assertEqual(cmd[cmd.index('--sandbox') + 1], 'read-only')
            self.assertNotIn('shell_tool', cmd)
            self.assertIn('model="gpt-6.1-sol"', cmd)
            self.assertIn('model_reasoning_effort="high"', cmd)
            self.assertEqual(result, {'results': []})

    def test_chat_only_provider_is_not_silently_routed_to_another_model(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, 'Responses'):
                CodexAgent().request_json('test', root, {}, selection={'source': 'custom', 'protocol': 'chat',
                    'model': 'other-model', 'api_key': 'secret', 'base_url': 'https://example.invalid'})

    def test_default_effort_omits_override_and_shell_cannot_inherit_api_environment(self):
        with tempfile.TemporaryDirectory() as root:
            seen = []
            def run(cmd, **options):
                seen.append(cmd)
                Path(cmd[cmd.index('-o') + 1]).write_text('{"ok":true}')
                return SimpleNamespace(returncode=0)
            with patch('server.core.codex_agent.shutil.which', return_value='/fixture/codex'), \
                 patch('server.core.codex_agent.run_process', side_effect=run), \
                 patch('server.codex_model.CodexModel.connection_config', return_value=[]):
                CodexAgent().request_json('test', root, {}, selection={'source':'relay','model':'same','effort':None})
            self.assertFalse(any(v.startswith('model_reasoning_effort=') for v in seen[0]))
            self.assertIn('shell_environment_policy.inherit="none"', seen[0])
            self.assertTrue(any(v.startswith('shell_environment_policy.set.HOME=') for v in seen[0]))
            self.assertTrue(any(v.startswith('shell_environment_policy.set.ZDOTDIR=') for v in seen[0]))

    def test_department_project_agent_preserves_pinned_model_and_skill(self):
        from server.core.integrations import ModelCapability
        from server.ai_models import current_selection
        from server.node_skills import current_skill
        seen = []
        def request(*args, **kwargs):
            seen.append((current_selection(), current_skill(), args[0]))
            return {'ok':True}
        capability = ModelCapability(None, {'model':'pinned','effort':'high','source':'relay'}, 'exact skill')
        with patch.object(CodexAgent, 'request_json', side_effect=request):
            capability.request_project_json('read source', '/fixture', {})
        self.assertEqual(seen[0][0]['model'], 'pinned')
        self.assertEqual(seen[0][1], 'exact skill')
