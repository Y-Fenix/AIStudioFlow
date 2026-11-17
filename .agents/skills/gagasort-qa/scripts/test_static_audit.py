#!/usr/bin/env python3
"""验证静态报告门禁；全部为渲染夹具，不运行或宣称测试过游戏。"""
from copy import deepcopy
import json
import re
from pathlib import Path
import tempfile
import unittest

import render_report as report


def fixture():
    trace = [{'path': 'Fixture.cs', 'line': 2, 'note': '仅用于校验源码定位，非产品证据'}]
    cases = [dict(id='case-' + str(i), dimension=dim, scenario='合成静态场景：' + dim,
                  preconditions='渲染测试夹具', input='合成输入', basis='模板字段约束',
                  expected='展示该场景结论', actual='渲染测试输入，非产品结果',
                  verdict='未见问题', trace=deepcopy(trace))
             for i, dim in enumerate(sorted(report.DIMENSIONS))]
    feature = dict(id='fixture', name='模板夹具', checks=[], source_paths=['Fixture.cs'],
                   related_findings=[], source_drift=[],
                   installation=dict(upgrade='合成输入', same_identity='合成输入', new_identity='合成输入', cause='只验证渲染'),
                   assessment=dict(code_review='完成静态审查', code_conclusion='模板夹具',
                                   verdict='局部检查未见问题', conclusion='只验证模板', run_ids=['blocked']),
                   display=dict(category='系统', group='渲染夹具', name='模板夹具', check_summary='非产品检查'),
                   static_audit=dict(status='已完成', summary='合成静态记录，非游戏测试结果', cases=cases))
    return dict(report_contract_version='2.1',
                presentation=dict(audit_mode='静态检查', overall='检查完成且范围内未见问题',
                                  conclusion='仅验证报告机制', execution_scope='合成模板输入',
                                  not_executed='未运行游戏', format_only=False, product_test_run_id='fixture',
                                  evidence_head='fixture', supplement_summary='没有产品测试'),
                baseline=dict(run_id='fixture', head='fixture'), external_change=dict(observed_head='fixture'),
                source_changed=[], features=[feature], findings=[],
                suites=[dict(id='blocked', status='环境受阻', command=['fixture-command'],
                             exit_code=1, reason='仅验证可选执行受阻不阻塞静态收口', summary='模板夹具', evidence='fixture.log')],
                additional_runs=[], configuration_cases=[], configuration_groups=[], configuration_fields=[],
                level_audit={key: dict(status='未检查', summary='不在此合成范围', evidence=[], run_ids=[])
                             for key in ['solvability', 'layout']})


