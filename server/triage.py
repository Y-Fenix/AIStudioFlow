"""确认根因后的合并规则；不把相同报错自动当成相同原因。"""


def confirmed_groups(results, assignments, roots):
    """只合并已确认且具有证据的产品断言失败，保留全部结果关联。"""
    if not all(isinstance(items, list) for items in (results, assignments, roots)):
        raise ValueError('归因输入必须为列表')
    by_result, by_root = {}, {}
    for result in results:
        if not isinstance(result, dict) or not isinstance(result.get('id'), str) or not result['id']:
            raise ValueError('执行结果缺少ID')
        if result['id'] in by_result:
            raise ValueError('执行结果ID重复')
        by_result[result['id']] = result
    for root in roots:
        if not isinstance(root, dict) or not isinstance(root.get('id'), str) or not root['id']:
            raise ValueError('根因缺少ID')
        if root['id'] in by_root:
            raise ValueError('根因ID重复')
        by_root[root['id']] = root
    groups, seen = {}, set()
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise ValueError('归因映射格式错误')
        result_id, root_id = assignment.get('result_id'), assignment.get('root_cause_id')
        if not isinstance(result_id, str) or result_id not in by_result or root_id not in by_root:
            raise ValueError('归因引用不存在')
        if result_id in seen:
            raise ValueError('同一失败记录不可重复归入多个根因')
        seen.add(result_id)
        result, root = by_result[result_id], by_root[root_id]
        if result.get('status') != 'failed':
            raise ValueError('仅断言失败可进入产品Bug归因；运行器异常与缺口需另处理')
        if not result.get('evidence'):
            raise ValueError('失败记录缺少证据')
        evidence = root.get('evidence')
        if root.get('confirmed') is not True or not isinstance(evidence, list) or not evidence or any(not isinstance(e, str) or not e.strip() for e in evidence):
            raise ValueError('根因必须已确认且有证据')
        title = root.get('title')
        if not isinstance(title, str) or not title.strip():
            raise ValueError('根因缺少说明')
        group = groups.setdefault(root_id, {'root_cause_id': root_id, 'title': title,
            'root_evidence': list(evidence), 'result_ids': [], 'failure_evidence': []})
        group['result_ids'].append(result_id)
        if result['evidence'] not in group['failure_evidence']:
            group['failure_evidence'].append(result['evidence'])
    return list(groups.values())


def triage_report(results, assignments, roots, exclusions):
    groups = confirmed_groups(results, assignments, roots)
    if not isinstance(exclusions, list):
        raise ValueError('排除记录必须为列表')
    assigned = {item['result_id'] for item in assignments}
    failures = {item['id'] for item in results if item['status'] == 'failed'}
    seen = set()
    for item in exclusions:
        if not isinstance(item, dict) or item.get('result_id') not in failures:
            raise ValueError('排除记录引用不存在')
        identifier = item['result_id']
        if identifier in assigned or identifier in seen:
            raise ValueError('失败记录不能重复归因或排除')
        if not isinstance(item.get('reason'), str) or not item['reason'].strip():
            raise ValueError('排除失败记录必须说明原因')
        seen.add(identifier)
    unresolved = sorted(failures - assigned - seen)
    return {'groups': groups, 'assignments': assignments, 'roots': roots,
            'exclusions': exclusions, 'unresolved': unresolved,
            'ready_for_review': not unresolved,
            'environment_issues': [r for r in results if r['status'] in ('runner_error', 'not_run', 'skipped', 'needs_runtime', 'requirement_unclear', 'insufficient_evidence')]}


def filter_groups(triage, selected, excluded):
    if not triage.get('ready_for_review'):
        raise ValueError('仍有未归因的失败记录')
    if not isinstance(selected, list) or not all(isinstance(x, str) for x in selected) or len(set(selected)) != len(selected):
        raise ValueError('筛选根因ID不合法或重复')
    if not isinstance(excluded, dict) or any(not isinstance(v, str) or not v.strip() for v in excluded.values()):
        raise ValueError('不提单的根因必须填写原因')
    groups = {g['root_cause_id']: g for g in triage['groups']}
    if set(selected) & set(excluded) or set(selected) | set(excluded) != set(groups):
        raise ValueError('每个根因都必须选择提单或明确排除')
    return {'groups': [groups[x] for x in selected], 'excluded': excluded,
            'result_ids': [r for x in selected for r in groups[x]['result_ids']]}
