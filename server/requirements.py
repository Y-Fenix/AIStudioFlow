"""结构化用例与需求引用校验；不把结构覆盖当作业务完整性证明。"""
import copy


def text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field}不能为空')
    return value


def validate_cases(output, requirements):
    """拒绝虚构来源、缺断言及没有解释的覆盖缺口。"""
    if not isinstance(output, dict):
        raise ValueError('生成结果必须为对象')
    for key in ('points', 'cases', 'gaps', 'ambiguities'):
        if not isinstance(output.get(key), list):
            raise ValueError(f'{key}必须为列表')
    sources = {r['id']: r['content'] for r in requirements}
    points = {}
    for point in output['points']:
        if not isinstance(point, dict):
            raise ValueError('测试点格式错误')
        point_id = text(point.get('id'), '测试点ID')
        if point_id in points:
            raise ValueError('测试点ID重复')
        text(point.get('title'), '测试点名称')
        source = point.get('requirement_id')
        quote = text(point.get('quote'), '来源引用')
        if source not in sources or quote not in sources[source]:
            raise ValueError('测试点来源或引用不存在')
        points[point_id] = point
    if not points:
        raise ValueError('没有可审阅的测试点')
    represented_sources = {point['requirement_id'] for point in points.values()}
    if set(sources) - represented_sources:
        raise ValueError('存在需求来源未拆解为测试点，请补充或确认来源范围')
    covered, case_ids, signatures = set(), set(), set()
    for case in output['cases']:
        if not isinstance(case, dict):
            raise ValueError('用例格式错误')
        case_id = text(case.get('id'), '用例ID')
        if case_id in case_ids:
            raise ValueError('用例ID重复')
        case_ids.add(case_id)
        text(case.get('title'), '用例名称')
        conditions = case.get('preconditions')
        if not isinstance(conditions, list) or not conditions:
            raise ValueError('用例缺少前置条件')
        for condition in conditions:
            text(condition, '前置条件')
        refs = case.get('point_ids')
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in points for ref in refs):
            raise ValueError('用例关联测试点不存在')
        steps = case.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ValueError('用例缺少步骤')
        signature = []
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError('步骤格式错误')
            signature.append((text(step.get('action'), '操作'), text(step.get('expected'), '预期')))
        fingerprint = (tuple(conditions), tuple(signature), tuple(sorted(refs)))
        if fingerprint in signatures:
            raise ValueError('检测到完全重复用例，请合并')
        signatures.add(fingerprint)
        covered.update(refs)
    gaps = set()
    for gap in output['gaps']:
        if not isinstance(gap, dict) or gap.get('point_id') not in points:
            raise ValueError('覆盖缺口引用不存在')
        text(gap.get('reason'), '缺口原因')
        gaps.add(gap['point_id'])
    if covered & gaps:
        raise ValueError('已覆盖测试点不能同时标记为缺口')
    if set(points) - covered - gaps:
        raise ValueError('存在未说明的覆盖缺口')
    for ambiguity in output['ambiguities']:
        text(ambiguity, '待确认问题')
    result = copy.deepcopy(output)
    result.pop('user_review', None)
    result['coverage'] = {'identified': len(points), 'covered': len(covered), 'gaps': len(gaps),
        'scope': '仅针对已识别测试点；需要人工确认需求是否完整拆解'}
    return result


def case_review_items(output, requirements):
    import hashlib
    import json
    items = []
    def add(kind, source, detail):
        key = json.dumps([kind, source, detail], ensure_ascii=False)
        items.append({'id': hashlib.sha256(key.encode()).hexdigest(), 'kind': kind,
                      'source': source, 'detail': detail})
    for requirement in resolve_source_gaps(requirements):
        metadata = requirement.get('metadata', {})
        for gap in metadata.get('effective_source_gaps', metadata.get('source_gaps', [])):
            add('source_gap', requirement['source'], gap)
    for gap in output.get('gaps', []):
        add('coverage_gap', gap['point_id'], gap['reason'])
    for ambiguity in output.get('ambiguities', []):
        add('ambiguity', '需求歧义', ambiguity)
    return list({item['id']: item for item in items}.values())


def case_review_hash(output, requirements):
    import hashlib
    import json
    base = {k:v for k,v in output.items() if k != 'user_review'}
    sources = [{k:r.get(k) for k in ('id','sha256','metadata')} for r in resolve_source_gaps(requirements)]
    return hashlib.sha256(json.dumps([base,sources], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def resolve_source_gaps(requirements):
    """保留原始缺口；仅同一父需求版本的实际导入来源可消除读取提示。"""
    from urllib.parse import urlsplit
    result = copy.deepcopy(requirements)
    for parent in result:
        metadata = parent.setdefault('metadata', {})
        if not metadata.get('resources'):
            continue
        gaps = list(metadata.get('source_gaps', []))
        children = [child for child in requirements if child.get('content', '').strip()
                    and child.get('metadata', {}).get('referenced_by') == parent.get('source')
                    and child.get('metadata', {}).get('parent_sha256') == parent.get('sha256')
                    and parent.get('sha256')
                    and child.get('metadata', {}).get('parent_revision_id') == metadata.get('revision_id')]
        resources = metadata.get('resources', [])
        unread_citations, attachments = [], []
        for resource in resources:
            if resource.get('kind') == 'cite' and resource.get('type') == 'doc':
                path = '/'+str(resource.get('file-type'))+'/'+str(resource.get('doc-id'))
                found = any(urlsplit(child['source']).path == path
                            and urlsplit(child['source']).netloc == urlsplit(parent['source']).netloc for child in children)
                if not found:
                    unread_citations.append(resource.get('title') or resource.get('doc-id', '未知文档'))
            if resource.get('kind') == 'source':
                attachments.append(any(child.get('metadata', {}).get('file_token') == resource.get('token')
                                       and resource.get('token') for child in children))
        if any(r.get('kind') == 'cite' and r.get('type') == 'doc' for r in resources):
            gaps = [g for g in gaps if not g.startswith('引用文档未展开：')]
            if unread_citations:
                gaps.append('引用文档未展开：'+'、'.join(unread_citations))
        if attachments and all(attachments):
            gaps = [g for g in gaps if g != '尚未完整读取资源：source']
        metadata['effective_source_gaps'] = gaps
    return result


def review_cases(output, requirements, decisions, decomposition_confirmed):
    if decomposition_confirmed is not True:
        raise ValueError('请核对需求原文、测试点和用例，确认本次评审范围')
    items = case_review_items(output, requirements)
    if not isinstance(decisions, list) or len(decisions) != len(items):
        raise ValueError('请逐项记录来源缺口、覆盖缺口及歧义的处理方式')
    known = {item['id'] for item in items}
    seen, checked = set(), []
    for decision in decisions:
        if not isinstance(decision, dict) or decision.get('id') not in known or decision['id'] in seen:
            raise ValueError('评审条目不存在或重复')
        seen.add(decision['id'])
        if decision.get('action') not in ('accept_scope_gap', 'needs_revision'):
            raise ValueError('只能记录接受本次范围缺口或要求补充需求')
        reason = decision.get('reason')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError('请填写具体处理理由')
        checked.append({**decision,'reason':reason.strip()})
    return {'decisions': checked, 'decomposition_confirmed': True,
            'review_hash': case_review_hash(output, requirements),
            'ready_for_execution': all(d['action'] == 'accept_scope_gap' for d in checked),
            'scope': '人工确认本次测试范围；接受缺口不代表需求已全面覆盖'}
