import copy
import json
import unittest
from types import SimpleNamespace

from server.core import integrations
from server.model_output import ModelOutputError, parse_object


class DeliverableContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = {'id': 'sample', 'title': '测试交付', 'sections': [
            {'id': 'scope', 'title': '范围', 'instruction': '说明已知范围和边界'},
            {'id': 'acceptance', 'title': '验收', 'instruction': '给出可检查的验收条件'},
        ], 'limitations': ['仅基于用户资料，未运行客户端']}
        self.answer = {'sections': [{'id': 'scope', 'content': '关卡规则的静态分析'},
                                    {'id': 'acceptance', 'content': '检查需求中的边界'}],
                       'claims': [{'statement': '每局有三次机会', 'kind': 'fact', 'quote': '每局三次机会'}],
                       'risks': ['尚无源码证据'], 'next_actions': ['补充指定版本源码']}
        self.prompts = []

    def context(self, answers=None, inputs='需求原文：每局三次机会。'):
        answers = list(answers or [self.answer])
        def request(prompt):
            self.prompts.append(prompt)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return copy.deepcopy(answer)
        return SimpleNamespace(inputs=inputs, skill_content='# 用户导入规则\n不得虚构事实',
                               node_id='product:0', input_revision=2, model=SimpleNamespace(request_json=request))

    def generate(self, context):
        return integrations.generate_document(context, self.contract)

    def test_empty_input_or_skill_rejected_before_model_call(self):
        for field in ('inputs', 'skill_content'):
            with self.subTest(field=field):
                context = self.context()
                setattr(context, field, ' \n ')
                with self.assertRaisesRegex(ValueError, '输入|Skill'):
                    self.generate(context)
        self.assertEqual(self.prompts, [])

    def test_sections_render_in_contract_order_with_honest_quality_report(self):
        answer = copy.deepcopy(self.answer)
        answer['sections'].reverse()
        result = self.generate(self.context([answer]))
        self.assertLess(result['deliverable'].index('范围'), result['deliverable'].index('验收'))
        self.assertIn('未运行客户端', result['deliverable'])
        self.assertEqual(result['evidence'][0]['quote'], '每局三次机会')
        self.assertIn('尚无源码证据', result['gaps'])
        self.assertFalse(result['quality']['fact_checked'])
        self.assertEqual(result['quality']['source_quotes_checked'], 1)
        self.assertEqual(result['quality']['repair_attempts'], 0)
        self.assertIn('不得虚构事实', self.prompts[0])
        self.assertIn('每局三次机会', self.prompts[0])

    def test_missing_duplicate_unknown_empty_sections_get_only_one_repair(self):
        variants = [[], [self.answer['sections'][0]] * 2,
                    self.answer['sections'] + [{'id': 'invented', 'content': 'extra'}],
                    [{'id': 'scope', 'content': ' '}, self.answer['sections'][1]]]
        for sections in variants:
            with self.subTest(sections=sections):
                bad = {**self.answer, 'sections': sections}
                self.prompts.clear()
                result = self.generate(self.context([bad, self.answer]))
                self.assertEqual(len(self.prompts), 2)
                self.assertEqual(result['quality']['repair_attempts'], 1)
                self.assertIn('修正', self.prompts[1])
                self.prompts.clear()
                with self.assertRaisesRegex(ValueError, '交付结构|引用'):
                    self.generate(self.context([bad, bad]))
                self.assertEqual(len(self.prompts), 2)

    def test_unmatched_fact_quote_or_claim_kind_cannot_be_accepted(self):
        for claim in ({'statement': 'fake', 'kind': 'fact', 'quote': '全球收入十亿'},
                      {'statement': 'fake', 'kind': 'fact', 'quote': ''},
                      {'statement': 'fake', 'kind': 'verified', 'quote': ''}):
            with self.subTest(claim=claim):
                answer = {**self.answer, 'claims': [claim]}
                with self.assertRaises(ValueError):
                    self.generate(self.context([answer, answer]))

    def test_repair_identifies_claim_path_and_limits_quotes_to_inputs(self):
        bad = copy.deepcopy(self.answer)
        bad['claims'].append({'statement': '来自契约的限制', 'kind': 'fact',
                              'quote': self.contract['limitations'][0]})
        self.generate(self.context([bad, self.answer]))
        self.assertIn('claims[1].quote', self.prompts[1])
        self.assertIn('quote 只能逐字复制 inputs 字段', self.prompts[0])
        self.assertIn('Skill、契约和你自己生成的正文都不是输入原文', self.prompts[0])

    def test_no_claims_is_explicitly_recorded_as_evidence_gap(self):
        result = self.generate(self.context([{**self.answer, 'claims': []}]))
        self.assertEqual(result['evidence'], [])
        self.assertTrue(any('引用' in item for item in result['gaps']))

    def test_transport_failure_is_not_retried_as_structure_repair(self):
        with self.assertRaisesRegex(RuntimeError, 'network unavailable'):
            self.generate(self.context([RuntimeError('network unavailable')]))
        self.assertEqual(len(self.prompts), 1)

    def test_completed_malformed_json_gets_one_source_bound_repair(self):
        raw = '{"sections": [完整但JSON格式错误的模型正文]}'
        result = self.generate(self.context([ModelOutputError(raw, '不是合法JSON'), self.answer]))
        self.assertEqual(result['quality']['repair_attempts'], 1)
        self.assertEqual(len(self.prompts), 2)
        self.assertIn(raw, self.prompts[1])
        self.assertIn('每局三次机会', self.prompts[1])
        self.assertIn('不得虚构事实', self.prompts[1])

    def test_parse_and_contract_errors_share_one_repair_budget(self):
        malformed = ModelOutputError('private-raw-response', '不是合法JSON')
        bad_contract = {**self.answer, 'claims': [{'kind': 'fact', 'statement': '假事实', 'quote': '不存在'}]}
        for answers in ([malformed, malformed], [malformed, bad_contract], [bad_contract, malformed]):
            self.prompts.clear()
            with self.subTest(answers=[type(item).__name__ for item in answers]):
                with self.assertRaisesRegex(ValueError, '已修正1次') as caught:
                    self.generate(self.context(answers))
                self.assertNotIn('private-raw-response', str(caught.exception))
                self.assertEqual(len(self.prompts), 2)

    def test_oversized_invalid_json_is_not_sent_for_repair(self):
        with self.assertRaisesRegex(ValueError, '过大'):
            self.generate(self.context([ModelOutputError('x' * 500000, '不是合法JSON')]))
        self.assertEqual(len(self.prompts), 1)

    def test_actual_parser_failure_can_recover_without_accepting_bad_quotations(self):
        context = self.context()
        responses = iter(['{"sections":', json.dumps(self.answer, ensure_ascii=False)])
        def request(prompt):
            self.prompts.append(prompt)
            return parse_object(next(responses))
        context.model.request_json = request
        result = self.generate(context)
        self.assertEqual(result['quality']['repair_attempts'], 1)
        self.assertEqual(result['evidence'][0]['quote'], '每局三次机会')

    def test_wrong_list_shapes_and_oversized_result_rejected(self):
        for patch in ({'risks': 'bad'}, {'next_actions': []}, {'claims': 'bad'},
                      {'sections': [{'id': 'scope', 'content': 'a' * 810000}]}):
            with self.subTest(patch=list(patch)):
                bad = {**self.answer, **patch}
                with self.assertRaises(ValueError):
                    self.generate(self.context([bad, bad]))


if __name__ == '__main__':
    unittest.main()
