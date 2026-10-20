"""由确认根因与运行记录生成内部草稿，不补写虚构复现结果。"""
import hashlib
import json


def prepare_drafts(groups, results, observations, environment):
    """补充复现信息与自动执行证据分开保存，禁止覆盖原始结果。"""
    if not isinstance(observations, list):
        raise ValueError('复现记录必须为列表')
    allowed = {r['id'] for r in results if r['status'] == 'failed'}
    notes = {}
    for item in observations:
        if not isinstance(item, dict) or item.get('result_id') not in allowed or item['result_id'] in notes:
            raise ValueError('复现记录引用不存在或重复')
        note = {}
        for field in ('steps', 'preconditions'):
            value = item.get(field, [])
            if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError('复现步骤与前置条件必须为非空文本列表')
            note[field] = value
        for field in ('expected', 'actual'):
            value = item.get(field, '')
            if not isinstance(value, str):
                raise ValueError('预期与实际结果必须为文本')
            note[field] = value.strip()
        notes[item['result_id']] = note
    enriched = [{**r, **notes.get(r['id'], {})} for r in results]
    drafts = build_drafts(groups, enriched, environment)
    for draft in drafts:
        draft['reproduction_provenance'] = 'user_supplied' if draft['representative_result_id'] in notes else 'static_inference' if environment.get('method') == 'static_code_review' else 'runner'
    return {'drafts': drafts, 'observations': observations,
            'publication_complete': not drafts, 'target_schema_verified': False}


def build_drafts(groups, failures, environment):
    """每个根因一单，使用具有完整复现记录的关联失败作为代表。"""
    by_id = {item['id']: item for item in failures}
    if len(by_id) != len(failures):
        raise ValueError('失败ID重复')
    drafts, seen = [], set()
    for group in groups:
        root_id = group.get('root_cause_id')
        if not isinstance(root_id, str) or not root_id or root_id in seen:
            raise ValueError('根因ID不合法或重复')
        seen.add(root_id)
        refs = group.get('result_ids')
        if not isinstance(refs, list) or not refs or any(ref not in by_id for ref in refs):
            raise ValueError('草稿关联失败记录不存在')
        records = [by_id[ref] for ref in refs]
        if any(record.get('status') != 'failed' for record in records):
            raise ValueError('草稿只能关联断言失败')
        def quality(record):
            return sum(bool(record.get(key)) for key in ('steps', 'expected', 'actual', 'preconditions', 'evidence'))
        representative = max(records, key=quality)
        missing = []
        steps = representative.get('steps')
        if not isinstance(steps, list) or not steps or any(not isinstance(step, str) or not step.strip() for step in steps):
            missing.append('复现步骤')
            steps = []
        for field, label in [('expected','预期结果'),('actual','实际结果'),('preconditions','前置条件'),('evidence','运行证据')]:
            if not representative.get(field):
                missing.append(label)
        for field, label in [('project','项目'),('code_fingerprint','代码版本')]:
            if not environment.get(field):
                missing.append(label)
        logic_only = environment.get('method') in ('production_method_probe_with_stubs', 'production_suite_with_stubs', 'static_code_review')
        if not logic_only and not environment.get('build'):
            missing.append('构建版本')
        identity = json.dumps({'root':root_id,'results':sorted(refs),'version':environment.get('code_fingerprint')},sort_keys=True)
        drafts.append({'draft_key':hashlib.sha256(identity.encode()).hexdigest(),
            'root_cause_id':root_id,'title':group.get('title'),'related_result_ids':list(refs),
            'representative_result_id':representative['id'],'environment':dict(environment),
            'steps':list(steps),'preconditions':representative.get('preconditions'),
            'expected':representative.get('expected'),'actual':representative.get('actual'),
            'root_evidence':group.get('root_evidence',[]),
            'failure_evidence':[r['evidence'] for r in records if r.get('evidence')],
            'verification_scope': '静态推导的触发条件与异常；未实机复现，未编译或运行客户端' if environment.get('method') == 'static_code_review' else '生产逻辑断言；未执行Unity客户端，未验证客户端构建' if logic_only else '以实际执行环境和构建证据为准',
            'missing':missing,'ready_for_review':not missing,'publication_status':'internal_draft'})
    return drafts


