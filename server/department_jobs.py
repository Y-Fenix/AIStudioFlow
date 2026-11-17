"""Durable queue for trusted non-testing department executors."""
from contextlib import nullcontext
import json
import logging
import sqlite3
import threading
import time
import uuid

from server.core.identity import current_user, user_id
from server.core.permissions import Policy


class DepartmentExecutionQueue:
    def __init__(self, store, registry):
        self.store = store
        self.registry = registry

    def enqueue(self, studio, project, node, revision, actor=None, *, connection=None, flow=""):
        actor = user_id(actor)
        for action in ('view', 'edit', 'execute'):
            Policy(self.store).require('node', action, studio=studio, project=project,
                                       node=node, actor=actor)
        if self.registry.get(node,store=self.store,project=project) is None:
            raise ValueError('本部门尚未接入执行器；请由部门负责人实现 adapter.py')
        from server.studio_workspaces import Workspaces
        workspace = Workspaces(self.store).get(studio, project, node, flow=flow)
        if not workspace['skill']['content'].strip():
            raise ValueError('未配置 Skill，请先导入或恢复规则')
        if type(revision) is not int or workspace['revision'] != revision:
            raise ValueError('输入版本已变化，请刷新')
        identity = uuid.uuid4().hex
        with (nullcontext(connection) if connection is not None else self.store.connection()) as db:
            if connection is None: db.execute('BEGIN IMMEDIATE')
            from server.core.project_content import require_enabled
            require_enabled(db,project,node.split(':')[0])
            try:
                db.execute('''INSERT INTO department_jobs
                    (id,studio_id,project_id,node,actor,revision,flow_id,status)
                    VALUES(?,?,?,?,?,?,?,'queued')''',
                    (identity, studio, project, node, actor, revision, flow))
            except sqlite3.IntegrityError as exc:
                raise ValueError('本节点已有执行任务，请等待完成或刷新任务状态') from exc
        return {"id": identity, "status": "queued"} if connection is not None else self.get(studio, project, identity, actor)

    def get(self, studio, project, identity, actor=None):
        actor = user_id(actor)
        self.store.check_project(studio, project, actor)
        with self.store.connection() as db:
            row = db.execute('SELECT * FROM department_jobs WHERE id=? AND studio_id=? AND project_id=?',
                             (identity, studio, project)).fetchone()
        if row is None:
            raise KeyError('执行任务不存在')
        Policy(self.store).require('node', 'view', studio=studio, project=project,
                                   node=row['node'], actor=actor)
        value = dict(row)
        value['progress'] = json.loads(value['progress']) if value['progress'] else None
        value['result'] = json.loads(value['result']) if value['result'] else None
        value.pop('actor', None)
        return value

    def latest(self, studio, project, node, actor=None, *, flow=""):
        actor = user_id(actor)
        self.store.check_project(studio, project, actor)
        Policy(self.store).require('node', 'view', studio=studio, project=project,
                                   node=node, actor=actor)
        with self.store.connection() as db:
            row = db.execute('''SELECT id FROM department_jobs WHERE studio_id=? AND project_id=? AND node=? AND flow_id=?
                ORDER BY created_at DESC,rowid DESC LIMIT 1''', (studio, project, node, flow)).fetchone()
        return self.get(studio, project, row['id'], actor) if row else None

    def claim(self):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM department_jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
            if row is None:
                return None
            changed = db.execute("UPDATE department_jobs SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'",
                                 (row['id'],)).rowcount
            return dict(row) if changed else None

    def finish(self, job, result=None, error=None, status=None):
        final_status = status or ('failed' if error else 'completed')
        with self.store.connection() as db:
            changed=db.execute('''UPDATE department_jobs SET status=?,result=?,error=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='running' ''',
                (final_status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                 error, job['id'])).rowcount
            if changed and final_status in ('completed','failed','interrupted'):
                from server.core.notifications import enqueue
                enqueue(self.store,db,job['project_id'],job['node'],'department-job:'+job['id'],final_status,result,flow_id=job['flow_id'])

    def recover(self):
        """Do not replay arbitrary department side effects after a server crash."""
        with self.store.connection() as db:
            rows=db.execute("SELECT * FROM department_jobs WHERE status='running'").fetchall()
            changed=db.execute("UPDATE department_jobs SET status='interrupted',error='服务重启时任务仍在运行；未自动重试',updated_at=CURRENT_TIMESTAMP WHERE status='running'").rowcount
            from server.core.notifications import enqueue
            for row in rows:enqueue(self.store,db,row['project_id'],row['node'],'department-job:'+row['id'],'interrupted',flow_id=row['flow_id'])
            return changed

    def run_once(self):
        job = self.claim()
        if job is None:
            return False
        token = current_user.set(job['actor'])
        try:
            from server.core.integrations import ExecutionService
            from server.core.execution_progress import ExecutionProgress
            from server.ai_models import ModelSettings
            from server.codex_model import diagnostic_scope
            telemetry = ExecutionProgress(self.store, 'department_jobs', job['id'],
                                          ModelSettings(self.store).runtime_selection())
            with diagnostic_scope(telemetry.publish):
                telemetry.publish({})
                result = ExecutionService(self.store, self.registry).execute(
                    job['studio_id'], job['project_id'], job['node'], job['revision'], flow=job['flow_id'])
            self.finish(job, result=result)
        except ValueError as exc:
            self.finish(job, error=str(exc))
        except PermissionError:
            self.finish(job, error='执行权限已收回；未保存交付。请联系负责人核对权限')
        except Exception:
            logging.getLogger(__name__).exception('Department executor failed for job %s', job['id'])
            self.finish(job, error='部门执行器内部错误；请查看本机服务日志')
        finally:
            current_user.reset(token)
        return True


class DepartmentExecutionWorker:
    def __init__(self, store, registry):
        self.queue = DepartmentExecutionQueue(store, registry)
        self.queue.recover()
        self.stop = threading.Event()
        self.threads = [threading.Thread(target=self.run, daemon=True, name='department-executors-'+str(i)) for i in range(3)]
        self.thread = self.threads[0]  # Compatibility for older callers.
        for thread in self.threads: thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                if not self.queue.run_once():
                    self.stop.wait(.25)
            except Exception:
                logging.getLogger(__name__).exception('Department execution queue iteration failed')
                self.stop.wait(.5)

    def close(self):
        self.stop.set()
        for thread in self.threads: thread.join(timeout=2)
