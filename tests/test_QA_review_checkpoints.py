import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import static_review as sr
from server.ai_models import selection_scope
from server.node_skills import skill_scope
from tests.test_static_review import CASE, SOURCE, assertion


class QA_CheckpointTests(unittest.TestCase):
    def setUp(self):
        # These tests exercise sequential interruption; parallel cancellation has
        # its own event-synchronized suite and must not depend on thread order.
        worker_config = patch.dict(os.environ, {'TESTFLOW_STATIC_WORKERS': '1'})
        worker_config.start()
        self.addCleanup(worker_config.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'Assets').mkdir()
        (self.root / 'Assets/Reward.cs').write_text(SOURCE)
        self.binding = {'repository': str(self.root), 'project_root': str(self.root),
                        'branch': 'fixture', 'commit': 'abc', 'code_fingerprint': 'baseline'}
        self.cases = [copy.deepcopy(CASE), {**copy.deepcopy(CASE), 'id': 'C2'}]
        self.requirements = [{'id': 'r1', 'content': '不重复发奖'}]

    def run_review(self, reviewer, **extra):
        from departments.testing.QA_review_checkpoints import QA_checkpoint_scope
        with patch('server.gagasort.inspect_project', return_value=self.binding), \
             patch.object(sr, 'review_case', side_effect=reviewer), \
             QA_checkpoint_scope(self.root / 'checkpoints'):
            return sr.execute_static(self.binding, self.cases, self.requirements,
                                     self.root / 'evidence', client=object(), **extra)

    def reviewer(self, case, *_):
        row = sr.validate_case({'assertions': [assertion(0), assertion(1)]}, case,
                               {'Assets/Reward.cs': SOURCE})
        return row, {'sources': {'Assets/Reward.cs': SOURCE}}

    def test_retry_resumes_only_unfinished_cases_and_preserves_complete_gate(self):
        calls = []
        def interrupted(case, *args):
            calls.append(case['id'])
            if case['id'] == 'C2':
                raise ValueError('fixture interruption')
            return self.reviewer(case, *args)
        with self.assertRaisesRegex(ValueError, 'fixture interruption'):
            self.run_review(interrupted)
        progress = []
        def resumed(case, *args):
            calls.append(case['id'])
            return self.reviewer(case, *args)
        report = self.run_review(resumed, progress=progress.append)
        self.assertEqual(calls, ['C1', 'C2', 'C2'])
        self.assertEqual(report['checkpoint_reused'], 1)
        self.assertEqual(progress[-1]['checkpoint_reused_count'], 1)
        sr.validate_coverage(report, self.cases)
        self.assertEqual(report['runtime_status'], 'not_run')

    def test_changed_case_only_invalidates_that_case(self):
        self.run_review(self.reviewer)
        self.cases[1]['title'] = '新标题'
        calls = []
        def review(case, *args):
            calls.append(case['id'])
            return self.reviewer(case, *args)
        self.run_review(review)
        self.assertEqual(calls, ['C2'])

    def test_requirement_skill_model_and_baseline_changes_invalidate_all(self):
        for change in ('requirement', 'skill', 'model', 'baseline'):
            with self.subTest(change=change):
                self.run_review(self.reviewer)
                calls = []
                def review(case, *args):
                    calls.append(case['id'])
                    return self.reviewer(case, *args)
                if change == 'requirement':
                    self.requirements[0]['content'] += '变更'
                if change == 'baseline':
                    self.binding['code_fingerprint'] += 'new'
                with skill_scope('变更' if change == 'skill' else ''), \
                     selection_scope({'model': 'new', 'effort': 'high', 'api_key': 'never-save'} if change == 'model' else None):
                    self.run_review(review)
                self.assertEqual(calls, ['C1', 'C2'])
        self.assertNotIn('never-save', ''.join(p.read_text() for p in (self.root/'checkpoints').rglob('*.json')))

    def test_corrupt_or_forged_checkpoint_is_recomputed(self):
        self.run_review(self.reviewer)
        files = list((self.root / 'checkpoints').rglob('*.json'))
        self.assertEqual(len(files), 2)
        for file in files:
            self.assertEqual(os.stat(file).st_mode & 0o777, 0o600)
        first = json.loads(files[0].read_text())
        first['result']['assertions'][0]['call_chain'][0]['quote'] = 'Invented();'
        files[0].write_text(json.dumps(first))
        files[1].write_text('{invalid')
        calls = []
        def review(case, *args):
            calls.append(case['id'])
            return self.reviewer(case, *args)
        self.assertEqual(self.run_review(review)['checkpoint_reused'], 0)
        self.assertEqual(len(calls), 2)

    def test_invalid_cached_source_pool_is_recomputed_without_counting_as_reused(self):
        self.run_review(self.reviewer)
        for file in (self.root / 'checkpoints').glob('*.json'):
            cached = json.loads(file.read_text())
            cached['trace']['sources'] = None
            file.write_text(json.dumps(cached))
        calls = []
        def review(case, *args):
            calls.append(case['id'])
            return self.reviewer(case, *args)
        report = self.run_review(review)
        self.assertEqual(len(calls), 2)
        self.assertEqual(report['checkpoint_reused'], 0)

    def test_relay_connection_change_cannot_reuse_an_old_provider_result(self):
        with patch.object(sr.CodexModel, 'connection_config', return_value=['-c', 'provider=A']):
            self.run_review(self.reviewer)
        calls = []
        def review(case, *args):
            calls.append(case['id'])
            return self.reviewer(case, *args)
        with patch.object(sr.CodexModel, 'connection_config', return_value=['-c', 'provider=B']):
            self.run_review(review)
        self.assertEqual(calls, ['C1', 'C2'])

    def test_corrected_model_line_metadata_does_not_prevent_safe_reuse(self):
        def review(case, *args):
            rows = [assertion(0), assertion(1)]
            rows[0]['call_chain'][0]['line'] = 1
            return sr.validate_case({'assertions': rows}, case, {'Assets/Reward.cs': SOURCE}), {}
        self.run_review(review)
        report = self.run_review(review)
        self.assertEqual(report['checkpoint_reused'], 2)

    def test_cache_cannot_skip_cancellation_or_final_baseline_check(self):
        self.run_review(self.reviewer)
        from departments.testing.QA_review_checkpoints import QA_checkpoint_scope
        from server.processes import cancellation_scope
        with cancellation_scope(lambda: True), self.assertRaises(ValueError):
            self.run_review(self.reviewer)
        with QA_checkpoint_scope(self.root/'checkpoints'), \
             patch('server.gagasort.inspect_project', side_effect=[self.binding, {**self.binding, 'commit': 'changed'}]), \
             self.assertRaisesRegex(ValueError, '检测期间代码变化'):
            sr.execute_static(self.binding, self.cases, self.requirements, self.root/'evidence', client=object())