BUG_CONTENT_FIELDS = {
    'full_description': '完整缺陷描述（标题、条件、步骤、预期、实际、证据）',
    'title': '标题', 'preconditions': '前置条件', 'steps': '复现步骤',
    'expected': '预期结果', 'actual': '实际结果', 'root_evidence': '根因证据',
    'failure_evidence': '运行证据', 'environment': '测试环境',
    'related_result_ids': '关联失败', 'draft_key': '草稿唯一标识',
}


def preview_field_mapping(drafts, target, mapping):
    """只构造文本字段提单预览；不发布、不自动推断字段含义。"""
    if not target.get('verified') or not target.get('table_id') or not target.get('base_token'):
        raise ValueError('请先只读识别飞书 Bug 表字段')
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError('请配置字段映射')
    fields = {f.get('field_id', f.get('id')): f for f in target.get('fields', [])}
    for identifier, source in mapping.items():
        field = fields.get(identifier)
        if not field:
            raise ValueError('字段映射引用不存在的字段')
        if isinstance(source, dict):
            value = source.get('literal')
            options = {o.get('name') for o in field.get('options', [])}
            if field.get('type') != 'select' or field.get('multiple') or not isinstance(value, str) or not value or value not in options:
                raise ValueError('单选值必须是目标表已有选项')
            continue
        if not isinstance(source, str) or source not in BUG_CONTENT_FIELDS:
            raise ValueError('字段映射引用不存在的内容')
        style = field.get('style') or {}
        if field.get('type') != 'text' or style.get('type', 'plain') != 'plain':
            raise ValueError('当前映射仅支持普通文本字段；不转换其他类型')
    if not drafts:
        raise ValueError('尚无 Bug 草稿')
    records = []
    for draft in drafts:
        values, rows = {}, []
        for identifier, source in mapping.items():
            if isinstance(source, dict):
                value = source['literal']
            elif source == 'full_description':
                def lines(value):
                    return '\n'.join(str(v) for v in value) if isinstance(value, list) else str(value or '未提供')
                value = '\n\n'.join(label+'：\n'+lines(draft.get(key)) for key,label in [
                    ('title','标题'), ('preconditions','前置条件'), ('steps','复现步骤'),
                    ('expected','预期结果'), ('actual','实际结果'),
                    ('root_evidence','根因证据'), ('failure_evidence','运行证据'),
                    ('verification_scope','验证范围')])
                value += '\n\n测试环境与版本：\n'+json.dumps(draft.get('environment', {}), ensure_ascii=False, indent=2)
            else:
                value = draft.get(source)
            if source == 'environment':
                value = json.dumps(value or {}, ensure_ascii=False, indent=2)
            elif isinstance(value, list):
                value = '\n'.join((f'{i+1}. ' if source == 'steps' else '') + str(v)
                                  for i, v in enumerate(value))
            elif value is None:
                value = ''
            if not isinstance(value, str):
                raise ValueError('草稿内容不是可映射文本')
            values[identifier] = value
            rows.append({'field_id': identifier, 'field_name': fields[identifier].get('field_name', fields[identifier].get('name', identifier)),
                         'source': source, 'value': value})
        essential = {'title', 'steps', 'expected', 'actual'}
        mapped = {v for v in mapping.values() if isinstance(v, str)}
        if 'full_description' in mapped:
            mapped.update(essential)
        unmapped = [BUG_CONTENT_FIELDS[k] for k in sorted(essential - mapped)]
        records.append({'draft_key': draft['draft_key'], 'fields': values, 'rows': rows,
                        'missing': list(draft.get('missing', [])), 'unmapped': unmapped,
                        'ready_for_review': not draft.get('missing') and not unmapped})
    identity = json.dumps({'target': target, 'mapping': mapping, 'records': records}, sort_keys=True, ensure_ascii=False)
    return {'mapping': mapping, 'records': records, 'target_table_id': target['table_id'],
            'preview_hash': hashlib.sha256(identity.encode()).hexdigest(),
            'publication_status': 'preview_only', 'external_write_performed': False,
            'scope': '文本字段提单预览；未发布，尚未校验表的必填字段与其他类型'}


