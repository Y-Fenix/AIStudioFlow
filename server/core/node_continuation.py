"""Explicit per-edge continuation; human approval is never synthesized."""
import json
import logging
import threading
from server.core.identity import current_user, user_id
from server.core.permissions import Policy
from server.core.project_nodes import read_config


def _edges(db,project,department):
    topology,nodes=read_config(db,project,department)
    nodes=[n for n in nodes if not n['archived']]
    row=db.execute('SELECT * FROM node_continuation_configs WHERE project_id=? AND department=?',(project,department)).fetchone()
    config=json.loads(row['edges']) if row else {}
    result=[]
    for source,target in zip(nodes,nodes[1:]):
        a,b=source['id'],target['id']
        valid=not (department=='testing' and (a.startswith('testing:custom-') or b.startswith('testing:custom-') or
                    not a.split(':')[1].isdigit() or not b.split(':')[1].isdigit() or int(b.split(':')[1])!=int(a.split(':')[1])+1))
        value=config.get(a+'>'+b,{})
        result.append({'source':a,'target':b,'source_name':source['definition'][0],'target_name':target['definition'][0],
            'enabled':valid and value.get('enabled') is True and value.get('topology_revision')==topology,
            'edge_revision':value.get('revision',0),'available':valid,'reason':'' if valid else '展示顺序不符合测试证据依赖，请恢复原阶段顺序后启用'})
    return f"{row['revision'] if row else 0}:{topology}",topology,result


