"""Department workflow instances; stable node IDs and legacy workspace stay intact."""
import hashlib
import json
import uuid
from server.core.identity import user_id
from server.core.permissions import Policy
from server.studio_catalog import node_definition


def migrate(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS department_flows (
            id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
            department TEXT NOT NULL,name TEXT NOT NULL,task_id TEXT NOT NULL DEFAULT '',
            archived INTEGER NOT NULL DEFAULT 0,created_by TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS flow_workspaces (
            flow_id TEXT NOT NULL REFERENCES department_flows(id),node TEXT NOT NULL,
            inputs TEXT NOT NULL DEFAULT '',skill TEXT NOT NULL,deliverable TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'not_started',revision INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(flow_id,node));
        CREATE TABLE IF NOT EXISTS flow_events (
            id INTEGER PRIMARY KEY,flow_id TEXT NOT NULL REFERENCES department_flows(id),node TEXT NOT NULL,
            action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    ''')
    columns={r['name'] for r in db.execute('PRAGMA table_info(department_jobs)')}
    if 'flow_id' not in columns:db.execute("ALTER TABLE department_jobs ADD COLUMN flow_id TEXT NOT NULL DEFAULT ''")
    index=db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='active_department_job'").fetchone()
    if index and 'flow_id' not in index['sql']:db.execute('DROP INDEX active_department_job')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_department_job ON department_jobs(project_id,flow_id,node) WHERE status IN ('queued','running')")


class DepartmentFlows:
    def __init__(self,store):self.store=store

    def _check(self,studio,project,department,action='view'):
        self.store.check_project(studio,project)
        if department not in ('product','design','development','testing','growth'):raise ValueError('部门不存在')
        Policy(self.store).require('department',action,studio=studio,project=project,department=department)

    def row(self,db,studio,project,flow,node=None,write=False):
        self.store.check_project(studio,project)
        row=db.execute('SELECT * FROM department_flows WHERE id=? AND project_id=?',(flow,project)).fetchone()
        if row is None:raise KeyError('流程不属于当前项目')
        value=dict(row)
        if node and node_definition(node,self.store,project)[0]['id']!=value['department']:raise ValueError('节点不属于当前流程部门')
        if write and value['archived']:raise ValueError('流程已归档，只能查看历史')
        return value

    def listing(self,studio,project,department):
        self._check(studio,project,department)
        with self.store.connection() as db:
            items=[dict(r) for r in db.execute('SELECT * FROM department_flows WHERE project_id=? AND department=? AND archived=0 ORDER BY rowid DESC',(project,department))]
        return {'items':items}

    def create(self,studio,project,value):
        if not isinstance(value,dict):raise ValueError('请求必须是对象')
        department=value.get('department');self._check(studio,project,department,'edit')
        policy=Policy(self.store)
        policy.require('node','create',studio=studio,project=project,department=department)
        name=value.get('name')
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:raise ValueError('流程名称须为1至120字')
        identity=uuid.uuid4().hex;task_id=value.get('task_id','')
        if department=='testing':
            policy.require('node','edit',studio=studio,project=project,node='testing:0')
            if task_id:self.store.task(project,task_id)
        elif task_id:raise ValueError('只有测试流程可以绑定测试批次')
        from server.studio_workspaces import Workspaces
        from server.core.project_nodes import project_records
        seeds=[]
        if department!='testing':
            for n in project_records(self.store,project):
                if n['id'].split(':')[0]==department and not n['archived']:
                    policy.require('node','view',studio=studio,project=project,node=n['id'])
                    seeds.append((n['id'],Workspaces(self.store).get(studio,project,n['id'])['skill']))
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from server.core.project_content import require_enabled
            require_enabled(db,project,department)
            if department=='testing' and not task_id:task_id=self.store.create_task(project,name.strip(),connection=db)['id']
            if task_id and db.execute('SELECT 1 FROM department_flows WHERE project_id=? AND task_id=?',(project,task_id)).fetchone():raise ValueError('此批次已绑定其他流程')
            db.execute('INSERT INTO department_flows(id,project_id,department,name,task_id,created_by) VALUES(?,?,?,?,?,?)',(identity,project,department,name.strip(),task_id,user_id()))
            for node,skill in seeds:db.execute('INSERT INTO flow_workspaces(flow_id,node,skill) VALUES(?,?,?)',(identity,node,json.dumps(skill,ensure_ascii=False)))
        return self.get(studio,project,identity)

    def get(self,studio,project,identity):
        with self.store.connection() as db:
            row=self.row(db,studio,project,identity)
            self._check(studio,project,row['department'])
            nodes=[dict(r) for r in db.execute('SELECT node,status,revision,updated_at,length(trim(deliverable))>0 AS has_deliverable FROM flow_workspaces WHERE flow_id=?',(identity,))]
        # Release the read cursor before Policy opens another connection. A queued
        # writer otherwise waits for this cursor while blocking that nested read.
        row['nodes']=[r for r in nodes if Policy(self.store).allowed('node','view',studio=studio,project=project,node=r['node'])]
        return row

    def archive(self,studio,project,identity):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=self.row(db,studio,project,identity,write=True)
            Policy(self.store).require('node','delete',studio=studio,project=project,department=row['department'])
            busy=db.execute("SELECT 1 FROM department_jobs WHERE flow_id=? AND status IN ('queued','running')",(identity,)).fetchone()
            busy=busy or db.execute("SELECT 1 FROM node_questions WHERE project_id=? AND scope=? AND status IN ('queued','running')",(project,'task:'+row['task_id'] if row['task_id'] else 'flow:'+identity)).fetchone()
            if row['task_id']:busy=busy or db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')",(row['task_id'],)).fetchone()
            if busy:raise ValueError('流程有在途任务，不能归档')
            db.execute('UPDATE department_flows SET archived=1 WHERE id=?',(identity,))
        return {'archived':True}


class FlowWorkspaces:
    def __init__(self,store):self.store=store;self.flows=DepartmentFlows(store)

    def _read(self,db,studio,project,node,flow,write=False):
        self.flows.row(db,studio,project,flow,node,write)
        if node in {f'testing:{i}' for i in range(6)}:
            raise ValueError('固定测试节点请使用流程绑定的测试批次工作区')
        Policy(self.store).require('node','view',studio=studio,project=project,node=node)
        row=db.execute('SELECT * FROM flow_workspaces WHERE flow_id=? AND node=?',(flow,node)).fetchone()
        if row is None:
            from server.studio_catalog import default_skill
            value={'flow_id':flow,'node':node,'inputs':'','deliverable':'','status':'not_started','revision':0,'updated_at':None,'skill':default_skill(node,self.store,project)}
        else:value=dict(row);value['skill']=json.loads(value['skill'])
        value.update(studio_id=studio,project_id=project)
        value['events']=[dict(r) for r in db.execute('SELECT action,detail,created_at FROM flow_events WHERE flow_id=? AND node=? ORDER BY id',(flow,node))]
        return value

    def get(self,studio,project,node,flow):
        with self.store.connection() as db:return self._read(db,studio,project,node,flow)

    def save(self,studio,project,node,value,flow,origin='manual'):
        if not isinstance(value,dict):raise ValueError('请求必须是对象')
        from server.node_skills import validate
        from server.core.project_nodes import project_records
        if any(n['id']==node and n['archived'] for n in project_records(self.store,project)):raise ValueError('节点已归档')
        policy=Policy(self.store)
        policy.require('node','edit',studio=studio,project=project,node=node)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from server.core.project_content import require_enabled
            require_enabled(db,project,node.split(':')[0])
            current=self._read(db,studio,project,node,flow,True)
            if type(value.get('revision')) is not int or value['revision']!=current['revision']:raise ValueError('节点已变化，请刷新后再保存')
            inputs=value.get('inputs',current['inputs']);deliverable=value.get('deliverable',current['deliverable']);skill=current['skill']
            if not all(isinstance(x,str) and len(x.encode())<=800000 for x in (inputs,deliverable)):raise ValueError('节点内容过大或格式错误')
            if 'skill' in value:
                policy.require('skill','import',studio=studio,project=project,node=node)
                raw=value['skill']
                if raw is None:
                    from server.studio_catalog import default_skill
                    skill=default_skill(node,self.store,project)
                else:
                    if isinstance(raw,str):raw={'content':raw}
                    if not isinstance(raw,dict):raise ValueError('Skill 格式错误')
                    content=validate(raw.get('content'))
                    skill={'name':str(raw.get('name') or '流程 Skill')[:200],'content':content,'source_kind':'imported','sha256':hashlib.sha256(content.encode()).hexdigest(),'uploader_id':user_id()}
            db.execute('''INSERT INTO flow_workspaces(flow_id,node,inputs,skill,deliverable,status,revision) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(flow_id,node) DO UPDATE SET inputs=excluded.inputs,skill=excluded.skill,deliverable=excluded.deliverable,
                status=excluded.status,revision=excluded.revision,updated_at=CURRENT_TIMESTAMP''',(flow,node,inputs,json.dumps(skill,ensure_ascii=False),deliverable,'waiting_user' if deliverable.strip() else 'draft',current['revision']+1))
            db.execute('INSERT INTO flow_events(flow_id,node,action,detail) VALUES(?,?,?,?)',(flow,node,'workspace_saved','保存流程节点'+(' Skill' if 'skill' in value else '输入与交付')))
            if origin=='manual' and 'deliverable' in value and deliverable.strip() and deliverable!=current['deliverable']:
                from server.core.notifications import enqueue
                enqueue(self.store,db,project,node,'flow-manual:'+flow+':'+node+':'+str(current['revision']+1),'manual',{'deliverable':deliverable},origin='manual',flow_id=flow)
        return self.get(studio,project,node,flow)

    def decide(self,studio,project,node,value,flow):
        if not isinstance(value,dict):raise ValueError('请求必须是对象')
        from server.core.project_nodes import project_records
        if any(n['id']==node and n['archived'] for n in project_records(self.store,project)):raise ValueError('节点已归档')
        Policy(self.store).require('node','approve',studio=studio,project=project,node=node)
        reason=value.get('reason');action=value.get('action')
        if action not in ('approve','reject') or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000:raise ValueError('请填写有效审批动作及理由')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            from server.core.project_content import require_enabled
            require_enabled(db,project,node.split(':')[0])
            current=self._read(db,studio,project,node,flow,True)
            if type(value.get('revision')) is not int or value['revision']!=current['revision']:raise ValueError('节点已变化，请刷新')
            if not current['deliverable'].strip() or current['status'] not in ('waiting_user','rejected'):raise ValueError('没有可审核交付')
            db.execute('UPDATE flow_workspaces SET status=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE flow_id=? AND node=?',('approved' if action=='approve' else 'rejected',flow,node))
            db.execute('INSERT INTO flow_events(flow_id,node,action,detail) VALUES(?,?,?,?)',(flow,node,'human_decision',('确认交付：' if action=='approve' else '退回：')+reason.strip()))
            if action=='approve':
                from server.core.notifications import enqueue
                enqueue(self.store,db,project,node,'flow-approval:'+flow+':'+node+':'+str(current['revision']+1),'approved',flow_id=flow)
        # Flow approval never dispatches the legacy project's continuation graph.
        return self.get(studio,project,node,flow)
