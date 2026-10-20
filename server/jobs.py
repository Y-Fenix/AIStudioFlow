"""单机持久化生成队列；中断的运行不自动重试。"""
import os
import json
import threading
from pathlib import Path
from server.codex_model import CodexModel, diagnostic_scope
from server.node_skills import skill_scope
from server.generation_batches import generation_scope
import hashlib
from server.gagasort import execute_logic, inspect_project
from server.attribution import suggest_attribution
from server.regression import assess_logic_roots
from server.processes import cancellation_scope
from server.ai_models import ModelSettings,selection_scope
from server.core.identity import current_user
from server.core.queued_operations import authorize_testing_job


class GenerationWorker:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        store.recover_generations()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            job = self.store.claim_generation()
            if job is None:
                self.stop.wait(.25)
                continue
            identity = current_user.set(job.get('actor') or '')
            try:
                authorize_testing_job(self.store, job)
                task = self.store.task(job['project_id'], job['task_id'])
                if task['revision'] != job['revision'] or task['status'] in ('cancelled', 'completed'):
                    self.store.finish_generation(job, error='任务已变化')
                    continue
                def cancelled():
                    if self.stop.is_set():
                        return True
                    latest = self.store.task(job['project_id'], job['task_id'])
                    if latest['revision'] != job['revision'] or latest['status'] in ('cancelled', 'completed'):
                        return True
                    authorize_testing_job(self.store, job)
                    return False
                def diagnostic(value):
                    with self.store.connection() as db:
                        previous=json.loads(db.execute('SELECT progress FROM jobs WHERE id=?',(job['id'],)).fetchone()['progress'])
                    self.store.operation_progress(job,{**previous,**value})
                    if value['state']!='running':
                        with self.store.connection() as db:
                            self.store._event(db,job['task_id'],'model_request',
                                'Codex调用 '+json.dumps(value,ensure_ascii=False),job['stage'])
                stage=job['stage']
                content=task['node_skills'][str(stage)]['content']
                if not content.strip():raise ValueError('未配置 Skill，请先导入或恢复当前批次规则')
                with selection_scope(ModelSettings(self.store).runtime_selection()), cancellation_scope(cancelled), skill_scope(content), diagnostic_scope(diagnostic), generation_scope(
                    Path(__file__).resolve().parent.parent / 'data/generation-checkpoints' / task['id'] / str(task.get('reset_history',[]) [-1]['id'] if task.get('reset_history') else 0),
                    lambda value: self.store.operation_progress(job,value)):
                    kind = job.get('kind', 'generate')
                    evidence = Path(__file__).resolve().parent.parent / 'data/execution-evidence'
                    if kind == 'generate':
                        client = ModelSettings(self.store).generation_client()
                        result = client.generate(task['requirements'])
                    elif kind == 'execute':
                        result = execute_logic(task['binding'], evidence, task['artifacts']['0']['cases'], task['requirements'],
                                               progress=lambda value: self.store.operation_progress(job, value))
                    elif kind == 'attribution':
                        result = suggest_attribution(task['binding'], task['artifacts']['1'])
                    else:
                        binding = inspect_project(task['binding']['repository'], task['binding']['branch'])
                        binding['execution_suite'] = task['binding'].get('execution_suite', 'business')
                        execution = execute_logic(binding, evidence, task['artifacts']['0']['cases'], task['requirements'],
                                                  progress=lambda value: self.store.operation_progress(job, value))
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
                self.store.finish_generation(job, artifact=result)
            except (ValueError, PermissionError) as exc:
                self.store.finish_generation(job, error=str(exc))
            except Exception:
                self.store.finish_generation(job, error='后台操作内部错误，请查看本机服务')
            finally:
                current_user.reset(identity)