class ModuleSummaryTests(unittest.TestCase):
    """只验证汇总归属和计数，不把报告测试当产品测试。"""
    def owner(self, id='f', category='系统', complete=True, tone='green', issues=None):
        return dict(id=id, category_plain=category, tone=tone, issue_ids=issues or [],
                    static_audit={'status': '已完成' if complete else '未完成'})

    def issue(self, id='i', category='系统', confirmed=True):
        return dict(id=id, category_plain=category, confirmed=confirmed)

    def test_unlinked_tracking_issues_are_visible(self):
        issues = [self.issue(str(i), '埋点') for i in range(3)]
        result = report.module_summaries([], [], issues, {}, True)['埋点']
        self.assertEqual(result['confirmed_ids'], ['0', '1', '2'])
        self.assertEqual(result['tone'], 'red')

    def test_category_and_references_union_deduplicates_root_causes(self):
        owners = [self.owner('f1', issues=['i', 'external']), self.owner('f2', issues=['i'])]
        issues = [self.issue(), self.issue('external', '配置'), self.issue('orphan')]
        result = report.module_summaries(owners, [], issues, {}, True)['系统']
        self.assertEqual(result['confirmed_ids'], ['i', 'external', 'orphan'])

    def test_confirmed_problem_does_not_hide_unchecked_branches(self):
        owner = self.owner(complete=False, tone='red', issues=['i'])
        result = report.module_summaries([owner], [], [self.issue()], {}, True)['系统']
        self.assertEqual(result['incomplete_refs'], ['feature-f'])
        self.assertEqual(result['confirmed_ids'], ['i'])
        self.assertEqual(result['clear_refs'], [])
        self.assertEqual(result['tone'], 'red')

    def test_pending_or_empty_module_is_never_green(self):
        owners = [self.owner(complete=False, tone='amber')]
        result = report.module_summaries(owners, [], [], {}, True)
        self.assertEqual(result['系统']['tone'], 'amber')
        self.assertEqual(result['配置']['tone'], 'amber')
        self.assertIn('不能下', result['系统']['headline'])

    def test_groups_and_features_both_count_and_source_drift_is_pending(self):
        owner = self.owner(category='配置', tone='amber')
        owner['source_drift'] = ['changed']
        group = self.owner('g')
        result = report.module_summaries([owner], [group], [], {}, True)['配置']
        self.assertEqual((result['feature_count'], result['config_group_count']), (1, 1))
        self.assertEqual(result['incomplete_refs'], ['feature-f'])
        self.assertEqual(result['clear_refs'], ['configcase-g'])

    def test_visual_risk_uses_unique_levels_not_risk_occurrences(self):
        level = {'risks': [{'level_id': '593'}, {'level_id': '593'}, {'level_id': '46'}]}
        result = report.module_summaries([], [], [], level, True)['关卡']
        self.assertEqual(result['visual_risk_count'], 2)
        self.assertEqual(result['confirmed_ids'], [])

    def test_level_failure_stays_red_even_when_function_review_is_green(self):
        level = {key: dict(status='检查完成未见问题', total=2, checked=2)
                 for key in ('layout', 'visual', 'solvability')}
        level['solvability']['status'] = '发现问题'
        owner = self.owner(category='关卡')
        result = report.module_summaries([owner], [], [], level, True)['关卡']
        self.assertEqual(result['tone'], 'red')
        self.assertIn('逐关检查发现问题', result['headline'])
        self.assertNotIn('范围内未发现问题', result['headline'])

    def test_complete_static_is_green_without_runtime_and_input_not_mutated(self):
        owner = self.owner()
        original = deepcopy(owner)
        result = report.module_summaries([owner], [], [], {}, True)['系统']
        self.assertEqual(result['tone'], 'green')
        self.assertEqual(result['clear_refs'], ['feature-f'])
        self.assertEqual(owner, original)


class StaticAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gagasort-report-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'sources').mkdir()
        (self.root / 'sources/Fixture.cs.txt').write_text('// 渲染夹具，非产品代码\nclass Fixture {}\n')
        (self.root / 'fixture.log').write_text('只用于测试报告门禁，未执行游戏测试。\n')
        self.data = fixture()

    def validate(self):
        report.validate(self.data, self.root)

    def reject(self):
        with self.assertRaises(ValueError):
            self.validate()

    def set_level_results(self):
        (self.root / 'levels').mkdir(exist_ok=True)
        (self.root / 'levels/level-inventory.json').write_text(json.dumps(
            {'levels': [{'level_id': '1'}, {'level_id': '2'}]}, ensure_ascii=False), encoding='utf-8')
        result_path = 'levels/layout-results.json'
        (self.root / result_path).write_text(json.dumps(
            {'schema_version': 1, 'inventory': 'levels/level-inventory.json', 'total': 2, 'checked': 2,
             'results': [dict(level_id=str(i), verdict='未见问题', checks=['边界'], evidence=['fixture.log'])
                         for i in (1, 2)]}, ensure_ascii=False), encoding='utf-8')
        entry = self.data['level_audit']['layout']
        entry.update(status='检查完成未见问题', summary='测试逐关结果门禁', total=2, checked=2,
                     evidence=['fixture.log'], result_file=result_path)
        self.data['level_audit']['inventory_file'] = 'levels/level-inventory.json'

    def test_static_complete_with_blocked_optional_run_is_green(self):
        self.validate()
        view = report.prepare_view(self.data)
        self.assertEqual(view['features'][0]['tone'], 'green')
        self.assertEqual(view['features'][0]['outcome'], '代码检查未见问题')
        self.assertEqual(view['features'][0]['assessment']['manual_readiness'], '无需人工')
        self.assertEqual(view['runs']['blocked']['status'], '环境受阻')

    def test_static_complete_does_not_require_any_runtime(self):
        self.data['features'][0]['assessment']['run_ids'] = []
        self.data['suites'] = []
        self.validate()

    def test_missing_ledger_is_rejected(self):
        del self.data['features'][0]['static_audit']
        self.reject()

    def test_missing_dimension_is_rejected(self):
        self.data['features'][0]['static_audit']['cases'].pop()
        self.reject()

    def test_pending_case_cannot_be_called_complete(self):
        self.data['features'][0]['static_audit']['cases'][0].update(verdict='待核实', reason='未读到调用者')
        self.reject()

    def test_incomplete_case_remains_brown(self):
        f = self.data['features'][0]
        self.data['presentation']['overall'] = '执行不完整'
        f['static_audit']['status'] = '未完成'
        f['static_audit']['cases'][0].update(verdict='未检查', reason='此调用分支尚未检查', trace=[])
        self.validate()
        self.assertEqual(report.prepare_view(self.data)['features'][0]['tone'], 'amber')

    def test_completed_case_requires_real_source_reference(self):
        self.data['features'][0]['static_audit']['cases'][0]['trace'] = []
        self.reject()

    def test_bad_source_line_is_rejected(self):
        self.data['features'][0]['static_audit']['cases'][0]['trace'][0]['line'] = 999
        self.reject()

    def test_all_not_applicable_cannot_be_green(self):
        for c in self.data['features'][0]['static_audit']['cases']:
            c.update(verdict='不适用', reason='合成不适用')
        self.reject()

    def test_completed_static_cannot_hide_an_unresolved_assessment(self):
        for verdict in ['证据不足', '风险待确认', '当前版本待复审']:
            with self.subTest(verdict=verdict):
                self.data['features'][0]['assessment']['verdict'] = verdict
                self.reject()

    def add_external(self):
        self.data['features'][0]['external_checks'] = [
            dict(id='external', assertion='真实平台是否允许某种事件顺序',
                 dependency='真实平台/SDK行为', why_not_local='本地代码只能证明处理分支，无法确定真实平台的发送合同',
                 local_case_ids=['case-0'], remaining_fact='平台的实际回调顺序合同')]

    def test_external_fact_keeps_local_static_green(self):
        self.add_external()
        self.validate()
        self.assertEqual(report.prepare_view(self.data)['features'][0]['tone'], 'green')

    def test_local_clock_cannot_be_sent_to_human(self):
        self.add_external()
        self.data['features'][0]['external_checks'][0]['dependency'] = '本地时间变化'
        self.reject()

    def test_external_fact_requires_completed_local_cases(self):
        self.add_external()
        self.data['features'][0]['external_checks'][0]['local_case_ids'] = []
        self.reject()

    def add_static_issue(self):
        f = self.data['features'][0]
        self.data['presentation']['overall'] = '检查完成且发现问题'
        issue = dict(id='fixture-defect', kind='静态缺陷已证', title='合成问题字段', status='静态已证',
                     condition='只用于渲染夹具', cause='仅校验静态证明字段', actual='合成实际', expected='合成预期',
                     impact='不是游戏缺陷', missing='本夹具未运行游戏',
                     display=dict(category='系统', title='渲染夹具问题', condition='合成条件', cause='合成原因',
                                  impact='不代表产品问题', expected='合成预期', actual='合成推导结果'),
                     static_proof=dict(basis='模板约束', preconditions='合成初态', entry='Fixture',
                                       contradiction='仅用于验证证明结构', steps=['核对夹具源码与推导结构'],
                                       trace=deepcopy(f['static_audit']['cases'][0]['trace'])))
        self.data['findings'] = [issue]
        f['related_findings'] = ['fixture-defect']
        f['assessment']['verdict'] = '发现静态缺陷'
        f['static_audit']['cases'][0].update(verdict='发现问题', finding_ids=['fixture-defect'])

    def test_static_proof_can_be_red_without_fake_dynamic_log(self):
        self.add_static_issue()
        self.validate()
        view = report.prepare_view(self.data)
        self.assertEqual(view['features'][0]['tone'], 'red')
        self.assertEqual(view['issues'][0]['confirmation_label'], '静态已证 · 未动态运行')

    def test_static_issue_requires_proof(self):
        self.add_static_issue()
        del self.data['findings'][0]['static_proof']
        self.reject()

    def test_dynamic_issue_still_requires_execution_log(self):
        self.add_static_issue()
        self.data['findings'][0]['kind'] = '方法问题已证'
        self.reject()

    def test_unverified_risk_cannot_be_a_confirmed_case(self):
        self.add_static_issue()
        self.data['findings'][0]['kind'] = '风险或待确认'
        self.reject()

    def test_source_drift_is_not_silently_green(self):
        f = self.data['features'][0]
        f['source_drift'] = ['Fixture.cs']
        f['assessment']['verdict'] = '当前版本待复审'
        self.data['presentation']['overall'] = '执行不完整'
        self.validate()
        self.assertEqual(report.prepare_view(self.data)['features'][0]['tone'], 'amber')

    def test_configuration_can_finish_statically_without_running(self):
        self.data['configuration_cases'] = [{'name': '合成配置边界'}]
        self.data['configuration_groups'] = [dict(id='config', name='配置夹具', status='代码检查未见问题',
                                                 conclusion='仅验证模板', case_indices=[0], run_ids=[], issue_ids=[],
                                                 static_audit=dict(status='已完成', summary='合成配置输入',
                                                                   cases=[deepcopy(self.data['features'][0]['static_audit']['cases'][0])]))]
        self.validate()
        self.assertEqual(report.prepare_view(self.data)['config_groups'][0]['tone'], 'green')

    def test_configuration_risk_cannot_be_promoted_to_confirmed_problem(self):
        self.add_static_issue()
        self.data['findings'][0]['kind'] = '风险或待确认'
        f = self.data['features'][0]
        f['related_findings'] = []
        f['assessment']['verdict'] = '局部检查未见问题'
        case = deepcopy(f['static_audit']['cases'][0])
        f['static_audit']['cases'][0].update(verdict='未见问题', finding_ids=[])
        self.data['configuration_cases'] = [{'name': '合成配置边界'}]
        self.data['configuration_groups'] = [dict(id='config', name='配置夹具', status='有风险待核实',
                                                 conclusion='未证风险', case_indices=[0], run_ids=[],
                                                 issue_ids=['fixture-defect'],
                                                 static_audit=dict(status='已完成', summary='合成配置输入', cases=[case]))]
        self.reject()

    def test_render_keeps_static_fields_and_optional_run_separate(self):
        template = Path(__file__).resolve().parents[1] / 'assets/report-template.html'
        manifest = report.render(self.data, self.root, self.root / 'report.html', template)
        self.assertEqual(manifest['report_contract_version'], '2.1')
        content = (self.root / 'report.html').read_text()
        self.assertIn('staticCasesBlock', content)
        self.assertIn('合成静态记录', content)
        self.assertNotIn('__PAYLOAD__', content)

    def test_gap_plain_is_exposed_for_incomplete_depth(self):
        self.data['features'][0]['static_audit']['depth'] = {
            'protocol': 'deep-v2',
            'branches': [],
            'coverage': [
                {'dimension': '边界与异常', 'status': '未检查', 'branch_ids': [],
                 'case_ids': [], 'gap': '尚未读取取消后的回滚分支'},
            ],
        }
        view = report.prepare_view(self.data)
        self.assertIn('边界与异常：尚未读取取消后的回滚分支', view['features'][0]['gap_plain'])

    def test_multi_agent_v2_depth_requires_case_branch_closure(self):
        f = self.data['features'][0]
        cases = f['static_audit']['cases']
        branches = []
        coverage = []
        for i, c in enumerate(cases):
            bid = f'branch-{i}'
            c['branch_ids'] = [bid]
            branches.append({'id': bid, 'dimension': c['dimension'],
                             'condition': '夹具条件', 'consumer': '夹具消费者',
                             'evidence': deepcopy(c['trace'])})
            coverage.append({'dimension': c['dimension'], 'status': '已闭合',
                             'branch_ids': [bid], 'case_ids': [c['id']]})
        f['static_audit']['depth'] = {'protocol': 'deep-v2', 'branches': branches,
                                      'coverage': coverage}
        self.data['agent_audit'] = {'protocol': 'multi-agent-v2'}
        self.validate()
        f['static_audit']['cases'][0]['branch_ids'] = []
        self.reject()

    def test_completed_level_audit_requires_per_level_result_file(self):
        self.set_level_results()
        self.data['level_audit']['solvability'].update(status='检查完成未见问题', summary='测试',
                                                       total=2, checked=2, evidence=['fixture.log'],
                                                       result_file='levels/solvability-results.json')
        self.reject()

    def test_level_result_count_must_match_unique_results(self):
        self.set_level_results()
        result = json.loads((self.root / 'levels/layout-results.json').read_text(encoding='utf-8'))
        result['results'].pop()
        (self.root / 'levels/layout-results.json').write_text(json.dumps(result), encoding='utf-8')
        self.reject()

    def test_completed_level_audit_must_match_inventory(self):
        self.set_level_results()
        result = json.loads((self.root / 'levels/layout-results.json').read_text(encoding='utf-8'))
        result['results'][1]['level_id'] = '3'
        (self.root / 'levels/layout-results.json').write_text(json.dumps(result), encoding='utf-8')
        self.reject()

    def test_partial_levels_retain_unresolved_rows_without_counting_them_passed(self):
        self.set_level_results()
        path = self.root / 'levels/layout-results.json'
        result = json.loads(path.read_text())
        result['results'][1]['verdict'] = '未定'
        result['checked'] = 1
        path.write_text(json.dumps(result))
        entry = self.data['level_audit']['layout']
        entry.update(status='检查未完成', checked=1)
        self.validate()
        entry['status'] = '检查完成未见问题'
        self.reject()

    def test_layout_sample_cannot_claim_a_level_outside_inventory(self):
        self.set_level_results()
        (self.root / 'sample.png').write_bytes(b'fixture')
        self.data['level_audit']['samples'] = [dict(level_id='missing', caption='示例',
            image='sample.png', evidence='fixture.log')]
        self.reject()

    def set_pipeline2(self, risk=False, unresolved=False):
        self.set_level_results()
        level = self.data['level_audit']
        level['pipeline_version'] = 2
        self.data['presentation']['overall'] = '执行不完整' if risk or unresolved else '检查完成且范围内未见问题'
        solver_path = 'levels/solvability-results.json'
        solver = json.loads((self.root / 'levels/layout-results.json').read_text())
        if unresolved:
            solver['results'][1]['verdict'] = '未定'
            solver['checked'] = 1
        (self.root / solver_path).write_text(json.dumps(solver))
        level['solvability'] = dict(status='检查未完成' if unresolved else '检查完成未见问题',
            summary='合成求解结果', total=2, checked=solver['checked'], evidence=['fixture.log'], result_file=solver_path)
        visual_path = 'levels/visual-summary.json'
        visual = dict(schema_version=1, inventory=level['inventory_file'], total=2, checked=2,
            results=[dict(level_id=str(i), verdict='风险待确认' if risk and i == 1 else '未见问题',
                wall_risk=risk and i == 1, water_risk=False, checks=[], evidence=['fixture.log']) for i in (1, 2)])
        (self.root / visual_path).write_text(json.dumps(visual))
        level['visual'] = dict(status='有风险待确认' if risk else '检查完成未见问题', summary='合成视觉结果',
            total=2, checked=2, result_file=visual_path, evidence=['fixture.log'], wall_risk_count=int(risk), water_risk_count=0)
        level['summary_rows'] = [dict(id=key, name=key, status='有风险待确认' if risk and key == 'wall' else
            '检查未完成' if unresolved and key == 'solver' else '检查完成未见问题',
            summary='合成汇总', evidence=['fixture.log']) for key in ['structure', 'package', 'solver', 'wall', 'water']]
        level['table'] = [dict(level_id=str(i), number=i, structure='未见问题', layout='未见问题',
            solvability='Timeout：合成预算耗尽' if unresolved and i == 2 else '已回放通关',
            visual=visual['results'][i-1]['verdict'], evidence='fixture.log') for i in (1, 2)]
        if risk:
            # A valid 1×1 PNG. This is explicitly synthetic report test data.
            import base64
            (self.root / 'risk.png').write_bytes(base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='))
            level['risks'] = [dict(level_id='1', caption='合成风险图', image='risk.png', evidence='fixture.log',
                steps=['仅校验报告回链，不是产品测试结果'], kind='visual-risk')]

    def edit_visual(self, edit):
        path = self.root / self.data['level_audit']['visual']['result_file']
        result = json.loads(path.read_text())
        edit(result)
        path.write_text(json.dumps(result))

    def test_pipeline2_complete_has_three_dimensions(self):
        self.set_pipeline2()
        self.validate()
        self.assertEqual(report.level_progress(self.data['level_audit']),
            dict(done=3, total=3, tone='green', summary='有解性、布局与视觉均有逐关结果'))

    def test_pipeline2_risk_is_amber_and_never_a_confirmed_issue(self):
        self.set_pipeline2(risk=True)
        self.validate()
        view = report.prepare_view(self.data)
        self.assertEqual(view['level_progress']['tone'], 'amber')
        self.assertEqual(view['level_progress']['done'], 3)
        self.assertEqual(view['issues'], [])
        self.data['presentation']['overall'] = '检查完成且范围内未见问题'
        self.reject()

    def test_solver_timeout_does_not_count_as_completed(self):
        self.set_pipeline2(unresolved=True)
        self.validate()
        self.assertEqual(report.level_progress(self.data['level_audit'])['done'], 2)
        self.assertEqual(report.level_progress(self.data['level_audit'])['tone'], 'amber')
        self.data['presentation']['overall'] = '检查完成且范围内未见问题'
        self.reject()

    def test_pipeline2_missing_sections_are_rejected(self):
        for key in ['visual', 'summary_rows', 'table']:
            with self.subTest(key=key):
                self.set_pipeline2()
                del self.data['level_audit'][key]
                self.reject()

    def test_pipeline2_summary_must_have_all_five_checks(self):
        self.set_pipeline2()
        self.data['level_audit']['summary_rows'].pop()
        self.reject()

    def test_package_problem_cannot_hide_behind_three_completed_dimensions(self):
        self.set_pipeline2()
        self.data['level_audit']['summary_rows'][1]['status'] = '发现问题'
        self.assertEqual(report.level_progress(self.data['level_audit'])['tone'], 'red')
        self.reject()

    def test_unfinished_solver_or_visual_cannot_claim_green_summary(self):
        for key in ['solver', 'water']:
            with self.subTest(key=key):
                if key == 'solver':
                    self.set_pipeline2(unresolved=True)
                else:
                    self.set_pipeline2(risk=True)
                    self.data['level_audit']['visual']['checked'] = 1
                    self.edit_visual(lambda r: (r.update(checked=1), r['results'][1].update(verdict='未定')))
                    self.data['level_audit']['visual']['status'] = '检查未完成'
                    self.data['level_audit']['table'][1]['visual'] = '未定'
                next(r for r in self.data['level_audit']['summary_rows'] if r['id'] == key)['status'] = '检查完成未见问题'
                self.reject()

    def test_visual_id_set_must_match_inventory(self):
        for wrong in ['1', 'outside']:
            with self.subTest(wrong=wrong):
                self.set_pipeline2()
                self.edit_visual(lambda r: r['results'][1].update(level_id=wrong))
                self.reject()

    def test_visual_counts_are_recomputed_from_results(self):
        self.set_pipeline2()
        self.data['level_audit']['visual']['checked'] = 1
        self.reject()

    def test_visual_risk_types_are_counted_separately(self):
        self.set_pipeline2(risk=True)
        self.data['level_audit']['visual'].update(wall_risk_count=0, water_risk_count=1)
        self.reject()

    def test_nonflat_unresolved_can_keep_partial_risk_without_becoming_complete(self):
        self.set_pipeline2(risk=True)
        self.edit_visual(lambda r: (r.update(checked=1), r['results'][0].update(verdict='未定',
            errors=['合成非平面夹具：尚无三维岸壁判定'])))
        level = self.data['level_audit']
        level['visual'].update(status='检查未完成', checked=1)
        level['table'][0]['visual'] = '未定'
        for row in level['summary_rows']:
            if row['id'] == 'water':
                row['status'] = '检查未完成'
        self.validate()
        self.assertEqual(report.level_progress(level)['done'], 2)
        self.assertEqual(report.level_progress(level)['tone'], 'amber')
        level['visual']['status'] = '检查完成未见问题'
        self.reject()

    def test_visual_result_must_reference_this_inventory(self):
        self.set_pipeline2()
        self.edit_visual(lambda r: r.update(inventory='levels/other-inventory.json'))
        self.reject()

    def test_risk_requires_matching_result_evidence_and_image(self):
        for mutation in ['wrong-id', 'wrong-evidence', 'missing-image', 'missing-risk']:
            with self.subTest(mutation=mutation):
                self.set_pipeline2(risk=True)
                risk = self.data['level_audit']['risks'][0]
                if mutation == 'wrong-id':
                    risk['level_id'] = '2'
                elif mutation == 'wrong-evidence':
                    risk['evidence'] = 'sources/Fixture.cs.txt'
                elif mutation == 'missing-image':
                    risk['image'] = 'missing.png'
                else:
                    self.data['level_audit']['risks'] = []
                self.reject()

    def test_table_cannot_turn_unresolved_solver_green(self):
        self.set_pipeline2(unresolved=True)
        self.data['level_audit']['table'][1]['solvability'] = '已回放通关'
        self.reject()

    def test_table_cannot_hide_visual_risk(self):
        self.set_pipeline2(risk=True)
        self.data['level_audit']['table'][0]['visual'] = '未见问题'
        self.reject()

    def test_render_embeds_risk_image_but_leaves_large_intermediates_external(self):
        self.set_pipeline2(risk=True)
        for name in ['solver-input.json', 'solver-kernel.json', 'visual-kernel.json']:
            (self.root / 'levels' / name).write_text('{"synthetic": true}')
        template = Path(__file__).resolve().parents[1] / 'assets/report-template.html'
        report.render(self.data, self.root, self.root / 'report.html', template)
        html = (self.root / 'report.html').read_text()
        payload = json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(payload['assets']['risk.png']['mime'], 'image/png')
        self.assertIn('levels/visual-summary.json', payload['assets'])
        self.assertNotIn('levels/solver-input.json', payload['assets'])
        self.assertNotIn('levels/solver-kernel.json', payload['assets'])
        self.assertNotIn('levels/visual-kernel.json', payload['assets'])

    def test_risk_gallery_categories_follow_results_not_caption(self):
        for kinds in (['wall'], ['water'], ['wall', 'water']):
            with self.subTest(kinds=kinds):
                self.set_pipeline2(risk=True)
                level = self.data['level_audit']
                level['risks'][0]['caption'] = '无法根据标题推断类别的合成图'
                level['risks'][0]['risk_types'] = ['untrusted']
                self.edit_visual(lambda result: result['results'][0].update(
                    wall_risk='wall' in kinds, water_risk='water' in kinds))
                level['visual'].update(wall_risk_count=int('wall' in kinds), water_risk_count=int('water' in kinds))
                for row in level['summary_rows']:
                    if row['id'] in ('wall', 'water'):
                        row['status'] = '有风险待确认' if row['id'] in kinds else '检查完成未见问题'
                template = Path(__file__).resolve().parents[1] / 'assets/report-template.html'
                output = self.root / 'report.html'
                report.render(self.data, self.root, output, template)
                payload = json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>', output.read_text(), re.S).group(1))
                self.assertEqual(payload['level_audit']['risks'][0]['risk_types'], kinds)
                self.assertEqual(level['risks'][0]['risk_types'], ['untrusted'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
