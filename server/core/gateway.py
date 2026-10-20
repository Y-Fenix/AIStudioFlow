"""Single authorization boundary for both the team shell and legacy testing APIs."""
from urllib.parse import parse_qs
from server.core.identity import user_id
from server.core.permissions import Policy, AccessDenied

# Unknown legacy actions are denied, so new department code cannot bypass policy by accident.
TEST_OPERATIONS = {
 'execution-mapping':(1,'edit'),'case-review':(0,'approve'),'edit-case':(0,'edit'),
 'execution-binding':(1,'edit'),'execute-logic':(1,'execute'),'editor-preflight':(1,'view'),
 'generation-jobs':(0,'execute'),'generate':(0,'execute'),'requirements':(0,'import'),
 'feishu-requirements':(0,'import'),'file-requirements':(0,'import'),
 'referenced-requirements':(0,'import'),'attachment-requirement':(0,'import'),'archive-requirement':(0,'edit'),
 'attribution-suggestions':(2,'execute'),'triage':(2,'edit'),'filter':(3,'approve'),
 'bug-target':(4,'edit'),'confirm-existing-bugs':(4,'edit'),'bug-status':(4,'view'),
 'reconcile-bug-publication':(4,'execute'),'publish-bug':(4,'execute'),
 'prepare-bug-publication':(4,'edit'),'bug-preview':(4,'view'),'bug-drafts':(4,'execute'),
 'bug-export':(4,'export'),'publication-ledger':(4,'view'),
 'check-pending-regression':(5,'execute'),'regression-review':(5,'approve'),
 'regress-logic':(5,'execute'),'prepare-status-change':(5,'approve'),
 'confirm-status-change':(5,'approve'),'reconcile-status-change':(5,'view')}


