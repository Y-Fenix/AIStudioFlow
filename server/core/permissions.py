"""Explicit resource grants and denials; home-page role never grants access."""
from server.core.identity import user_id
from server.studio_catalog import DEPARTMENTS, node_definition

ACTIONS = ('view','edit','execute','approve','create','delete','import','export','manage','reorder')
# Connector permissions are exact-match only. In particular, a node grant never
# implicitly authorizes access to a server-side external system.
RESOURCES = ('platform','studio','project','department','node','skill','model','permission','gm','content')
DEPARTMENT_IDS = tuple(d['id'] for d in DEPARTMENTS)


class AccessDenied(PermissionError):
    pass


class Policy:
    def __init__(self, store): self.store = store

    def allowed(self, resource, action, studio='', project='', department='', node='', actor=None):
        actor = user_id(actor)
        if resource not in RESOURCES or action not in ACTIONS: return False
        if node:
            try: definition = node_definition(node,self.store,project)
            except ValueError: return False
            if department and department != definition[0]['id']: return False
            department = definition[0]['id']
        with self.store.connection() as db:
            user = db.execute('SELECT * FROM users WHERE id=?', (actor,)).fetchone()
            if not user or user['status'] != 'active': return False
            if user['global_role'] == 'project_lead': return True
            if resource=='model' and action=='view': return True
            if studio:
                row = db.execute('SELECT archived FROM studios WHERE id=?',(studio,)).fetchone()
                if not row or row['archived']: return False
                if not db.execute('SELECT 1 FROM studio_memberships WHERE studio_id=? AND user_id=?',(studio,actor)).fetchone(): return False
            if project:
                p = db.execute('SELECT studio_id,archived FROM projects WHERE id=?',(project,)).fetchone()
                if not p or p['archived'] or p['studio_id'] != studio: return False
            memberships = [dict(r) for r in db.execute('SELECT * FROM team_members WHERE user_id=? AND studio_id=? AND project_id IN (?,?)',(actor,studio,'',project))]
            rules = db.execute('SELECT * FROM permission_rules WHERE studio_id IN (?,?) AND project_id IN (?,?) AND department IN (?,?) AND node IN (?,?)',('',studio,'',project,'',department,'',node)).fetchall()
            allowed = False
            for rule in rules:
                matches = rule['subject_type']=='user' and rule['subject_id']==actor or rule['subject_type']=='department' and any(m['department']==rule['subject_id'] for m in memberships)
                if not matches: continue
                # Scope coordinates can target a whole studio/project/department, but
                # resource types stay exact so node access never silently grants Skill.
                if rule['resource']==resource and rule['action']==action:
                    if rule['effect']=='deny': return False
                    allowed=True
            if allowed: return True
            if resource=='content':
                if action=='view':return any(m['department']==department for m in memberships)
                if action not in ('create','delete'):return False
                return bool(db.execute("SELECT 1 FROM studio_memberships WHERE studio_id=? AND user_id=? AND role='studio_owner'",(studio,actor)).fetchone()
                            or any(m['role']=='project_lead' and m['project_id'] in ('',project) for m in memberships))
            if resource=='node' and action in ('create','delete','reorder'): return False
            scope_owner = db.execute("SELECT 1 FROM studio_memberships WHERE studio_id=? AND user_id=? AND role='studio_owner'",(studio,actor)).fetchone()
            if scope_owner:
                # Ownership controls membership and scoped configuration, but entity lifecycle
                # stays with the platform lead unless an explicit rule delegates it.
                if resource in ('studio','project') and action in ('create','delete'): return False
                return resource not in ('platform','model','gm')
            if any(m['role']=='project_lead' and m['project_id'] in ('',project) for m in memberships):
                if resource=='project' and action=='create':
                    return any(m['role']=='project_lead' and m['project_id']=='' for m in memberships)
                if resource=='project' and action=='delete':
                    return any(m['role']=='project_lead' and m['project_id']==project for m in memberships)
                return resource in ('studio','project','department','node','skill','permission') and not (resource=='studio' and action in ('create','delete'))
            own = [m for m in memberships if m['department']==department]
            if resource in ('department','node') and own:
                return action in ('view','edit','execute','import','export') or action=='approve' and any(m['role']=='lead' for m in own)
            if resource=='skill' and own:
                return action in ('view','export') or action in ('edit','import') and any(m['role']=='lead' for m in own)
            # Container visibility must not grant child contents.
            if resource in ('studio','project') and action=='view':
                return any(m['project_id'] in ('',project) for m in memberships)
        return False

    def require(self, resource, action, **scope):
        if not self.allowed(resource,action,**scope):
            raise AccessDenied('无此资源的'+action+'权限；请联系负责人授权')

    def can_manage_scope(self, studio, project='', actor=None):
        """Permission managers may delegate only inside their studio/project boundary."""
        actor=user_id(actor)
        if self.allowed('platform','manage',actor=actor):return True
        if not studio:return False
        with self.store.connection() as db:
            owner=db.execute("SELECT 1 FROM studio_memberships WHERE studio_id=? AND user_id=? AND role='studio_owner'",(studio,actor)).fetchone()
            if owner:return True
            memberships=db.execute("SELECT project_id,role FROM team_members WHERE user_id=? AND studio_id=?",(actor,studio)).fetchall()
        return bool(project and any(m['role']=='project_lead' and m['project_id'] in ('',project) for m in memberships))

    def visible_nodes(self, studio, project):
        from server.core.project_nodes import project_records
        return [n['id'] for n in project_records(self.store,project)
                if self.allowed('node','view',studio,project,node=n['id'])]

    def capabilities(self, studio='', project=''):
        from server.core.project_nodes import project_records
        keys=[n['id'] for n in project_records(self.store,project)] if project else [f'{d["id"]}:{i}' for d in DEPARTMENTS for i in range(len(d['nodes']))]
        return {'studio_create':self.allowed('studio','create'),
                'studio_delete':self.allowed('studio','delete',studio),
                'project_create':self.allowed('project','create',studio),
                'project_delete':self.allowed('project','delete',studio,project),
                'permission_manage':self.allowed('permission','manage',studio,project),
                'model_edit':self.allowed('model','edit'),
                'content':{d['id']:{a:self.allowed('content',a,studio,project,d['id']) for a in ('create','delete')} for d in DEPARTMENTS},
                'node_management':{d['id']:{a:self.allowed('node',a,studio,project,d['id']) for a in ('create','delete','reorder')} for d in DEPARTMENTS},
                'nodes':{key:{action:self.allowed('node',action,studio,project,node=key) for action in ('view','edit','execute','approve','import','export','delete')} |
                         {'skill_'+action:self.allowed('skill',action,studio,project,node=key) for action in ('view','edit','import','export')}
                         for key in keys}}
