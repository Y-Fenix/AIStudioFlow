import copy
import tempfile
import unittest
from pathlib import Path
from server import static_review as sr


CASE = {'id': 'C1', 'title': '奖励边界', 'preconditions': ['活动已开启'],
        'steps': [{'action': '领取奖励', 'expected': '得到奖励'}, {'action': '再次领取', 'expected': '不重复发奖'}]}
SOURCE = 'class Reward {\n void Claim() { Grant(); }\n}\n'


def assertion(index, status='passed'):
    return {'step_index': index, 'status': status, 'reasoning': '入口调用领取方法后修改奖励状态',
            'precondition_analysis': '活动入口可进入领取方法',
            'call_chain': [{'file': 'Assets/Reward.cs', 'line': 2, 'quote': ' void Claim() { Grant(); }'}],
            'counterexample_search': '检查重复调用与资格状态', 'gap': '', 'next_action': ''}


class StaticReviewTests(unittest.TestCase):
    def validate(self, assertions):
        return sr.validate_case({'assertions': assertions}, CASE, {'Assets/Reward.cs': SOURCE})

    def test_requires_each_expected_step_and_verified_quotes(self):
        with self.assertRaises(ValueError):
            self.validate([assertion(0)])
        a = assertion(1)
        a['call_chain'][0]['quote'] = 'NeverExists();'
        with self.assertRaises(ValueError):
            self.validate([assertion(0), a])
        a = assertion(1)
        a['call_chain'][0]['line'] = 1
        row = self.validate([assertion(0), a])
        ref = row['assertions'][1]['call_chain'][0]
        self.assertEqual(ref['line'], 2)
        self.assertEqual(ref['model_reported_line'], 1)

    def test_failure_needs_reachable_counterexample(self):
        a = assertion(1, 'failed')
        with self.assertRaises(ValueError):
            self.validate([assertion(0), a])
        a['counterexample'] = {'preconditions': ['活动开启且已领过奖励'], 'steps': ['再次调用Claim'],
            'expected': '不发奖', 'actual': '再次调用Grant', 'reachability': '领取入口未检查已领取状态'}
        row = self.validate([assertion(0), a])
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['actual'], '静态推导：再次调用Grant')
        self.assertEqual(row['runtime_status'], 'not_run')

    def test_unresolved_assertion_prevents_whole_case_pass(self):
        for status in ('needs_runtime', 'requirement_unclear', 'insufficient_evidence'):
            a = assertion(1, status)
            a.update(gap='缺少奖励服务实现', next_action='读取奖励服务并核对回调')
            self.assertEqual(self.validate([assertion(0), a])['status'], status)

    def test_catalog_refuses_symlinks_and_non_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Assets').mkdir()
            (root / 'Assets/Reward.cs').write_text(SOURCE)
            (root / 'Assets/secret.cs').symlink_to('/etc/passwd')
            catalog = sr.SourceCatalog(root)
            self.assertEqual(catalog.paths, ['Assets/Reward.cs'])
            with self.assertRaises(ValueError):
                catalog.read('../outside.cs')
            with self.assertRaises(ValueError):
                catalog.read('Assets/secret.cs')

    def test_review_fetches_real_sources_before_accepting_conclusions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'Assets').mkdir()
            (root / 'Assets/Reward.cs').write_text(SOURCE)
            class Client:
                def __init__(self): self.calls = 0
                def request_json(self, prompt):
                    self.calls += 1
                    if self.calls == 1: return {'read': ['Assets/Reward.cs'], 'search': []}
                    return {'assertions': [assertion(0), assertion(1)]}
            client = Client()
            row, trace = sr.review_case(CASE, [], sr.SourceCatalog(root), client)
            self.assertEqual(row['status'], 'passed')
            self.assertEqual(client.calls, 2)
            self.assertEqual(trace['sources']['Assets/Reward.cs'], SOURCE)

    def test_exhausted_discovery_retains_case_as_evidence_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            class Client:
                def request_json(self, prompt): return {'search': ['unknownSymbol'], 'read': []}
            row, trace = sr.review_case(CASE, [], sr.SourceCatalog(Path(directory)), Client(), max_rounds=2)
            self.assertEqual(row['status'], 'insufficient_evidence')
            self.assertEqual(len(row['assertions']), 2)
            self.assertEqual(len(trace['requests']), 2)

    def test_static_regression_matches_case_ids_not_duplicate_titles(self):
        from server.regression import assess_logic_roots
        old = {'method': 'static_code_review', 'case_input_hash':'cases', 'requirements_hash':'requirements', 'code_fingerprint': 'old', 'results': [
            {'id': 'C1', 'case_id': 'C1', 'test_name': '同名', 'status': 'failed', 'evidence': 'old.json'},
            {'id': 'C2', 'case_id': 'C2', 'test_name': '同名', 'status': 'failed', 'evidence': 'old2.json'}]}
        current = {**old, 'code_fingerprint': 'new', 'results': [{**r, 'status': 'passed'} for r in old['results']]}
        report = assess_logic_roots([{'root_cause_id': 'root', 'title': '缺陷', 'related_result_ids': ['C1','C2']}], old, current)
        self.assertEqual(report['roots'][0]['verdict'], 'logic_assertions_passed')
        current['results'][1]['status'] = 'insufficient_evidence'
        self.assertEqual(assess_logic_roots([{'root_cause_id': 'root', 'title': '缺陷', 'related_result_ids': ['C1','C2']}], old, current)['roots'][0]['verdict'], 'insufficient_evidence')

    def test_static_execution_rejects_baseline_drift_and_never_runs_compiler(self):
        from unittest.mock import patch
        binding = {'repository': '/fixture', 'project_root': '/fixture/GagaSort', 'branch': 'master', 'commit': 'sha', 'code_fingerprint': 'old'}
        with tempfile.TemporaryDirectory() as directory:
            with patch('server.gagasort.inspect_project', side_effect=[binding, {**binding, 'code_fingerprint': 'changed'}]), \
                 patch.object(sr, 'review_case', return_value=(self.validate([assertion(0), assertion(1)]), {})):
                with self.assertRaisesRegex(ValueError, '检测期间代码变化'):
                    sr.execute_static(binding, [CASE], [], directory, client=object())

    def test_static_draft_preserves_inference_scope_without_build(self):
        from server.bugs import prepare_drafts
        a = assertion(1, 'failed')
        a['counterexample'] = {'preconditions': ['活动开启且已领过奖励'], 'steps': ['再次调用Claim'],
            'expected': '不发奖', 'actual': '再次调用Grant', 'reachability': '领取入口未检查已领取状态'}
        row = self.validate([assertion(0), a])
        row['evidence'] = 'static-evidence.json'
        result = prepare_drafts([{'root_cause_id': 'root', 'title': '缺少去重', 'result_ids': ['C1']}], [row], [],
                                {'project': 'fixture', 'code_fingerprint': 'sha', 'method': 'static_code_review'})
        draft = result['drafts'][0]
        self.assertEqual(draft['missing'], [])
        self.assertEqual(draft['reproduction_provenance'], 'static_inference')
        self.assertIn('未实机复现', draft['verification_scope'])

    def test_gate_rejects_missing_or_changed_case_results(self):
        cases = [CASE]
        row = self.validate([assertion(0), assertion(1)])
        report = {'method': 'static_code_review', 'results': [row], 'case_input_hash': sr.input_hash(cases)}
        sr.validate_coverage(report, cases)
        changed = copy.deepcopy(cases)
        changed[0]['steps'][1]['expected'] = '改了期望'
        with self.assertRaises(ValueError): sr.validate_coverage(report, changed)
        report['results'] = []
        with self.assertRaises(ValueError): sr.validate_coverage(report, cases)

    def test_bad_model_response_can_only_end_in_evidence_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            class Client:
                def request_json(self, prompt): return {'assertions': [assertion(0), assertion(1)]}
            row, trace = sr.review_case(CASE, [], sr.SourceCatalog(Path(directory)), Client(), max_rounds=2)
            self.assertEqual(row['status'], 'insufficient_evidence')
            self.assertIn('protocol_error', trace['requests'][0])

    def test_gate_rejects_summary_overriding_step_gap(self):
        gap = assertion(1, 'insufficient_evidence')
        gap.update(gap='缺少存档实现', next_action='读取存档调用链')
        row = self.validate([assertion(0), gap])
        report = {'results': [row], 'case_input_hash': sr.input_hash([CASE])}
        sr.validate_coverage(report, [CASE])
        row['status'] = 'passed'
        with self.assertRaisesRegex(ValueError, '逐步骤状态'):
            sr.validate_coverage(report, [CASE])

    def test_gate_rejects_unknown_step_state_and_boolean_index(self):
        for field, value in [('status', 'verified'), ('step_index', False)]:
            with self.subTest(field=field):
                row = self.validate([assertion(0), assertion(1)])
                row['assertions'][0][field] = value
                with self.assertRaises(ValueError):
                    sr.validate_coverage({'results': [row], 'case_input_hash': sr.input_hash([CASE])}, [CASE])

    def test_source_discovery_does_not_silently_read_whole_large_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'Assets').mkdir()
            (root/'Assets/Large.cs').write_text('Header\n'*250+'SecretTail\n')
            class Client:
                def __init__(self): self.calls=0
                def request_json(self,prompt):
                    self.calls+=1
                    if self.calls==1: return {'read':['Assets/Large.cs']}
                    self.prompt=prompt
                    return {'read':[{'file':'Assets/Large.cs','start_line':249,'end_line':251}]}
            client=Client()
            row,trace=sr.review_case(CASE,[],sr.SourceCatalog(root),client,max_rounds=2)
            self.assertNotIn('SecretTail', client.prompt)
            self.assertIn('SecretTail', trace['sources']['Assets/Large.cs'])
            self.assertEqual(trace['sources']['Assets/Large.cs'].splitlines()[250],'SecretTail')

    def test_progress_persists_without_changing_task_revision_and_stops_on_cancel(self):
        from server.store import Store
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'db.sqlite')
            project=store.create_project('静态进度')['id']
            task=store.create_task(project,'隔离样例')
            task=store.import_requirement(project,task['id'],'样例','测试规则')
            store.enqueue_generation(project,task['id'])
            job=store.claim_generation()
            value={'completed':1,'total':2,'case_id':'C1','title':'样例'}
            store.operation_progress(job,value)
            snapshot=store.task(project,task['id'])
            import json
            self.assertEqual(json.loads(snapshot['jobs'][0]['progress']),value)
            self.assertEqual(snapshot['revision'],job['revision'])
            store.decide(project,task['id'],'cancel',snapshot['revision'])
            with self.assertRaises(ValueError):store.operation_progress(job,value)
