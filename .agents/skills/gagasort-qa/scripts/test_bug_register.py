"""Synthetic export/render tests, never project audit results."""
from copy import deepcopy
import csv
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bug_register import build_register, register_csv, static_description
from finalize_report import export_results
from test_static_audit import fixture
import render_report

HEADERS = ['缺陷描述', '期望描述', '日志信息', '截图/视频', '版本号', '滞留时长(天)', '创建人',
           '操作平台', '缺陷状态', '严重程度', '优先级', '问题类型', '复现率', '功能模块', '修复人',
           '发现Jenkins构建号', '验收Jenkins构建号', '验收图片/视频', '验收备注', '创建时间', '状态更新时间', '父记录', '父记录 2']


def finding(kind='静态缺陷已证', id='fixture-bug'):
    return dict(id=id, kind=kind, missing='仅用于导出测试，不是真实缺陷', source_drift=[],
                display=dict(category='系统', title='中文与逗号,以及"引号"', condition='合成输入',
                             cause='合成归因', impact='不代表产品问题', actual='合成实际', expected='合成预期'),
                static_proof=dict(preconditions='合成初态', entry='合成入口', basis='测试设定',
                                  contradiction='合成矛盾', steps=['第一步\n同一步的补充行', '第二步'],
                                  trace=[dict(path='Fixture.cs', line=2, note='合成源码')]))


class BugRegisterTests(unittest.TestCase):
    def parse(self, register):
        result = register_csv(register)
        self.assertTrue(result.startswith('\ufeff'))
        return list(csv.reader(io.StringIO(result.lstrip('\ufeff'), newline='')))

    def test_empty_results_still_export_all_23_original_headers(self):
        register = build_register([])
        self.assertEqual(register['headers'], HEADERS)
        self.assertEqual(self.parse(register), [HEADERS])

    def test_only_confirmed_root_causes_not_risks_or_duplicate_ids(self):
        item = finding()
        register = build_register([item, finding('风险或待确认', 'risk'), deepcopy(item), finding('方法问题已证', 'method')])
        self.assertEqual([r['id'] for r in register['rows']], ['fixture-bug', 'method'])
        self.assertIn('玩家入口待核', register['rows'][1]['fields']['缺陷描述'])

    def test_static_steps_and_proof_remain_readable_without_fake_blackbox(self):
        original = finding()
        before = deepcopy(original)
        row = build_register([original])['rows'][0]
        body = row['fields']['缺陷描述']
        for text in ['静态已证 · 未动态运行', '白盒静态推导', '第一步', '合成归因', '合成实际', '合成初态', '合成入口', '合成矛盾']:
            self.assertIn(text, body)
        self.assertTrue(body.startswith('【静态检测】'))
        self.assertNotIn('黑盒', body)
        self.assertIn('Fixture.cs:2', row['fields']['日志信息'])
        self.assertEqual(original, before)

    def test_full_blackbox_preserves_observations_restore_and_whitebox(self):
        item = finding()
        item.update(manual_readiness='完整待执行', manual=dict(prepare='合成准备', steps=[dict(action='点合成按钮', observe='观察合成状态')],
                                                        restore='恢复合成输入', abnormal='合成异常判据'))
        body = build_register([item])['rows'][0]['fields']['缺陷描述']
        for text in ['操作步骤（黑盒）', '点合成按钮', '观察合成状态', '补充白盒核查', '第一步', '恢复合成输入', '合成异常判据', '玩家操作步骤尚未执行']:
            self.assertIn(text, body)

    def test_unknown_fields_remain_blank_and_known_metadata_is_preserved(self):
        item = finding()
        item['bug_fields'] = {'版本号': '实际提供的新版本', '操作平台': 'iOS', '功能模块': '【多语言】'}
        item['source_drift'] = ['changed']
        fields = build_register([item])['rows'][0]['fields']
        self.assertEqual(fields['版本号'], 'Codex')
        self.assertEqual(fields['操作平台'], 'iOS')
        self.assertIn('当前版本待复核', fields['缺陷描述'])
        for key in ['修复人', '创建人', '创建时间', '状态更新时间', '滞留时长(天)', '严重程度', '优先级',
                    '发现Jenkins构建号', '验收Jenkins构建号', '父记录', '父记录 2']:
            self.assertEqual(fields[key], '')

    def test_csv_retains_empty_columns_multiline_quotes_and_chinese(self):
        item = finding()
        register = build_register([item])
        rows = self.parse(register)
        self.assertEqual(len(rows[1]), 23)
        self.assertEqual(rows[1][HEADERS.index('版本号')], 'Codex')
        self.assertIn('中文与逗号,以及"引号"', rows[1][0])
        self.assertIn('第一步\r\n同一步的补充行', rows[1][0])
        self.assertEqual(rows[1][HEADERS.index('修复人')], '')

    def test_csv_cannot_turn_supplied_cells_into_spreadsheet_formulas(self):
        for value in ['=1+1', '+SUM(A1)', '-1+2', '@SUM(A1)', '\t=1', '\n=1', '  =1']:
            item = finding()
            item['bug_fields'] = {'操作平台': value}
            cell = self.parse(build_register([item]))[1][HEADERS.index('操作平台')]
            self.assertTrue(cell.startswith("'"))

    def test_metadata_cannot_overwrite_evidence_or_invent_acceptance(self):
        for key in ['缺陷描述', '创建人', '验收备注', 'unknown']:
            item = finding()
            item['bug_fields'] = {key: 'invented'}
            with self.assertRaises(ValueError):
                build_register([item])

    def test_static_prefix_is_idempotent(self):
        self.assertEqual(static_description('【静态检测】已有前缀'), '【静态检测】已有前缀')
        self.assertEqual(static_description('新内容'), '【静态检测】新内容')

    def test_ticket_has_four_sections_and_numbered_actions(self):
        row = build_register([finding()])['rows'][0]
        body = row['fields']['缺陷描述']
        for title in ['前置条件：', '操作步骤', '当前错误表现：合成实际', '预期正确表现：合成预期', '未真机复现']:
            self.assertIn(title, body)
        self.assertIn('1、第一步', body)
        self.assertEqual(row['detail']['expected'], '合成预期')
        self.assertEqual(row['fields']['复现率'], '')

    def test_incomplete_ticket_copy_cannot_be_exported(self):
        item = finding()
        item['display']['expected'] = ''
        with self.assertRaisesRegex(ValueError, '预期正确表现'):
            build_register([item])

    def test_html_payload_and_companion_csv_use_same_rows_and_bytes(self):
        data = fixture()
        data['baseline'].update(head='fixture', branch='fixture')
        data['findings'] = [finding()]
        data['level_audit']['visual'] = dict(summary='未执行游戏')
        view = render_report.prepare_view(data)
        with TemporaryDirectory() as folder:
            export_results(data, Path(folder))
            self.assertEqual((Path(folder) / 'bugs.csv').read_bytes(), view['bug_register']['csv'].encode('utf-8'))
        self.assertEqual(view['bug_register']['headers'], HEADERS)
        self.assertEqual(len(view['bug_register']['rows']), 1)


if __name__ == '__main__':
    unittest.main()
