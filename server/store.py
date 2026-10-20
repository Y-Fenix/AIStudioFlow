"""SQLite 项目、任务及版本化决策存储；不执行外部副作用。"""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from server.core.identity import user_id as resolve_user
from server.requirements import validate_cases, case_review_items, case_review_hash, resolve_source_gaps


class Store:
    """每个操作使用独立事务，拒绝跨项目任务访问。"""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    name_key TEXT NOT NULL UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id),
                    title TEXT NOT NULL, stage INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'waiting_user', revision INTEGER DEFAULT 1,
                    artifacts TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS requirements (
                    id TEXT PRIMARY KEY, task_id TEXT REFERENCES tasks(id), source TEXT NOT NULL,
                    version INTEGER NOT NULL, content TEXT NOT NULL, sha256 TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(task_id,source,version));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id TEXT REFERENCES tasks(id),
                    kind TEXT NOT NULL, detail TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS node_resets (
                    id INTEGER PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(id),
                    stage INTEGER NOT NULL,revision INTEGER NOT NULL,reason TEXT NOT NULL,
                    snapshot TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                CREATE UNIQUE INDEX IF NOT EXISTS active_generation ON jobs(task_id)
                    WHERE status IN ('queued','running');
            ''')
            if 'stage' not in {r['name'] for r in db.execute('PRAGMA table_info(events)')}:
                db.execute('ALTER TABLE events ADD COLUMN stage INTEGER')
            if 'node_skills' not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
                db.execute("ALTER TABLE tasks ADD COLUMN node_skills TEXT NOT NULL DEFAULT '{}'")
            columns = {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}
            if 'context' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")
            if 'kind' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'generate'")
            if 'progress' not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN progress TEXT NOT NULL DEFAULT '{}'")
            if 'stage' not in columns:
                db.execute('ALTER TABLE jobs ADD COLUMN stage INTEGER NOT NULL DEFAULT 0')
            if 'archived' not in {r['name'] for r in db.execute('PRAGMA table_info(requirements)')}:
                db.execute('ALTER TABLE requirements ADD COLUMN archived INTEGER NOT NULL DEFAULT 0')
            if 'metadata' not in {r['name'] for r in db.execute('PRAGMA table_info(requirements)')}:
                db.execute("ALTER TABLE requirements ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
            if 'binding' not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
                db.execute("ALTER TABLE tasks ADD COLUMN binding TEXT NOT NULL DEFAULT '{}'")
            if 'attribution' not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
                db.execute("ALTER TABLE tasks ADD COLUMN attribution TEXT NOT NULL DEFAULT '{}'")
            if 'bug_target' not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
                db.execute("ALTER TABLE tasks ADD COLUMN bug_target TEXT NOT NULL DEFAULT '{}'")
            if 'regression' not in {r['name'] for r in db.execute('PRAGMA table_info(tasks)')}:
                db.execute("ALTER TABLE tasks ADD COLUMN regression TEXT NOT NULL DEFAULT '{}'")
        from server.studio_schema import migrate
        migrate(self.path)
        from server.core.schema import migrate as migrate_team
        migrate_team(self)

    @contextmanager
    def connection(self):
        """事务失败自动回滚，连接退出时关闭。"""
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_studio(self, name, user_id=None):
        user_id = resolve_user(user_id)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError('工作室名称必须为1至60个字符')
        name = name.strip()
        studio_id = uuid.uuid4().hex
        with self.connection() as db:
            try:
                db.execute('INSERT INTO studios(id,name,name_key) VALUES(?,?,?)',
                           (studio_id, name, name.casefold()))
            except sqlite3.IntegrityError as exc:
                raise ValueError('工作室名称已存在') from exc
            db.execute('INSERT INTO studio_memberships(studio_id,user_id,role) VALUES(?,?,?)',
                       (studio_id, user_id, 'studio_owner'))
        return {'id': studio_id, 'name': name}

    def studios(self, user_id=None):
        user_id = resolve_user(user_id)
        with self.connection() as db:
            return [dict(r) for r in db.execute(
                '''SELECT s.id,s.name,s.created_at,m.role FROM studios s
                   JOIN studio_memberships m ON m.studio_id=s.id WHERE m.user_id=? AND s.archived=0
                   ORDER BY s.created_at,s.id''', (user_id,))]

    def create_project(self, name, studio_id=None, user_id=None):
        user_id = resolve_user(user_id)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
            raise ValueError('项目名称必须为1至60个字符')
        name = name.strip()
        project_id = uuid.uuid4().hex
        with self.connection() as db:
            if studio_id is None:
                row = db.execute('SELECT active_studio_id FROM user_preferences WHERE user_id=?', (user_id,)).fetchone()
                studio_id = row['active_studio_id'] if row else None
            if not studio_id or not db.execute(
                    'SELECT 1 FROM studio_memberships WHERE studio_id=? AND user_id=?', (studio_id, user_id)).fetchone():
                raise KeyError('工作室不存在或无权访问')
            try:
                db.execute('INSERT INTO projects(id,name,name_key,studio_id) VALUES(?,?,?,?)',
                           (project_id, name, name.casefold(), studio_id))
            except sqlite3.IntegrityError as exc:
                raise ValueError('项目名称已存在') from exc
        return {'id': project_id, 'name': name, 'studio_id': studio_id}

    def projects(self, query='', page=1, size=5, studio_id=None, user_id=None):
        user_id = resolve_user(user_id)
        if page < 1 or size not in (5, 10, 20, 50, 100):
            raise ValueError('非法分页参数')
        with self.connection() as db:
            # instr 按字面搜索，百分号与下划线不作为通配符。
            term = query.casefold()
            if studio_id is None:
                row = db.execute('SELECT active_studio_id FROM user_preferences WHERE user_id=?', (user_id,)).fetchone()
                studio_id = row['active_studio_id'] if row else None
            if not studio_id or not db.execute('SELECT 1 FROM studio_memberships WHERE studio_id=? AND user_id=?',
                                                (studio_id, user_id)).fetchone():
                raise KeyError('工作室不存在或无权访问')
            candidates = [dict(r) for r in db.execute(
                'SELECT id,name,studio_id FROM projects WHERE studio_id=? AND archived=0 AND instr(name_key,?)>0 ORDER BY created_at,id',
                (studio_id, term))]
            from server.core.permissions import Policy
            policy = Policy(self)
            visible = [p for p in candidates if policy.allowed('project','view',studio_id,p['id'],actor=user_id)
                       or any(policy.allowed('node','view',studio_id,p['id'],node=f'{d}:{i}',actor=user_id)
                              for d,c in (('product',4),('design',4),('development',4),('testing',6),('growth',4)) for i in range(c))]
            total = len(visible)
            rows = visible[(page-1)*size:page*size]
        return {'items': rows, 'total': total, 'page': page, 'size': size, 'studio_id': studio_id}

    def preferences(self, user_id=None):
        user_id = resolve_user(user_id)
        with self.connection() as db:
            row = db.execute('SELECT user_id,active_studio_id,active_role,default_workspace,updated_at FROM user_preferences WHERE user_id=?', (user_id,)).fetchone()
            if row is None: raise KeyError('用户偏好不存在')
            value = dict(row)
            visit = db.execute('SELECT project_id FROM studio_visits WHERE user_id=? AND studio_id=?',
                               (user_id, value['active_studio_id'])).fetchone()
            value['project_id'] = visit['project_id'] if visit else None
            return value

    def check_project(self, studio_id, project_id, user_id=None):
        user_id = resolve_user(user_id)
        with self.connection() as db:
            row = db.execute('''SELECT p.id,p.name,p.studio_id FROM projects p
                JOIN studio_memberships m ON m.studio_id=p.studio_id
                WHERE p.id=? AND p.studio_id=? AND m.user_id=? AND p.archived=0''',
                (project_id, studio_id, user_id)).fetchone()
            if row is None: raise KeyError('项目不属于当前工作室')
            return dict(row)

    def enter_studio(self, studio_id, user_id=None):
        user_id = resolve_user(user_id)
        with self.connection() as db:
            if not db.execute('SELECT 1 FROM studio_memberships WHERE studio_id=? AND user_id=?',
                              (studio_id, user_id)).fetchone():
                raise KeyError('工作室不存在或无权访问')
            db.execute('UPDATE user_preferences SET active_studio_id=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?',
                       (studio_id, user_id))
        return self.preferences(user_id)

    def enter_project(self, studio_id, project_id, user_id=None):
        user_id = resolve_user(user_id)
        with self.connection() as db:
            if not db.execute('''SELECT 1 FROM projects p JOIN studio_memberships m ON m.studio_id=p.studio_id
                WHERE p.id=? AND p.studio_id=? AND m.user_id=? AND p.archived=0''', (project_id, studio_id, user_id)).fetchone():
                raise KeyError('项目不属于当前工作室')
            db.execute('''INSERT INTO studio_visits(user_id,studio_id,project_id) VALUES(?,?,?)
                ON CONFLICT(user_id,studio_id) DO UPDATE SET project_id=excluded.project_id''',
                (user_id, studio_id, project_id))
            db.execute('UPDATE user_preferences SET active_studio_id=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?',
                       (studio_id, user_id))
        return self.preferences(user_id)

    def save_preferences(self, value, user_id=None):
        user_id = resolve_user(user_id)
        roles = {'studio_owner':'overview','product':'product','design':'design','development':'development','qa':'testing','growth':'growth'}
        role = value.get('role', value.get('active_role'))
        workspace = value.get('default_workspace', roles.get(role, 'overview'))
        studio_id = value.get('active_studio_id')
        if role not in roles: raise ValueError('身份不支持')
        if workspace not in {'overview','product','design','development','testing','growth'}: raise ValueError('默认工作区不支持')
        if workspace != roles[role]: raise ValueError('默认工作区与身份不匹配')
        with self.connection() as db:
            if not studio_id or not db.execute('SELECT 1 FROM studio_memberships WHERE studio_id=? AND user_id=?', (studio_id,user_id)).fetchone():
                raise KeyError('工作室不存在或无权访问')
            db.execute('''INSERT INTO user_preferences(user_id,active_studio_id,active_role,default_workspace,updated_at)
                          VALUES(?,?,?,?,CURRENT_TIMESTAMP)
                          ON CONFLICT(user_id) DO UPDATE SET active_studio_id=excluded.active_studio_id,
                          active_role=excluded.active_role,default_workspace=excluded.default_workspace,
                          updated_at=CURRENT_TIMESTAMP''', (user_id,studio_id,role,workspace))
        return self.preferences(user_id)

    def create_task(self, project_id, title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            raise ValueError('任务名称必须为1至120个字符')
        task_id = uuid.uuid4().hex
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from server.core.project_content import require_enabled
            require_enabled(db,project_id,'testing')
            if not db.execute('SELECT id FROM projects WHERE id=?', (project_id,)).fetchone():
                raise KeyError('项目不存在')
            from server.core.project_nodes import read_config
            version,nodes=read_config(db,project_id,'testing')
            active=[n for n in nodes if not n['archived']]
            if not {f'testing:{i}' for i in range(6)}.issubset({n['id'] for n in active}):
                raise ValueError('测试流程缺少必需节点，请先恢复配置后创建新批次')
            from server.core.skill_library import bound_skill,legacy_skill
            skills={str(i):bound_skill(db,project_id,f'testing:{i}',legacy_skill(db,self,project_id,f'testing:{i}')) for i in range(6)}
            db.execute('INSERT INTO tasks(id,project_id,title,workflow_nodes,node_skills) VALUES(?,?,?,?,?)',
                       (task_id, project_id, title.strip(),json.dumps({'revision':version,'nodes':active},ensure_ascii=False),json.dumps(skills,ensure_ascii=False)))
            self._event(db, task_id, 'created', '创建任务')
        return self.task(project_id, task_id)

    def tasks(self, project_id):
        """返回指定项目任务，不泄漏其它项目记录。"""
        with self.connection() as db:
            if not db.execute('SELECT id FROM projects WHERE id=?', (project_id,)).fetchone():
                raise KeyError('项目不存在')
            return [dict(r) for r in db.execute(
                'SELECT id,title,stage,status,revision FROM tasks WHERE project_id=? ORDER BY rowid DESC',
                (project_id,))]

    def _task(self, db, project_id, task_id):
        row = db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?',
                         (task_id, project_id)).fetchone()
        if row is None:
            raise KeyError('任务不存在')
        return dict(row)

    def task(self, project_id, task_id):
        with self.connection() as db:
            # 同一快照读取任务版本和队列状态，避免返回“旧产物 + 新完成状态”。
            db.execute('BEGIN')
            task = self._task(db, project_id, task_id)
            from server.core.project_nodes import template_nodes
            task['workflow_nodes'] = json.loads(task['workflow_nodes']) or {'revision':0,'nodes':template_nodes('testing')}
            task['artifacts'] = json.loads(task['artifacts'])
            task['binding'] = json.loads(task['binding'])
            task['attribution'] = json.loads(task['attribution'])
            task['bug_target'] = json.loads(task['bug_target'])
            task['regression'] = json.loads(task['regression'])
            task['requirements'] = [dict(r) for r in db.execute('SELECT r.* FROM requirements r WHERE r.task_id=? AND r.archived=0 AND r.version=(SELECT MAX(s.version) FROM requirements s WHERE s.task_id=r.task_id AND s.source=r.source) ORDER BY r.rowid', (task_id,))]
            for requirement in task['requirements']:
                requirement['metadata'] = json.loads(requirement['metadata'])
            task['archived_requirements']=[dict(r) for r in db.execute('SELECT r.* FROM requirements r WHERE r.task_id=? AND r.archived=1 AND r.version=(SELECT MAX(s.version) FROM requirements s WHERE s.task_id=r.task_id AND s.source=r.source)',(task_id,))]
            task['requirements'] = resolve_source_gaps(task['requirements'])
            task['case_review_items'] = case_review_items(task['artifacts'].get('0', {}), task['requirements'])
            from server.node_skills import defaults
            task['node_skills'] = {**defaults(), **json.loads(task['node_skills'])}
            from server.core.skill_library import bound_skill
            task['node_skills'] = {stage:bound_skill(db,project_id,f'testing:{stage}',skill,task_id)
                                   for stage,skill in task['node_skills'].items()}
            task['events'] = [dict(r) for r in db.execute(
                'SELECT kind,detail,created_at,stage FROM events WHERE task_id=? ORDER BY id', (task_id,))]
            task['reset_history'] = [dict(r) for r in db.execute(
                'SELECT id,stage,revision,reason,created_at,snapshot FROM node_resets WHERE task_id=? ORDER BY id',(task_id,))]
            for reset in task['reset_history']:
                snapshot=json.loads(reset.pop('snapshot'))
                reset['remote_records']=snapshot.get('artifacts',{}).get('4',{}).get('linked_records',[])
                reset['publication_records']=snapshot.get('publication_records',[])
            task['jobs'] = [dict(r) for r in db.execute('SELECT * FROM jobs WHERE task_id=? ORDER BY rowid DESC LIMIT 10', (task_id,))]
        return task

    def bind_execution(self, project_id, task_id, binding, revision):
        with self.connection() as db:
            task = self._task(db, project_id, task_id)
            if task['revision'] != revision or task['status'] in ('cancelled', 'completed'):
                raise ValueError('任务已变化或结束，请刷新')
            artifacts = json.loads(task['artifacts'])
            artifacts = {key: value for key, value in artifacts.items() if key == '0'}
            db.execute("UPDATE tasks SET binding=?,artifacts=?,stage=?,attribution='{}',regression='{}',revision=revision+1 WHERE id=?",
                       (json.dumps(binding, ensure_ascii=False), json.dumps(artifacts, ensure_ascii=False), min(task['stage'], 1), task_id))
            self._event(db, task_id, 'execution_binding', '只读检查并绑定代码；未执行测试，下游产物失效',1)
        return self.task(project_id, task_id)

    def enqueue_generation(self, project_id, task_id):
        return self.enqueue_operation(project_id, task_id, 'generate')

    def operation_progress(self, job, progress):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, job['project_id'], job['task_id'])
            if task['revision'] != job['revision'] or task['status'] in ('cancelled', 'completed'):
                raise ValueError('任务已变化，停止静态审查')
            db.execute("UPDATE jobs SET progress=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",
                       (json.dumps(progress, ensure_ascii=False), job['id']))

    def enqueue_operation(self, project_id, task_id, kind, *, connection=None):
        stages = {'generate': (0,), 'execute': (1,), 'attribution': (2,), 'regression': (4, 5)}
        if kind not in stages:
            raise ValueError('未知后台操作')
        with (nullcontext(connection) if connection is not None else self.connection()) as db:
            if connection is None: db.execute('BEGIN IMMEDIATE')
            task = self._task(db, project_id, task_id)
            if task['stage'] not in stages[kind] or task['status'] in ('cancelled', 'completed'):
                raise ValueError('当前节点不能执行此操作')
            artifacts = json.loads(task['artifacts'])
            if kind == 'generate' and not db.execute('SELECT id FROM requirements WHERE task_id=? AND archived=0', (task_id,)).fetchone():
                raise ValueError('请先导入需求')
            if kind != 'generate' and not json.loads(task['binding']):
                raise ValueError('请先绑定代码')
            if kind == 'attribution' and '1' not in artifacts:
                raise ValueError('请先执行测试')
            if kind == 'regression' and not artifacts.get('4', {}).get('drafts'):
                raise ValueError('尚无需要回归的Bug草稿')
            existing = db.execute("SELECT * FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone()
            if existing:
                if existing['kind'] != kind:
                    raise ValueError('当前任务已有其他后台操作')
                return dict(existing)
            job_id = uuid.uuid4().hex
            db.execute('INSERT INTO jobs(id,project_id,task_id,revision,kind,stage,actor) VALUES(?,?,?,?,?,?,?)',
                       (job_id, project_id, task_id, task['revision'], kind, task['stage'], resolve_user()))
            labels = {'generate':'用例生成','execute':'逻辑执行','attribution':'候选归因','regression':'逻辑回归'}
            self._event(db, task_id, 'operation_queued', labels[kind] + '已排队')
            return dict(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())

    def refresh_pending_bugs(self, project_id, task_id, checks, revision):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, project_id, task_id)
            if task['stage'] != 5 or task['revision'] != revision or task['status'] != 'waiting_user':
                raise ValueError('当前任务不能刷新待验证状态')
            if db.execute("SELECT id FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone():
                raise ValueError('请等待当前后台操作结束')
            artifacts = json.loads(task['artifacts'])
            submission = artifacts.get('4', {})
            links = submission.get('linked_records', [])
            if not links or set(checks) != {l['draft_key'] for l in links}:
                raise ValueError('需要读取全部已关联 Bug 状态')
            pending = []
            for link in links:
                check = checks[link['draft_key']]
                if check.get('record_id') != link['record_id'] or check.get('table_id') != link['table_id']:
                    raise ValueError('返回状态与关联 Bug 不一致')
                if check.get('pending') is True:
                    pending.append(link['root_cause_id'])
            if pending and not json.loads(task['binding']):
                raise ValueError('请先绑定代码')
            submission['remote_checks'] = checks
            db.execute('UPDATE tasks SET artifacts=?,revision=revision+1 WHERE id=?',
                       (json.dumps(artifacts, ensure_ascii=False), task_id))
            self._event(db, task_id, 'bug_status_refresh', f'只读刷新{len(links)}条Bug，待验证{len(pending)}条')
            job = None
            if pending:
                job_id = uuid.uuid4().hex
                context = {'trigger':'fresh_pending_status', 'root_cause_ids':pending, 'status_checks':checks}
                db.execute('INSERT INTO jobs(id,project_id,task_id,revision,kind,stage,context,actor) VALUES(?,?,?,?,?,?,?,?)',
                           (job_id,project_id,task_id,revision+1,'regression',5,json.dumps(context,ensure_ascii=False),resolve_user()))
                self._event(db, task_id, 'operation_queued', '待验证根因的关联逻辑回归已排队')
                job = dict(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
        return {'task': self.task(project_id, task_id), 'job': job, 'pending_root_ids':pending}

    def claim_generation(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?", (row['id'],))
            self._event(db, row['task_id'], 'operation_running', '开始后台操作：' + row['kind'])
            return dict(row)

    def finish_generation(self, job, artifact=None, error=None):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, job['project_id'], job['task_id'])
            if task['revision'] != job['revision'] or task['stage'] != job.get('stage', 0) or task['status'] in ('cancelled', 'completed'):
                status, error = 'superseded', '需求或任务已变化，本次结果未保存'
            elif error:
                status = 'failed'
            else:
                status = 'completed'
                kind = job.get('kind', 'generate')
                if kind in ('generate', 'execute'):
                    artifacts = json.loads(task['artifacts'])
                    artifacts[str(job.get('stage', 0))] = artifact
                    db.execute("UPDATE tasks SET artifacts=?,revision=revision+1,status='waiting_user',attribution='{}',regression='{}' WHERE id=?",
                               (json.dumps(artifacts, ensure_ascii=False), task['id']))
                else:
                    if kind == 'regression':
                        artifacts = json.loads(task['artifacts'])
                        artifacts.pop('5', None)
                        db.execute('UPDATE tasks SET artifacts=? WHERE id=?', (json.dumps(artifacts, ensure_ascii=False), task['id']))
                    column = 'attribution' if kind == 'attribution' else 'regression'
                    db.execute(f'UPDATE tasks SET {column}=?,revision=revision+1 WHERE id=?',
                               (json.dumps(artifact, ensure_ascii=False), task['id']))
            db.execute('UPDATE jobs SET status=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, error, job['id']))
            self._event(db, task['id'], 'operation_' + status, error or '后台操作完成，等待人工评审', job.get('stage',0))

    def recover_generations(self):
        with self.connection() as db:
            rows = db.execute("SELECT task_id,stage FROM jobs WHERE status='running'").fetchall()
            db.execute("UPDATE jobs SET status='failed',error='服务中断，请手动重试',updated_at=CURRENT_TIMESTAMP WHERE status='running'")
            for row in rows:
                self._event(db, row['task_id'], 'generation_interrupted', '服务中断，后台操作未完成；没有自动重试',row['stage'])

    def import_requirement(self, project_id, task_id, source, content, metadata=None, expected_revision=None):
        """导入来源版本；内容变化时原子失效下游产物。"""
        if not isinstance(source, str) or not 1 <= len(source.strip()) <= 500:
            raise ValueError('需要有效来源名称')
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > 800000:
            raise ValueError('需求正文不能为空且不得超过800KB')
        source = source.strip()
        digest = hashlib.sha256(content.encode()).hexdigest()
        encoded_metadata = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, project_id, task_id)
            if expected_revision is not None and task['revision'] != expected_revision:
                raise ValueError('读取期间需求已变化，结果未保存')
            if task['status'] in ('cancelled', 'completed'):
                raise ValueError('已结束任务不能导入需求')
            previous = db.execute('SELECT version,sha256,metadata,archived FROM requirements WHERE task_id=? AND source=? ORDER BY version DESC LIMIT 1', (task_id, source)).fetchone()
            if previous and previous['archived']:raise ValueError('此来源已归档，请先恢复后再导入')
            if previous is None or previous['sha256'] != digest or previous['metadata'] != encoded_metadata:
                version = previous['version'] + 1 if previous else 1
                db.execute('INSERT INTO requirements(id,task_id,source,version,content,sha256,metadata) VALUES(?,?,?,?,?,?,?)',
                           (uuid.uuid4().hex, task_id, source, version, content, digest, encoded_metadata))
                db.execute("UPDATE tasks SET stage=0,status='waiting_user',artifacts='{}',attribution='{}',regression='{}',revision=revision+1 WHERE id=?", (task_id,))
                self._event(db, task_id, 'requirement_import', f'导入需求：{source} v{version}；下游产物失效')
        return self.task(project_id, task_id)

    def archive_requirement(self,project_id,task_id,requirement_id,revision,archived):
        if type(archived) is not bool:raise ValueError('归档状态必须为布尔值')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE');task=self._task(db,project_id,task_id)
            if type(revision) is not int or revision!=task['revision']:raise ValueError('任务版本已变化，请刷新')
            if task['status'] in ('cancelled','completed'):raise ValueError('任务已结束，请先重置')
            if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')",(task_id,)).fetchone():raise ValueError('任务排队或运行中，不能增删来源')
            if json.loads(task['artifacts']):raise ValueError('已有下游产物引用资料，请先重置用例节点后再增删来源')
            row=db.execute('SELECT source,archived FROM requirements WHERE task_id=? AND id=?',(task_id,requirement_id)).fetchone()
            if row is None:raise KeyError('需求来源不存在')
            if bool(row['archived'])==archived:raise ValueError('来源已处于目标状态')
            db.execute('UPDATE requirements SET archived=? WHERE task_id=? AND source=?',(int(archived),task_id,row['source']))
            db.execute('UPDATE tasks SET revision=revision+1 WHERE id=?',(task_id,))
            self._event(db,task_id,'requirement_archived' if archived else 'requirement_restored',('归档需求来源：' if archived else '恢复需求来源：')+row['source'],0)
        return self.task(project_id,task_id)

    def _event(self, db, task_id, kind, detail, stage=None):
        if stage is None:
            stage = db.execute('SELECT stage FROM tasks WHERE id=?',(task_id,)).fetchone()['stage']
        db.execute('INSERT INTO events(task_id,kind,detail,stage) VALUES(?,?,?,?)', (task_id, kind, detail, stage))

    def save_node_skill(self, project_id, task_id, stage, content, revision, *, name=None):
        from server.node_skills import validate
        if type(stage) is not int or not 0 <= stage <= 5:
            raise ValueError('节点不合法')
        content=validate(content)
        if name is not None and (not isinstance(name,str) or not 1 <= len(name.strip()) <= 200):
            raise ValueError('Skill 名称必须为1至200字')
        skill_name=name.strip() if name is not None else '用户导入规则'
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task=self._task(db,project_id,task_id)
            if task['revision'] != revision:
                raise ValueError('任务已变化，请刷新')
            if db.execute("SELECT id FROM jobs WHERE task_id=? AND status IN ('queued','running')",(task_id,)).fetchone():
                raise ValueError('请等待后台操作结束再修改Skill')
            skills=json.loads(task['node_skills'])
            skills[str(stage)]={'name':skill_name,'content':content,'source_kind':'imported','sha256':hashlib.sha256(content.encode()).hexdigest()}
            from server.core.skill_library import append_version
            append_version(db,self,project_id,f'testing:{stage}',skills[str(stage)],'测试批次导入规则：'+skill_name,task=task_id)
            db.execute('UPDATE tasks SET node_skills=?,revision=revision+1 WHERE id=?',(json.dumps(skills,ensure_ascii=False),task_id))
            self._event(db,task_id,'skill_import','导入节点Skill：'+skill_name+'；仅后续操作使用，旧产物未重新生成',stage)
        return self.task(project_id,task_id)

    def save_attribution(self, project_id, task_id, suggestions, revision):
        with self.connection() as db:
            task = self._task(db, project_id, task_id)
            if task['stage'] != 2 or task['revision'] != revision or task['status'] in ('cancelled', 'completed'):
                raise ValueError('任务已变化，归因建议未保存')
            db.execute('UPDATE tasks SET attribution=?,revision=revision+1 WHERE id=?',
                       (json.dumps(suggestions, ensure_ascii=False), task_id))
            self._event(db, task_id, 'attribution_suggested', '生成候选归因，待人工确认；未合并提单',2)
        return self.task(project_id, task_id)

    def save_bug_target(self, project_id, task_id, target, revision):
        with self.connection() as db:
            task = self._task(db, project_id, task_id)
            if task['revision'] != revision or task['status'] in ('cancelled', 'completed'):
                raise ValueError('任务已变化或结束，目标格式未保存')
            artifacts = json.loads(task['artifacts'])
            if '4' in artifacts:
                artifacts['4'].pop('field_preview', None)
                artifacts['4'].pop('publication_plan', None)
                artifacts['4'].pop('remote_checks', None)
                artifacts['4'].pop('linked_records', None)
                artifacts['4']['publication_complete'] = not artifacts['4'].get('drafts')
            db.execute('UPDATE tasks SET bug_target=?,artifacts=?,revision=revision+1 WHERE id=?',
                       (json.dumps(target, ensure_ascii=False), json.dumps(artifacts, ensure_ascii=False), task_id))
            self._event(db, task_id, 'bug_target_read', '只读识别 Bug 数据表字段；没有发布记录',4)
        return self.task(project_id, task_id)

    def save_logic_regression(self, project_id, task_id, regression, revision):
        with self.connection() as db:
            task = self._task(db, project_id, task_id)
            if task['revision'] != revision or task['stage'] < 4 or task['status'] in ('cancelled', 'completed'):
                raise ValueError('任务已变化，回归结果未保存')
            artifacts = json.loads(task['artifacts'])
            artifacts.pop('5', None)
            db.execute('UPDATE tasks SET artifacts=? WHERE id=?', (json.dumps(artifacts, ensure_ascii=False), task_id))
            db.execute('UPDATE tasks SET regression=?,revision=revision+1 WHERE id=?',
                       (json.dumps(regression, ensure_ascii=False), task_id))
            self._event(db, task_id, 'logic_regression', '完成关联逻辑探针回归；没有修改飞书状态',5)
        return self.task(project_id, task_id)

    def edit_case(self, project_id, task_id, case_id, changes, revision):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, project_id, task_id)
            if task['revision'] != revision or task['status'] in ('cancelled', 'completed'):
                raise ValueError('任务已变化或结束，请刷新')
            if not isinstance(changes, dict) or set(changes) != {'title', 'preconditions', 'steps'}:
                raise ValueError('仅允许修改名称、前置条件和步骤预期')
            output = json.loads(task['artifacts']).get('0')
            if not output:
                raise ValueError('尚无生成用例')
            case = next((c for c in output['cases'] if c['id'] == case_id), None)
            if case is None:
                raise ValueError('用例不存在')
            case.update(changes)
            requirements = [dict(r) for r in db.execute('SELECT r.* FROM requirements r WHERE task_id=? AND r.archived=0 AND version=(SELECT MAX(s.version) FROM requirements s WHERE s.task_id=r.task_id AND s.source=r.source)', (task_id,))]
            validated = validate_cases(output, requirements)
            db.execute("UPDATE tasks SET stage=0,status='waiting_user',artifacts=?,attribution='{}',regression='{}',revision=revision+1 WHERE id=?",
                       (json.dumps({'0': validated}, ensure_ascii=False), task_id))
            self._event(db, task_id, 'case_edited', '用户修改用例：' + case_id + '；执行及下游产物失效',0)
        return self.task(project_id, task_id)

    def record_artifact(self, project_id, task_id, stage, artifact, expected_revision=None):
        """只允许执行器登记当前节点产物，不开放直接伪造通过。"""
        if not isinstance(artifact, dict) or not artifact:
            raise ValueError('产物不能为空')
        with self.connection() as db:
            task = self._task(db, project_id, task_id)
            if expected_revision is not None and task['revision'] != expected_revision:
                raise ValueError('需求或任务已变化，请重新生成')
            if stage != task['stage'] or task['status'] == 'cancelled':
                raise ValueError('节点不匹配或任务已取消')
            artifacts = json.loads(task['artifacts'])
            artifacts[str(stage)] = artifact
            db.execute('UPDATE tasks SET artifacts=?,revision=revision+1,status=? WHERE id=?',
                       (json.dumps(artifacts, ensure_ascii=False), 'waiting_user', task_id))
            if stage < 5:
                db.execute("UPDATE tasks SET regression='{}' WHERE id=?", (task_id,))
            if stage <= 1:
                db.execute("UPDATE tasks SET attribution='{}',regression='{}' WHERE id=?", (task_id,))
            self._event(db, task_id, 'artifact', f'节点{stage}产物登记',stage)
        return self.task(project_id, task_id)

    def decide(self, project_id, task_id, action, revision):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, project_id, task_id)
            if task['revision'] != revision:
                raise ValueError('数据已更新，请刷新后确认')
            if task['status'] in ('cancelled', 'completed'):
                raise ValueError('任务已结束')
            if action == 'confirm':
                if db.execute("SELECT id FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone():
                    raise ValueError('生成任务尚未结束，不能确认旧产物')
                if str(task['stage']) not in json.loads(task['artifacts']):
                    raise ValueError('当前节点没有产物，不能确认')
                artifact = json.loads(task['artifacts'])[str(task['stage'])]
                if task['stage'] == 0 and 'points' in artifact:
                    requirements = [dict(r) for r in db.execute('SELECT r.* FROM requirements r WHERE r.task_id=? AND r.archived=0 AND r.version=(SELECT MAX(s.version) FROM requirements s WHERE s.task_id=r.task_id AND s.source=r.source) ORDER BY r.rowid', (task_id,))]
                    for requirement in requirements:
                        requirement['metadata'] = json.loads(requirement['metadata'])
                    review = artifact.get('user_review', {})
                    if not review.get('ready_for_execution') or review.get('review_hash') != case_review_hash(artifact, requirements):
                        raise ValueError('请先保存当前用例评审；未处理的范围缺口不能进入执行')
                if task['stage'] == 1 and artifact.get('method') in ('production_method_probe_with_stubs', 'production_suite_with_stubs') and not artifact.get('mapping_review_complete'):
                    raise ValueError('请先确认用例与断言关联，未执行用例必须记录缺口')
                if task['stage'] == 1 and artifact.get('method') == 'static_code_review':
                    from server.static_review import validate_coverage
                    validate_coverage(artifact, json.loads(task['artifacts'])['0']['cases'])
                if task['stage'] == 2 and not artifact.get('ready_for_review'):
                    raise ValueError('仍有未归因的失败记录，不能进入筛选')
                if task['stage'] == 5 and not artifact.get('ready_for_review'):
                    raise ValueError('请先逐根因保存回归决策')
                if task['stage'] == 4 and not artifact.get('publication_complete'):
                    raise ValueError('Bug 尚未发布，内部草稿不能冒充提单完成')
                if task['stage'] == 4 and artifact.get('drafts') == []:
                    artifacts = json.loads(task['artifacts'])
                    if artifacts.get('3', {}).get('groups') != []:
                        raise ValueError('筛选仍有提单根因，不能用空草稿结束')
                    results = artifacts.get('1', {}).get('results', [])
                    artifacts['5'] = {
                        'ready_for_review': True, 'no_bug_regression_required': True,
                        'unresolved_results': [r for r in results if r.get('status') not in ('passed', 'failed')],
                        'excluded_roots': artifacts.get('3', {}).get('excluded', {}),
                        'client_verified': False, 'remote_state_changed': False,
                        'scope': '本批次没有需提单回归的根因；未运行回归，不代表全部测试通过。未决项与排除理由保留。'}
                    db.execute('UPDATE tasks SET artifacts=? WHERE id=?', (json.dumps(artifacts, ensure_ascii=False), task_id))
                stage = min(5, task['stage'] + 1)
                status = 'completed' if task['stage'] == 5 else 'waiting_user'
            elif action == 'cancel':
                stage, status = task['stage'], 'cancelled'
            else:
                raise ValueError('未知决策')
            db.execute('UPDATE tasks SET stage=?,status=?,revision=revision+1 WHERE id=?',
                       (stage, status, task_id))
            self._event(db, task_id, action, f'用户决策：{action}', task['stage'])
            if action == 'confirm' and task['stage'] < 5:
                from server.core.node_continuation import record_completion
                studio=db.execute('SELECT studio_id FROM projects WHERE id=?',(project_id,)).fetchone()['studio_id']
                record_completion(self,db,studio,project_id,'testing:'+str(task['stage']),revision+1,task_id)
        return self.task(project_id, task_id)

    def reset_node(self, project_id, task_id, stage, revision, reason, confirmed):
        """重置当前或上游节点，归档原产物；不调用外部服务。"""
        if type(stage) is not int or not 0 <= stage <= 5 or confirmed is not True:
            raise ValueError('需要确认重置合法节点')
        if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 1000:
            raise ValueError('请填写重置理由（最多1000字）')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task=self._task(db,project_id,task_id)
            if task['revision'] != revision:
                raise ValueError('任务已变化，请刷新后重置')
            if stage > task['stage']:
                raise ValueError('尚未到达此节点，无需重置')
            if db.execute("SELECT id FROM jobs WHERE task_id=? AND status IN ('queued','running')",(task_id,)).fetchone():
                raise ValueError('请等待后台操作结束；或先取消任务并等待操作停止')
            tables={r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('publications','status_changes'):
                if table in tables and db.execute(f"SELECT identity FROM {table} WHERE task_id=? AND status='sending'",(task_id,)).fetchone():
                    raise ValueError('飞书请求正在发送，请等待结果后重置')
            artifacts=json.loads(task['artifacts'])
            if any(str(i) not in artifacts for i in range(stage)):
                raise ValueError('前置节点缺少产物，请先重置更早的节点')
            snapshot={**task,'artifacts':artifacts}
            if 'publications' in tables:
                snapshot['publication_records']=[dict(r) for r in db.execute(
                    'SELECT identity,record_id,status FROM publications WHERE task_id=?',(task_id,))]
            db.execute('INSERT INTO node_resets(task_id,stage,revision,reason,snapshot) VALUES(?,?,?,?,?)',
                (task_id,stage,revision,reason.strip(),json.dumps(snapshot,ensure_ascii=False)))
            remaining={key:value for key,value in artifacts.items() if int(key)<stage}
            attribution=task['attribution'] if stage>2 else '{}'
            db.execute("UPDATE tasks SET stage=?,status='waiting_user',artifacts=?,attribution=?,regression='{}',revision=revision+1 WHERE id=?",
                (stage,json.dumps(remaining,ensure_ascii=False),attribution,task_id))
            self._event(db,task_id,'node_reset',f'重置节点{stage+1}，本节点及后续产物已归档并失效；理由：'+reason.strip(),stage)
        return self.task(project_id,task_id)

    def invalidate(self, project_id, task_id, reason):
        with self.connection() as db:
            self._task(db, project_id, task_id)
            db.execute("UPDATE tasks SET stage=0,status='waiting_user',artifacts='{}',attribution='{}',regression='{}',revision=revision+1 WHERE id=?",
                       (task_id,))
            self._event(db, task_id, 'invalidated', reason)
        return self.task(project_id, task_id)
