"""按实际回归证据提供建议，不自动变更远端Bug状态。"""


def assess_regression(required_case_ids, results, code_version, build_version):
    """验证全部指定场景及版本一致性；不给出未经校准的概率。"""
    if not isinstance(required_case_ids, list) or not required_case_ids:
        raise ValueError('需要原失败及关联回归范围')
    if any(not isinstance(case_id, str) or not case_id for case_id in required_case_ids):
        raise ValueError('回归用例ID不合法')
    if len(set(required_case_ids)) != len(required_case_ids):
        raise ValueError('回归范围重复')
    by_case = {}
    for result in results:
        case_id = result.get('case_id')
        if case_id in by_case or case_id not in required_case_ids:
            raise ValueError('回归结果重复或超出范围')
        if result.get('status') not in ('passed','failed','runner_error','not_run','skipped'):
            raise ValueError('回归结果状态不合法')
        by_case[case_id] = result
    missing = [case_id for case_id in required_case_ids if case_id not in by_case]
    verified = [case_id for case_id, result in by_case.items()
                if result['status'] == 'passed' and result.get('evidence')]
    failed = [case_id for case_id, result in by_case.items()
              if result['status'] == 'failed' and result.get('evidence')]
    if not code_version or not build_version or code_version != build_version:
        verdict = 'version_mismatch'
    elif failed:
        verdict = 'still_reproducible'
    elif missing or len(verified) != len(required_case_ids):
        verdict = 'insufficient_evidence'
    else:
        verdict = 'runtime_passed'
    return {'verdict': verdict, 'required_case_ids': list(required_case_ids),
            'verified_case_ids': verified, 'failed_case_ids': failed,
            'missing_case_ids': missing, 'code_version': code_version,
            'build_version': build_version, 'repair_probability': None,
            'probability_reason': '没有经过历史结果校准的概率模型',
            'requires_user_confirmation': True,
            'remote_state_changed': False}


def assess_logic_roots(drafts, original, current):
    """按稳定的探针名称关联，不能按可能变化的报告行号匹配。"""
    if current.get('method') not in ('production_method_probe_with_stubs', 'production_suite_with_stubs', 'static_code_review') or not current.get('code_fingerprint'):
        raise ValueError('回归报告缺少逻辑执行来源')
    if current.get('method') == 'static_code_review':
        validate_static_inputs(original, current)
    before = {r['id']: r for r in original['results']}
    after = {}
    for result in current['results']:
        name = result['case_id'] if current.get('method') == 'static_code_review' else result['test_name']
        if name in after:
            raise ValueError('回归探针名称重复，无法可靠关联')
        after[name] = result
    roots = []
    for draft in drafts:
        refs = draft['related_result_ids']
        if not refs or any(ref not in before for ref in refs):
            raise ValueError('回归范围引用不存在')
        names = [before[ref].get('case_id', before[ref]['id']) if current.get('method') == 'static_code_review' else before[ref]['test_name'] for ref in refs]
        matched = [after[name] for name in names if name in after]
        missing = [name for name in names if name not in after]
        failed = [r for r in matched if r['status'] == 'failed' and r.get('evidence')]
        passed = [r for r in matched if r['status'] == 'passed' and r.get('evidence')]
        verdict = 'still_reproducible' if failed else 'logic_assertions_passed' if not missing and len(passed) == len(names) else 'insufficient_evidence'
        roots.append({'root_cause_id': draft['root_cause_id'], 'title': draft['title'],
                      'verdict': verdict, 'required_test_names': names, 'missing_test_names': missing,
                      'results': matched, 'repair_probability': None, 'requires_user_confirmation': True})
    return {'roots': roots, 'execution': current, 'remote_state_changed': False,
            'scope': '仅关联用例静态回归；未实机复现或验证客户端，未修改飞书状态' if current.get('method') == 'static_code_review' else '仅关联逻辑探针回归；未验证客户端构建、飞书待验证状态或完整需求回归范围',
            'probability_reason': '没有历史校准数据，不提供修复概率'}


def validate_static_inputs(original, current):
    """修复前后必须检查同一用例及需求版本，不能通过改预期制造修复。"""
    if original.get('method') != 'static_code_review' or current.get('method') != 'static_code_review':
        raise ValueError('原检测与回归方式不一致，请重新建立静态缺陷基线')
    for key in ('case_input_hash', 'requirements_hash'):
        if not isinstance(original.get(key), str) or not original[key] or current.get(key) != original[key]:
            raise ValueError('原用例或需求版本与静态回归不一致，不能沿用修复结论')


def review_logic_regression(regression, decisions):
    """结束本次回归评审，不等于关闭 Bug 或确认客户端通过。"""
    roots = regression.get('roots')
    if not isinstance(roots, list) or not roots:
        raise ValueError('请先运行回归并取得结果')
    if not isinstance(decisions, list) or len(decisions) != len(roots):
        raise ValueError('需要逐条根因做出决策')
    by_root = {r['root_cause_id']: r for r in roots}
    seen, reviewed = set(), []
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError('决策格式不合法')
        root_id = decision.get('root_cause_id')
        if root_id not in by_root or root_id in seen:
            raise ValueError('根因决策缺失或重复')
        seen.add(root_id)
        action = decision.get('action')
        reason = decision.get('reason')
        if action not in ('accept_logic_only', 'keep_open', 'needs_more_evidence'):
            raise ValueError('当前仅支持逻辑评审，不支持确认客户端验证通过')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError('请记录决策理由（最多2000字）')
        root = by_root[root_id]
        if action == 'accept_logic_only' and root.get('verdict') != 'logic_assertions_passed':
            raise ValueError('断言失败或证据不足，不能接受逻辑通过')
        reviewed.append({'root_cause_id': root_id, 'action': action, 'reason': reason.strip(),
                         'observed_verdict': root['verdict']})
    execution = regression.get('execution', {})
    if not execution.get('code_fingerprint'):
        raise ValueError('回归缺少代码版本')
    return {'decisions': reviewed, 'ready_for_review': True,
            'code_fingerprint': execution['code_fingerprint'],
            'scope': '仅记录回归评审；此操作不修改飞书或执行客户端，后续状态决定另记台账',
            'remote_state_changed': False, 'client_verified': False}
