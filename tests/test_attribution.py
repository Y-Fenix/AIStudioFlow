import unittest
from unittest.mock import patch
from server.attribution import validate_suggestions, suggest_attribution


class AttributionTests(unittest.TestCase):
    def test_suite_failure_uses_matching_sources_and_excludes_runner_errors(self):
        binding = {'repository': '/fixture', 'branch': 'master', 'code_fingerprint': 'hash'}
        execution = {'method': 'production_suite_with_stubs', 'code_fingerprint': 'hash',
                     'results': [{'id': 'streakgroup-rank', 'status': 'failed'},
                                 {'id': 'streakgroup-domain', 'status': 'runner_error'}]}
        with patch('server.attribution.inspect_project', return_value=binding), \
             patch('server.streakgroup_execution.attribution_sources', return_value={'code': 'real'}) as sources, \
             patch('server.attribution.CodexModel') as model:
            model.return_value.request_json.return_value = {'suggestions': []}
            result = suggest_attribution(binding, execution)
            sources.assert_called_once_with('/fixture', {'streakgroup-rank'})
            self.assertEqual(result['unanalysed'], ['streakgroup-rank'])
            self.assertIn('real', model.return_value.request_json.call_args.args[0])

    def test_verified_quote_still_requires_human_confirmation(self):
        failures=[{'id':'f1'},{'id':'f2'}]
        sources={'/fixture/code.cs':'first line\nreturn array[index];\n'}
        output={'suggestions':[{'id':'r1','title':'缺少边界检查','reasoning':'索引超过长度',
            'result_ids':['f1'],'confirmed':True,'evidence':[{'file':'/fixture/code.cs','quote':'return array[index];','line':999}]}]}
        result=validate_suggestions(output,failures,sources)
        self.assertFalse(result['suggestions'][0]['confirmed'])
        self.assertEqual(result['suggestions'][0]['evidence'][0]['line'],2)
        self.assertEqual(result['unanalysed'],['f2'])
        output['suggestions'][0]['evidence'][0]['quote']='不存在的代码'
        with self.assertRaisesRegex(ValueError,'引用不存在'):
            validate_suggestions(output,failures,sources)

    def test_nonfailure_reference_rejected(self):
        output={'suggestions':[{'id':'r1','title':'原因','reasoning':'说明','result_ids':['passed'],
                               'evidence':[{'file':'code','quote':'actual'}]}]}
        with self.assertRaisesRegex(ValueError,'不存在的失败'):
            validate_suggestions(output,[{'id':'failed'}],{'code':'actual'})
