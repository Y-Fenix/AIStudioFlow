import copy
import unittest
from departments.testing.QA_native_review import QA_plan_batches, QA_validate_agent_batch
from server.static_review import validate_case
from tests.test_static_review import CASE, SOURCE, assertion


class QA_NativeReviewTests(unittest.TestCase):
    def test_batch_grouping_uses_exact_requirement_mapping_and_preserves_indices(self):
        cases = [{**CASE, 'id': f'C{i}', 'point_ids': [f'P{i % 2}']} for i in range(5)]
        points = [{'id': 'P0', 'requirement_id': 'R0'}, {'id': 'P1', 'requirement_id': 'R1'}]
        batches = QA_plan_batches(cases, points, size=2)
        self.assertEqual([[i for i, _ in b] for b in batches], [[0, 2], [4], [1, 3]])

    def test_agent_result_is_reordered_and_quotes_are_still_checked(self):
        cases = [copy.deepcopy(CASE), {**copy.deepcopy(CASE), 'id': 'C2'}]
        output = {'results': [{'case_id': c['id'], 'assertions': [assertion(0), assertion(1)]} for c in reversed(cases)]}
        results, sources = QA_validate_agent_batch(output, cases, lambda _: SOURCE, validate_case)
        self.assertEqual([r['case_id'] for r in results], ['C1', 'C2'])
        output['results'][0]['assertions'][0]['call_chain'][0]['quote'] = 'Fake();'
        with self.assertRaises(ValueError):
            QA_validate_agent_batch(output, cases, lambda _: SOURCE, validate_case)

    def test_missing_or_duplicate_case_cannot_be_reported_complete(self):
        cases = [CASE, {**CASE, 'id': 'C2'}]
        with self.assertRaises(ValueError):
            QA_validate_agent_batch({'results': [{'case_id': 'C1'}, {'case_id': 'C1'}]}, cases, lambda _: SOURCE, validate_case)

    def test_unambiguous_one_based_steps_are_canonicalized_without_changing_raw_report(self):
        output={'results':[{'case_id':'C1','assertions':[assertion(1),assertion(2)]}]}
        original=copy.deepcopy(output)
        rows,_=QA_validate_agent_batch(output,[CASE],lambda _: SOURCE,validate_case)
        self.assertEqual([a['step_index'] for a in rows[0]['assertions']],[0,1])
        self.assertEqual([a['model_reported_step_index'] for a in rows[0]['assertions']],[1,2])
        self.assertEqual(output,original)
        output['results'][0]['assertions'][1]['step_index']=1
        with self.assertRaises(ValueError):
            QA_validate_agent_batch(output,[CASE],lambda _:SOURCE,validate_case)
