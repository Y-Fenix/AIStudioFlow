import unittest
from server.regression import assess_regression, assess_logic_roots


class RegressionTests(unittest.TestCase):
    def test_logic_matches_names_not_changed_row_identifiers(self):
        original = {'results':[{'id':'old','test_name':'领取次数'}]}
        drafts = [{'root_cause_id':'root','title':'次数问题','related_result_ids':['old']}]
        current = {'method':'production_method_probe_with_stubs','code_fingerprint':'new',
                   'results':[{'id':'different','test_name':'领取次数','status':'passed','evidence':'new-run'}]}
        result = assess_logic_roots(drafts,original,current)
        self.assertEqual(result['roots'][0]['verdict'],'logic_assertions_passed')
        self.assertFalse(result['remote_state_changed'])
        self.assertIsNone(result['roots'][0]['repair_probability'])
        current['results'][0]['test_name'] = '新增探针'
        self.assertEqual(assess_logic_roots(drafts,original,current)['roots'][0]['verdict'],'insufficient_evidence')

    def test_pass_requires_original_and_related_scenarios_same_build(self):
        result=assess_regression(['original','related'],
            [{'case_id':'original','status':'passed','evidence':'a'}, {'case_id':'related','status':'passed','evidence':'b'}],
            'sha','sha')
        self.assertEqual(result['verdict'],'runtime_passed')
        self.assertIsNone(result['repair_probability'])
        self.assertTrue(result['requires_user_confirmation'])

    def test_missing_and_version_mismatch_never_pass(self):
        result=assess_regression(['original','related'],[{'case_id':'original','status':'passed','evidence':'a'}],'sha','sha')
        self.assertEqual(result['verdict'],'insufficient_evidence')
        self.assertEqual(result['missing_case_ids'],['related'])
        result=assess_regression(['original'],[{'case_id':'original','status':'passed','evidence':'a'}],'new','old')
        self.assertEqual(result['verdict'],'version_mismatch')

    def test_failed_original_remains_reproducible(self):
        result=assess_regression(['original'],[{'case_id':'original','status':'failed','evidence':'a'}],'sha','sha')
        self.assertEqual(result['verdict'],'still_reproducible')

    def test_user_review_does_not_turn_probe_into_client_pass(self):
        from server.regression import review_logic_regression
        r={'roots':[{'root_cause_id':'r','verdict':'logic_assertions_passed'}], 'execution':{'code_fingerprint':'hash'}}
        d=[{'root_cause_id':'r','action':'accept_logic_only','reason':'关联断言通过，客户端另测'}]
        result=review_logic_regression(r,d)
        self.assertTrue(result['ready_for_review'])
        self.assertFalse(result['client_verified'])
        self.assertFalse(result['remote_state_changed'])
        for decision in [{**d[0],'action':'client_passed'},{**d[0],'reason':''},{**d[0],'root_cause_id':'wrong'}]:
            with self.assertRaises(ValueError):review_logic_regression(r,[decision])
        failed={**r,'roots':[{'root_cause_id':'r','verdict':'still_reproducible'}]}
        with self.assertRaises(ValueError):review_logic_regression(failed,d)
        self.assertTrue(review_logic_regression(failed,[{**d[0],'action':'keep_open'}])['ready_for_review'])

    def test_static_regression_requires_same_case_and_requirement_inputs(self):
        original={'method':'static_code_review','case_input_hash':'cases','requirements_hash':'requirements',
                  'results':[{'id':'C1','case_id':'C1','test_name':'标题','status':'failed'}]}
        current={**original,'code_fingerprint':'new','results':[{'id':'C1','case_id':'C1','test_name':'标题','status':'passed','evidence':'new.json'}]}
        drafts=[{'root_cause_id':'R','title':'缺陷','related_result_ids':['C1']}]
        self.assertEqual(assess_logic_roots(drafts,original,current)['roots'][0]['verdict'],'logic_assertions_passed')
        for key in ('case_input_hash','requirements_hash'):
            with self.assertRaises(ValueError):assess_logic_roots(drafts,original,{**current,key:'changed'})
            missing=dict(current);missing.pop(key)
            with self.assertRaises(ValueError):assess_logic_roots(drafts,original,missing)
        with self.assertRaises(ValueError):assess_logic_roots(drafts,{**original,'method':'production_suite_with_stubs'},current)
