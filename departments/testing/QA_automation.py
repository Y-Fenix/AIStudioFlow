"""Pure delegated QA decisions; no storage, authority, source IO or external writes."""
import json


def QA_scope_decisions(items):
    return [{'id': item['id'], 'action': 'accept_scope_gap',
             'reason': '自动范围决策：本次仅审查已识别且可执行的规则；此项保留为未覆盖/待确认风险，不视为测试通过。'+item['detail'][:1400]}
            for item in items]


def QA_root_decisions(suggestions, failures):
    expected = {row['id'] for row in failures}
    assigned, roots, assignments = set(), [], []
    for item in suggestions:
        refs = set(item['result_ids'])
        if not refs or not refs <= expected or assigned & refs or not item.get('evidence'):
            raise ValueError('归因证据或失败关联不完整，需补充后继续')
        assigned.update(refs)
        roots.append({'id': item['id'], 'title': item['title'], 'confirmed': True,
                      'confirmation_origin': 'automation',
                      'evidence': [json.dumps(ref, ensure_ascii=False) for ref in item['evidence']]})
        assignments.extend({'result_id': ref, 'root_cause_id': item['id']} for ref in item['result_ids'])
    if assigned != expected:
        raise ValueError('存在未完成归因的失败，不能自动编造根因或排除缺陷')
    return {'roots': roots, 'assignments': assignments, 'exclusions': [], 'decision_origin': 'automation'}
