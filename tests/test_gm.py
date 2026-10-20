import unittest
from unittest.mock import patch
from server.connectors.gm import GmClient


class GmTests(unittest.TestCase):
    def client(self):
        return GmClient.__new__(GmClient)

    def test_mutations_and_implicit_environment_rejected_before_network(self):
        client = self.client()
        with patch.object(client, '_post') as post:
            for name, args in [('gm_update_user', {'env':'test'}), ('gm_resolve_pg', {'query':'GagaSort'}), ('gm_resolve_pg', {'env':'invalid'})]:
                with self.assertRaises(ValueError):
                    client.call_read(name, args)
            post.assert_not_called()

    def test_initialize_then_read_preserves_explicit_environment(self):
        client = self.client()
        with patch.object(client, '_post', side_effect=[{'protocolVersion':'2024-11-05'}, {}, {'content':[{'type':'text','text':'{"recommendedPg":"GagaSort"}'}]}]) as post:
            result = client.call_read('gm_resolve_pg', {'env':'test','query':'GagaSort'})
        self.assertEqual(result['recommendedPg'], 'GagaSort')
        self.assertEqual(post.call_args.args[0]['params']['arguments']['env'], 'test')
        self.assertEqual(post.call_args_list[1].args[0]['method'], 'notifications/initialized')

    def test_tool_error_does_not_report_success(self):
        client = self.client()
        with patch.object(client, '_post', side_effect=[{}, {}, {'isError':True}]):
            with self.assertRaises(ValueError):
                client.call_read('gm_health', {})
