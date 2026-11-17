"""Build the fixed BUG管理 rows from confirmed findings; never invent ticket data."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re

CONFIRMED = {'静态缺陷已证', '方法问题已证', '产品问题已证'}
SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'assets/bug-columns.json'
# These fields may be supplied only from known facts. System/acceptance fields stay blank.
METADATA = {'版本号', '操作平台', '严重程度', '优先级', '复现率', '功能模块', '发现Jenkins构建号', '截图/视频'}
STATIC_PREFIX = '【静态检测】'
BUG_VERSION = 'Codex'


def text(value):
    return '' if value is None else str(value)


def static_description(value):
    value = text(value)
    return value if value.startswith(STATIC_PREFIX) else STATIC_PREFIX + value


def ticket_text(value):
    return text(value).replace('\\r\\n', '\n').replace('\\n', '\n').replace('\\r', '\n').strip()


def build_register(findings):
    profile = json.loads((SCHEMA_PATH.parent / 'delivery-profile.json').read_text(encoding='utf-8'))
    raw = SCHEMA_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != profile['bug_columns_sha256']:
        raise ValueError('Bug 表头与已确认版本不一致')
    schema = json.loads(raw)
    headers = [field['name'] for field in schema['fields']]
    if len(headers) != 23 or len(set(headers)) != 23:
        raise ValueError('Bug 表头须完整保留23个不同字段')
    rows, seen = [], set()
    for finding in findings:
        if finding.get('kind') not in CONFIRMED or finding['id'] in seen:
            continue
        seen.add(finding['id'])
        view = finding['display']
        manual = finding.get('manual', {})
        blackbox = finding.get('manual_readiness') in {'完整待执行', '已执行'} and bool(manual.get('steps'))
        manual_steps = [(text(step.get('action')) + ('；观察：' + text(step['observe']) if step.get('observe') else ''))
                        for step in manual.get('steps', [])] if blackbox else []
        proof = finding.get('static_proof', {})
        whitebox = view.get('whitebox_steps') or finding.get('local_steps') or proof.get('steps') or view.get('review_steps', [])
        label = {'静态缺陷已证': '静态已证 · 未动态运行', '方法问题已证': '白盒已复现 · 玩家入口待核',
                 '产品问题已证': '产品问题已复现'}[finding['kind']]
        detail = dict(title=view['title'], condition=view['condition'], actual=view['actual'], expected=view.get('expected', ''), cause=view['cause'],
                      impact=view['impact'], method='黑盒' if blackbox else '白盒静态推导' if proof else '白盒',
                      steps=manual_steps if blackbox else whitebox, whitebox_steps=whitebox if blackbox else [],
                      prepare=manual.get('prepare', '') if blackbox else proof.get('preconditions', ''),
                      entry=proof.get('entry', ''), basis=proof.get('basis', ''),
                      contradiction=proof.get('contradiction', ''), missing=finding.get('missing', ''),
                      restore=manual.get('restore', '') if blackbox else '', abnormal=manual.get('abnormal', '') if blackbox else '',
                      label=label, category=view['category'], source_drift=bool(finding.get('source_drift')))
        for key in ['title', 'condition', 'prepare', 'actual', 'expected']:
            detail[key] = ticket_text(detail[key])
        detail['steps'] = [ticket_text(step) for step in detail['steps'] if ticket_text(step)]
        required = {'问题标题': detail['title'], '前置条件': detail['prepare'] or detail['condition'],
                    '操作步骤': detail['steps'], '当前错误表现': detail['actual'], '预期正确表现': detail['expected']}
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(finding['id'] + ': 缺少' + '、'.join(missing) + '，不得导出或提单')
        detail['verification'] = ('代码推导，未真机复现。' if finding['kind'] == '静态缺陷已证' else
                                  '本地白盒验证，未真机复现。' if finding['kind'] == '方法问题已证' else
                                  '已有产品观察记录；结论范围以所附证据为准。')
        if blackbox and finding.get('manual_readiness') != '已执行':
            detail['verification'] += '下列玩家操作步骤尚未执行。'
        precondition = '\n'.join(dict.fromkeys(v for v in [detail['condition'], detail['prepare']] if v))
        sections = [finding['id'] + ' · ' + detail['title'], '验证方式：' + detail['verification'],
                    '证据层级：' + label, '前置条件：' + precondition]
        if detail['entry']:
            sections.append('入口：' + detail['entry'])
        sections += ['操作步骤（' + detail['method'] + '）：', *[f'{n}、{step}' for n, step in enumerate(detail['steps'], 1)]]
        sections += ['当前错误表现：' + detail['actual'], '预期正确表现：' + detail['expected']]
        if detail['whitebox_steps']:
            sections += ['补充白盒核查：', *[f'{n}、{step}' for n, step in enumerate(detail['whitebox_steps'], 1)]]
        sections += ['归因：' + detail['cause'], '影响范围：' + detail['impact']]
        for key, title in [('basis', '判定依据'), ('contradiction', '矛盾点'), ('missing', '范围限制'),
                           ('abnormal', '异常标准'), ('restore', '恢复方式')]:
            if detail[key]:
                sections.append(title + '：' + detail[key])
        if detail['source_drift']:
            sections.append('版本提示：检查后源码已变化，当前版本待复核。')
        detail['description'] = static_description('\n\n'.join(sections))
        evidence = []
        if finding.get('log'):
            evidence.append('复现日志：' + finding['log'])
        for trace in proof.get('trace', []) + finding.get('evidence', []):
            if trace.get('path'):
                evidence.append(trace['path'] + (':' + str(trace['line']) if trace.get('line') else '')
                                + (' · ' + trace['note'] if trace.get('note') else ''))
        fields = dict.fromkeys(headers, '')
        fields.update({'缺陷描述': detail['description'], '期望描述': detail['expected'],
                       '日志信息': '\n'.join(dict.fromkeys(evidence)), '缺陷状态': '未解决', '问题类型': 'BUG缺陷'})
        metadata = finding.get('bug_fields', {})
        if not isinstance(metadata, dict) or set(metadata) - METADATA:
            raise ValueError(finding['id'] + ': bug_fields 包含未知或不可自动填写的字段')
        for name, value in metadata.items():
            if not isinstance(value, str):
                raise ValueError(finding['id'] + ': Bug 字段必须是字符串：' + name)
            fields[name] = value
        # User-defined ticket label; independent of the inspected game build.
        fields['版本号'] = BUG_VERSION
        rows.append(dict(id=finding['id'], detail=detail, fields=fields))
    return dict(headers=headers, rows=rows, source_view=schema['view'])


def csv_text(value):
    value = text(value)
    if re.match(r'^[\s\ufeff]*[=+@-]', value) or value.startswith(('\t', '\r', '\n')):
        value = "'" + value
    return re.sub(r'\r\n|\r|\n', '\r\n', value)


def register_csv(register):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator='\r\n')
    writer.writerow(register['headers'])
    for row in register['rows']:
        writer.writerow([csv_text(row['fields'][name]) for name in register['headers']])
    return '\ufeff' + stream.getvalue()