class Gateway:
    def __init__(self,store):self.store=store;self.policy=Policy(store)

    def authorize(self, parts, query, body, write):
        p=self.policy;q=parse_qs(query);scope={}
        with self.store.connection() as db:
            actor=db.execute('SELECT status FROM users WHERE id=?',(user_id(),)).fetchone()
        if not actor or actor['status']!='active':raise AccessDenied('账号待负责人审批，或已被禁用')
        if parts==['api','studio-catalog'] or parts==['api','me','preferences']:return scope
        if parts[:2]==['api','ai-models']:
            p.require('model','edit' if write else 'view');return scope
        if parts[:2]==['api','gm'] or parts[:2]==['api','gagasort']:
            p.require('platform','manage');return scope
        if parts==['api','studios']:
            if write:p.require('studio','create')
            return scope
        if parts[:2]==['api','studios'] and len(parts)>=3:
            studio=parts[2];scope['studio']=studio
            # Membership and container identity check before any external work.
            if not any(s['id']==studio for s in self.store.studios()):raise KeyError('工作室不存在')
            if len(parts)==4 and parts[3]=='enter':return scope
            if len(parts)==4 and parts[3]=='projects':
                if write:p.require('project','create',studio=studio)
                return scope
            if len(parts)>=5 and parts[3]=='projects':
                scope['project']=parts[4];self.store.check_project(studio,parts[4])
                return self.project_route(parts[5:],scope,q,body,write)
        if parts==['api','projects']:
            studio=self.store.preferences()['active_studio_id'];scope['studio']=studio
            if write:p.require('project','create',studio=studio)
            return scope
        if len(parts)>=4 and parts[:2]==['api','projects']:
            studio=self.store.preferences()['active_studio_id'];scope={'studio':studio,'project':parts[2]}
            self.store.check_project(studio,parts[2]);return self.project_route(parts[3:],scope,q,body,write)
        raise KeyError('接口不存在')

    def project_route(self, tail, scope, query, body, write):
        p=self.policy;studio=scope['studio'];project=scope['project'];nodes=p.visible_nodes(studio,project)
        if not nodes and not p.allowed('project','view',studio,project):raise AccessDenied('无权访问此项目')
        if not tail or tail[0] in ('enter','summary'):return scope
        if tail[0] in ('read-sources','parse-file'):
            node=body.get('node')
            if not node:
                # Old shell requests can only use this endpoint with project-wide edit rights.
                p.require('project','edit',**scope)
            else:p.require('node','import',node=node,**scope)
            if write:p.require('content','create',department=node.split(':')[0] if node else '',**scope)
            return scope
        if tail[0]=='workspace':
            node=query.get('node',[''])[0];p.require('node','view',node=node,**scope)
            if len(tail)>1 and tail[1]=='skill-export':p.require('skill','export',node=node,**scope)
            if write:
                if len(tail)>1 and tail[1]=='decision':p.require('node','approve',node=node,**scope)
                else:
                    if 'inputs' in body or 'deliverable' in body or 'skill' not in body:p.require('node','edit',node=node,**scope)
                    if 'skill' in body:p.require('skill','import',node=node,**scope)
            scope['node']=node;return scope
        if tail[0]!='tasks':raise AccessDenied('未知项目接口')
        testing=[n for n in nodes if n.startswith('testing:')]
        if not testing:raise AccessDenied('无测试部门访问权限')
        scope['testing']=True
        if len(tail)==1:
            if write:p.require('node','edit',node='testing:0',**{k:v for k,v in scope.items() if k in ('studio','project')})
            return scope
        # Loading a complete task is filtered in the response; internal execution retains its full evidence.
        task=self.store.task(project,tail[1]);scope['task_stage']=task['stage']
        basic={'studio':studio,'project':project}
        if len(tail)==2:return scope
        op=tail[2]
        if op=='codex-handoff':
            stage=int(query.get('stage',['-1'])[0]);node=f'testing:{stage}'
            p.require('node','view',node=node,**basic);p.require('skill','export',node=node,**basic)
            return scope
        if op=='node-skill':
            stage=int(query.get('stage',['0'])[0]);p.require('node','view',node=f'testing:{stage}',**basic);p.require('skill','import' if write else 'export',node=f'testing:{stage}',**basic);return scope
        if op=='reset-node':
            stage=body.get('stage')
            if type(stage) is not int or not 0<=stage<=5:raise ValueError('节点无效')
            for i in range(stage,6):p.require('node','edit',node=f'testing:{i}',**basic)
            return scope
        if op=='operation-jobs':
            stage={'generate':0,'execute':1,'attribution':2,'regression':5}.get(body.get('kind'))
            if stage is None:raise ValueError('操作类型无效')
            action='execute'
        elif op=='decisions':stage=task['stage'];action='approve'
        elif op in TEST_OPERATIONS:stage,action=TEST_OPERATIONS[op]
        else:raise AccessDenied('未知测试操作，尚未配置权限')
        p.require('node','view',node=f'testing:{stage}',**basic)
        p.require('node',action,node=f'testing:{stage}',**basic)
        if write and op in ('requirements','feishu-requirements','file-requirements','referenced-requirements','attachment-requirement','archive-requirement'):
            permission='delete' if op=='archive-requirement' and body.get('archived') is True else 'create'
            p.require('content',permission,department='testing',**basic)
        if stage in (1,5) and action in ('edit','execute') and op in ('execution-binding','execute-logic','regress-logic','operation-jobs') and not p.allowed('platform','manage'):
            from pathlib import Path
            with self.store.connection() as db:
                connection=db.execute('SELECT repository FROM project_connections WHERE project_id=?',(project,)).fetchone()
            requested=body.get('path') if op=='execution-binding' else task.get('binding',{}).get('repository')
            if not connection or not connection['repository'] or not requested or Path(requested).expanduser().resolve()!=Path(connection['repository']).resolve():
                raise AccessDenied('代码目录必须由负责人在项目接入设置中登记，成员不能访问其他服务器目录')
        return scope

    def filter_response(self,value,scope):
        if not scope.get('project') or not isinstance(value,dict):return value
        studio,project=scope['studio'],scope['project'];p=self.policy;visible=set(p.visible_nodes(studio,project));testing={int(n.split(':')[1]) for n in visible if n.startswith('testing:') and n.split(':')[1].isdigit()}
        for key in ('result','workspace'):
            if isinstance(value.get(key),dict):
                value={**value,key:self.filter_response(value[key],scope)}
        if 'nodes' in value and 'tasks' in value:
            value={**value,'nodes':[n for n in value['nodes'] if n['node'] in visible], 'tasks':value['tasks'] if testing else []}
        if 'task' in value and isinstance(value['task'],dict):value={**value,'task':self.filter_response(value['task'],scope)}
        if 'artifacts' in value and 'node_skills' in value:
            value={**value,'artifacts':{k:v for k,v in value['artifacts'].items() if int(k) in testing},
                   'node_skills':{k:v for k,v in value['node_skills'].items() if int(k) in testing and p.allowed('skill','view',studio,project,node=f'testing:{k}')},
                   'events':[e for e in value['events'] if e.get('stage') in testing]}
            for key,stage in (('attribution',2),('bug_target',4),('regression',5),('status_changes',5)):
                if stage not in testing:value[key]=[] if key=='status_changes' else {}
            value['reset_history']=[]
            value['jobs']=[j for j in value.get('jobs',[]) if j['stage'] in testing]
            if 0 not in testing:value['requirements']=[];value['archived_requirements']=[];value['case_review_items']=[]
            if 4 not in testing:value.pop('publication_ledger',None)
        if 'skill' in value and 'node' in value and not p.allowed('skill','view',studio,project,node=value['node']):
            value={**value,'skill':{'name':'无 Skill 查看权限','content':'','source_kind':'restricted','sha256':''}}
        return value
