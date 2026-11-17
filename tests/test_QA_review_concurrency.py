"""Real scheduling/source evidence with explicit model and Git-boundary substitutes."""
import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import nullcontext

from server import static_review as sr
from server.ai_models import current_selection, selection_scope
from server.codex_model import current_diagnostic, diagnostic_scope
from server.node_skills import current_skill, skill_scope
from server.processes import cancellation_scope, check_cancelled
from departments.testing.QA_review_checkpoints import QA_checkpoint_scope
from departments.testing.QA_review_pool import QA_map_reviews, QA_review_workers
from tests.test_static_review import CASE, SOURCE, assertion


class QA_ReviewConcurrencyTests(unittest.TestCase):
    def test_real_review_path_warms_exact_groups_and_preserves_independent_results(self):
        calls, lock = {}, threading.Lock()
        cases = [{**copy.deepcopy(CASE), 'id': f'C{i}', 'point_ids': ['P1' if i < 2 else 'P2']} for i in range(4)]
        class Client:
            def request_json(self, prompt):
                p = json.loads(prompt.split('审查数据：\n', 1)[1])
                with lock:
                    key = p['case']['id']
                    calls[key] = calls.get(key, 0) + 1
                return {'assertions': [assertion(0), assertion(1)]} if p['sources'] else {'read': ['Assets/Reward.cs']}
        with patch('server.gagasort.inspect_project', return_value=self.binding), QA_checkpoint_scope(self.root / 'group-checkpoints'):
            report = sr.execute_static(self.binding, cases, [], self.root / 'group-evidence', client=Client())
        self.assertEqual(calls, {'C0': 2, 'C1': 1, 'C2': 2, 'C3': 1})
        self.assertEqual([r['case_id'] for r in report['results']], [c['id'] for c in cases])
        sr.validate_coverage(report, cases)

    def test_affinity_serializes_related_cases_but_runs_other_groups_in_parallel(self):
        barrier = threading.Barrier(2, timeout=2)
        lock, active, first_finished = threading.Lock(), set(), set()
        items = ['A', 'A', 'B', 'B']
        def review(index, key):
            with lock:
                self.assertNotIn(key, active)
                active.add(key)
                first = key not in first_finished
            if first:
                barrier.wait()
            with lock:
                first_finished.add(key)
                active.remove(key)
            return index
        result = QA_map_reviews(items, review, 2, check_cancelled=lambda: None,
                                cancellation_scope=lambda _: nullcontext(), affinity_key=lambda key: key)
        self.assertEqual(result, [0, 1, 2, 3])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'Assets').mkdir()
        (self.root/'Assets/Reward.cs').write_text(SOURCE)
        self.binding = {'repository': str(self.root), 'project_root': str(self.root),
                        'branch': 'fixture', 'commit': 'abc', 'code_fingerprint': 'baseline'}
        self.cases = [{**copy.deepcopy(CASE), 'id': f'C{i}'} for i in range(6)]

    def QA_result(self, case):
        return sr.validate_case({'assertions': [assertion(0), assertion(1)]}, case,
                                {'Assets/Reward.cs': SOURCE}), {}

    def QA_run(self, review, **kwargs):
        with patch.dict(os.environ, {'TESTFLOW_STATIC_WORKERS': '3'}), \
             patch('server.gagasort.inspect_project', return_value=self.binding), \
             patch.object(sr, 'review_case', side_effect=review), \
             QA_checkpoint_scope(self.root/'checkpoints'):
            return sr.execute_static(self.binding, self.cases, [], self.root/'evidence', client=object(), **kwargs)

    def test_bounded_parallel_work_preserves_context_order_evidence_and_progress(self):
        barrier = threading.Barrier(3, timeout=2)
        lock = threading.Lock()
        active, peak, completed = 0, 0, []
        progress, diagnostics = [], []
        def review(case, *_):
            nonlocal active, peak
            self.assertEqual(current_skill(), 'QA fixture skill')
            self.assertEqual(current_selection()['model'], 'fixture-model')
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait()
            current_diagnostic()({'state': 'running', 'assistant_chars': 10})
            try:
                return self.QA_result(case)
            finally:
                with lock:
                    completed.append(case['id'])
                    active -= 1
        with selection_scope({'model': 'fixture-model', 'effort': 'high', 'source': 'custom'}), \
             skill_scope('QA fixture skill'), diagnostic_scope(diagnostics.append):
            report = self.QA_run(review, progress=progress.append)
        self.assertEqual(peak, 3)
        self.assertEqual([r['case_id'] for r in report['results']], [c['id'] for c in self.cases])
        self.assertEqual(sorted({p['completed'] for p in progress}), list(range(7)))
        self.assertEqual([p['completed'] for p in progress], sorted(p['completed'] for p in progress))
        self.assertEqual({d['case_id'] for d in diagnostics}, {c['id'] for c in self.cases})
        self.assertTrue(all(Path(r['evidence']).is_file() for r in report['results']))
        sr.validate_coverage(report, self.cases)
        self.assertEqual(len(list((self.root/'checkpoints').glob('*.json'))), 6)
        self.assertNotIn('fixture-model', ''.join(p.read_text() for p in (self.root/'checkpoints').glob('*.json')))

    def test_reverse_completion_keeps_input_order(self):
        self.cases = self.cases[:3]
        release = [threading.Event() for _ in range(3)]
        release[2].set()
        completed = []
        def review(case, *_):
            index = int(case['id'][1:])
            self.assertTrue(release[index].wait(2))
            return self.QA_result(case)
        def progress(value):
            if 'last_status' in value:
                index = int(value['case_id'][1:])
                completed.append(index)
                if index:
                    release[index-1].set()
        report = self.QA_run(review, progress=progress)
        self.assertEqual(completed, [2, 1, 0])
        self.assertEqual([r['case_id'] for r in report['results']], ['C0', 'C1', 'C2'])

    def test_single_worker_matches_parallel_canonical_results(self):
        parallel = self.QA_run(lambda case, *_: self.QA_result(case))
        with patch.dict(os.environ, {'TESTFLOW_STATIC_WORKERS': '1'}), \
             patch('server.gagasort.inspect_project', return_value=self.binding), \
             patch.object(sr, 'review_case', side_effect=lambda case, *_: self.QA_result(case)):
            serial = sr.execute_static(self.binding, self.cases, [], self.root/'serial', client=object())
        for report in (parallel, serial):
            for row in report['results']:
                row.pop('evidence')
        self.assertEqual(parallel['results'], serial['results'])
        self.assertEqual(parallel['counts'], serial['counts'])

    def test_worker_configuration_rejects_invalid_values(self):
        for value in ('0', '4', '-1', 'invalid', '1.5'):
            with self.subTest(value=value), patch.dict(os.environ, {'TESTFLOW_STATIC_WORKERS': value}):
                with self.assertRaisesRegex(ValueError, '1至3'):
                    QA_review_workers()

    def test_failure_cancels_siblings_and_stops_dispatch(self):
        started = threading.Barrier(3, timeout=2)
        sibling_stopped = threading.Event()
        calls = []
        def review(case, *_):
            calls.append(case['id'])
            started.wait()
            if case['id'] == 'C0':
                raise PermissionError('fixture permission revoked')
            # A cooperative in-flight transport observes the pool cancellation.
            for _ in range(100):
                try:
                    check_cancelled()
                except ValueError:
                    sibling_stopped.set()
                    raise
                sibling_stopped.wait(.01)
            self.fail('sibling did not observe cancellation')
        with self.assertRaisesRegex(PermissionError, 'permission revoked'):
            self.QA_run(review)
        self.assertTrue(sibling_stopped.is_set())
        self.assertEqual(set(calls), {'C0', 'C1', 'C2'})

    def test_pool_accepts_platform_callbacks_without_private_imports(self):
        calls = []
        result = QA_map_reviews([3, 2, 1], lambda index, item: (calls.append(index), item)[1], 1,
                                check_cancelled=lambda: None,
                                cancellation_scope=lambda aborted: nullcontext())
        self.assertEqual(calls, [0, 1, 2])
        self.assertEqual(result, [3, 2, 1])

    def test_cancellation_propagates_and_does_not_start_remaining_cases(self):
        barrier = threading.Barrier(3, timeout=2)
        cancelled = threading.Event()
        calls = []
        def review(case, *_):
            calls.append(case['id'])
            barrier.wait()
            cancelled.set()
            check_cancelled()
            self.fail('cancelled worker cannot continue')
        with cancellation_scope(cancelled.is_set), self.assertRaisesRegex(ValueError, '取消'):
            self.QA_run(review)
        self.assertEqual(set(calls), {'C0', 'C1', 'C2'})
        self.assertFalse(list((self.root/'evidence').rglob('execution.json')))

    def test_failure_keeps_completed_checkpoint_and_retry_only_runs_missing(self):
        self.cases = self.cases[:2]
        first_finished = threading.Event()
        def review(case, *_):
            if case['id'] == 'C1':
                self.assertTrue(first_finished.wait(2))
                raise ValueError('fixture transport failure')
            return self.QA_result(case)
        def progress(value):
            if value['completed'] == 1:
                first_finished.set()
        with self.assertRaisesRegex(ValueError, 'fixture transport failure'):
            self.QA_run(review, progress=progress)
        self.assertFalse(list((self.root/'evidence').rglob('execution.json')))
        called = []
        def retry(case, *_):
            called.append(case['id'])
            return self.QA_result(case)
        report = self.QA_run(retry)
        self.assertEqual(called, ['C1'])
        self.assertEqual(report['checkpoint_reused'], 1)
        sr.validate_coverage(report, self.cases)


if __name__ == '__main__':
    unittest.main()
