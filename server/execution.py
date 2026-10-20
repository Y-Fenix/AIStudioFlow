"""GagaSort 报告适配；不根据历史报告冒充本次运行。"""
STATUS = {'PASS': 'passed', 'FAIL': 'failed', 'SKIP': 'skipped',
          'NOT_RUN': 'not_run', 'ERROR': 'runner_error'}


def map_cases(cases, execution, mappings):
    """记录人工确认的断言关联；有缺口仍保持未执行，不能算通过。"""
    import copy
    if not isinstance(mappings, list):
        raise ValueError('用例映射必须为列表')
    by_case = {c['id']: c for c in cases}
    by_result = {r['id']: r for r in execution['results']}
    records = {}
    for item in mappings:
        if not isinstance(item, dict) or item.get('case_id') not in by_case or item['case_id'] in records:
            raise ValueError('用例映射引用不存在或重复')
        refs = item.get('result_ids', [])
        if not isinstance(refs, list) or any(not isinstance(x, str) or x not in by_result for x in refs) or len(set(refs)) != len(refs):
            raise ValueError('断言结果引用不存在或重复')
        reason, gap = item.get('reason', ''), item.get('gap_reason', '')
        if not isinstance(reason, str) or not isinstance(gap, str):
            raise ValueError('映射依据与缺口原因必须为文本')
        if refs and (not reason.strip() or gap.strip()):
            raise ValueError('关联断言需填写映射依据，不能同时标记未执行')
        results = [by_result[x] for x in refs]
        status = 'not_run'
        if results:
            status = 'failed' if any(r['status'] == 'failed' for r in results) else 'assertions_passed' if all(r['status'] == 'passed' and r.get('evidence') for r in results) else 'insufficient_evidence'
        records[item['case_id']] = {'case_id': item['case_id'], 'title': by_case[item['case_id']]['title'],
            'result_ids': refs, 'reason': reason, 'gap_reason': gap, 'status': status}
    for identifier, case in by_case.items():
        records.setdefault(identifier, {'case_id': identifier, 'title': case['title'], 'result_ids': [],
                                       'reason': '', 'gap_reason': '', 'status': 'not_run'})
    output = copy.deepcopy(execution)
    output['case_mapping'] = list(records.values())
    output['mapping_review_complete'] = all(r['result_ids'] or r['gap_reason'].strip() for r in records.values())
    output['mapping_scope'] = '人工确认断言关联；断言通过不等于已执行客户端步骤，未关联用例保持未执行'
    return output


def normalize_report(report, returncode, code_fingerprint, evidence_path):
    """从逐项记录重算统计，断言失败仍需归因而非直接提单。"""
    if not isinstance(report, dict) or not isinstance(report.get('cases'), list) or not report['cases']:
        raise ValueError('报告缺少逐项测试结果')
    results = []
    counts = {state: 0 for state in STATUS.values()}
    raw_counts = {state: 0 for state in STATUS}
    identifiers = set()
    for index, row in enumerate(report['cases']):
        if not isinstance(row, dict) or row.get('status') not in STATUS:
            raise ValueError('报告状态不合法')
        if not isinstance(row.get('name'), str) or not row['name'].strip():
            raise ValueError('报告缺少测试名称')
        if not isinstance(row.get('layer'), str) or not row['layer'].strip():
            raise ValueError('报告缺少验证层')
        identifier = str(row.get('id', index))
        if identifier in identifiers:
            raise ValueError('报告结果ID重复')
        identifiers.add(identifier)
        raw_status = row['status']
        state = STATUS[raw_status]
        raw_counts[raw_status] += 1
        counts[state] += 1
        classification = {'FAIL': 'assertion_failure_needs_triage', 'ERROR': 'execution_environment_error',
                          'NOT_RUN': 'coverage_gap', 'SKIP': 'coverage_gap', 'PASS': 'verified_assertions'}[raw_status]
        results.append({'id': identifier, 'test_name': row['name'], 'method': row['layer'],
                        'status': state, 'classification': classification,
                        'detail': row.get('detail', ''), 'evidence': evidence_path})
    if 'counts' in report and report['counts'] != raw_counts:
        raise ValueError('报告汇总与逐项结果不一致')
    incomplete = counts['runner_error'] or counts['not_run'] or counts['skipped']
    if returncode != 0 and not counts['failed'] and not counts['runner_error']:
        incomplete = True
    return {'results': results, 'counts': counts, 'returncode': returncode,
            'code_fingerprint': code_fingerprint, 'evidence': evidence_path,
            'overall': 'incomplete' if incomplete else 'failed' if counts['failed'] else 'passed',
            'scope': '仅证明本报告列出的断言；尚未证明需求用例映射完整'}
