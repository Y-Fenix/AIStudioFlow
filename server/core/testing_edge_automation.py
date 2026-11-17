"""Explicit QA edge switches delegate only the source node's required decisions.

Completion creates a durable intent; switching on never replays historical jobs.
The existing continuation outbox dispatches the target after guarded approval.
"""
import json
import logging
from server.core.identity import current_user
from server.core.permissions import Policy
from server.core.node_continuation import _edges
from server.core.testing_automation import TestingAutomation


def migrate(db):
    db.execute('''CREATE TABLE IF NOT EXISTS testing_edge_advances (
        job_id TEXT PRIMARY KEY REFERENCES jobs(id),task_id TEXT NOT NULL,
        project_id TEXT NOT NULL,studio_id TEXT NOT NULL,actor TEXT NOT NULL,
        source TEXT NOT NULL,target TEXT NOT NULL,edge_revision INTEGER NOT NULL,
        topology_revision INTEGER NOT NULL,task_revision INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',detail TEXT NOT NULL DEFAULT '',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')


def record_completed(store, db, job, task_revision):
    stage=job.get('stage',0)
    if job.get('kind','generate') not in ('generate','execute','attribution') or stage not in (0,1,2):return
    if db.execute('SELECT 1 FROM testing_automation WHERE task_id=? AND enabled=1',(job['task_id'],)).fetchone():return
    if db.execute('SELECT 1 FROM department_flows WHERE task_id=?',(job['task_id'],)).fetchone():return
    _,topology,edges=_edges(db,job['project_id'],'testing')
    edge=next((e for e in edges if e['source']=='testing:'+str(stage) and e['enabled']),None)
    if not edge:return
    # Only the merged attribution -> internal drafts edge is delegated; no remote writes.
    if stage==2 and edge['target']!='testing:4':return
    studio=db.execute('SELECT studio_id FROM projects WHERE id=?',(job['project_id'],)).fetchone()[0]
    db.execute('''INSERT OR IGNORE INTO testing_edge_advances
        (job_id,task_id,project_id,studio_id,actor,source,target,edge_revision,topology_revision,task_revision)
        VALUES(?,?,?,?,?,?,?,?,?,?)''',(job['id'],job['task_id'],job['project_id'],studio,job['actor'],edge['source'],edge['target'],edge['edge_revision'],topology,task_revision))


def check_edge(db, intent):
    _,topology,edges=_edges(db,intent['project_id'],'testing')
    edge=next((e for e in edges if e['source']==intent['source'] and e['target']==intent['target']),None)
    if not edge or not edge['enabled'] or topology!=intent['topology_revision'] or edge['edge_revision']!=intent['edge_revision']:
        raise ValueError('节点开关已关闭或连接已变化；未继续自动决策')
    for node in (intent['source'],intent['target']):
        for action in ('view','edit','execute','approve'):
            Policy(intent['store']).require('node',action,studio=intent['studio_id'],project=intent['project_id'],node=node)
        Policy(intent['store']).require('skill','view',studio=intent['studio_id'],project=intent['project_id'],node=node)


class EdgeDecision(TestingAutomation):
    def __init__(self,store,intent):
        super().__init__(store);self.intent={**intent,'store':store}
    def _authorize(self,project):
        self._scope(project)
        with self.store.connection() as db:check_edge(db,self.intent)
        return self.intent['studio_id']
    def _decide(self,task):
        self._authorize(task['project_id'])
        return self.store.decide(task['project_id'],task['id'],'confirm',task['revision'],
                                 decision_origin='automation',edge_guard=self.intent)


class TestingEdgeAutomation:
    def __init__(self,store):self.store=store
    def recover(self):
        with self.store.connection() as db:
            db.execute("UPDATE testing_edge_advances SET status='stopped',detail='服务重启，节点自动决策已暂停；已有结果保留',updated_at=CURRENT_TIMESTAMP WHERE status='pending'")
    def run_once(self):
        with self.store.connection() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM testing_edge_advances WHERE status='pending' ORDER BY rowid LIMIT 20")]
        for row in rows:
            token=current_user.set(row['actor']);task=None;status='pending';detail=''
            try:
                decision=EdgeDecision(self.store,row);decision._authorize(row['project_id'])
                task=self.store.task(row['project_id'],row['task_id'])
                if task['revision']!=row['task_revision'] or task['status']!='waiting_user' or task['stage']!=int(row['source'].split(':')[1]):
                    raise ValueError('任务内容或阶段已变化；节点自动决策已停止')
                if task['automation']['enabled']:raise ValueError('全自动已接管，未重复推进')
                if any(j['status'] in ('running','queued') for j in task['jobs']):continue
                # Scope risk decisions, static evidence and attribution use the existing validators.
                updated,job,detail=decision._step(row,task)
                if job:raise ValueError('来源节点尚未完成，未重复执行')
                task=updated
                if task['stage']!=int(row['source'].split(':')[1]):status='completed'
            except (ValueError,KeyError,PermissionError) as exc:
                status='stopped';detail=str(exc)
            except Exception:
                logging.getLogger(__name__).exception('节点自动决策失败，job=%s',row['job_id'])
                status='stopped';detail='节点自动决策内部错误，请查看本机日志'
            finally:current_user.reset(token)
            with self.store.connection() as db:
                db.execute('UPDATE testing_edge_advances SET status=?,detail=?,task_revision=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=? AND status=\'pending\'',
                           (status,detail,task['revision'] if task else row['task_revision'],row['job_id']))
                self.store._event(db,row['task_id'],'edge_automation_'+status,detail,int(row['source'].split(':')[1]))
                job=db.execute('SELECT progress FROM jobs WHERE id=?',(row['job_id'],)).fetchone()
                progress=json.loads(job['progress']);progress.update(continuation_state=status,continuation_detail=detail)
                db.execute('UPDATE jobs SET progress=? WHERE id=?',(json.dumps(progress,ensure_ascii=False),row['job_id']))
        return bool(rows)
