"""Real QA business chain, with model transport and Git inspection replaced explicitly.

Uses real generation batching, source discovery/citation validation, attribution,
human gates, one-root drafting and unchanged-case regression. No Unity or Feishu.
"""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.ai_models import selection_scope
from server.attribution import suggest_attribution
from server.bugs import prepare_drafts
from server.codex_model import CodexModel
from server.model_output import ModelOutputError
from server.gagasort import execute_logic
from server.node_skills import defaults, skill_scope
from server.regression import assess_logic_roots, review_logic_regression
from server.static_review import validate_coverage
from server.triage import triage_report, filter_groups


QA_BROKEN = '''class Reward {
 public int coins;
 private bool claimed;
 public void Claim() { coins += 10; claimed = true; }
 public void Retry() { Claim(); }
}
'''
QA_FIXED = QA_BROKEN.replace('coins += 10;', 'if (claimed) return; coins += 10;')


class QA_StaticPipelineTests(unittest.TestCase):
    def setUp(self):
        # This suite replaces the single-shot text transport explicitly. Native
        # Agent execution has its own source/capability tests and real benchmarks.
        override=patch.dict(os.environ, {'TESTFLOW_STATIC_ENGINE':'legacy'})
        override.start()
        self.addCleanup(override.stop)

    def test_two_paths_one_root_fixed_code_regression_and_skill_injection(self):
        self.QA_run_pipeline()

    def test_pipeline_preserves_evidence_gates_with_one_format_failure_per_model_node(self):
        self.QA_run_pipeline(inject_format_errors=True)

    def QA_run_pipeline(self, inject_format_errors=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'Assets/Reward.cs'
            source.parent.mkdir()
            source.write_text(QA_BROKEN)
            requirements = [{'id': 'req', 'source': 'isolated.md',
                             'content': '首次领取增加10金币；重复领取与重试不得重复发奖。'}]
            skills, calls, injected = defaults(), [], set()
            selected = {'source': 'custom', 'base_url': 'http://127.0.0.1:1/v1', 'protocol': 'responses',
                        'api_key': 'fixture-only', 'model': 'gpt-6.1-sol', 'effort': 'high'}

            def baseline(*_):
                return {'repository': folder, 'project_root': folder, 'branch': 'fixture',
                        'commit': 'fixture-git-boundary', 'execution_suite': 'static',
                        'code_fingerprint': hashlib.sha256(source.read_bytes()).hexdigest()}

            def transport(connection, prompt, model, effort, timeout, callback):
                self.assertEqual((model, effort), ('gpt-6.1-sol', 'high'))
                # Assert actual prompt injection, including on generation's worker threads.
                matched = [int(i) for i, s in skills.items() if s['content'] in prompt]
                self.assertEqual(len(matched), 1)
                stage = matched[0]
                calls.append(stage)
                if inject_format_errors and stage not in injected:
                    injected.add(stage)
                    raise ModelOutputError('{', '模型返回内容不是合法JSON')
                if stage == 0:
                    return {'points': [{'id': 'reward', 'title': '奖励幂等', 'requirement_id': 'req',
                                        'quote': requirements[0]['content']}],
                            'cases': [{'id': identifier, 'title': title, 'point_ids': ['reward'],
                                       'preconditions': ['新账号，coins=0，claimed=false'],
                                       'steps': [{'action': '调用Claim', 'expected': 'coins=10'},
                                                 {'action': action, 'expected': 'coins仍为10'}]}
                                      for identifier, title, action in (
                                          ('repeat', '重复领取不重复发奖', '再次调用Claim'),
                                          ('retry', '重试不重复发奖', '调用Retry'))],
                            'gaps': [], 'ambiguities': []}
                if stage == 2:
                    # Input is JSON after the fixed attribution prompt, before Skill text.
                    data = json.JSONDecoder().raw_decode(prompt[prompt.index('{"failures":'):])[0]
                    self.assertIn('coins += 10;', data['sources']['Assets/Reward.cs'])
                    return {'suggestions': [{'id': 'shared', 'title': '领取入口未拦截重复领取',
                        'reasoning': '重复调用与重试均可达Claim，未检查claimed便增加金币',
                        'result_ids': [r['id'] for r in data['failures']], 'confirmed': True,
                        'evidence': [{'file': 'Assets/Reward.cs', 'line': 4,
                                      'quote': ' public void Claim() { coins += 10; claimed = true; }'}]}]}
                self.assertIn(stage, (1, 5))
                data = json.JSONDecoder().raw_decode(prompt.split('审查数据：\n', 1)[1])[0]
                if not data['sources']:
                    return {'read': ['Assets/Reward.cs'], 'search': []}
                actual = data['sources']['Assets/Reward.cs']
                fixed = 'if (claimed) return;' in actual
                assertions = []
                for index, step in enumerate(data['case']['steps']):
                    failed = index == 1 and not fixed
                    row = {'step_index': index, 'status': 'failed' if failed else 'passed',
                           'reasoning': '根据实际读取的Claim及Retry路径核对金币状态',
                           'precondition_analysis': '新账号首次领取可达；随后由相同入口再次调用',
                           'counterexample_search': '检查首次领取、重复入口与Retry共享路径',
                           'call_chain': [{'file': 'Assets/Reward.cs', 'line': 1, 'quote': actual}]}
                    if failed:
                        row['counterexample'] = {'preconditions': ['已领取一次，coins=10，claimed=true'],
                            'steps': [step['action']], 'expected': step['expected'], 'actual': 'coins变为20',
                            'reachability': 'Claim没有已领取守卫，Retry亦直接调用Claim'}
                    assertions.append(row)
                return {'assertions': assertions}

            with selection_scope(selected), \
                 patch('server.responses_model.request_json', side_effect=transport), \
                 patch('server.gagasort.inspect_project', side_effect=baseline), \
                 patch('server.attribution.inspect_project', side_effect=baseline):
                with skill_scope(skills['0']['content']):
                    generated = CodexModel().generate(requirements)
                self.assertEqual(generated['coverage']['gaps'], 0)
                cases = generated['cases']
                original_cases = copy.deepcopy(cases)
                with skill_scope(skills['1']['content']):
                    original = execute_logic(baseline(), root / 'evidence', cases, requirements)
                validate_coverage(original, cases)
                self.assertEqual([r['status'] for r in original['results']], ['failed', 'failed'])
                self.assertTrue(all(Path(r['evidence']).is_file() for r in original['results']))
                with skill_scope(skills['2']['content']):
                    suggestions = suggest_attribution(baseline(), original)
                self.assertFalse(suggestions['suggestions'][0]['confirmed'])
                candidate = suggestions['suggestions'][0]
                roots = [{'id': candidate['id'], 'title': candidate['title'], 'confirmed': False,
                          'evidence': [str(candidate['evidence'])]}]
                assignments = [{'result_id': r, 'root_cause_id': 'shared'} for r in candidate['result_ids']]
                with self.assertRaisesRegex(ValueError, '确认'):
                    triage_report(original['results'], assignments, roots, [])
                roots[0]['confirmed'] = True  # Explicit simulated human approval.
                triage = triage_report(original['results'], assignments, roots, [])
                groups = filter_groups(triage, ['shared'], {})['groups']
                drafts = prepare_drafts(groups, original['results'], [], {
                    'project': 'isolated', 'method': original['method'],
                    'code_fingerprint': original['code_fingerprint']})['drafts']
                self.assertEqual(len(drafts), 1)
                self.assertEqual(drafts[0]['missing'], [])
                self.assertEqual(len(drafts[0]['related_result_ids']), 2)
                self.assertEqual(drafts[0]['reproduction_provenance'], 'static_inference')
                source.write_text(QA_FIXED)  # Changes only this temporary fixture.
                with skill_scope(skills['5']['content']):
                    current = execute_logic(baseline(), root / 'evidence', cases, requirements)
                validate_coverage(current, cases)
                regression = assess_logic_roots(drafts, original, current)
                self.assertEqual(cases, original_cases)
                self.assertNotEqual(current['code_fingerprint'], original['code_fingerprint'])
                self.assertEqual(regression['roots'][0]['verdict'], 'logic_assertions_passed')
                self.assertIsNone(regression['roots'][0]['repair_probability'])
                self.assertFalse(regression['remote_state_changed'])
                reviewed = review_logic_regression(regression, [{'root_cause_id': 'shared',
                    'action': 'accept_logic_only', 'reason': '仅接受隔离样例静态证据'}])
                self.assertTrue(reviewed['ready_for_review'])
                self.assertFalse(reviewed['client_verified'])
            self.assertEqual(set(calls), {0, 1, 2, 5})
            if inject_format_errors:
                self.assertEqual(injected, {0, 1, 2, 5})


if __name__ == '__main__':
    unittest.main()
