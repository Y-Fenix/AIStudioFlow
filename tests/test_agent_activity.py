import json
import tempfile
import unittest
from pathlib import Path
from server.codex_stream import StreamStats


class AgentActivityTests(unittest.TestCase):
    def test_shell_activity_counts_unique_tools_and_never_exposes_command_or_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'events.jsonl'
            tool={'id':'one','type':'command_execution','command':'SECRET_COMMAND','aggregated_output':'PRIVATE_SOURCE'}
            path.write_text('\n'.join(json.dumps(e) for e in [
                {'type':'item.started','item':{**tool,'status':'in_progress'}},
                {'type':'item.completed','item':{**tool,'status':'completed'}},
                {'type':'item.completed','item':{**tool,'status':'completed'}}])+'\n')
            stats=StreamStats(path)
            snapshot=stats.sample()
            self.assertEqual(snapshot['tool_calls'],1)
            self.assertEqual(snapshot['commands_completed'],1)
            self.assertEqual(snapshot['last_tool'],'command_execution')
            self.assertNotIn('SECRET_COMMAND',json.dumps(snapshot))
            self.assertNotIn('PRIVATE_SOURCE',json.dumps(snapshot))
            self.assertEqual(stats.sample()['tool_calls'],1)
