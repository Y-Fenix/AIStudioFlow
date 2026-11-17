"""QA evidence and operation-Skill regressions; isolated data, no live tools."""
import copy
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from server.attribution import validate_suggestions
from server.jobs import GenerationWorker
from server.core.queued_operations import authorize_testing_job
from server.node_skills import current_skill, defaults
from server.store import Store
from server import static_review as sr
from tests.test_static_review import CASE, assertion


class QA_PipelineGuardTests(unittest.TestCase):
    def test_static_invalid_search_is_feedback_instead_of_aborting_the_job(self):
        prompts = []
        class QA_Client:
            def request_json(self, prompt):
                prompts.append(prompt)
                if len(prompts) == 1:
                    return {'search': [None, '', {'symbol': 'Reward'}]}
                return {'assertions': [{**assertion(i, 'needs_runtime'), 'call_chain': [],
                    'gap': '需客户端观察', 'next_action': '人工检查'} for i in range(len(CASE['steps']))]}
        with tempfile.TemporaryDirectory() as folder:
            result, trace = sr.review_case(CASE, [], sr.SourceCatalog(folder), QA_Client(), max_rounds=2)
        self.assertEqual(result['status'], 'needs_runtime')
        self.assertEqual(len(trace['requests'][0]['search']), 3)
        self.assertTrue(all('error' in item for item in trace['requests'][0]['search']))

    def test_persistent_static_format_error_exhausts_rounds_as_insufficient_evidence(self):
        from server.model_output import ModelOutputError
        with tempfile.TemporaryDirectory() as folder, patch('server.codex_model.CodexModel.request_json',
                side_effect=ModelOutputError('{', 'JSON格式错误')) as request:
            result, _ = sr.review_case(CASE, [], sr.SourceCatalog(folder), sr.CodexModel(), max_rounds=2)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(request.call_count, 2)

    def test_static_review_malformed_json_uses_existing_bounded_exploration_loop(self):
        from server.model_output import ModelOutputError
        prompts = []
        class QA_Client:
            def request_json(self, prompt):
                prompts.append(prompt)
                if len(prompts) == 1:
                    raise ModelOutputError('{', '模型返回内容不是合法JSON')
                return {'assertions': [{**assertion(i, 'needs_runtime'),
                    'call_chain': [], 'gap': '需要观察客户端画面', 'next_action': '人工运行核对'} for i in range(len(CASE['steps']))]}
        with tempfile.TemporaryDirectory() as folder:
            result, trace = sr.review_case(CASE, [], sr.SourceCatalog(folder), QA_Client(), max_rounds=2)
        self.assertEqual(result['status'], 'needs_runtime')
        self.assertEqual(len(prompts), 2)
        self.assertIn('不是合法JSON', prompts[1])
        self.assertEqual(trace['model_outputs'][0]['unparsed_output'], '{')

    def test_attribution_repairs_format_and_reference_errors_before_accepting(self):
        from server.attribution import suggest_attribution
        from server.model_output import ModelOutputError
        binding = {'repository': '/fixture', 'branch': 'main', 'code_fingerprint': 'same', 'project_root': '/fixture'}
        execution = {'code_fingerprint': 'same', 'method': 'static_code_review', 'results': [
            {'id': 'f1', 'status': 'failed', 'assertions': [{'call_chain': [
                {'file': 'Assets/Reward.cs', 'line': 1, 'quote': 'Grant();'}]}]}]}
        valid = {'suggestions': [{**self.QA_suggestion(line=1), 'evidence': [
            {'file': 'Assets/Reward.cs', 'line': 1, 'quote': 'Grant();'}]}]}
        invalid = copy.deepcopy(valid)
        invalid['suggestions'][0]['evidence'][0]['quote'] = 'invented();'
        with patch('server.attribution.inspect_project', return_value=binding), patch.object(
                sr.SourceCatalog, 'read', return_value='Grant();'), patch('server.codex_model.CodexModel.request_json',
                side_effect=[ModelOutputError('{', 'JSON格式错误'), invalid, valid]) as request:
            result = suggest_attribution(binding, execution)
        self.assertEqual(result['suggestions'][0]['result_ids'], ['f1'])
        self.assertFalse(result['suggestions'][0]['confirmed'])
        self.assertEqual(request.call_count, 3)

    def test_authorized_operation_node_is_independent_of_task_page(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / 'db.sqlite')
            project = store.create_project('隔离权限验证')['id']
            task = store.create_task(project, '回归入口')['id']
            for kind, stage in (('generate', 0), ('execute', 1), ('attribution', 2), ('regression', 5)):
                self.assertEqual(authorize_testing_job(store, {'actor': 'local', 'project_id': project,
                    'task_id': task, 'stage': 4, 'kind': kind}), stage)

    def QA_suggestion(self, identifier='root', refs=None, line=3):
        return {'id': identifier, 'title': '缺少去重', 'reasoning': '同一入口重复发奖',
                'result_ids': refs or ['f1'],
                'evidence': [{'file': 'code', 'line': line, 'quote': 'Grant();'}]}

    def test_attribution_retains_correct_line_when_quote_repeats(self):
        result = validate_suggestions({'suggestions': [self.QA_suggestion()]},
                                      [{'id': 'f1'}], {'code': 'Grant();\nelse\nGrant();\n'})
        self.assertEqual(result['suggestions'][0]['evidence'][0]['line'], 3)

    def test_attribution_rejects_ambiguous_line_instead_of_guessing_first(self):
        with self.assertRaisesRegex(ValueError, '歧义'):
            validate_suggestions({'suggestions': [self.QA_suggestion(line=99)]},
                                 [{'id': 'f1'}], {'code': 'Grant();\nelse\nGrant();\n'})

    def test_attribution_rejects_duplicate_failure_assignments(self):
        for suggestions in ([self.QA_suggestion(refs=['f1', 'f1'])],
                            [self.QA_suggestion(), self.QA_suggestion('second')]):
            with self.subTest(suggestions=suggestions), self.assertRaisesRegex(ValueError, '重复'):
                validate_suggestions({'suggestions': suggestions}, [{'id': 'f1'}], {'code': 'Grant();'})

    def test_mixed_report_keeps_failure_visible_alongside_unresolved_counts(self):
        failed = assertion(0, 'failed')
        failed['counterexample'] = {'preconditions': ['已领过奖励'], 'steps': ['重复领取'],
                                   'expected': '不发奖', 'actual': '再次发奖', 'reachability': '无去重守卫'}
        gap = assertion(0, 'needs_runtime')
        gap.update(gap='未检查视觉', next_action='人工查看客户端')
        cases = [{**copy.deepcopy(CASE), 'id': identifier, 'steps': [CASE['steps'][0]]}
                 for identifier in ('failure', 'gap')]
        source = {'Assets/Reward.cs': 'class Reward {\n void Claim() { Grant(); }\n}\n'}
        rows = [sr.validate_case({'assertions': [a]}, c, source) for a, c in zip((failed, gap), cases)]
        with tempfile.TemporaryDirectory() as folder:
            binding = {'repository': folder, 'project_root': folder, 'branch': 'master',
                       'commit': 'fixture', 'code_fingerprint': 'fixture'}
            with patch('server.gagasort.inspect_project', return_value=binding), \
                 patch.object(sr, 'review_case', side_effect=[(r, {}) for r in rows]):
                report = sr.execute_static(binding, cases, [], folder, client=object())
        self.assertEqual(report['overall'], 'failed')
        self.assertEqual(report['counts']['failed'], 1)
        self.assertEqual(report['counts']['needs_runtime'], 1)

    def test_read_window_beyond_eof_returns_actual_source_without_wasting_round(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'Assets').mkdir()
            (root / 'Assets/Reward.cs').write_text('class Reward {\n void Claim() { Grant(); }\n}\n')
            class QA_Client:
                calls = 0
                def request_json(self, prompt):
                    self.calls += 1
                    if self.calls == 1:
                        return {'read': [{'file': 'Assets/Reward.cs', 'start_line': 1, 'end_line': 200}]}
                    return {'assertions': [assertion(0), assertion(1)]}
            client = QA_Client()
            result, trace = sr.review_case(CASE, [], sr.SourceCatalog(root), client, max_rounds=2)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(client.calls, 2)
            self.assertEqual(trace['requests'][0]['read'][0]['end_line'], 3)

    def test_empty_static_scope_cannot_be_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            binding = {'repository': folder, 'project_root': folder, 'branch': 'master',
                       'commit': 'fixture', 'code_fingerprint': 'fixture'}
            with patch('server.gagasort.inspect_project', return_value=binding):
                with self.assertRaisesRegex(ValueError, '非空'):
                    sr.execute_static(binding, [], [], folder, client=object())

    def test_filing_page_regression_loads_regression_skill_and_records_its_hash(self):
        # The job stays at task stage 4 for optimistic locking; its operation is node 5.
        with tempfile.TemporaryDirectory() as folder:
            completed = threading.Event()
            task = {'id': 'isolated', 'revision': 1, 'status': 'waiting_user', 'node_skills': defaults(),
                    'binding': {'repository': '/fixture', 'branch': 'master'}, 'requirements': [],
                    'artifacts': {'0': {'cases': []}, '1': {}, '4': {'drafts': []}}}
            task['node_skills']['4']['content'] = 'FILING_ONLY'
            task['node_skills']['5']['content'] = 'REGRESSION_ONLY'
            job = {'project_id': 'p', 'task_id': task['id'], 'revision': 1, 'stage': 4,
                   'kind': 'regression', 'actor': 'fixture-user'}
            class QA_Store:
                path = Path(folder) / 'db.sqlite'
                artifact = None
                error = None
                def recover_generations(self): pass
                claimed = False
                lock = threading.Lock()
                def claim_generation(self):
                    with self.lock:
                        if self.claimed:return None
                        self.claimed=True
                        return job
                def task(self, *_): return task
                def finish_generation(self, _, artifact=None, error=None):
                    self.artifact, self.error = artifact, error
                    completed.set()
            store = QA_Store()
            seen = []
            def execute(*_, **kwargs):
                seen.append(current_skill())
                return {}
            with patch('server.jobs.authorize_testing_job', return_value=5), \
                 patch('server.jobs.ModelSettings') as settings, \
                 patch('server.jobs.JobTelemetry'), \
                 patch('server.jobs.inspect_project', return_value=task['binding']), \
                 patch('server.jobs.execute_logic', side_effect=execute), \
                 patch('server.jobs.assess_logic_roots', return_value={}):
                settings.return_value.runtime_selection.return_value = {'source': 'custom', 'model': 'fixture', 'effort': 'high'}
                worker = GenerationWorker(store)
                try:
                    self.assertTrue(completed.wait(3))
                finally:
                    worker.close()
            self.assertIsNone(store.error)
            self.assertEqual(seen, ['REGRESSION_ONLY'])
            self.assertEqual(store.artifact['node_skill_sha256'], hashlib.sha256(b'REGRESSION_ONLY').hexdigest())


if __name__ == '__main__':
    unittest.main()
