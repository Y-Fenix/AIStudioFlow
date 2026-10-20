import copy
import unittest
from server.requirements import validate_cases


class CaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.requirements = [{'id': 'r1', 'content': '关闭后保存状态'}]
        self.output = {'points': [{'id': 'p1', 'requirement_id': 'r1', 'quote': '关闭后保存状态', 'title': '状态保存'}],
            'cases': [{'id': 'c1', 'title': '关闭后重启', 'point_ids': ['p1'],
                       'preconditions': ['已打开开关'], 'steps': [{'action': '关闭并重启', 'expected': '仍为关闭'}]}],
            'gaps': [], 'ambiguities': []}

    def test_valid_output_and_explicit_gap(self):
        result = validate_cases(self.output, self.requirements)
        self.assertEqual(result['coverage']['covered'], 1)
        output = copy.deepcopy(self.output)
        output['cases'] = []
        output['gaps'] = [{'point_id': 'p1', 'reason': '没有可运行设备'}]
        self.assertEqual(validate_cases(output, self.requirements)['coverage']['covered'], 0)

    def test_missing_or_fabricated_evidence_is_rejected(self):
        for mutation in ('source', 'quote', 'expected', 'coverage'):
            with self.subTest(mutation=mutation):
                output = copy.deepcopy(self.output)
                if mutation == 'source': output['points'][0]['requirement_id'] = 'fake'
                if mutation == 'quote': output['points'][0]['quote'] = '不存在的正文'
                if mutation == 'expected': output['cases'][0]['steps'][0]['expected'] = ''
                if mutation == 'coverage': output['cases'] = []
                with self.assertRaises(ValueError): validate_cases(output, self.requirements)

    def test_silently_omitted_requirement_is_rejected(self):
        requirements = self.requirements + [{'id': 'r2', 'content': '重启后保持状态'}]
        with self.assertRaisesRegex(ValueError, '需求来源未拆解'):
            validate_cases(self.output, requirements)
