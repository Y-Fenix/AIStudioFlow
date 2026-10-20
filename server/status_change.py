"""用户确认后的单条 Bug 状态更新；不确定结果只能只读核对，禁止自动重发。"""
import hashlib
import json
import uuid
from datetime import datetime, timezone


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class StatusChanges:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS status_changes (
                identity TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),root_cause_id TEXT NOT NULL,
                preview_hash TEXT NOT NULL,request TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'prepared',
                attempt TEXT,detail TEXT,checked_at TEXT,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    def list(self, project, task_id):
        with self.store.connection() as db:
            self.store._task(db, project, task_id)
            rows = [dict(r) for r in db.execute('SELECT * FROM status_changes WHERE task_id=? ORDER BY rowid', (task_id,))]
        for row in rows:
            row['request'] = json.loads(row['request'])
        return rows

    def recover_interrupted(self):
        with self.store.connection() as db:
            db.execute("UPDATE status_changes SET status='uncertain',detail='服务中断，不能确定是否已更新；只读核对，禁止重发',updated_at=CURRENT_TIMESTAMP WHERE status='sending'")

    def _context(self, task, root_id, desired):
        if task['stage'] != 5 or task['status'] != 'waiting_user':
            raise ValueError('请在未结束的回归节点确认状态')
        if any(j['status'] in ('queued', 'running') for j in task.get('jobs', [])):
            raise ValueError('请等待当前后台操作结束')
        regression, artifacts, target = task['regression'], task['artifacts'], task['bug_target']
        execution = regression.get('execution', {})
        review = artifacts.get('5', {})
        if execution.get('method') != 'static_code_review' or not execution.get('code_fingerprint'):
            raise ValueError('需要本次逐用例静态回归证据，固定探针不能替代')
        from server.regression import validate_static_inputs
        validate_static_inputs(artifacts.get('1', {}), execution)
        decision = next((d for d in review.get('decisions', []) if d['root_cause_id'] == root_id), None)
        if not review.get('ready_for_review') or review.get('code_fingerprint') != execution['code_fingerprint'] or not decision or decision['action'] != 'accept_logic_only':
            raise ValueError('请先保存此根因的静态通过评审与理由')
        roots = [r for r in regression.get('roots', []) if r['root_cause_id'] == root_id]
        if len(roots) != 1 or roots[0].get('verdict') != 'logic_assertions_passed':
            raise ValueError('缺陷仍存在或证据不足，不能确认验证通过')
        drafts = [d for d in artifacts.get('4', {}).get('drafts', []) if d['root_cause_id'] == root_id]
        links = [l for l in artifacts.get('4', {}).get('linked_records', []) if l['root_cause_id'] == root_id]
        if len(drafts) != 1 or len(links) != 1 or links[0]['draft_key'] != drafts[0]['draft_key']:
            raise ValueError('根因与远端 Bug 尚未唯一关联')
        link = links[0]
        if not target.get('verified') or any(link.get(k) != target.get(k) for k in ('base_token', 'table_id')):
            raise ValueError('关联 Bug 的目标表已变化')
        results = roots[0].get('results', [])
        ids = [r.get('case_id', r.get('id')) for r in results]
        required = drafts[0]['related_result_ids']
        if not required or len(ids) != len(required) or set(ids) != set(required) or any(r.get('status') != 'passed' or not r.get('evidence') for r in results):
            raise ValueError('原问题用例未全部取得静态支持证据')
        field_id = link['status_snapshot']['field_id']
        field = next((f for f in target['fields'] if f.get('field_id', f.get('id')) == field_id), None)
        if not field or field.get('type') != 'select' or field.get('multiple'):
            raise ValueError('最终状态当前仅支持已识别的单选状态字段')
        pending = link['status_snapshot']['pending_value']
        if not isinstance(desired, str) or desired not in {o['name'] for o in field.get('options', [])} or desired == pending:
            raise ValueError('请选择目标表中真实的验证通过选项，不能与待验证相同')
        return {'root_cause_id': root_id, 'title': roots[0]['title'], 'base_token': target['base_token'],
                'table_id': target['table_id'], 'record_id': link['record_id'], 'field_id': field_id,
                'expected_value': pending, 'target_value': desired,
                'payload': {'update_records': {link['record_id']: {field_id: desired}}},
                'branch': execution.get('branch'), 'commit': execution.get('commit'),
                'code_fingerprint': execution['code_fingerprint'], 'regression_hash': digest(regression),
                'review_hash': digest(review), 'review_reason': decision['reason'],
                'evidence': [r['evidence'] for r in results], 'revision': task['revision'],
                'scope': '用户依据静态回归作出状态决定；不代表平台已实机验证',
                'concurrency_limit': '飞书CLI不支持原子条件更新；提交前复查状态，仍存在检查与写入之间的并发窗口'}

    def _baseline(self, task, request, inspector):
        binding = task['binding']
        current = inspector(binding['repository'], binding['branch'])
        if any(current.get(key) != request.get(key) for key in ('branch', 'commit', 'code_fingerprint')):
            raise ValueError('代码已变化，请重新回归并评审')

    def _fresh_target(self, task, request, client):
        fresh = client.inspect_bug_target(task['bug_target']['url'])
        if any(fresh.get(key) != request[key] for key in ('base_token', 'table_id')):
            raise ValueError('飞书目标表已变化')
        old_field = next(f for f in task['bug_target']['fields'] if f.get('field_id', f.get('id')) == request['field_id'])
        new_field = next((f for f in fresh.get('fields', []) if f.get('field_id', f.get('id')) == request['field_id']), None)
        if not fresh.get('verified') or new_field != old_field:
            raise ValueError('状态字段或选项已变化，请重新识别目标表')
        return fresh

    def prepare(self, project, task_id, root_id, desired, revision, client, inspector):
        task = self.store.task(project, task_id)
        if task['revision'] != revision:
            raise ValueError('任务已变化，请刷新')
        request = self._context(task, root_id, desired)
        self._baseline(task, request, inspector)
        target = self._fresh_target(task, request, client)
        check = client.read_bug_status(target, request['record_id'], request['field_id'], request['expected_value'])
        if check.get('value') != request['expected_value']:
            raise ValueError('远端 Bug 已不是待验证，未准备状态变更')
        request['prepared_at'] = now()
        identity = digest([task_id, root_id, request['base_token'], request['table_id'], request['record_id'],
                           request['field_id'], request['code_fingerprint']])
        preview_hash = digest(request)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = self.store._task(db, project, task_id)
            if latest['revision'] != revision or latest['status'] != 'waiting_user':
                raise ValueError('任务已变化，预览未保存')
            blockers = db.execute("SELECT request,status FROM status_changes WHERE task_id=? AND status IN ('sending','uncertain')", (task_id,)).fetchall()
            if any(json.loads(r['request'])['record_id'] == request['record_id'] for r in blockers):
                raise ValueError('该 Bug 已在发送或结果不确定，只能核对，禁止重发')
            old = db.execute('SELECT status FROM status_changes WHERE identity=?', (identity,)).fetchone()
            if old and old['status'] in ('confirmed', 'reconciled'):
                raise ValueError('此代码版本的状态决定已完成，禁止重复发送')
            db.execute('''INSERT INTO status_changes(identity,task_id,root_cause_id,preview_hash,request)
                VALUES(?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET preview_hash=excluded.preview_hash,
                request=excluded.request,status='prepared',attempt=NULL,detail=NULL,updated_at=CURRENT_TIMESTAMP''',
                (identity, task_id, root_id, preview_hash, json.dumps(request, ensure_ascii=False)))
            self.store._event(db, task_id, 'status_change_prepared', '只读准备状态变更：'+request['record_id']+'；尚未写入')
        return next(r for r in self.list(project, task_id) if r['identity'] == identity)

    def _finish(self, identity, attempt, state, detail):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT task_id FROM status_changes WHERE identity=? AND attempt=? AND status=\'sending\'', (identity, attempt)).fetchone()
            if not row:
                raise ValueError('状态变更尝试已结束或不匹配')
            db.execute('UPDATE status_changes SET status=?,detail=?,checked_at=?,updated_at=CURRENT_TIMESTAMP WHERE identity=?',
                       (state, detail, now(), identity))
            self.store._event(db, row['task_id'], 'status_change_'+state, detail)

    def confirm(self, project, task_id, identity, preview_hash, revision, confirmed, acknowledged, client, inspector):
        if confirmed is not True or acknowledged is not True:
            raise ValueError('需要明确确认远端状态变更，并确认这是静态回归决定')
        row = next((r for r in self.list(project, task_id) if r['identity'] == identity), None)
        if not row or row['status'] != 'prepared' or row['preview_hash'] != preview_hash:
            raise ValueError('预览已过期、已发送或结果不确定，禁止重复更新')
        request = row['request']
        task = self.store.task(project, task_id)
        if task['revision'] != revision or request['revision'] != revision:
            raise ValueError('审核版本已变化，请重新准备')
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(request['prepared_at'])).total_seconds()
        if not 0 <= age <= 300:
            raise ValueError('状态变更预览超过5分钟，请重新准备')
        current = self._context(task, request['root_cause_id'], request['target_value'])
        if any(current[k] != request[k] for k in current):
            raise ValueError('回归、评审或关联已变化，请重新准备')
        self._baseline(task, request, inspector)
        target = self._fresh_target(task, request, client)
        attempt = uuid.uuid4().hex
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = self.store._task(db, project, task_id)
            if latest['revision'] != revision or latest['status'] != 'waiting_user' or latest['stage'] != 5:
                raise ValueError('任务已变化，禁止发送')
            if db.execute("SELECT id FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone():
                raise ValueError('后台操作尚未完成')
            cursor = db.execute("UPDATE status_changes SET status='sending',attempt=?,detail=?,updated_at=CURRENT_TIMESTAMP WHERE identity=? AND preview_hash=? AND status='prepared'",
                (attempt, '本机用户明确确认状态决定及静态范围；飞书CLI用户身份执行', identity, preview_hash))
            if cursor.rowcount != 1:
                raise ValueError('已有发送者领取此请求，禁止重复发送')
            import getpass
            self.store._event(db, task_id, 'status_change_user_confirmed', json.dumps({
                'local_os_user': getpass.getuser(), 'identity': identity, 'attempt': attempt,
                'record_id': request['record_id'], 'target_value': request['target_value'],
                'review_reason': request['review_reason'], 'static_scope_acknowledged': True,
                'confirmed_at': now(), 'remote_identity': 'lark-cli --as user；未记录飞书用户ID'}, ensure_ascii=False))
        try:
            check = client.read_bug_status(target, request['record_id'], request['field_id'], request['expected_value'])
            if check.get('value') != request['expected_value']:
                self._finish(identity, attempt, 'conflict', '提交前状态已变化，未发送更新：'+request['record_id'])
                raise ValueError('远端状态已变化，未发送更新')
        except Exception:
            # 此段没有调用更新接口；读取失败也不应被标为发送成功。
            rows = self.list(project, task_id)
            if next(r for r in rows if r['identity'] == identity)['status'] == 'sending':
                self._finish(identity, attempt, 'conflict', '发送前读取失败，未调用更新接口')
            raise
        try:
            response = client.update_bug_status(request)
            if not isinstance(response, dict) or response.get('ignored_fields'):
                raise ValueError('状态字段被忽略或响应不完整')
            after = client.read_bug_status(target, request['record_id'], request['field_id'], request['expected_value'])
            if after.get('value') != request['target_value']:
                raise ValueError('更新后状态读回不一致')
        except Exception:
            self._finish(identity, attempt, 'uncertain', '更新或读回未取得完整证据；只读核对，禁止重发：'+request['record_id'])
            raise ValueError('状态变更结果不确定，请只读核对；禁止重复发送') from None
        self._finish(identity, attempt, 'confirmed', '用户确认后更新，读回状态为 '+request['target_value']+'：'+request['record_id'])
        return next(r for r in self.list(project, task_id) if r['identity'] == identity)

    def reconcile(self, project, task_id, identity, client):
        row = next((r for r in self.list(project, task_id) if r['identity'] == identity), None)
        if not row or row['status'] != 'uncertain':
            raise ValueError('只有结果不确定的状态变更需要核对')
        request = row['request']
        task = self.store.task(project, task_id)
        target = self._fresh_target(task, request, client)
        check = client.read_bug_status(target, request['record_id'], request['field_id'], request['expected_value'])
        if check.get('value') != request['target_value']:
            raise ValueError('远端状态与目标不同，保持不确定，不能重发')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            cursor = db.execute("UPDATE status_changes SET status='reconciled',detail=?,checked_at=?,updated_at=CURRENT_TIMESTAMP WHERE identity=? AND task_id=? AND status='uncertain'",
                ('只读核对已为目标状态；不宣称一定由本次请求写入', now(), identity, task_id))
            if cursor.rowcount != 1:
                raise ValueError('状态变更台账已变化')
            self.store._event(db, task_id, 'status_change_reconciled', request['record_id']+' 当前为 '+request['target_value']+'；没有重发')
        return next(r for r in self.list(project, task_id) if r['identity'] == identity)
