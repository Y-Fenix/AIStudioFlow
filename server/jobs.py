"""单机持久化生成队列；中断的运行不自动重试。"""
import os
import json
import threading
import sqlite3
from pathlib import Path
from server.codex_model import CodexModel, diagnostic_scope
from server.node_skills import skill_scope
from server.generation_batches import generation_scope
import hashlib
import logging
from server.gagasort import execute_logic, inspect_project
from server.attribution import suggest_attribution
from server.regression import assess_logic_roots
from server.processes import cancellation_scope
from server.ai_models import ModelSettings,selection_scope
from server.core.identity import current_user
from server.core.queued_operations import authorize_testing_job
from server.core.job_telemetry import JobTelemetry
from departments.testing.QA_review_checkpoints import QA_checkpoint_scope

logger = logging.getLogger(__name__)


class GenerationWorker:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        store.recover_generations()
        self.threads = [threading.Thread(target=self.run, daemon=True, name='qa-jobs-'+str(i)) for i in range(3)]
        self.thread = self.threads[0]
        for thread in self.threads:thread.start()

    def close(self):
        self.stop.set()
        for thread in self.threads:thread.join(timeout=5)

    def run(self):
        while not self.stop.is_set():
            try:
                job = self.store.claim_generation()
            except sqlite3.OperationalError as exc:
                if (getattr(exc,'sqlite_errorcode',0) & 255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                    raise
                logger.warning('测试队列暂时等待数据库写入，工作线程保持运行')
                self.stop.wait(.5)
                continue
            if job is None:
                self.stop.wait(.25)
                continue
            identity = current_user.set(job.get('actor') or '')
            try:
                operation_stage = authorize_testing_job(self.store, job)
                task = self.store.task(job['project_id'], job['task_id'])
                if task['revision'] != job['revision'] or task['status'] in ('cancelled', 'completed'):
                    self.store.finish_generation(job, error='任务已变化')
                    continue
                def cancelled():
                    if self.stop.is_set():
                        return True
                    # File scans probe cancellation very frequently. Never load
                    # all requirements/cases/Skill history for this status check.
                    with self.store.connection() as db:
                        latest = db.execute('SELECT revision,status FROM tasks WHERE id=? AND project_id=?',
                                            (job['task_id'], job['project_id'])).fetchone()
                        current_job = db.execute('SELECT context FROM jobs WHERE id=?', (job['id'],)).fetchone()
                    if current_job is None or json.loads(current_job['context']).get('cancel_requested'):
                        return True
                    if latest is None or latest['revision'] != job['revision'] or latest['status'] in ('cancelled', 'completed'):
                        return True
                    authorize_testing_job(self.store, job)
                    return False
                selection = ModelSettings(self.store).runtime_selection()
                telemetry = JobTelemetry(self.store, job, selection)
                telemetry.publish({})
                def diagnostic(value):
                    telemetry.publish(value)
                    if value['state']!='running':
                        with self.store.connection() as db:
                            self.store._event(db,job['task_id'],'model_request',
                                'Codex调用 '+json.dumps(value,ensure_ascii=False),job['stage'])
                # Task stage guards revisions; operation stage determines the Skill.
                # A pending Bug can be regressed while the task is still at filing.
                content=task['node_skills'][str(operation_stage)]['content']
                if not content.strip():raise ValueError('未配置 Skill，请先导入或恢复当前批次规则')
                checkpoint_base = self.store.path.resolve().parent / 'static-review-checkpoints' / task['id'] / str(task.get('reset_history', [])[-1]['id'] if task.get('reset_history') else 0) / job.get('kind', 'generate')
                with selection_scope(selection), cancellation_scope(cancelled), skill_scope(content), diagnostic_scope(diagnostic), QA_checkpoint_scope(checkpoint_base), generation_scope(
                    Path(__file__).resolve().parent.parent / 'data/generation-checkpoints' / task['id'] / str(task.get('reset_history',[]) [-1]['id'] if task.get('reset_history') else 0),
                    telemetry.publish):
                    kind = job.get('kind', 'generate')
                    evidence = Path(__file__).resolve().parent.parent / 'data/execution-evidence'
                    if kind == 'generate':
                        client = ModelSettings(self.store).generation_client()
                        result = client.generate(task['requirements'])
                    elif kind == 'execute':
                        result = execute_logic(task['binding'], evidence, task['artifacts']['0']['cases'], task['requirements'],
                                               progress=telemetry.publish, points=task['artifacts']['0'].get('points', []))
                    elif kind == 'attribution':
                        result = suggest_attribution(task['binding'], task['artifacts']['1'])
                    else:
                        binding = inspect_project(task['binding']['repository'], task['binding']['branch'])
                        binding['execution_suite'] = task['binding'].get('execution_suite', 'business')
                        execution = execute_logic(binding, evidence, task['artifacts']['0']['cases'], task['requirements'],
                                                  progress=telemetry.publish, points=task['artifacts']['0'].get('points', []))
                        drafts = task['artifacts']['4']['drafts']
                        context = json.loads(job.get('context', '{}'))
                        if context.get('trigger') == 'fresh_pending_status':
                            roots = set(context['root_cause_ids'])
                            drafts = [d for d in drafts if d['root_cause_id'] in roots]
                            if {d['root_cause_id'] for d in drafts} != roots:
                                raise ValueError('待验证回归范围已变化')
                        result = assess_logic_roots(drafts, task['artifacts']['1'], execution)
                        result['trigger_context'] = context
                        if context.get('trigger') == 'fresh_pending_status':
                            result['scope'] = '仅待验证根因的关联用例代码回归；触发前只读检查飞书状态，未验证客户端完整回归，未修改远端状态'

                result['node_skill_sha256']=hashlib.sha256(content.encode()).hexdigest()
                authorize_testing_job(self.store, job)
                if kind=='generate':
                    self.store.finish_generation(job, artifact=result, skill_snapshot=task['node_skills'].get('0'))
                else:
                    self.store.finish_generation(job, artifact=result)
            except (ValueError, PermissionError) as exc:
                if isinstance(exc, OSError):
                    logger.exception('测试后台任务本机权限错误，job=%s', job.get('id'))
                self.store.finish_generation(job, error=str(exc))
            except Exception:
                logger.exception('测试后台任务内部错误，job=%s', job.get('id'))
                self.store.finish_generation(job, error='后台操作内部错误，请查看本机服务')
            finally:
                current_user.reset(identity)
