import unittest
from server.execution import normalize_report, map_cases


class ExecutionTests(unittest.TestCase):
    def test_unmapped_cases_never_inherit_probe_pass(self):
        cases = [{'id':'c1','title':'用例一'}, {'id':'c2','title':'用例二'}]
        execution = {'results':[{'id':'r1','status':'passed','evidence':'run'}]}
        result = map_cases(cases,execution,[{'case_id':'c1','result_ids':['r1'],'reason':'匹配保存状态断言'}])
        self.assertEqual(result['case_mapping'][0]['status'],'assertions_passed')
        self.assertEqual(result['case_mapping'][1]['status'],'not_run')
        self.assertFalse(result['mapping_review_complete'])
        self.assertNotIn('case_mapping', execution)
        result = map_cases(cases,execution,[{'case_id':'c1','result_ids':['r1'],'reason':'匹配断言'},
                                           {'case_id':'c2','result_ids':[],'gap_reason':'缺少客户端运行器'}])
        self.assertTrue(result['mapping_review_complete'])
        self.assertEqual(result['case_mapping'][1]['status'],'not_run')

    def test_mapping_rejects_unknown_results_and_false_double_classification(self):
        cases = [{'id':'c','title':'用例'}]
        execution = {'results':[{'id':'r','status':'passed','evidence':'run'}]}
        for item in ({'case_id':'c','result_ids':['unknown'],'reason':'依据'},
                     {'case_id':'c','result_ids':['r'],'reason':'依据','gap_reason':'未执行'},
                     {'case_id':'c','result_ids':['r'],'reason':''}):
            with self.assertRaises(ValueError): map_cases(cases,execution,[item])

    def test_report_distinguishes_failure_from_runner_error(self):
        report = {'cases': [{'id': '1', 'name': 'Switch', 'layer': 'PlayMode', 'status': 'FAIL', 'detail': 'expected true'},
                            {'id': '2', 'name': 'Runner', 'layer': 'PlayMode', 'status': 'ERROR', 'detail': 'exit timeout'},
                            {'id': '3', 'name': 'Device', 'layer': 'Device', 'status': 'NOT_RUN', 'detail': 'missing'}]}
        result = normalize_report(report, 1, 'sha1', '/report.json')
        self.assertEqual(result['counts']['failed'], 1)
        self.assertEqual(result['counts']['runner_error'], 1)
        self.assertEqual(result['counts']['not_run'], 1)
        self.assertEqual(result['overall'], 'incomplete')
        self.assertEqual(result['results'][0]['classification'], 'assertion_failure_needs_triage')

    def test_empty_report_unknown_status_and_false_summary_are_rejected(self):
        for report in ({'cases': []}, {'cases': [{'name':'x','status':'UNKNOWN'}]},
                       {'counts': {'PASS': 10}, 'cases': [{'name': 'x', 'status': 'FAIL', 'layer': 'Logic'}]}):
            with self.assertRaises(ValueError):
                normalize_report(report, 0, 'sha1', '/report.json')
