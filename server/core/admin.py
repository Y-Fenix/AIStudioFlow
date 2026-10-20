"""Team administration: explicit memberships, scoped grants, revocation, soft deletion."""
import json
import uuid
from server.core.identity import user_id
from server.core.permissions import Policy, ACTIONS, RESOURCES, DEPARTMENT_IDS
from server.studio_catalog import node_definition


class Administration:
    def __init__(self, store): self.store=store; self.policy=Policy(store)

    def audit(self, db, studio, action, value):
        db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',
                   (user_id(),studio,action,json.dumps(value,ensure_ascii=False)))

    def overview(self, studio='', project=''):
        self.policy.require('permission','manage',studio=studio,project=project)
        with self.store.connection() as db:
            owner=self.policy.allowed('platform','manage')
            if owner:
                users=db.execute('SELECT id,name,tenant_key,status,global_role,created_at FROM users').fetchall()
            elif project:
                users=db.execute('''SELECT id,name,tenant_key,status,global_role,created_at FROM users
                    WHERE id IN (SELECT user_id FROM team_members WHERE studio_id=? AND project_id IN ('',?))''',
                                 (studio,project)).fetchall()
            else:
                users=db.execute('''SELECT id,name,tenant_key,status,global_role,created_at FROM users
                    WHERE id IN (SELECT user_id FROM studio_memberships WHERE studio_id=?)''',(studio,)).fetchall()
            audit_rows=[dict(r) for r in db.execute('SELECT * FROM team_audit'+('' if owner else ' WHERE studio_id=?')+' ORDER BY id DESC LIMIT 100',() if owner else (studio,))]
            if project and not owner:
                audit_rows=[r for r in audit_rows if (json.loads(r['detail']).get('project_id') in ('',project))]
            user_rows=[dict(r) for r in users]
            credentials={r['user_id']:r['username'] for r in db.execute('SELECT user_id,username FROM local_credentials')}
            for row in user_rows:row['username']=credentials.get(row['id'])
            return {'users':user_rows,
                    'projects':[dict(r) for r in db.execute('SELECT id,name FROM projects WHERE studio_id=? AND archived=0'+(' AND id=?' if project and not owner else ''),(studio,project) if project and not owner else (studio,))],
                    'members':[dict(r) for r in db.execute('SELECT * FROM team_members WHERE studio_id=?'+(' AND project_id IN (?,?)' if project and not owner else ''),(studio,'',project) if project and not owner else (studio,))],
                    'rules':[dict(r) for r in db.execute('SELECT * FROM permission_rules WHERE studio_id IN (?,?)',('',studio))]
                            if owner else [dict(r) for r in db.execute('SELECT * FROM permission_rules WHERE studio_id=?'+(' AND project_id IN (?,?)' if project and not owner else ''),(studio,'',project) if project and not owner else (studio,))],
                    'audit':audit_rows,
                    'global_admin':owner,'actions':ACTIONS,'resources':RESOURCES}

    def member(self, value):
        studio=value.get('studio_id',''); project=value.get('project_id',''); dept=value.get('department',''); target=value.get('user_id');role=value.get('role','member')
        self.policy.require('permission','manage',studio=studio,project=project)
        if dept not in DEPARTMENT_IDS or role not in ('member','lead','project_lead'): raise ValueError('部门或成员角色无效')
        if not studio: raise ValueError('请选择工作室')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self.policy.require('permission','manage',studio=studio,project=project)
            target_user=db.execute('SELECT status FROM users WHERE id=?',(target,)).fetchone()
            if not target_user: raise ValueError('用户尚未注册账号')
            if target_user['status']=='pending' and not self.policy.allowed('platform','manage'):
                raise PermissionError('新登记账号须由平台负责人首次审批并分配工作室')
            if not db.execute('SELECT 1 FROM studios WHERE id=? AND archived=0',(studio,)).fetchone(): raise ValueError('工作室无效')
            if project and not db.execute('SELECT 1 FROM projects WHERE id=? AND studio_id=? AND archived=0',(project,studio)).fetchone(): raise ValueError('项目不属于此工作室')
            if role=='project_lead' and not self.policy.allowed('platform','manage'): raise PermissionError('只有平台负责人能任命项目负责人')
            if value.get('remove') is True:
                db.execute('DELETE FROM team_members WHERE user_id=? AND studio_id=? AND project_id=? AND department=?',(target,studio,project,dept))
                self.audit(db,studio,'member_removed',{'user_id':target,'project_id':project,'department':dept})
            else:
                if target_user['status']=='disabled':
                    raise ValueError('账号已禁用；请由平台负责人通过账号状态入口明确启用后再分配部门')
                first_approval=target_user['status']=='pending'
                db.execute("UPDATE users SET status='active' WHERE id=?",(target,))
                db.execute('INSERT OR IGNORE INTO studio_memberships VALUES(?,?,?)',(studio,target,'member'))
                # Project leaders receive only their assigned scope, never a global role.
                db.execute('''INSERT INTO team_members VALUES(?,?,?,?,?) ON CONFLICT(user_id,studio_id,project_id,department)
                              DO UPDATE SET role=excluded.role''',(target,studio,project,dept,role))
                home=dept; viewrole='qa' if dept=='testing' else dept
                db.execute('''INSERT INTO user_preferences(user_id,active_studio_id,active_role,default_workspace)
                    VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                    active_studio_id=COALESCE(user_preferences.active_studio_id,excluded.active_studio_id),
                    active_role=CASE WHEN ? THEN excluded.active_role ELSE user_preferences.active_role END,
                    default_workspace=CASE WHEN ? THEN excluded.default_workspace ELSE user_preferences.default_workspace END''',
                           (target,studio,viewrole,home,int(first_approval),int(first_approval)))
                self.audit(db,studio,'member_assigned',{'user_id':target,'project_id':project,'department':dept,'role':role})
        return {'ok':True}

    def rule(self, value):
        studio=value.get('studio_id','');project=value.get('project_id','');department=value.get('department','');node=value.get('node','')
        resource=value.get('resource');action=value.get('action');effect=value.get('effect');subject_type=value.get('subject_type');subject=value.get('subject_id')
        self.policy.require('permission','manage',studio=studio,project=project)
        if not studio and not self.policy.allowed('platform','manage'): raise PermissionError('需要平台管理权限')
        if resource not in RESOURCES or action not in ACTIONS or effect not in ('allow','deny') or subject_type not in ('user','department'): raise ValueError('授权规则无效')
        if department and department not in DEPARTMENT_IDS: raise ValueError('部门无效')
        if node:
            d,_,_=node_definition(node,self.store,project)
            if department!=d['id'] or not project: raise ValueError('节点授权需要明确项目与对应部门')
        if resource=='node' and action in ('create','reorder') and (not department or node):
            raise ValueError('节点新增与排序需限定部门范围，不能限定单个节点')
        if resource=='node' and action=='delete' and not department:
            raise ValueError('节点删除需限定部门范围')
        if resource=='gm' and (action!='execute' or not node):
            raise ValueError('GM MCP 仅可授权到明确项目、部门和节点的只读执行权限')
        if project and not studio: raise ValueError('项目范围需要明确工作室')
        if resource=='model' and (studio or project or department or node):raise ValueError('服务器模型配置必须使用全平台范围')
        if subject_type=='department' and subject not in DEPARTMENT_IDS: raise ValueError('授权部门无效')
        if subject_type=='department' and not studio: raise ValueError('部门授权必须限定工作室')
        # Delegation is bounded by the manager's own organization/project scope. A studio
        # owner can delegate project lifecycle actions without being able to perform them.
        if not self.policy.can_manage_scope(studio,project):raise PermissionError('不能在当前工作室/项目范围之外管理授权')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if subject_type=='user' and not db.execute('SELECT 1 FROM users WHERE id=?',(subject,)).fetchone(): raise ValueError('授权用户不存在')
            if studio and not db.execute('SELECT 1 FROM studios WHERE id=? AND archived=0',(studio,)).fetchone(): raise ValueError('工作室不存在')
            if project and not db.execute('SELECT 1 FROM projects WHERE id=? AND studio_id=? AND archived=0',(project,studio)).fetchone(): raise ValueError('项目范围无效')
            if subject_type=='user' and studio:
                if not db.execute('SELECT 1 FROM studio_memberships WHERE user_id=? AND studio_id=?',(subject,studio)).fetchone(): raise ValueError('请先将用户加入此工作室')
            key=uuid.uuid4().hex
            db.execute('INSERT INTO permission_rules VALUES(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                       (key,subject_type,subject,studio,project,department,node,resource,action,effect,user_id()))
            self.audit(db,studio,'permission_added',{'rule_id':key,**{k:value.get(k) for k in ('subject_type','subject_id','project_id','department','node','resource','action','effect')}})
        return {'id':key}

    def revoke(self, key):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rule=db.execute('SELECT * FROM permission_rules WHERE id=?',(key,)).fetchone()
            if not rule: raise KeyError('授权不存在')
            self.policy.require('permission','manage',studio=rule['studio_id'],project=rule['project_id'])
            db.execute('DELETE FROM permission_rules WHERE id=?',(key,))
            self.audit(db,rule['studio_id'],'permission_revoked',{'rule_id':key})
        return {'ok':True}

    def user_status(self,value):
        self.policy.require('platform','manage')
        target=value.get('user_id');status=value.get('status')
        if status not in ('active','disabled','pending'):raise ValueError('用户状态无效')
        with self.store.connection() as db:
            user=db.execute('SELECT * FROM users WHERE id=?',(target,)).fetchone()
            if not user:raise KeyError('用户不存在')
            if user['global_role']=='project_lead':raise ValueError('不能通过此入口禁用平台负责人')
            db.execute('UPDATE users SET status=? WHERE id=?',(status,target))
            db.execute('DELETE FROM auth_sessions WHERE user_id=?',(target,))
            self.audit(db,'','user_status_changed',{'user_id':target,'status':status})
        return {'ok':True}

    def archive(self,studio,project,confirmed,name):
        self.policy.require('project' if project else 'studio','delete',studio=studio,project=project)
        if confirmed is not True:raise ValueError('需要明确确认归档')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            table='projects' if project else 'studios';key=project or studio
            row=db.execute('SELECT name,archived FROM '+table+' WHERE id=?',(key,)).fetchone()
            if not row or row['archived']:raise KeyError('资源不存在')
            if row['name']!=name:raise ValueError('请输入完整名称确认')
            scope_projects=[r[0] for r in db.execute('SELECT id FROM projects WHERE studio_id=?',(studio,))] if not project else [project]
            if any(db.execute("SELECT 1 FROM "+job_table+" WHERE project_id=? AND status IN ('queued','running')",(p,)).fetchone()
                   for p in scope_projects for job_table in ('jobs','department_jobs')):
                raise ValueError('存在运行中任务，请先取消或等待完成')
            db.execute('UPDATE '+table+' SET archived=1 WHERE id=?',(key,))
            if not project:db.execute('UPDATE projects SET archived=1 WHERE studio_id=?',(studio,))
            db.execute('UPDATE studio_visits SET project_id=NULL WHERE studio_id=?'+(' AND project_id=?' if project else ''),(studio,project) if project else (studio,))
            if not project:db.execute('UPDATE user_preferences SET active_studio_id=NULL WHERE active_studio_id=?',(studio,))
            self.audit(db,studio,'project_archived' if project else 'studio_archived',{'id':key,'name':name})
        return {'ok':True,'archived':True}

    def project_connection(self, studio, project, value=None):
        from pathlib import Path
        self.store.check_project(studio,project)
        self.policy.require('project','manage',studio=studio,project=project)
        with self.store.connection() as db:
            if value is not None:
                raw=value.get('repository','')
                if not isinstance(raw,str) or len(raw)>2000:raise ValueError('源码路径无效')
                repository=Path(raw).expanduser().resolve() if raw else None
                if repository and not repository.is_dir():raise ValueError('源码目录不存在于服务器')
                db.execute('INSERT INTO project_connections(project_id,repository,updated_by) VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET repository=excluded.repository,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP',
                           (project,str(repository) if repository else '',user_id()))
                self.audit(db,studio,'project_connection_saved',{'project_id':project,'repository':str(repository) if repository else ''})
            row=db.execute('SELECT * FROM project_connections WHERE project_id=?',(project,)).fetchone()
            return dict(row) if row else {'project_id':project,'repository':''}