def record_completion(store,db,studio,project,source,revision,task_id=''):
    """Called in the confirmation transaction, with its post-confirmation revision."""
    _,topology,edges=_edges(db,project,source.split(':')[0])
    edge=next((e for e in edges if e['source']==source),None)
    if not edge:return
    if not edge['enabled']:
        detail='已完成，等待手动继续（自动继续已关闭）'
        if task_id:store._event(db,task_id,'continuation_stopped',detail,int(source.split(':')[1]))
        else:db.execute('INSERT INTO studio_events(project_id,node,action,detail) VALUES(?,?,?,?)',(project,source,'continuation_stopped',detail))
        return
    if task_id:
        task=store._task(db,project,task_id)
        from server.node_skills import defaults
        skills={**defaults(),**json.loads(task['node_skills'])}
        skill=skills.get(edge['target'].split(':')[1],{})
        from server.core.skill_library import bound_skill
        skill=bound_skill(db,project,edge['target'],skill,task_id)
        target_revision=revision
    else:
        from server.studio_workspaces import Workspaces
        workspace=Workspaces(store)._read(db,studio,project,edge['target'])
        target_revision=workspace['revision'];skill=workspace['skill']
    db.execute('''INSERT OR IGNORE INTO node_continuation_events
        (studio_id,project_id,source,target,task_id,source_revision,target_revision,skill_sha256,edge_revision,topology_revision,actor)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(studio,project,source,edge['target'],task_id,revision,target_revision,skill.get('sha256',''),edge['edge_revision'],topology,user_id()))


class NodeContinuation:
    def __init__(self,store,registry=None):self.store=store;self.registry=registry

    def get(self,studio,project,department):
        self.store.check_project(studio,project)
        policy=Policy(self.store)
        with self.store.connection() as db:revision,_,edges=_edges(db,project,department)
        visible=[]
        for edge in edges:
            if not all(policy.allowed('node','view',studio,project,node=n) for n in (edge['source'],edge['target'])):continue
            visible.append({**edge,'editable':edge['available'] and policy.allowed('node','edit',studio,project,node=edge['source'])})
        if not visible and not policy.allowed('department','view',studio,project,department):
            policy.require('project','view',studio=studio,project=project)
        with self.store.connection() as db:
            events=[dict(row) for row in db.execute(
                "SELECT id,node,action,detail,created_at FROM studio_events WHERE project_id=? AND action LIKE 'continuation_%' ORDER BY id DESC LIMIT 200",(project,))]
        sources={edge['source'] for edge in visible}
        return {'revision':revision,'department':department,'edges':visible,'events':[e for e in reversed(events) if e['node'] in sources]}


    def save(self,studio,project,department,value):
        self.store.check_project(studio,project)
        if not isinstance(value,dict) or type(value.get('enabled')) is not bool:raise ValueError('开关必须是布尔值')
        policy=Policy(self.store)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from server.core.project_content import require_enabled
            require_enabled(db,project,department)
            revision,topology,edges=_edges(db,project,department)
            if value.get('revision')!=revision:raise ValueError('衔接配置已变化，请刷新后重试')
            edge=next((e for e in edges if e['source']==value.get('source') and e['target']==value.get('target')),None)
            if not edge or not edge['available']:raise ValueError('只能设置当前有效相邻节点；测试节点必须遵守证据依赖')
            policy.require('node','edit',studio=studio,project=project,node=edge['source'])
            policy.require('node','view',studio=studio,project=project,node=edge['target'])
            row=db.execute('SELECT * FROM node_continuation_configs WHERE project_id=? AND department=?',(project,department)).fetchone()
            configs=json.loads(row['edges']) if row else {}
            configs[edge['source']+'>'+edge['target']]={'enabled':value['enabled'],'topology_revision':topology,'revision':(row['revision'] if row else 0)+1}
            db.execute('''INSERT INTO node_continuation_configs VALUES(?,?,?,?) ON CONFLICT(project_id,department)
                DO UPDATE SET revision=excluded.revision,edges=excluded.edges''',
                (project,department,(row['revision'] if row else 0)+1,json.dumps(configs)))
            detail=f"{edge['source_name']} → {edge['target_name']}："+('开启自动继续' if value['enabled'] else '关闭自动继续')
            db.execute('INSERT INTO studio_events(project_id,node,action,detail) VALUES(?,?,?,?)',(project,edge['source'],'continuation_changed',detail))
            db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',
                (user_id(),studio,'continuation_changed',json.dumps({'project':project,'source':edge['source'],'target':edge['target'],'enabled':value['enabled']},ensure_ascii=False)))
        return self.get(studio,project,department)

    def _dispatch(self,db,event):
        studio,project,source,target=event['studio_id'],event['project_id'],event['source'],event['target']
        self.store.check_project(studio,project)
        from server.core.project_content import require_enabled
        require_enabled(db,project,source.split(':')[0])
        _,topology,edges=_edges(db,project,source.split(':')[0])
        edge=next((e for e in edges if e['source']==source and e['target']==target),None)
        if not edge or topology!=event['topology_revision']:raise ValueError('节点连接已变化，等待手动继续')
        if not edge['enabled']:raise ValueError('自动继续已关闭，等待手动继续')
        if edge['edge_revision']!=event['edge_revision']:raise ValueError('开关设置已变化，未补跑旧的续接请求')
        policy=Policy(self.store)
        for node,actions in ((source,('view','approve')),(target,('view','edit','execute'))):
            for action in actions:policy.require('node',action,studio=studio,project=project,node=node)
        if event['task_id']:return self._dispatch_testing(db,event)
        from server.studio_workspaces import Workspaces
        workspaces=Workspaces(self.store)
        origin=workspaces._read(db,studio,project,source);destination=workspaces._read(db,studio,project,target)
        if origin['revision']!=event['source_revision'] or origin['status']!='approved':raise ValueError('上游证据已变化，请重新审核')
        if destination['revision']!=event['target_revision'] or destination['skill']['sha256']!=event['skill_sha256']:raise ValueError('下一节点资料或 Skill 已变化，等待手动继续')
        if not self.registry or self.registry.get(target,store=self.store,project=project) is None:raise ValueError('下一节点尚未接通执行器，等待手动继续')
        if not destination['inputs'].strip():raise ValueError('下一节点缺少输入资料，请补充并手动执行')
        if destination['deliverable'].strip():raise ValueError('下一节点已有交付物，等待人工处理，未覆盖')
        from server.department_jobs import DepartmentExecutionQueue
        queue=DepartmentExecutionQueue(self.store,self.registry)
        if db.execute("SELECT 1 FROM department_jobs WHERE project_id=? AND node=? AND status IN ('queued','running')",(project,target)).fetchone():raise ValueError('下一节点已有执行任务，未重复派发')
        return queue.enqueue(studio,project,target,destination['revision'],connection=db)['id']

    def _dispatch_testing(self,db,event):
        project,task_id=event['project_id'],event['task_id'];task=self.store.task(project,task_id)
        stage=int(event['target'].split(':')[1])
        if task['revision']!=event['source_revision'] or task['stage']!=stage or task['status']!='waiting_user':raise ValueError('测试批次证据或阶段已变化，等待手动继续')
        skill=task['node_skills'].get(str(stage),{})
        if not skill.get('content','').strip() or skill.get('sha256')!=event['skill_sha256']:raise ValueError('下一节点 Skill 未配置或已变化')
        if stage not in (1,2):raise ValueError({3:'下一步需要人工筛选根因',4:'下一步需要核对复现及提单内容；不会自动发布 Bug',5:'回归需先核对关联 Bug 待验证状态'}.get(stage,'此节点需要人工操作'))
        binding=task['binding']
        if not binding:raise ValueError('请先绑定代码分支，再手动执行')
        if binding.get('execution_suite')!='static':raise ValueError('自动继续仅支持静态代码检测，请先选择静态方式')
        from server.gagasort import inspect_project
        current=inspect_project(binding['repository'],binding['branch'])
        if any(current.get(k)!=binding.get(k) for k in ('branch','commit','code_fingerprint')):raise ValueError('代码已变化，请重新绑定并确认')
        kind='execute' if stage==1 else 'attribution'
        from server.core.queued_operations import authorize_testing_job
        authorize_testing_job(self.store,{'actor':user_id(),'project_id':project,'task_id':task_id,'kind':kind})
        if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')",(task_id,)).fetchone():raise ValueError('本批次已有执行任务，未重复派发')
        return self.store.enqueue_operation(project,task_id,kind,connection=db)['id']

    def run_once(self):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM node_continuation_events WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            if row is None:return False
            event=dict(row);token=current_user.set(event['actor'])
            try:
                job=self._dispatch(db,event);status='dispatched';detail='已自动排队下一节点：'+event['target']
            except (ValueError,PermissionError,KeyError) as exc:job=None;status='stopped';detail='自动继续暂停：'+str(exc)
            finally:current_user.reset(token)
            db.execute('UPDATE node_continuation_events SET status=?,detail=?,job_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,detail,job,event['id']))
            if event['task_id']:self.store._event(db,event['task_id'],'continuation_'+status,detail,int(event['source'].split(':')[1]))
            else:db.execute('INSERT INTO studio_events(project_id,node,action,detail) VALUES(?,?,?,?)',(event['project_id'],event['source'],'continuation_'+status,detail))
        return True


class ContinuationWorker:
    def __init__(self,store,registry):
        self.service=NodeContinuation(store,registry);self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True,name='node-continuation');self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                if not self.service.run_once():self.stop.wait(.25)
            except Exception:
                logging.getLogger(__name__).exception('Continuation transaction failed; no intent or job was committed')
                self.stop.wait(1)

    def close(self):self.stop.set();self.thread.join(timeout=5)
