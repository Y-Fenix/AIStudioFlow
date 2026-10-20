"""持久化发布台账；本模块不调用飞书，不自动重试不确定写入。"""
import hashlib
import json
import re
import uuid


class PublicationLedger:
    def __init__(self, store):
        self.store = store
        with store.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS publications (
                identity TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                root_cause_id TEXT NOT NULL, request_hash TEXT NOT NULL, request TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'prepared', attempt TEXT, record_id TEXT, detail TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    def prepare(self, project, task_id, revision, plan):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self.store._task(db, project, task_id)
            if task['revision'] != revision or task['stage'] != 4 or task['status'] != 'waiting_user':
                raise ValueError('节点或版本已变化，请刷新')
            for request in plan['requests']:
                identity = hashlib.sha256(json.dumps([task_id, request['base_token'], request['table_id'],
                                                       request['root_cause_id']], ensure_ascii=False).encode()).hexdigest()
                old = db.execute('SELECT * FROM publications WHERE identity=?', (identity,)).fetchone()
                if old and old['request_hash'] != request['request_hash'] and old['status'] != 'prepared':
                    raise ValueError('此根因已有发送记录，不能用新内容重新创建；需核对已有单据')
                if old and old['status'] != 'prepared':
                    continue
                db.execute('''INSERT INTO publications(identity,task_id,root_cause_id,request_hash,request)
                    VALUES(?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET
                    request_hash=excluded.request_hash,request=excluded.request,updated_at=CURRENT_TIMESTAMP''',
                    (identity, task_id, request['root_cause_id'], request['request_hash'], json.dumps(request, ensure_ascii=False)))
        return self.list(project, task_id)

    def list(self, project, task_id):
        with self.store.connection() as db:
            self.store._task(db, project, task_id)
            return [dict(row) for row in db.execute('''SELECT identity,root_cause_id,request_hash,status,
                record_id,detail,updated_at FROM publications WHERE task_id=? ORDER BY rowid''', (task_id,))]

    def claim(self, project, task_id, identity, request_hash, revision=None):
        """调用外部写入前独占领取；此后任何异常都不能退回prepared。"""
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self.store._task(db, project, task_id)
            if task['stage'] != 4 or task['status'] != 'waiting_user':
                raise ValueError('当前任务不能发布')
            if revision is not None and task['revision'] != revision:
                raise ValueError('发布审核版本已变化，请刷新')
            row = db.execute('SELECT * FROM publications WHERE identity=? AND task_id=?', (identity, task_id)).fetchone()
            if not row or row['request_hash'] != request_hash or row['status'] != 'prepared':
                raise ValueError('请求已发送、过期或结果不确定，禁止重复创建')
            artifact = json.loads(task['artifacts']).get('4', {})
            plan = artifact.get('publication_plan', {})
            if not any(r['request_hash'] == request_hash for r in plan.get('requests', [])):
                raise ValueError('请求不属于当前发布预览')
            attempt = uuid.uuid4().hex
            db.execute("UPDATE publications SET status='sending',attempt=?,updated_at=CURRENT_TIMESTAMP WHERE identity=?", (attempt, identity))
            return {'attempt': attempt, 'request': json.loads(row['request'])}

    def finish(self, identity, attempt, response=None):
        """成功须唯一记录ID且无被忽略字段；其他响应保留不确定。"""
        ids = response.get('record_id_list') if isinstance(response, dict) else None
        known_record = (isinstance(ids, list) and len(ids) == 1 and isinstance(ids[0], str)
                        and re.fullmatch(r'rec[A-Za-z0-9_-]+', ids[0]))
        valid = known_record and not response.get('ignored_fields')
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM publications WHERE identity=?', (identity,)).fetchone()
            if not row or row['attempt'] != attempt or row['status'] != 'sending':
                raise ValueError('发布尝试不匹配或已经结束')
            db.execute('''UPDATE publications SET status=?,record_id=?,detail=?,updated_at=CURRENT_TIMESTAMP
                WHERE identity=?''', ('published' if valid else 'uncertain', ids[0] if known_record else None,
                '创建接口返回唯一记录ID' if valid else '未取得完整成功响应，需只读核对；禁止自动重试', identity))

    def recover_interrupted(self):
        with self.store.connection() as db:
            db.execute("UPDATE publications SET status='uncertain',detail='服务中断，需核对远端记录；禁止自动重试',updated_at=CURRENT_TIMESTAMP WHERE status='sending'")

    def reconciliation_request(self, project, task_id, identity):
        with self.store.connection() as db:
            self.store._task(db, project, task_id)
            row = db.execute('SELECT * FROM publications WHERE identity=? AND task_id=?', (identity, task_id)).fetchone()
            if not row or row['status'] != 'uncertain':
                raise ValueError('只有结果不确定的发布需要核对')
            return json.loads(row['request'])

    def reconcile(self, project, task_id, identity, check, revision):
        from datetime import datetime, timezone
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self.store._task(db, project, task_id)
            if task['revision'] != revision or task['stage'] != 4 or task['status'] != 'waiting_user':
                raise ValueError('任务已变化，核对结果未登记')
            row = db.execute('SELECT * FROM publications WHERE identity=? AND task_id=?', (identity, task_id)).fetchone()
            if not row or row['status'] != 'uncertain':
                raise ValueError('发布状态已变化')
            request = json.loads(row['request'])
            if (check.get('matched') is not True or check.get('mismatched_field_ids') != []
                    or check.get('request_hash') != row['request_hash']
                    or check.get('table_id') != request['table_id'] or check.get('base_token') != request['base_token']
                    or not isinstance(check.get('record_id'), str) or not re.fullmatch(r'rec[A-Za-z0-9_-]+', check['record_id'])):
                raise ValueError('远端记录与发布内容不一致，不能确认')
            age = (datetime.now(timezone.utc)-datetime.fromisoformat(check['checked_at'])).total_seconds()
            if not 0 <= age <= 120:
                raise ValueError('核对结果已过期')
            if row['record_id'] and row['record_id'] != check['record_id']:
                raise ValueError('创建响应已有记录ID，不能换成另一条记录')
            duplicate = db.execute('SELECT identity FROM publications WHERE task_id=? AND record_id=? AND identity!=?',
                                   (task_id, check['record_id'], identity)).fetchone()
            if duplicate:
                raise ValueError('该记录已经关联其他根因')
            db.execute("UPDATE publications SET status='reconciled',record_id=?,detail=?,updated_at=CURRENT_TIMESTAMP WHERE identity=?",
                       (check['record_id'], '用户指定记录；只读核对提交字段一致，'+check['checked_at'], identity))
