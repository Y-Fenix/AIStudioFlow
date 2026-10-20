"""飞书CLI连接器；写入仅由审核发布入口调用，不隐式授权或自动重试。"""
import json
import os
import subprocess
import re
from urllib.parse import urlsplit


class LarkClient:
    def _url(self, url):
        if not isinstance(url, str):
            raise ValueError('需要飞书链接')
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or not (
            parsed.hostname.endswith('.feishu.cn') or parsed.hostname.endswith('.larksuite.com')):
            raise ValueError('只接受飞书或Lark HTTPS资源链接')
        return url

    def _read(self, arguments, cwd=None):
        env=dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER='1', LARKSUITE_CLI_NO_SKILLS_NOTIFIER='1')
        try:
            result=subprocess.run(['lark-cli',*arguments,'--as','user'],text=True,
                                  capture_output=True,timeout=60,env=env,check=False,cwd=cwd)
        except subprocess.TimeoutExpired:
            raise ValueError('飞书读取超时') from None
        except OSError:
            raise ValueError('无法启动 lark-cli') from None
        try:
            envelope=json.loads(result.stdout if result.returncode==0 else result.stderr)
        except (ValueError,TypeError):
            raise ValueError('飞书CLI返回格式不合法') from None
        if result.returncode or envelope.get('ok') is not True:
            error=envelope.get('error',{})
            # 仅输出错误类型，不回传凭据或任意原始诊断。
            if error.get('code') == 3380002 and "document type 'sheet'" in error.get('message', ''):
                raise ValueError('引用指向电子表格，文档读取入口不支持；未导入表格内容')
            kind=error.get('type','unknown')
            subtype=error.get('subtype','unknown')
            raise ValueError(f'飞书读取失败：{kind}/{subtype}')
        data=envelope.get('data')
        if not isinstance(data,dict):
            raise ValueError('飞书响应缺少数据对象')
        return data

    def fetch_document(self,url):
        return self._read(['docs','+fetch','--doc',self._url(url),'--detail','with-ids'])

    def create_bug_record(self, request):
        """创建单个已审核根因；调用方须先领取持久化台账。"""
        import tempfile
        from pathlib import Path
        token, table = request.get('base_token'), request.get('table_id')
        payload = request.get('payload')
        if (not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9]+', token)
                or not isinstance(table, str) or not re.fullmatch(r'tbl[A-Za-z0-9]+', table)
                or not isinstance(payload, dict) or set(payload) != {'create_records'}
                or not isinstance(payload['create_records'], list) or len(payload['create_records']) != 1
                or not isinstance(payload['create_records'][0], dict) or not payload['create_records'][0]):
            raise ValueError('发布请求格式不合法')
        with tempfile.TemporaryDirectory(prefix='testflow-publish-') as folder:
            path = Path(folder)/'request.json'
            path.write_text(json.dumps(payload, ensure_ascii=False))
            path.chmod(0o600)
            return self._read(['base', '+record-batch-create', '--base-token', token,
                               '--table-id', table, '--json', '@'+str(path), '--format', 'json'])

    def update_bug_status(self, request):
        """仅更新一个已审核记录的状态字段；调用方负责台账、复查与读回。"""
        import tempfile
        from pathlib import Path
        token, table = request.get('base_token'), request.get('table_id')
        record, field, value = request.get('record_id'), request.get('field_id'), request.get('target_value')
        if (not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9]+', token)
                or not isinstance(table, str) or not re.fullmatch(r'tbl[A-Za-z0-9]+', table)
                or not isinstance(record, str) or not re.fullmatch(r'rec[A-Za-z0-9_-]+', record)
                or not isinstance(field, str) or not field or not isinstance(value, str) or not value.strip()
                or request.get('payload') != {'update_records': {record: {field: value}}}):
            raise ValueError('状态更新只能包含一个记录的一个已审核状态字段')
        with tempfile.TemporaryDirectory(prefix='testflow-status-') as folder:
            path = Path(folder)/'request.json'
            path.write_text(json.dumps(request['payload'], ensure_ascii=False))
            path.chmod(0o600)
            return self._read(['base', '+record-batch-update', '--base-token', token,
                               '--table-id', table, '--json', '@'+str(path), '--format', 'json'])

    def verify_bug_record(self, request, target, record_id):
        """投影读取并逐字段精确核对；不把相似文本当作同一发布。"""
        if not isinstance(record_id, str) or not re.fullmatch(r'rec[A-Za-z0-9_-]+', record_id):
            raise ValueError('需要真实飞书记录 ID')
        if (not target.get('verified') or request['base_token'] != target.get('base_token')
                or request['table_id'] != target.get('table_id')):
            raise ValueError('核对目标与发布目标不一致')
        expected = request['payload']['create_records'][0]
        fields = {f.get('field_id', f.get('id')): f for f in target['fields']}
        arguments = ['base', '+record-get', '--base-token', request['base_token'],
                     '--table-id', request['table_id'], '--record-id', record_id, '--format', 'json']
        for identifier in expected:
            if identifier not in fields or fields[identifier].get('type') not in ('text', 'select'):
                raise ValueError('核对字段已变化或类型不支持')
            arguments.extend(['--field-id', identifier])
        data = self._read(arguments)
        columns, rows = data.get('field_id_list'), data.get('data')
        if (data.get('record_id_list') != [record_id] or not isinstance(columns, list)
                or any(not isinstance(c, str) for c in columns) or len(set(columns)) != len(columns)
                or set(columns) != set(expected) or not isinstance(rows, list) or len(rows) != 1
                or not isinstance(rows[0], list) or len(rows[0]) != len(columns)):
            raise ValueError('核对响应与记录或字段投影不一致')
        mismatches = []
        for identifier, value in zip(columns, rows[0]):
            if fields[identifier]['type'] == 'select':
                if fields[identifier].get('multiple') or not isinstance(value, list) or len(value) != 1:
                    raise ValueError('核对单选值格式不支持')
                value = value[0]
            if not isinstance(value, str) or value != expected[identifier]:
                mismatches.append(identifier)
        from datetime import datetime, timezone
        return {'record_id': record_id, 'base_token': request['base_token'], 'table_id': request['table_id'],
                'request_hash': request['request_hash'], 'matched': not mismatches,
                'mismatched_field_ids': mismatches, 'checked_at': datetime.now(timezone.utc).isoformat(),
                'remote_state_changed': False}

    def resolve_base(self,url):
        return self._read(['base','+url-resolve','--url',self._url(url)])

    def inspect_bug_target(self, url):
        resolved = self.resolve_base(url)
        token, table = resolved.get('base_token'), resolved.get('table_id')
        if isinstance(token, str) and token and not table and resolved.get('block_id'):
            blocks = self._read(['base', '+base-block-list', '--base-token', token]).get('blocks')
            if not isinstance(blocks, list):
                raise ValueError('资源目录响应格式不支持')
            matches = [b for b in blocks if isinstance(b, dict) and b.get('id') == resolved['block_id']]
            if len(matches) != 1 or matches[0].get('type') != 'table':
                raise ValueError('链接选中的资源未确认为数据表')
            table = matches[0]['id']
        if not isinstance(token, str) or not token or not isinstance(table, str) or not table.startswith('tbl'):
            raise ValueError('链接未解析为明确的数据表，请提供 Bug 数据表链接')
        if resolved.get('block_type') not in (None, 'table'):
            raise ValueError('链接指向非数据表资源')
        fields, offset = [], 0
        while offset <= 1000:
            data = self._read(['base', '+field-list', '--base-token', token, '--table-id', table,
                               '--limit', '200', '--offset', str(offset)])
            page = data.get('fields', data.get('items'))
            if not isinstance(page, list) or any(not isinstance(f, dict) for f in page):
                raise ValueError('字段响应格式不支持，未保存目标格式')
            fields.extend(page)
            if len(page) < 200 and not data.get('has_more'):
                break
            offset += len(page)
            if not page:
                raise ValueError('字段分页无法继续，未保存不完整格式')
        else:
            raise ValueError('字段数量超出读取范围')
        identifiers = [field.get('field_id', field.get('id')) for field in fields]
        if not fields or any(not isinstance(x, str) or not x for x in identifiers) or len(set(identifiers)) != len(identifiers):
            raise ValueError('字段为空或标识重复，未保存目标格式')
        return {'url': url, 'base_token': token, 'table_id': table, 'fields': fields,
                'verified': True, 'scope': '已读取数据表字段；未读取或修改记录'}

    def requirement(self, url):
        self._url(url)
        from server.sheet_requirements import read_sheet_requirement
        if urlsplit(url).path.startswith('/sheets/'):
            return read_sheet_requirement(self, url)
        try:
            data = self.fetch_document(url)
        except ValueError as exc:
            if str(exc) == '引用指向电子表格，文档读取入口不支持；未导入表格内容':
                return read_sheet_requirement(self, url)
            raise
        document = data.get('document', {})
        content = document.get('content')
        if not isinstance(content, str) or not content.strip():
            raise ValueError('飞书文档正文为空，未导入')
        gaps = []
        for tag in ('img', 'source', 'whiteboard', 'sheet', 'bitable', 'synced_reference', 'fragment', 'excerpt'):
            if re.search(r'<' + tag + r'(?:\s|/?>)', content):
                gaps.append('尚未完整读取资源：' + tag)
        if re.search(r'<cite\b[^>]*file-type=["\x27](sheets|bitable)["\x27]', content):
            gaps.append('尚未读取引用的电子表格或多维表格')
        from html.parser import HTMLParser
        resources, deleted = [], []
        class ResourceParser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag in ('img', 'source', 'cite', 'sheet', 'bitable', 'whiteboard'):
                    resources.append({'kind': tag, **values, 'read_status': 'reference_only'})
                if tag == 'del':
                    deleted.append(values.get('id'))
        parser = ResourceParser()
        parser.feed(content)
        citations = [r for r in resources if r['kind'] == 'cite' and r.get('type') == 'doc']
        if citations:
            gaps.append('引用文档未展开：' + '、'.join(r.get('title') or r.get('doc-id', '未知文档') for r in citations))
        if deleted:
            gaps.append('包含删除线历史内容（' + str(len(deleted)) + '处），需核对现行规则，不可当作当前要求')
        metadata = {'kind': 'feishu', 'document_id': document.get('document_id'),
                    'revision_id': document.get('revision_id'),
                    'reference_map': document.get('reference_map', {}),
                    'tips': document.get('tips'), 'source_gaps': gaps,
                    'resources': resources, 'deleted_block_count': len(deleted)}
        return content, metadata

    def attachment_requirement(self, parent_url, resource):
        """只下载已读取需求中明确的DOCX附件；不使用远端文件名作为本地路径。"""
        import base64
        import tempfile
        from pathlib import Path
        from server.file_import import parse_docx
        self._url(parent_url)
        token, name = resource.get('token'), resource.get('name')
        if (resource.get('kind') != 'source' or not isinstance(token, str)
                or not re.fullmatch(r'[A-Za-z0-9]+', token) or not isinstance(name, str)
                or not name.lower().endswith('.docx')):
            raise ValueError('当前仅支持需求中明确引用的DOCX源附件')
        try:
            size = int(resource['size'])
        except (ValueError, TypeError, KeyError):
            raise ValueError('附件缺少可核对的文件大小') from None
        if not 0 < size <= 700000:
            raise ValueError('DOCX附件不得超过700KB')
        with tempfile.TemporaryDirectory(prefix='testflow-requirement-') as folder:
            data = self._read(['drive', '+preview', '--file-token', token, '--type', 'source_file',
                               '--output', 'attachment.docx', '--format', 'json'], cwd=folder)
            if (data.get('file_token') != token or data.get('selected_type') != 'source_file'
                    or data.get('status') != 'READY'):
                raise ValueError('源附件下载结果不一致，未导入')
            path = Path(folder)/'attachment.docx'
            if not path.is_file() or path.is_symlink() or path.stat().st_size != size:
                raise ValueError('下载附件大小与需求引用不一致，未导入')
            raw = path.read_bytes()
            content, metadata = parse_docx(name, base64.b64encode(raw).decode())
        return content, {**metadata, 'kind': 'feishu_attachment', 'file_token': token,
                          'file_name': name, 'size_bytes': size, 'referenced_by': parent_url,
                          'resources': []}

    def read_bug_status(self, target, record_id, field_id, pending_value):
        """投影读取一条记录的状态；无法识别的响应绝不当作待验证。"""
        if not target.get('verified'):
            raise ValueError('请先识别 Bug 目标表')
        if not isinstance(record_id, str) or not re.fullmatch(r'rec[A-Za-z0-9_-]+', record_id):
            raise ValueError('需要真实飞书记录 ID（rec 开头）')
        field = next((f for f in target.get('fields', [])
                      if f.get('field_id', f.get('id')) == field_id), None)
        if not field or field.get('type') not in ('text', 'select') or field.get('multiple'):
            raise ValueError('状态字段必须是已识别的文本或单选字段')
        if not isinstance(pending_value, str) or not pending_value.strip() or len(pending_value) > 100:
            raise ValueError('请明确填写待验证状态值')
        data = self._read(['base', '+record-get', '--base-token', target['base_token'],
                           '--table-id', target['table_id'], '--record-id', record_id,
                           '--field-id', field_id, '--format', 'json'])
        if 'record_id_list' in data:
            ids, columns, rows = data.get('record_id_list'), data.get('field_id_list'), data.get('data')
            if ids != [record_id] or columns != [field_id] or not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], list) or len(rows[0]) != 1:
                raise ValueError('状态矩阵与指定记录/字段不一致')
            value = rows[0][0]
            if field.get('type') == 'select':
                if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], str):
                    raise ValueError('单选状态值为空或格式不支持')
                value = value[0]
            data = {'records': [{'record_id':record_id, 'fields':{field_id:value}}]}
        records = data.get('records')
        if records is None and isinstance(data.get('record'), dict):
            records = [data['record']]
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError('记录响应格式尚未验证，不能判断状态')
        record = records[0]
        if record.get('record_id', record.get('id')) != record_id:
            raise ValueError('返回记录与指定 Bug 不一致')
        fields = record.get('fields')
        if not isinstance(fields, dict):
            raise ValueError('记录缺少状态字段')
        name = field.get('field_name', field.get('name'))
        value = fields.get(field_id, fields.get(name))
        if not isinstance(value, str):
            raise ValueError('状态值不是已支持的文本；不能判断待验证')
        from datetime import datetime, timezone
        return {'record_id': record_id, 'table_id': target['table_id'],
                'field_id': field_id, 'field_name': name, 'value': value,
                'pending_value': pending_value.strip(), 'pending': value == pending_value.strip(),
                'checked_at': datetime.now(timezone.utc).isoformat(), 'remote_state_changed': False}

    def referenced_requirements(self, parent_url, metadata, limit=8):
        """只跟随已读取文档里的明确 Wiki/Docx/Sheets 引用；不猜附件内容。"""
        parsed = urlsplit(self._url(parent_url))
        resources = metadata.get('resources', [])
        if not isinstance(resources, list):
            raise ValueError('缺少已读取的引用资源清单')
        candidates, seen = [], set()
        for resource in resources:
            if resource.get('kind') != 'cite' or resource.get('type') != 'doc':
                continue
            kind, token = resource.get('file-type'), resource.get('doc-id')
            if kind not in ('wiki', 'docx', 'sheets') or not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9]+', token):
                continue
            url = 'https://' + parsed.netloc + '/' + kind + '/' + token
            if url not in seen and url != parent_url:
                candidates.append((url, resource.get('title', token)))
                seen.add(url)
        if len(candidates) > limit:
            raise ValueError('直接引用超过8个，请分批明确选择范围')
        results = []
        for url, title in candidates:
            try:
                content, child_metadata = self.requirement(url)
                results.append({'url': url, 'title': title, 'status': 'read', 'content': content,
                                'metadata': {**child_metadata, 'referenced_by': parent_url}})
            except ValueError as exc:
                results.append({'url': url, 'title': title, 'status': 'failed', 'error': str(exc)})
        return results
