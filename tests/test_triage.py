import unittest
from server.triage import confirmed_groups, triage_report, filter_groups


class TriageTests(unittest.TestCase):
    def test_unresolved_failures_block_filter_and_exclusions_need_reason(self):
        results = [{'id':'1','status':'failed','evidence':'a'}, {'id':'2','status':'failed','evidence':'b'}]
        roots = [{'id':'root','title':'共享原因','confirmed':True,'evidence':['代码证据']}]
        assignments = [{'result_id':'1','root_cause_id':'root'}]
        partial = triage_report(results, assignments, roots, [])
        self.assertEqual(partial['unresolved'], ['2'])
        with self.assertRaises(ValueError):
            filter_groups(partial, ['root'], {})
        complete = triage_report(results, assignments, roots, [{'result_id':'2','reason':'探针预期需核对需求'}])
        self.assertTrue(complete['ready_for_review'])
        with self.assertRaises(ValueError):
            filter_groups(complete, [], {})
        filtered = filter_groups(complete, ['root'], {})
        self.assertEqual(filtered['result_ids'], ['1'])
        with self.assertRaises(ValueError):
            triage_report(results, assignments, roots, [{'result_id':'1','reason':'重复排除'}])

    def test_hundred_failures_one_confirmed_root_cause(self):
        results = [{'id':str(i), 'status':'failed', 'evidence':'report.json'} for i in range(100)]
        assignments = [{'result_id':str(i), 'root_cause_id':'root1'} for i in range(100)]
        roots = [{'id':'root1', 'title':'共享状态读取错误', 'confirmed':True, 'evidence':['code.cs:10']}]
        groups = confirmed_groups(results, assignments, roots)
        self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0]['result_ids']),100)

    def test_different_causes_and_runner_errors(self):
        results = [{'id':'1','status':'failed','evidence':'a'}, {'id':'2','status':'failed','evidence':'b'},
                   {'id':'3','status':'runner_error','evidence':'c'}]
        roots = [{'id':n,'title':'相同报错','confirmed':True,'evidence':['code']} for n in ['a','b']]
        assignments = [{'result_id':'1','root_cause_id':'a'}, {'result_id':'2','root_cause_id':'b'}]
        self.assertEqual(len(confirmed_groups(results,assignments,roots)),2)
        with self.assertRaises(ValueError):
            confirmed_groups(results, assignments+[{'result_id':'3','root_cause_id':'a'}], roots)

    def test_unconfirmed_or_missing_evidence_cannot_be_grouped(self):
        with self.assertRaises(ValueError):
            confirmed_groups([{'id':'1','status':'failed','evidence':'a'}],
                [{'result_id':'1','root_cause_id':'a'}], [{'id':'a','title':'原因','confirmed':False,'evidence':[]}])