def confirm_existing_records(artifact, target):
    """用户确认已读到的根因/记录对应关系，不声称创建了远端单据。"""
    from datetime import datetime, timezone
    drafts = artifact.get('drafts', [])
    checks = artifact.get('remote_checks', {})
    if not target.get('verified') or not drafts:
        raise ValueError('需要目标表和根因草稿')
    linked, seen = [], set()
    for draft in drafts:
        check = checks.get(draft['draft_key'])
        if not isinstance(check, dict) or check.get('table_id') != target['table_id']:
            raise ValueError('每个根因都必须在当前目标表读取已有 Bug 单')
        record = check.get('record_id')
        if not record or record in seen:
            raise ValueError('不同根因不能重复关联同一记录；请先核对归因')
        seen.add(record)
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(check['checked_at'])).total_seconds()
        except (KeyError, TypeError, ValueError):
            raise ValueError('Bug 状态读取时间无效') from None
        if not 0 <= age <= 600:
            raise ValueError('Bug 读取结果已过期，请重新检查状态')
        if draft.get('missing'):
            raise ValueError('草稿复现信息仍有缺口，不能确认提单完成')
        linked.append({'draft_key': draft['draft_key'], 'root_cause_id': draft['root_cause_id'],
                       'record_id': record, 'table_id': target['table_id'],
                       'base_token': target['base_token'], 'status_snapshot': check})
    return {**artifact, 'linked_records': linked, 'publication_complete': True,
            'submission_method': 'user_confirmed_existing_records',
            'external_write_performed': False}


def prepare_publication(artifact, target, preview_hash):
    """依据当前草稿/字段重新构造实际CLI请求；只准备，不执行写入。"""
    preview = artifact.get('field_preview')
    if not isinstance(preview, dict) or not isinstance(preview_hash, str):
        raise ValueError('请先保存字段预览')
    fresh = preview_field_mapping(artifact.get('drafts', []), target, preview.get('mapping'))
    if preview_hash != fresh['preview_hash'] or preview != fresh:
        raise ValueError('字段或草稿已变化，请重新预览')
    drafts = artifact['drafts']
    keys = [d['draft_key'] for d in drafts]
    roots = [d.get('root_cause_id') for d in drafts]
    if len(set(keys)) != len(keys) or any(not isinstance(r, str) or not r for r in roots) or len(set(roots)) != len(roots):
        raise ValueError('草稿标识或根因重复，请重新归因')
    if any(not r['ready_for_review'] for r in fresh['records']):
        raise ValueError('复现信息或字段映射有缺口，不能准备发布')
    # 每条独立请求绑定一个根因，便于后续保存部分成功和结果不确定状态。
    requests = []
    for draft, record in zip(drafts, fresh['records']):
        payload = {'create_records': [record['fields']]}
        identity = {'base_token': target['base_token'], 'table_id': target['table_id'],
                    'draft_key': draft['draft_key'], 'payload': payload}
        requests.append({**identity, 'root_cause_id': draft['root_cause_id'],
                         'request_hash': hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()})
    return {'preview_hash': preview_hash, 'requests': requests,
            'command': ['lark-cli', 'base', '+record-batch-create'],
            'status': 'prepared_only', 'external_write_performed': False,
            'scope': '发布请求已准备；未创建记录，未验证写权限或目标表全部约束；请求哈希不等于远端幂等保证'}


def export_bug_preview(artifact, format):
    """导出已保存字段预览，一条根因一行；导出不等于发布。"""
    import csv
    import io
    preview = artifact.get('field_preview')
    if not isinstance(preview, dict) or not preview.get('records'):
        raise ValueError('请先保存飞书字段映射预览')
    records = preview['records']
    if format == 'json':
        data = {'scope': preview['scope'], 'preview_hash': preview['preview_hash'],
                'records': records, 'external_write_performed': False}
        return json.dumps(data, ensure_ascii=False, indent=2).encode(), 'application/json', 'json'
    if format != 'csv':
        raise ValueError('只支持 JSON 或 CSV 导出')
    first = records[0]['rows']
    identifiers = [row['field_id'] for row in first]
    # 保留同名字段的真实 ID，避免导入时误识别列。
    headers = [row['field_name']+' ['+row['field_id']+']' for row in first]
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    def safe(value):
        value = str(value or '')
        return "'"+value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value
    writer.writerow([safe(v) for v in headers]+['草稿标识','缺失信息','状态'])
    for record in records:
        if [row['field_id'] for row in record['rows']] != identifiers:
            raise ValueError('预览字段不一致，请重新生成预览')
        writer.writerow([safe(record['fields'].get(key, '')) for key in identifiers]+
                        [record['draft_key'],safe('、'.join(record['missing']+record['unmapped'])), '未发布的字段预览'])
    return ('\ufeff'+stream.getvalue()).encode(), 'text/csv', 'csv'
