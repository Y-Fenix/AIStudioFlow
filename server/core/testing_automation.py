"""Explicit per-task delegation. Only internal QA decisions; never remote writes."""
import json
import logging
import threading
from server.core.identity import current_user, user_id
from server.core.permissions import Policy
from server.core.queued_operations import authorize_testing_job
from server.core.project_nodes import testing_filter_merged, read_config
from server.core.project_content import require_enabled


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS testing_automation (
        task_id TEXT PRIMARY KEY REFERENCES tasks(id), actor TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'off',
        revision INTEGER NOT NULL DEFAULT 0, last_task_revision INTEGER NOT NULL,
        job_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')


def read_state(db, task_id):
    row = db.execute('SELECT * FROM testing_automation WHERE task_id=?', (task_id,)).fetchone()
    return {**dict(row), 'enabled': bool(row['enabled'])} if row else {
        'enabled': False, 'state': 'off', 'revision': 0, 'detail': '', 'actor': ''}


class TestingAutomation:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def _scope(self, project):
        with self.store.connection() as db:
            row = db.execute('SELECT studio_id FROM projects WHERE id=? AND archived=0', (project,)).fetchone()
            if not row:raise ValueError('项目不存在或已归档')
            studio = row['studio_id']
            active = [n['id'] for n in read_config(db, project, 'testing')[1] if not n['archived']]
            require_enabled(db, project, 'testing')
        self.store.check_project(studio, project)
        return studio, active

    def _authorize(self, project):
        studio, active = self._scope(project)
        required = ['testing:0', 'testing:1', 'testing:2', 'testing:4']
        if not all(n in active for n in required):raise ValueError('全自动需要保留用例、执行、归因、提单节点')
        with self.store.connection() as db:merged = testing_filter_merged(db, project)
        if not merged:required.append('testing:3')
        policy = Policy(self.store)
        for node in required:
            for action in ('view', 'edit', 'execute', 'approve'):
                policy.require('node', action, studio=studio, project=project, node=node)
            policy.require('skill', 'view', studio=studio, project=project, node=node)
        return studio

    def can_manage(self, project):
        try:self._authorize(project);return True
        except (ValueError, PermissionError, KeyError):return False

    def get(self, project, task_id):
        with self.store.connection() as db:
            self.store._task(db, project, task_id)
            return read_state(db, task_id)

    def save(self, project, task_id, value):
        if type(value.get('enabled')) is not bool:raise ValueError('全自动开关必须为布尔值')
        with self.lock:
            t = self.store.task(project, task_id)
            if value['enabled']:
                self._authorize(project)
                if t['stage'] > 4 or t['status'] != 'waiting_user':raise ValueError('当前批次不能开启到内部草稿的全自动')
            else:
                studio, _ = self._scope(project)
                if self.get(project, task_id).get('actor') != user_id():
                    Policy(self.store).require('node', 'edit', studio=studio, project=project, node='testing:'+str(t['stage']))
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                current = self.store._task(db, project, task_id);old = read_state(db, task_id)
                # Stopping must win even when the browser has not observed the latest step.
                if value['enabled'] and (current['revision'] != value.get('revision') or old['revision'] != value.get('config_revision')):
                    raise ValueError('批次或全自动设置已变化，请刷新后重试')
                detail = '全自动已开启：按静态范围保留风险并推进到内部 Bug 草稿；不会发布飞书或修改状态' if value['enabled'] else '全自动已停止；在途只读任务可完成，不再自动决策或续接'
                active = db.execute("SELECT id FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone()
                db.execute('''INSERT INTO testing_automation(task_id,actor,enabled,state,revision,last_task_revision,job_id,detail)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET actor=excluded.actor,
                    enabled=excluded.enabled,state=excluded.state,revision=excluded.revision,
                    last_task_revision=excluded.last_task_revision,job_id=excluded.job_id,detail=excluded.detail,updated_at=CURRENT_TIMESTAMP''',
                    (task_id,user_id(),int(value['enabled']),'running' if value['enabled'] else 'off',old['revision']+1,current['revision'],active['id'] if active and value['enabled'] else '',detail))
                self.store._event(db, task_id, 'automation_changed', detail, current['stage'])
        return self.get(project, task_id)

    def recover(self):
        with self.lock, self.store.connection() as db:
            rows = db.execute('SELECT a.task_id,t.stage FROM testing_automation a JOIN tasks t ON t.id=a.task_id WHERE a.enabled=1').fetchall()
            db.execute("UPDATE testing_automation SET enabled=0,state='paused',detail='服务已重启，全自动已暂停；请重新开启，原检查点保留',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE enabled=1")
            for row in rows:self.store._event(db,row['task_id'],'automation_paused','服务重启，全自动委托暂停；未自动续接',row['stage'])

    def _update(self, row, task, detail, *, job_id='', state='running', enabled=True):
        with self.store.connection() as db:
            db.execute('UPDATE testing_automation SET enabled=?,state=?,last_task_revision=?,job_id=?,detail=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE task_id=? AND enabled=1',
                       (int(enabled),state,task['revision'],job_id,detail,row['task_id']))
            self.store._event(db, row['task_id'], 'automation_'+state, detail, task['stage'])

    def _decide(self, task):
        self._authorize(task['project_id'])
        return self.store.decide(task['project_id'],task['id'],'confirm',task['revision'],decision_origin='automation')

    def _assert_execution_current(self, task):
        from server.gagasort import inspect_project
        execution = task['artifacts'].get('1', {})
        binding = task['binding']
        if execution.get('method') != 'static_code_review' or not binding:
            raise ValueError('全自动需要当前版本逐用例静态检测结果')
        authorize_testing_job(self.store, {'actor':user_id(), 'project_id':task['project_id'], 'task_id':task['id'], 'kind':'attribution'})
        current = inspect_project(binding['repository'], binding['branch'])
        if any(execution.get(k) != current.get(k) for k in ('code_fingerprint', 'commit', 'branch')):
            raise ValueError('代码已变化，请返回执行节点更新基线后检测')

    def _step(self, row, t):
        from server.requirements import review_cases, case_review_hash, validate_cases
        from server.gagasort import inspect_project
        from server.triage import triage_report, filter_groups
        project, task_id, stage = t['project_id'], t['id'], t['stage']
        artifact = t['artifacts'].get(str(stage))
        if stage in (2,3,4):self._assert_execution_current(t)
        if stage == 0:
            if not artifact:
                authorize_testing_job(self.store,{'actor':user_id(),'project_id':project,'task_id':task_id,'kind':'generate'})
                return t, self.store.enqueue_operation(project,task_id,'generate',expected_revision=t['revision']), '自动生成用例已排队'
            validate_cases(artifact, t['requirements'])
            review = artifact.get('user_review')
            if review:
                if not review.get('ready_for_execution') or review.get('review_hash') != case_review_hash(artifact,t['requirements']):
                    raise ValueError('现有范围评审要求补充或已失效；未覆盖用户决策')
                return self._decide(t),None,'自动决策：已确认本次静态范围，保留全部风险'
            from departments.testing.QA_automation import QA_scope_decisions
            review = review_cases(artifact,t['requirements'],QA_scope_decisions(t['case_review_items']),True)
            review.update(decision_origin='automation',scope='自动范围决策：仅审查已识别的可执行规则；来源、覆盖缺口和歧义保留为风险，不代表全面覆盖或人工已核对')
            updated = self.store.record_artifact(project,task_id,0,{**artifact,'user_review':review},expected_revision=t['revision'])
            return updated,None,'自动决策：已保存范围及 '+str(len(review['decisions']))+' 条风险处理理由'
        if stage == 1:
            binding = t['binding']
            if not binding:raise ValueError('请先填写仓库路径并绑定指定分支，再开启全自动')
            authorize_testing_job(self.store,{'actor':user_id(),'project_id':project,'task_id':task_id,'kind':'execute'})
            current = inspect_project(binding['repository'],binding['branch']);current['execution_suite']='static'
            self._authorize(project)
            if artifact and all(artifact.get(k)==current.get(k) for k in ('code_fingerprint','commit','branch')) and artifact.get('method')=='static_code_review':
                return self._decide(t),None,'自动决策：静态结果覆盖已校验；未决项保留为风险，继续归因'
            authorize_testing_job(self.store,{'actor':user_id(),'project_id':project,'task_id':task_id,'kind':'execute'})
            result = self.store.start_static_review(project,task_id,current,t['revision'])
            return result['task'],result['job'],'已检查当前分支基线，自动静态检测已排队'
        if stage == 2:
            if artifact:
                if not artifact.get('ready_for_review'):raise ValueError('已有归因仍未闭合，请补充归因证据')
                with self.store.connection() as db:merged=testing_filter_merged(db,project)
                if merged and not artifact.get('filing_scope'):
                    scope=filter_groups(artifact,[g['root_cause_id'] for g in artifact['groups']],{})
                    return self.store.record_artifact(project,task_id,2,{**artifact,'filing_scope':scope},expected_revision=t['revision']),None,'自动决策：全部有证据根因纳入内部草稿'
                return self._decide(t),None,'自动决策：归因和提单范围已确认'
            candidate=t.get('attribution',{})
            if 'suggestions' not in candidate:
                authorize_testing_job(self.store,{'actor':user_id(),'project_id':project,'task_id':task_id,'kind':'attribution'})
                return t,self.store.enqueue_operation(project,task_id,'attribution',expected_revision=t['revision']),'自动归因已排队'
            execution=t['artifacts']['1'];current=inspect_project(t['binding']['repository'],t['binding']['branch'])
            if any(execution.get(k)!=current.get(k) for k in ('code_fingerprint','commit','branch')):
                raise ValueError('代码已变化，请返回执行节点更新基线后检测')
            from server.attribution import validate_suggestions
            from server.static_review import SourceCatalog
            catalog=SourceCatalog(current['project_root']);failures=[r for r in execution['results'] if r['status']=='failed']
            sources={ref['file']:catalog.read(ref['file']) for item in candidate['suggestions'] for ref in item['evidence']}
            checked=validate_suggestions(candidate,failures,sources)
            from departments.testing.QA_automation import QA_root_decisions
            decisions=QA_root_decisions(checked['suggestions'],failures)
            result=triage_report(execution['results'],decisions['assignments'],decisions['roots'],[])
            result.update(decision_origin='automation',scope='AI自动归因确认，源码引用已复核；静态推导不代表实机复现，全部未决项保留')
            with self.store.connection() as db:merged=testing_filter_merged(db,project)
            if merged:result['filing_scope']=filter_groups(result,[g['root_cause_id'] for g in result['groups']],{})
            return self.store.record_artifact(project,task_id,2,result,expected_revision=t['revision']),None,'自动决策：有源码证据的候选根因已确认，未决结果保留'
        if stage == 3:
            if artifact:return self._decide(t),None,'自动决策：内部提单范围已确认'
            result=filter_groups(t['artifacts']['2'],[g['root_cause_id'] for g in t['artifacts']['2']['groups']],{})
            return self.store.record_artifact(project,task_id,3,result,expected_revision=t['revision']),None,'自动决策：已选择全部有证据根因'
        if stage == 4:
            if not artifact:
                from server.bugs import prepare_drafts
                with self.store.connection() as db:name=db.execute('SELECT name FROM projects WHERE id=?',(project,)).fetchone()['name']
                execution=t['artifacts']['1'];environment={k:execution.get(k) for k in ('branch','commit','build','method','code_fingerprint')};environment.update(project=name,project_id=project)
                result=prepare_drafts(t['artifacts']['3']['groups'],execution['results'],[],environment)
                result['decision_origin']='automation'
                return self.store.record_artifact(project,task_id,4,result,expected_revision=t['revision']),None,'自动决策：每个根因已生成一份内部 Bug 草稿'
            if not isinstance(artifact.get('drafts'),list):raise ValueError('尚无有效内部草稿，需重新准备')
            if any(d.get('missing') for d in artifact['drafts']):raise ValueError('内部草稿仍有复现条件或证据缺口，需补充；未发布')
            return t,None,'内部 Bug 草稿已准备好；飞书发布和状态修改等待人工确认'
        raise ValueError('当前节点超出全自动内部草稿范围')

    def run_once(self):
        changed=False
        with self.lock:
            with self.store.connection() as db:
                rows=[dict(r) for r in db.execute('SELECT a.*,t.project_id FROM testing_automation a JOIN tasks t ON t.id=a.task_id WHERE a.enabled=1 ORDER BY a.updated_at,a.task_id')]
            for row in rows:
                token=current_user.set(row['actor'])
                t=None
                try:
                    self._authorize(row['project_id']);t=self.store.task(row['project_id'],row['task_id'])
                    if t['status']!='waiting_user':raise ValueError('批次已取消或结束，全自动暂停')
                    active=next((j for j in t['jobs'] if j['status'] in ('queued','running')),None)
                    if row['job_id']:
                        job=next((j for j in t['jobs'] if j['id']==row['job_id']),None)
                        if not job or job['status'] not in ('queued','running','completed'):raise ValueError('自动任务失败或已失效：'+str((job or {}).get('error') or '未完成'))
                        if job['status'] in ('queued','running'):
                            if t['revision']!=row['last_task_revision']:raise ValueError('批次已被修改，全自动暂停')
                            continue
                        if t['revision']!=job['revision']+1:raise ValueError('执行完成后批次又被修改，请重新开启')
                    elif t['revision']!=row['last_task_revision']:raise ValueError('批次输入、Skill或决策已被修改，请核对后重新开启')
                    if active:
                        self._update(row,t,'等待当前后台任务完成',job_id=active['id']);changed=True;continue
                    updated,job,detail=self._step(row,t)
                    done=t['stage']==4 and '4' in t['artifacts'] and job is None
                    self._update(row,updated,detail,job_id=job['id'] if job else '',state='completed' if done else 'running',enabled=not done)
                    changed=True
                except (ValueError,PermissionError,KeyError) as exc:
                    t=t or self.store.task(row['project_id'],row['task_id'])
                    self._update(row,t,'全自动暂停：'+str(exc),state='paused',enabled=False);changed=True
                except Exception:
                    logging.getLogger(__name__).exception('自动委托内部错误，task=%s',row['task_id'])
                    t=t or self.store.task(row['project_id'],row['task_id'])
                    self._update(row,t,'全自动暂停：本机内部错误，请查看服务日志',state='paused',enabled=False);changed=True
                finally:current_user.reset(token)
        return changed


class TestingAutomationWorker:
    def __init__(self,service):
        self.service=service;self.stop=threading.Event();service.recover()
        from server.core.testing_edge_automation import TestingEdgeAutomation
        self.edges=TestingEdgeAutomation(service.store);self.edges.recover()
        self.thread=threading.Thread(target=self.run,daemon=True,name='testing-automation');self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                self.service.run_once()
                self.edges.run_once()
            except Exception:logging.getLogger(__name__).exception('自动委托调度失败')
            self.stop.wait(1)

    def close(self):self.stop.set();self.thread.join(timeout=5)
