#!/usr/bin/env python3
"""Validate the report contract and render offline HTML. Never executes product tests."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from bug_register import build_register, register_csv

VERSION = '2.1'
VERDICTS = {'发现静态缺陷', '发现方法级问题', '发现产品问题', '风险待确认', '局部检查未见问题', '证据不足', '当前版本待复审'}
CODE = {'未审查', '局部静态审查', '完成静态审查'}
MANUAL = {'无需人工', '步骤草案', '完整待执行', '已执行'}
OVERALL = {'执行不完整', '检查完成且发现问题', '检查完成且范围内未见问题'}
CATEGORIES = {'玩法', '关卡', '系统', '配置', '埋点'}
LEVEL_STATUS = {'未检查', '检查未完成', '检查完成未见问题', '发现问题'}
LEVEL_GREEN = {'未见问题', '检查完成未见问题', '有解', '通过', '已回放通关'}
CONFIG_STATUS = {'未检查', '测试未完成', '代码检查未见问题', '局部测试通过', '有风险待核实', '发现问题'}
CONFIRMED = {'静态缺陷已证', '方法问题已证', '产品问题已证'}
DIMENSIONS = {'入口与正常链路', '边界与异常', '重复与异步', '状态与持久化', '配置变化', '升级与重装', '跨模块影响'}
CASE_VERDICTS = {'未见问题', '发现问题', '待核实', '未检查', '不适用'}
EXTERNAL = {'真实设备表现', '真实平台/SDK行为', '真实服务端合同或下发', '可信已发布版本差异'}
DEPTH_STATUSES = {'已闭合', '部分闭合', '未检查', '不适用'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def nonempty(obj, keys, where):
    for key in keys:
        require(key in obj and obj[key] is not None and obj[key] != '', f'{where}: 缺少 {key}')


def unique(items, where):
    ids = [x['id'] for x in items]
    require(len(ids) == len(set(ids)), where + ': ID重复')
    return set(ids)


def validate_manual(owner, readiness, missing, evidence_dir, tag):
    require(readiness in MANUAL, tag + ': 黑盒状态无效')
    if readiness == '无需人工':
        require(not owner.get('manual'), tag + ': 无需人工不能同时塞入人工待执行步骤')
        return
    if readiness == '步骤草案':
        require(bool(missing), tag + ': 草案缺少具体缺口')
        return
    m = owner.get('manual', {})
    require(isinstance(m, dict), tag + ': 缺黑盒结构')
    nonempty(m, ['prepare', 'steps', 'abnormal', 'restore', 'status'], tag + ': 黑盒')
    require(isinstance(m['steps'], list) and bool(m['steps']), tag + ': 缺黑盒步骤')
    require(all(isinstance(s, dict) and s.get('action') and s.get('observe') for s in m['steps']), tag + ': 黑盒步骤不完整')
    if readiness == '已执行':
        nonempty(m, ['evidence'], tag + ': 已执行黑盒')
        require((evidence_dir / m['evidence']).is_file(), tag + ': 缺人工执行证据')
        require(all(s.get('actual') for s in m['steps']), tag + ': 缺每步实际观察')


def source_artifact(path):
    return '/'.join(path.split('/')[3:]) if path.startswith('QA/') else 'sources/' + path + '.txt'


def validate_trace(trace, evidence_dir, tag):
    require(isinstance(trace, list) and bool(trace), tag + ': 缺源码推导链')
    for node in trace:
        nonempty(node, ['path', 'line', 'note'], tag + ': 推导节点')
        source = evidence_dir / source_artifact(node['path'])
        require(source.is_file(), tag + ': 缺源码快照 ' + node['path'])
        count = len(source.read_text(errors='replace').splitlines())
        require(type(node['line']) is int and 0 < node['line'] <= count, tag + ': 源码行号无效')
        if 'end_line' in node:
            require(type(node['end_line']) is int and node['line'] <= node['end_line'] <= count, tag + ': 源码行尾无效')


def validate_level_visual(level, inventory_ids, evidence_dir):
    """Keep geometric risks separate from confirmed layout defects."""
    visual = level.get('visual')
    pipeline2 = level.get('pipeline_version') == 2
    if visual is None:
        require(not pipeline2, 'pipeline2 缺少 visual 检查')
        return
    nonempty(visual, ['status', 'summary', 'result_file'], 'level_audit.visual')
    require(visual['status'] in {'检查完成未见问题', '检查未完成', '有风险待确认'}, '视觉检查状态无效')
    result_path = evidence_dir / visual['result_file']
    require(result_path.is_file(), '缺少逐关视觉结果文件')
    result = json.loads(result_path.read_text(encoding='utf-8'))
    require(result.get('schema_version') == 1, '视觉结果 schema_version 必须为 1')
    items = result.get('results')
    require(isinstance(items, list), '视觉结果缺 results 数组')
    ids = [str(x.get('level_id', '')) for x in items]
    require(all(ids) and len(ids) == len(set(ids)), '视觉结果含空/重复 level_id')
    require(inventory_ids is not None and set(ids) == set(inventory_ids), '视觉结果必须覆盖全部枚举 ID')
    require(type(visual.get('total')) is int and visual['total'] == len(inventory_ids), '视觉 total 与枚举不一致')
    for item in items:
        nonempty(item, ['level_id', 'verdict', 'checks', 'evidence'], '逐关视觉结果')
        require(item['verdict'] in {'未见问题', '风险待确认', '未定'}, '逐关视觉 verdict 无效')
        require(isinstance(item['checks'], list) and isinstance(item['evidence'], list), '视觉 checks/evidence 须为数组')
        require(bool(item['evidence']) and all((evidence_dir / p).is_file() for p in item['evidence']), '逐关视觉缺可读证据')
        if pipeline2:
            require(all(type(item.get(k + '_risk')) is bool for k in ['wall', 'water']), '逐关视觉缺墙/水风险布尔值')
            has_risk = item['wall_risk'] or item['water_risk']
            require((has_risk and item['verdict'] in {'风险待确认', '未定'})
                    or (not has_risk and item['verdict'] in {'未见问题', '未定'}), '视觉风险布尔值与结论不符')
    checked = sum(x['verdict'] != '未定' for x in items)
    require(type(visual.get('checked')) is int and visual['checked'] == checked, '视觉 checked 与明确结论数不符')
    for key in ['total', 'checked']:
        require(result.get(key) == visual[key], '视觉汇总数量与结果文件不符: ' + key)
    require(result.get('inventory') == level.get('inventory_file'), '视觉结果未引用本轮清单')
    require(bool(visual.get('evidence')) and all((evidence_dir / p).is_file() for p in visual['evidence']), '视觉结论缺执行证据')
    risk_ids = {str(x['level_id']) for x in items if x['verdict'] == '风险待确认'
                or x.get('wall_risk') or x.get('water_risk')}
    if visual['status'] == '检查完成未见问题':
        require(checked == visual['total'] and not risk_ids, '视觉无问题结论含风险或未定')
    if visual['status'] == '有风险待确认':
        require(bool(risk_ids), '视觉风险状态没有风险关卡')
    for key in ['wall_risk_count', 'water_risk_count']:
        require(type(visual.get(key)) is int and 0 <= visual[key] <= len(risk_ids), '视觉风险计数无效: ' + key)
        if pipeline2:
            require(visual[key] == sum(item[key.replace('_count', '')] for item in items), '视觉分类风险计数与逐关结果不符: ' + key)
    require(max(visual['wall_risk_count'], visual['water_risk_count']) <= len(risk_ids)
            <= visual['wall_risk_count'] + visual['water_risk_count'], '视觉两类风险计数无法覆盖风险关卡')
    linked = set()
    for risk in level.get('risks', []):
        nonempty(risk, ['level_id', 'caption', 'image', 'evidence', 'steps', 'kind'], '视觉风险图')
        rid = str(risk['level_id'])
        require(risk['kind'] == 'visual-risk' and rid in risk_ids, '风险图未回链同关视觉风险结果')
        require(Path(risk['image']).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}
                and (evidence_dir / risk['image']).is_file(), '视觉风险缺真实位图')
        require((evidence_dir / risk['evidence']).is_file() and isinstance(risk['steps'], list)
                and bool(risk['steps']), '视觉风险缺证据或核查步骤')
        matched = next(x for x in items if str(x['level_id']) == rid)
        require(risk['evidence'] in matched['evidence'], '风险图证据未回链逐关视觉证据')
        linked.add(rid)
    require(linked == risk_ids, '视觉风险关卡缺风险图与证据回链')
    if not pipeline2:
        return
    summaries = level.get('summary_rows')
    require(isinstance(summaries, list) and len(summaries) == 5, 'pipeline2 缺五项检查汇总')
    require(unique(summaries, '关卡五项汇总') == {'structure', 'package', 'solver', 'wall', 'water'}, 'pipeline2 五项汇总 ID 不完整')
    for row in summaries:
        nonempty(row, ['id', 'name', 'status', 'summary', 'evidence'], '关卡汇总')
        require(row['status'] in LEVEL_STATUS | {'有风险待确认'}, '关卡汇总状态无效')
        require(isinstance(row['evidence'], list) and bool(row['evidence'])
                and all((evidence_dir / p).is_file() for p in row['evidence']), '关卡汇总缺证据')
        green = row['status'] in LEVEL_GREEN
        if row['id'] == 'solver' and green:
            require(level['solvability']['status'] == '检查完成未见问题', '求解未完成不能显示全绿')
        if row['id'] in {'wall', 'water'} and green:
            require(checked == visual['total'] and visual[row['id'] + '_risk_count'] == 0, '视觉未完成或有风险不能显示全绿')
    table = level.get('table')
    require(isinstance(table, list), 'pipeline2 缺逐关表')
    tids = [str(x.get('level_id', '')) for x in table]
    require(len(tids) == len(set(tids)) and set(tids) == set(inventory_ids), '逐关表与枚举 ID 不一致')
    visual_by_id = {str(item['level_id']): item for item in items}
    results_by_key = {}
    for key in ['layout', 'solvability']:
        path = level[key].get('result_file')
        require(path and (evidence_dir / path).is_file(), 'pipeline2 缺逐关结果: ' + key)
        rows = json.loads((evidence_dir / path).read_text(encoding='utf-8'))['results']
        results_by_key[key] = {str(item['level_id']): item for item in rows}
        require(set(results_by_key[key]) == set(inventory_ids), 'pipeline2 逐关结果须含全部 ID，包括未定: ' + key)
    for row in table:
        nonempty(row, ['level_id', 'number', 'structure', 'layout', 'solvability', 'visual', 'evidence'], '逐关表')
        require(all(isinstance(row[k], str) and row[k] for k in ['structure', 'layout', 'solvability', 'visual']), '逐关表状态须为文字')
        rid = str(row['level_id'])
        require(row['visual'] == visual_by_id[rid]['verdict'], '逐关表视觉结论与视觉结果不一致')
        require(row['layout'] == results_by_key['layout'][rid]['verdict'], '逐关表布局结论与结果不一致')
        if row['solvability'] in LEVEL_GREEN:
            require(results_by_key['solvability'][rid]['verdict'] == '未见问题', '逐关求解未定或失败不能显示绿色')
        paths = row['evidence'] if isinstance(row['evidence'], list) else [row['evidence']]
        require(bool(paths) and all(isinstance(p, str) and (evidence_dir / p).is_file() for p in paths), '逐关表缺证据')


def validate_depth(owner, evidence_dir, tag):
    """Validate the anti-shallow-review ledger emitted by multi-agent-v2."""
    depth = owner.get('static_audit', {}).get('depth')
    nonempty(depth or {}, ['protocol', 'coverage', 'branches'], tag + ': 缺深审账本')
    require(depth['protocol'] == 'deep-v2', tag + ': 深审协议版本错误')
    branches = depth['branches']
    coverage = depth['coverage']
    cases = owner.get('static_audit', {}).get('cases', [])
    require(isinstance(branches, list) and branches, tag + ': 深审账本缺真实分支')
    require(isinstance(coverage, list) and len(coverage) == len(DIMENSIONS), tag + ': 深审账本缺七维覆盖')
    branch_ids = set()
    branch_dim = {}
    for branch in branches:
        nonempty(branch, ['id', 'dimension', 'condition', 'consumer', 'evidence'], tag + ': 深审分支')
        require(branch['dimension'] in DIMENSIONS, tag + ': 深审分支维度无效')
        require(branch['id'] not in branch_ids, tag + ': 深审分支ID重复')
        validate_trace(branch['evidence'], evidence_dir, tag + '/' + branch['id'])
        branch_ids.add(branch['id'])
        branch_dim[branch['id']] = branch['dimension']
    case_ids = {c.get('id') for c in cases}
    require(None not in case_ids, tag + ': 深审场景缺ID')
    case_branch_ids = set()
    placeholder_ids = set()
    for case in cases:
        linked_branches = case.get('branch_ids')
        if not (isinstance(linked_branches, list) and linked_branches):
            # Inventory-only placeholders are explicitly uninspected and have
            # no source trace to link. Every analyzed scenario still needs a
            # concrete branch.
            no_business_branch = (
                case.get('verdict') == '不适用'
                and bool(case.get('trace'))
                and not case.get('finding_ids')
                and not case.get('run_ids')
            )
            placeholder = no_business_branch or (
                case.get('verdict') == '未检查'
                and not case.get('trace')
                and not case.get('finding_ids')
                and not case.get('run_ids')
            )
            require(placeholder, tag + '/' + case['id'] + ': 深审场景缺分支回链')
            placeholder_ids.add(case['id'])
            continue
        require(set(case['branch_ids']) <= branch_ids,
                tag + '/' + case['id'] + ': 深审场景引用不存在的分支')
        case_branch_ids.update(case['branch_ids'])
    seen_dims = set()
    covered_cases = set()
    for row in coverage:
        nonempty(row, ['dimension', 'status', 'branch_ids', 'case_ids'], tag + ': 深审覆盖')
        dim = row['dimension']
        require(dim in DIMENSIONS and dim not in seen_dims, tag + ': 深审覆盖维度重复/无效')
        require(row['status'] in DEPTH_STATUSES, tag + '/' + dim + ': 深审覆盖状态无效')
        require(set(row['branch_ids']) <= branch_ids, tag + '/' + dim + ': 深审分支引用无效')
        require(all(branch_dim[x] == dim for x in row['branch_ids']), tag + '/' + dim + ': 深审分支跨维度')
        require(set(row['case_ids']) <= case_ids, tag + '/' + dim + ': 深审场景引用无效')
        covered_cases.update(row['case_ids'])
        if row['status'] == '不适用':
            nonempty(row, ['reason', 'evidence'], tag + '/' + dim + ': 不适用依据')
            validate_trace(row['evidence'], evidence_dir, tag + '/' + dim + '/不适用')
        if row['status'] in {'部分闭合', '未检查'}:
            nonempty(row, ['gap'], tag + '/' + dim + ': 深审缺口')
        seen_dims.add(dim)
    require(seen_dims == DIMENSIONS, tag + ': 深审账本未覆盖七维')
    require(covered_cases == case_ids - placeholder_ids,
            tag + ': 深审场景未完整归属coverage')
    require(case_branch_ids == branch_ids, tag + ': 存在分支没有被具体场景回核')


def validate_static_audit(owner, evidence_dir, issue_ids, run_ids, tag, all_dimensions=True):
    audit = owner.get('static_audit', {})
    nonempty(audit, ['status', 'summary', 'cases'], tag + ': 静态检查')
    require(audit['status'] in {'已完成', '未完成'}, tag + ': 静态完成状态无效')
    cases = audit['cases']
    require(isinstance(cases, list) and bool(cases), tag + ': 缺静态场景')
    case_ids = unique(cases, tag + ': 静态场景')
    for c in cases:
        name = tag + '/' + c['id']
        nonempty(c, ['dimension', 'scenario', 'preconditions', 'input', 'basis', 'expected', 'actual', 'verdict'], name)
        require(c['dimension'] in DIMENSIONS and c['verdict'] in CASE_VERDICTS, name + ': 维度/结论无效')
        require(set(c.get('finding_ids', [])) <= issue_ids and set(c.get('run_ids', [])) <= run_ids, name + ': 证据引用无效')
        if c['verdict'] in {'未见问题', '发现问题', '不适用'}:
            validate_trace(c.get('trace'), evidence_dir, name)
        if c['verdict'] in {'待核实', '未检查', '不适用'}:
            nonempty(c, ['reason'], name)
        if c['verdict'] == '发现问题':
            require(bool(c.get('finding_ids')), name + ': 问题场景缺具体问题引用')
    if all_dimensions and not audit.get('depth'):
        require({c['dimension'] for c in cases} == DIMENSIONS, tag + ': 静态检查遗漏适用性维度')
    if audit['status'] == '已完成':
        require(all(c['verdict'] in {'未见问题', '发现问题', '不适用'} for c in cases), tag + ': 仍有未检查/待核实场景，不能标静态完成')
        require(any(c['verdict'] != '不适用' for c in cases), tag + ': 全部不适用不能冒充已检查功能')
    for item in owner.get('external_checks', []):
        nonempty(item, ['id', 'assertion', 'dependency', 'why_not_local', 'local_case_ids', 'remaining_fact'], tag + ': 外部事实')
        require(item['dependency'] in EXTERNAL, tag + ': 本地可检查事项不能转人工')
        require(isinstance(item['local_case_ids'], list) and bool(item['local_case_ids']), tag + ': 外部项缺本地完成场景')
        require(set(item['local_case_ids']) <= case_ids, tag + ': 外部项未回链已完成的本地场景')
        require(all(next(c for c in cases if c['id'] == cid)['verdict'] in {'未见问题', '发现问题', '不适用'} for cid in item['local_case_ids']), tag + ': 外部项不能掩盖未完成的本地检查')


def static_outcome(owner, issue_map):
    audit = owner['static_audit']
    ids = owner.get('related_findings', owner.get('issue_ids', []))
    if any(issue_map[i]['kind'] in CONFIRMED for i in ids):
        return '发现问题', 'red'
    if any(c['verdict'] == '发现问题' for c in audit['cases']):
        return '发现问题', 'red'
    if owner.get('source_drift'):
        return '当前版待复核', 'amber'
    if audit['status'] != '已完成':
        return '静态检查未完成', 'amber'
    if ids:
        return '有风险待核实', 'amber'
    return '代码检查未见问题', 'green'


def validate(data, evidence_dir):
    require(data.get('report_contract_version') in {'2.0', VERSION}, '报告契约版本错误')
    static_mode = data['report_contract_version'] == VERSION
    nonempty(data, ['presentation', 'baseline', 'features', 'findings', 'suites', 'external_change', 'source_changed', 'configuration_cases', 'configuration_fields'], '报告')
    nonempty(data['baseline'], ['run_id', 'head'], 'baseline')
    nonempty(data['external_change'], ['observed_head'], 'external_change')
    view = data['presentation']
    if static_mode:
        require(view.get('audit_mode') == '静态检查', 'v2.1默认模式必须为静态检查')
    nonempty(view, ['overall', 'conclusion', 'execution_scope', 'not_executed', 'product_test_run_id', 'evidence_head', 'supplement_summary'], 'presentation')
    require(type(view.get('format_only')) is bool, 'format_only必须为布尔')
    require(view['overall'] in OVERALL, 'overall无效')
    require(view['product_test_run_id'] == data['baseline']['run_id'], '产品执行批次与基线不一致')
    ids = unique(data['features'], '功能')
    issues = unique(data['findings'], '问题')
    runs = data['suites'] + data.get('additional_runs', [])
    run_ids = unique(runs, '执行记录')
    for run in runs:
        nonempty(run, ['status', 'reason', 'summary', 'evidence'], run['id'])
        require('exit_code' in run, run['id'] + ': 缺退出码/未执行空值')
        if run['status'].startswith('未执行'):
            require(run['exit_code'] is None and not run.get('command'), run['id'] + ': 未执行记录不能填实际命令/退出码')
        else:
            nonempty(run, ['command'], run['id'])
            require(isinstance(run['command'], list) and bool(run['command']), run['id'] + ': 命令须为参数数组')
        require((evidence_dir / run['evidence']).is_file(), run['id'] + ': 缺执行证据')
    for f in data['features']:
        tag = f['id']
        nonempty(f, ['name', 'assessment', 'checks', 'installation'], tag)
        a = f['assessment']
        nonempty(a, ['code_review', 'code_conclusion', 'verdict', 'conclusion'] + ([] if static_mode else ['follow_up', 'manual_readiness']), tag)
        readiness = a.get('manual_readiness', '无需人工')
        require(a['code_review'] in CODE and a['verdict'] in VERDICTS and readiness in MANUAL, tag + ': 状态无效')
        require(isinstance(a.get('run_ids'), list) and set(a['run_ids']) <= run_ids, tag + ': 执行记录引用无效')
        require(set(f.get('related_findings', [])) <= issues, tag + ': 问题引用无效')
        if a['verdict'] in {'发现静态缺陷', '发现方法级问题', '发现产品问题'}:
            require(bool(f.get('related_findings')), tag + ': 问题结论须关联具体问题')
        require(all(f['installation'].get(k) for k in ['upgrade', 'same_identity', 'new_identity']), tag + ': 三条安装静态链路不全')
        require(not f.get('source_drift') or a['verdict'] == '当前版本待复审', tag + ': 版本变化未降级')
        validate_manual(f, readiness, a.get('manual_missing'), evidence_dir, tag)
        nonempty(f.get('display', {}), ['category', 'group', 'name', 'check_summary'], tag + ': 大白话展示')
        require(f['display']['category'] in CATEGORIES, tag + ': 分类必须为玩法/关卡/系统/配置/埋点')
        if static_mode:
            validate_static_audit(f, evidence_dir, issues, run_ids, tag)
            # Dossier-backed rows carry audit_agent.  Also validate an
            # explicitly supplied deep ledger in fixtures/legacy callers that
            # only mark the batch protocol; inventory-only rows have no ledger
            # and must remain amber rather than failing the whole render.
            if data.get('agent_audit', {}).get('protocol') == 'multi-agent-v2' and (
                f.get('audit_agent') or f.get('static_audit', {}).get('depth')
            ):
                validate_depth(f, evidence_dir, tag)
            if f['static_audit']['status'] == '已完成':
                require(a['code_review'] == '完成静态审查', tag + ': 静态完成与代码审查状态冲突')
                require(a['verdict'] not in {'证据不足', '风险待确认'} and
                        (a['verdict'] != '当前版本待复审' or bool(f.get('source_drift'))),
                        tag + ': 静态完成与未核实结论冲突；具体风险须关联问题记录')
            for c in f['static_audit']['cases']:
                require(set(c.get('finding_ids', [])) <= set(f.get('related_findings', [])), tag + ': 场景问题未回链本功能')
                if c['verdict'] == '发现问题':
                    require(any(next(i for i in data['findings'] if i['id'] == iid).get('kind') in CONFIRMED for iid in c['finding_ids']), tag + ': 发现问题须有静态或动态已证依据')
    for f in data['findings']:
        nonempty(f, ['title', 'status', 'cause', 'condition', 'actual', 'expected', 'impact', 'missing'] + ([] if static_mode else ['manual', 'manual_readiness']), f['id'])
        readiness = f.get('manual_readiness', '无需人工')
        validate_manual(f, readiness, f.get('manual_missing'), evidence_dir, f['id'])
        if f.get('kind') == '方法问题已证':
            nonempty(f, ['log', 'local_steps'], f['id'])
        if f.get('log'):
            require((evidence_dir / f['log']).is_file(), f['id'] + ': 日志不存在')
        nonempty(f.get('display', {}), ['category', 'title', 'condition', 'cause', 'impact', 'expected', 'actual'], f['id'] + ': 大白话问题')
        require(f['display']['category'] in CATEGORIES, f['id'] + ': 问题分类无效')
        if f.get('kind') in {'方法问题已证', '产品问题已证'}:
            nonempty(f, ['log', 'local_steps'], f['id'])
            require(bool(f['display'].get('whitebox_steps')) or readiness in {'完整待执行', '已执行'}, f['id'] + ': 已证问题缺可读复现步骤')
        if f.get('kind') == '静态缺陷已证':
            proof = f.get('static_proof', {})
            nonempty(proof, ['basis', 'preconditions', 'entry', 'contradiction', 'steps'], f['id'] + ': 静态缺陷证明')
            require(isinstance(proof['steps'], list) and bool(proof['steps']), f['id'] + ': 缺静态推导步骤')
            validate_trace(proof.get('trace'), evidence_dir, f['id'])
    level = data.get('level_audit', {})
    inventory_ids = None
    inventory_path = level.get('inventory_file', 'levels/level-inventory.json')
    inventory_file = evidence_dir / inventory_path
    if inventory_file.is_file():
        inventory_data = json.loads(inventory_file.read_text(encoding='utf-8'))
        require(isinstance(inventory_data.get('levels'), list), '关卡枚举清单缺 levels 数组')
        inventory_ids = [str(item.get('level_id', '')) for item in inventory_data['levels']]
        require(all(inventory_ids) and len(inventory_ids) == len(set(inventory_ids)), '关卡枚举清单含空/重复 level_id')
    require(all(level.get(key, {}).get('status') == '未检查' for key in ['solvability', 'layout']) or inventory_ids is not None,
            '开始关卡检查后必须提供本轮有效关卡枚举清单')
    for key in ['solvability', 'layout']:
        entry = level.get(key, {})
        nonempty(entry, ['status', 'summary'], 'level_audit.' + key)
        require(entry['status'] in LEVEL_STATUS, '逐关检查状态无效')
        require(set(entry.get('run_ids', [])) <= run_ids, '逐关执行引用无效')
        if entry['status'] != '未检查':
            nonempty(entry, ['result_file'], 'level_audit.' + key)
            result_path = evidence_dir / entry['result_file']
            require(result_path.is_file(), '逐关结果文件不存在: ' + entry['result_file'])
            results_data = json.loads(result_path.read_text(encoding='utf-8'))
            require(results_data.get('schema_version') == 1, '逐关结果 schema_version 必须为 1: ' + key)
            results = results_data.get('results')
            require(isinstance(results, list), '逐关结果文件缺 results 数组: ' + key)
            result_ids = [str(item.get('level_id', '')) for item in results]
            require(all(result_ids) and len(result_ids) == len(set(result_ids)), '逐关结果含空/重复 level_id: ' + key)
            require(type(entry.get('total')) is int and type(entry.get('checked')) is int, '逐关结果须有整数 total/checked')
            require(results_data.get('total') == entry['total'] and results_data.get('checked') == entry['checked'], '逐关报告数量与结果文件不一致: ' + key)
            require(entry['total'] > 0 and entry['checked'] <= len(result_ids) <= entry['total'],
                    '逐关结果条数须介于 checked 与 total 之间: ' + key)
            if inventory_ids is not None:
                require(results_data.get('inventory') == inventory_path and level.get('inventory_file') == inventory_path, '逐关结果未引用本轮枚举清单: ' + key)
                require(entry['total'] == len(inventory_ids) and set(result_ids) <= set(inventory_ids), '逐关范围与枚举清单不一致: ' + key)
                if entry['status'] in {'检查完成未见问题', '发现问题'}:
                    require(set(result_ids) == set(inventory_ids), '逐关完成结果未覆盖全部枚举 ID: ' + key)
            for item in results:
                nonempty(item, ['level_id', 'verdict', 'checks', 'evidence'], '逐关结果 ' + key)
                require(item['verdict'] in {'未见问题', '发现问题', '未定', '未检查'}, '逐关结果 verdict 无效: ' + key)
                require(isinstance(item['checks'], list) and isinstance(item['evidence'], list), '逐关 checks/evidence 须为数组: ' + key)
                require(all((evidence_dir / path).is_file() for path in item['evidence']), '逐关证据文件不存在: ' + key + '/' + str(item['level_id']))
            determinate = sum(item['verdict'] in {'未见问题', '发现问题'} for item in results)
            require(entry['checked'] == determinate, '逐关 checked 必须等于有明确结论的关卡数: ' + key)
            if entry['status'] == '检查完成未见问题':
                require(entry['total'] > 0 and entry['checked'] == entry['total'] and all(item['verdict'] == '未见问题' for item in results), '逐关无问题结论含未定或发现问题')
            if entry['status'] == '发现问题':
                require(any(item['verdict'] == '发现问题' for item in results), '逐关发现问题状态没有逐关异常结果')
        if entry['status'] != '未检查':
            require(bool(entry.get('evidence')) and all((evidence_dir / p).is_file() for p in entry['evidence']), '逐关结论缺执行证据')
    if level['layout']['status'] == '发现问题':
        require(bool(level.get('anomalies')), '布局异常须有真实关卡图')
    for sample in level.get('samples', []):
        nonempty(sample, ['level_id', 'caption', 'image', 'evidence'], '布局检查示例图')
        require(inventory_ids is not None and str(sample['level_id']) in inventory_ids, '布局示例不在本轮关卡清单')
        require(Path(sample['image']).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}, '布局示例须为位图')
        require((evidence_dir / sample['image']).is_file() and (evidence_dir / sample['evidence']).is_file(), '布局示例缺原图或执行证据')
    for anomaly in level.get('anomalies', []):
        nonempty(anomaly, ['level_id', 'caption', 'image', 'evidence', 'steps'], '布局异常')
        require(Path(anomaly['image']).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}, '关卡图须为可内嵌位图')
        require((evidence_dir / anomaly['image']).is_file() and (evidence_dir / anomaly['evidence']).is_file(), '布局异常缺原图或证据')
        layout_entry = level['layout']
        if layout_entry.get('result_file') and (evidence_dir / layout_entry['result_file']).is_file():
            layout_results = json.loads((evidence_dir / layout_entry['result_file']).read_text(encoding='utf-8')).get('results', [])
            matched = [item for item in layout_results if str(item.get('level_id')) == str(anomaly['level_id'])]
            require(len(matched) == 1 and matched[0].get('verdict') == '发现问题', '异常图未回链同关卡的已确认布局异常结果')
    validate_level_visual(level, inventory_ids, evidence_dir)
    groups = data.get('configuration_groups', [])
    unique(groups, '配置组')
    assigned = []
    for g in groups:
        nonempty(g, ['id', 'name', 'status', 'conclusion', 'case_indices'], '配置组')
        require(g['status'] in CONFIG_STATUS, g['id'] + ': 配置状态无效')
        require(set(g.get('run_ids', [])) <= run_ids and set(g.get('issue_ids', [])) <= issues, g['id'] + ': 引用无效')
        require(all(type(i) is int and 0 <= i < len(data['configuration_cases']) for i in g['case_indices']), g['id'] + ': 输入实例索引无效')
        assigned += g['case_indices']
        if g['status'] == '局部测试通过':
            require(bool(g.get('run_ids')) and all(next(r for r in runs if r['id'] == rid)['status'] == '局部验证通过' for rid in g['run_ids']) and not g.get('issue_ids'), g['id'] + ': 通过结论缺有效通过记录或仍关联问题')
        if g['status'] == '发现问题':
            require(any(next(f for f in data['findings'] if f['id'] == iid).get('kind') in CONFIRMED for iid in g.get('issue_ids', [])), g['id'] + ': 红色问题须有已证问题引用')
        if static_mode:
            validate_static_audit(g, evidence_dir, issues, run_ids, g['id'], all_dimensions=False)
            if data.get('agent_audit', {}).get('protocol') == 'multi-agent-v2' and g.get('audit_agent'):
                validate_depth(g, evidence_dir, g['id'])
            for c in g['static_audit']['cases']:
                require(set(c.get('finding_ids', [])) <= set(g.get('issue_ids', [])), g['id'] + ': 场景问题未回链配置组')
                if c['verdict'] == '发现问题':
                    require(any(next(i for i in data['findings'] if i['id'] == iid).get('kind') in CONFIRMED for iid in c['finding_ids']), g['id'] + ': 配置问题须有静态或动态已证依据')
        if g['status'] == '代码检查未见问题':
            require(static_mode and g['static_audit']['status'] == '已完成' and not g.get('issue_ids'), g['id'] + ': 静态绿色缺完成的静态检查')
        for key in ['log', 'source']:
            if g.get(key):
                require((evidence_dir / g[key]).is_file(), g['id'] + ': 缺配置证据 ' + key)
    require(len(assigned) == len(set(assigned)) and set(assigned) == set(range(len(data['configuration_cases']))), '配置输入必须逐项分组，不得遗漏或重复计数')
    if view['overall'] != '执行不完整':
        if level.get('pipeline_version') == 2:
            require(level_progress(level)['done'] == 3, '求解/布局/视觉尚未全部完成，不能给完整结论')
        if not static_mode:
            require(not any('受阻' in r['status'] or '过期' in r['status'] or r['status'].startswith('未执行') for r in runs), '仍有受阻/过期/未执行记录，不能给检查完成结论')
        require(all(f['assessment']['code_review'] == '完成静态审查' and not f.get('source_drift') and (f['static_audit']['status'] == '已完成' if static_mode else not f.get('gaps')) for f in data['features']), '仍有静态缺口/版本变化，不能给检查完成结论')
        require(all(g['static_audit']['status'] == '已完成' if static_mode else g['status'] in {'局部测试通过', '发现问题'} for g in groups), '配置静态检查仍未完成')
        if any(f['display']['category'] == '关卡' for f in data['features']):
            require(all(level[k]['status'] in {'检查完成未见问题', '发现问题'} for k in ['solvability', 'layout']), '逐关检查仍未完成，不能给检查完成结论')
    if view['overall'] == '检查完成且范围内未见问题':
        if level.get('pipeline_version') == 2:
            require(level_progress(level)['tone'] == 'green', '逐关仍有问题或视觉风险，不能给完整无问题结论')
        require(not data['findings'] and all(f['assessment']['code_review'] == '完成静态审查' and (f['static_audit']['status'] == '已完成' if static_mode else not f.get('gaps')) for f in data['features']), '有问题/缺口不能给完整无问题结论')
    return ids


def level_progress(level):
    keys = ['solvability', 'layout', 'visual']
    done = sum(level.get(k, {}).get('status') in {'检查完成未见问题', '发现问题', '有风险待确认'}
               and level.get(k, {}).get('checked') == level.get(k, {}).get('total')
               and bool(level.get(k, {}).get('total')) for k in keys)
    red = any(level.get(k, {}).get('status') == '发现问题' for k in keys) or any(
        row.get('status') == '发现问题' for row in level.get('summary_rows', []))
    risk = bool(level.get('risks')) or level.get('visual', {}).get('status') == '有风险待确认'
    return {'done': done, 'total': 3, 'tone': 'red' if red else 'green' if done == 3 and not risk else 'amber',
            'summary': '逐关检查发现问题' if red else '有解性、布局与视觉均有逐关结果' if done == 3 and not risk else
                       '存在视觉风险待确认' if done == 3 else '仍有逐关检查未完成'}


def module_summaries(features, groups, issues, level, static_first):
    """问题归属和功能引用取并集；问题数与检查完成度分别统计。"""
    summaries = {}
    for category in ('玩法', '关卡', '系统', '配置', '埋点'):
        fs = [f for f in features if f['category_plain'] == category]
        gs = groups if category == '配置' else []
        owners = [('feature-' + f['id'], f) for f in fs] + [('configcase-' + g['id'], g) for g in gs]
        referenced = {i for _, owner in owners for i in owner.get('issue_ids', [])}
        linked = [i for i in issues if i['category_plain'] == category or i['id'] in referenced]
        confirmed = [i['id'] for i in linked if i['confirmed']]
        risks = [i['id'] for i in linked if not i['confirmed']]
        incomplete = [ref for ref, owner in owners if (
            owner.get('static_audit', {}).get('status') != '已完成' or owner.get('source_drift')
            or owner.get('assessment', {}).get('verdict') == '当前版本待复审'
        )] if static_first else [ref for ref, owner in owners if owner['tone'] == 'amber']
        clear = [ref for ref, owner in owners if owner['tone'] == 'green' and ref not in incomplete]
        visual_count = len({r['level_id'] for r in level.get('risks', [])}) if category == '关卡' else 0
        level_pending = category == '关卡' and level_progress(level)['done'] < level_progress(level)['total']
        level_problem = category == '关卡' and level_progress(level)['tone'] == 'red'
        has_problem = bool(confirmed) or level_problem or (category == '关卡' and bool(level.get('anomalies')))
        pending = bool(incomplete) or level_pending or not owners
        tone = 'red' if has_problem else 'amber' if pending or risks or visual_count else 'green'
        headline = f'已确认 {len(confirmed)} 个问题' if confirmed else '暂无已确认问题'
        if category == '关卡' and level.get('anomalies'):
            headline += f"；另有 {len(level['anomalies'])} 张已确认布局异常图"
        elif level_problem:
            headline = (f'已确认 {len(confirmed)} 个业务问题；' if confirmed else '') + '逐关检查发现问题，见下方逐关明细'
        if risks:
            headline += f'；{len(risks)} 项业务风险待核实'
        if visual_count:
            headline += f'；{visual_count} 关存在视觉风险'
        if pending:
            headline += '。检查尚未完成，不能下“没有问题”的结论。'
        elif not has_problem and not risks and not visual_count:
            headline = '所列代码检查范围内未发现问题。'
        else:
            headline += '。所列功能的静态检查已完成。'
        summaries[category] = dict(feature_count=len(fs), config_group_count=len(gs),
            confirmed_ids=confirmed, risk_ids=risks, incomplete_refs=incomplete, clear_refs=clear,
            visual_risk_count=visual_count, level_pending=bool(level_pending),
            tone=tone, headline=headline)
    return summaries


def prepare_view(data):
    """展示事实来自本轮数据；颜色由证据状态推导，不由文案或固定ID猜测。"""
    runs = {r['id']: r for r in data['suites'] + data.get('additional_runs', [])}
    category_order = {'玩法': 0, '关卡': 1, '系统': 2, '配置': 3, '埋点': 4}
    finding_order = {'产品问题已证': 0, '静态缺陷已证': 1, '方法问题已证': 2}
    findings = []
    for f in sorted(data['findings'], key=lambda row: (
            finding_order.get(row.get('kind'), 9),
            category_order.get(row.get('display', {}).get('category'), 9),
            str(row.get('id', '')).casefold(), str(row.get('id', '')))):
        item = dict(f)
        view = f['display']
        item.update({key + '_plain': view[key] for key in ['title', 'condition', 'cause', 'impact', 'expected', 'actual']})
        item.update(category_plain=view['category'], confirmed=f.get('kind') in CONFIRMED,
                    confirmation_label='静态已证 · 未动态运行' if f.get('kind') == '静态缺陷已证' else '产品问题已复现' if f.get('kind') == '产品问题已证' else '白盒已复现 · 玩家入口待核',
                    steps_plain=view.get('whitebox_steps', f.get('local_steps', [])),
                    manual_readiness=f.get('manual_readiness', '无需人工'))
        findings.append(item)
    issue_map = {f['id']: f for f in findings}
    rows = []
    for f in sorted(data['features'], key=lambda row: (
            category_order.get(row.get('display', {}).get('category'), 9),
            str(row.get('display', {}).get('group', '')).casefold(),
            str(row.get('display', {}).get('name', '')).casefold(),
            str(row.get('id', '')).casefold())):
        v, a = f['display'], f['assessment']
        item = dict(f)
        item.update(category_plain=v['category'], group_plain=v['group'], name_plain=v['name'], check_plain=v['check_summary'], issue_ids=f.get('related_findings', []))
        linked = [runs[rid] for rid in a['run_ids']]
        if any(issue_map[i]['confirmed'] for i in item['issue_ids']):
            outcome, tone = '发现问题', 'red'
        elif item['issue_ids'] or a['verdict'] == '风险待确认':
            outcome, tone = '有风险待核实', 'amber'
        elif f.get('source_drift') or a['verdict'] == '当前版本待复审':
            outcome, tone = '当前版待复核', 'amber'
        elif a['code_review'] == '未审查' or a['verdict'] == '证据不足':
            outcome, tone = '检查未完成', 'amber'
        elif linked and all(r['status'] == '局部验证通过' for r in linked):
            outcome, tone = '局部测试通过', 'green'
        elif linked:
            outcome, tone = '测试未完成', 'amber'
        else:
            outcome, tone = '代码检查未见问题', 'green'
        if data['report_contract_version'] == VERSION:
            outcome, tone = static_outcome(f, issue_map)
        depth = f.get('static_audit', {}).get('depth', {})
        gaps = [x for x in depth.get('coverage', []) if x.get('status') in {'部分闭合', '未检查'}]
        item['gap_plain'] = '；'.join(x.get('dimension', '') + '：' + x.get('gap', '未闭合') for x in gaps)
        item['assessment'] = dict(a, manual_readiness=a.get('manual_readiness', '无需人工'))
        item.update(outcome=outcome, tone=tone, result_plain=f['static_audit']['summary'] if data['report_contract_version'] == VERSION else v.get('result', a['conclusion']))
        rows.append(item)
    groups = []
    for g in sorted(data['configuration_groups'], key=lambda row: (
            str(row.get('display_name', row.get('name', ''))).casefold(),
            str(row.get('id', '')).casefold())):
        tone = 'green' if g['status'] in {'代码检查未见问题', '局部测试通过'} else 'red' if g['status'] == '发现问题' else 'amber'
        status = g['status']
        if data['report_contract_version'] == VERSION:
            status, tone = static_outcome(g, issue_map)
        groups.append(dict(g, cases=[data['configuration_cases'][i] for i in g['case_indices']], tone=tone, status=status, run_ids=g.get('run_ids', [])))
    audit = data.get('agent_audit', {})
    audit_summary = {
        'inventory_count': len(data['features']),
        'deep_review_count': sum(bool(f.get('static_audit', {}).get('depth', {}).get('branches')) for f in data['features']),
        'deep_review_complete': sum(f.get('static_audit', {}).get('status') == '已完成' and bool(f.get('static_audit', {}).get('depth', {}).get('branches')) for f in data['features']),
        'incomplete_count': sum(1 for f in data['features'] if f.get('static_audit', {}).get('status') != '已完成'),
    }
    register = build_register(data['findings'])
    register['csv'] = register_csv(register)
    quality_gate = dict(data.get('quality_gate') or {})
    return {'features': rows, 'issues': findings, 'runs': runs, 'config_groups': groups, 'bug_register': register,
            'module_summaries': module_summaries(rows, groups, findings, data['level_audit'], data['report_contract_version'] == VERSION),
            'baseline': data['baseline'], 'presentation': data['presentation'],
            'audit_summary': audit_summary,
            'level_audit': data['level_audit'], 'level_progress': level_progress(data['level_audit']), 'configuration_fields_count': len(data['configuration_fields']),
            'source_changed': data['source_changed'], 'external_change': data['external_change'],
            'suites_count': len(data['suites']), 'additional_count': len(data.get('additional_runs', [])),
            'static_first': data['report_contract_version'] == VERSION,
            'quality_gate': quality_gate,
            'feishu_authorized': data.get('runtime_context', {}).get('feishu_authorized') is True}


def render(data, evidence_dir, output, template):
    profile = json.loads((Path(__file__).resolve().parents[1] / 'assets/delivery-profile.json').read_text())
    require(hashlib.sha256(template.read_bytes()).hexdigest() == profile['template_sha256'],
            '模板与已确认版本不一致；不得逐轮改版或绕过模板指纹')
    validate(data, evidence_dir)
    assets = {}
    excluded = {'report-data.json', 'report-data-v2.json', 'preview-data.json', 'html-manifest.json', 'browser-verification.json', 'verification.json', 'report-format-verification.json', 'preview-verification.json', 'skill-report-verification.json', 'delivery-check.json', 'final-evidence-check.json', 'html-interaction-check.json'}
    image_paths = {a['image'] for a in data['level_audit'].get('anomalies', []) + data['level_audit'].get('samples', []) + data['level_audit'].get('risks', [])}
    for file in sorted(evidence_dir.rglob('*')):
        if file.is_symlink() or not file.is_file() or file.name in excluded or file.name.endswith(('-manifest.json', '-verification.json')) or '-before-format.' in file.name or file.name == 'format-original-evidence.json':
            continue
        if any(x in {'bin', 'obj', 'toolchain'} for x in file.relative_to(evidence_dir).parts):
            continue
        relpath = file.relative_to(evidence_dir).as_posix()
        # Per-level details already contain input and both kernel results. Avoid embedding
        # the same 900 paths several times; keep intermediate dumps beside the HTML.
        if relpath in {'levels/geometry-input.json', 'levels/resolved-geometry-input.json',
                       'levels/geometry-kernel.json', 'levels/spline-kernel.json',
                       'levels/solver-input.json', 'levels/solver-kernel.json', 'levels/visual-results.json'} or (file.suffix == '.json' and 'kernel' in file.stem):
            continue
        if file.suffix not in {'.txt', '.md', '.json', '.csv', '.log', '.py', '.cs', '.rsp'} and relpath not in image_paths:
            continue
        raw = file.read_bytes()
        if relpath in image_paths:
            mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}[file.suffix.lower()]
            assets[relpath] = {'base64': base64.b64encode(raw).decode(), 'mime': mime, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            continue
        text = raw.decode('utf-8', errors='replace')
        item = {'text': text, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        if text.encode() != raw:
            item['base64'] = base64.b64encode(raw).decode()
        assets[file.relative_to(evidence_dir).as_posix()] = item
    for f in data['features'] + data['findings']:
        for source in f.get('source_paths', []):
            rel = source_artifact(source)
            require(rel in assets, f['id'] + ': 源码摘录未内嵌 ' + rel)
    view = prepare_view(data)
    level_view = dict(view['level_audit'])
    if level_view.get('visual'):
        visual_rows = json.loads((evidence_dir / level_view['visual']['result_file']).read_text())['results']
        visual_by_id = {str(row['level_id']): row for row in visual_rows}
        level_view['risks'] = [dict(risk, risk_types=[kind for kind in ('wall', 'water')
            if visual_by_id[str(risk['level_id'])].get(kind + '_risk')])
            for risk in level_view.get('risks', [])]
    view['level_audit'] = level_view
    view['assets'] = assets
    payload = json.dumps(view, ensure_ascii=False).replace('<', '\\u003c')
    source = template.read_text()
    require(source.count('__PAYLOAD__') == 1, '固定模板必须有且只有一个payload插槽')
    html = source.replace('__PAYLOAD__', payload)
    output.write_text(html)
    manifest = {'report_contract_version': data['report_contract_version'], 'workflow_version': profile['workflow_version'], 'template_sha256': hashlib.sha256(template.read_bytes()).hexdigest(),
                'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'features': len(data['features']),
                'findings': len(data['findings']), 'execution_records': len(data['suites']),
                'additional_runs': len(data.get('additional_runs', [])), 'embedded_files': len(assets),
                'format_only': data['presentation']['format_only'], 'product_test_run_id': data['baseline']['run_id']}
    manifest_path = output.with_name('html-manifest.json' if output.name == 'report.html' else output.stem + '-manifest.json')
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.data.read_text())
    template = Path(__file__).resolve().parents[1] / 'assets/report-template.html'
    print(json.dumps(render(data, args.evidence_dir, args.output, template), ensure_ascii=False))


if __name__ == '__main__':
    main()
