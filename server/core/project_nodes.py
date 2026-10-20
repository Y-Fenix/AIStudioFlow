"""Project-owned node ordering and archives; identities never follow array positions."""
import copy
import hashlib
import json
import uuid
from server.studio_catalog import DEPARTMENTS
from server.core.identity import user_id


def template_nodes(department):
    definition = next((d for d in DEPARTMENTS if d['id'] == department), None)
    if definition is None:
        raise ValueError('部门无效')
    return [{'id':f'{department}:{i}', 'definition':copy.deepcopy(n), 'archived':False}
            for i,n in enumerate(definition['nodes'])]


def read_config(db, project, department):
    defaults = template_nodes(department)
    row = db.execute('SELECT revision,nodes FROM project_node_configs WHERE project_id=? AND department=?',
                     (project,department)).fetchone()
    return (row['revision'],json.loads(row['nodes'])) if row else (0,defaults)


def project_records(store, project, department=None):
    with store.connection() as db:
        return [n for d in DEPARTMENTS if department is None or d['id']==department
                for n in read_config(db,project,d['id'])[1]]


def custom_skill(key, definition):
    name = 'studioflow-' + key.replace(':','-')
    text = (f'---\nname: {name}\ndescription: {definition[1]}\n---\n\n# {definition[0]}\n\n'
            f'## 目标\n{definition[3]}\n\n## 输入\n{definition[5]}\n\n'
            '## 工作方式\n默认人工整理。只使用已核实的资料，记录来源、版本和证据；缺少条件时列出缺口，不编造结论。\n\n'
            f'## 交付与审核\n{definition[6]}\n{definition[4]}\n\n'
            '## 边界\nSkill 不授予工具或资源权限。不擅自修改源码、Git、Figma 或外部记录；未接通执行器时不得报告自动执行成功。\n')
    return {'name':name,'content':text,'source_kind':'bundled','sha256':hashlib.sha256(text.encode()).hexdigest()}


class ProjectNodes:
    def __init__(self,store): self.store=store

    def get(self,studio,project,department):
        from server.core.permissions import Policy
        self.store.check_project(studio,project)
        p=Policy(self.store)
        if not (p.allowed('project','view',studio,project) or p.allowed('department','view',studio,project,department)
                or any(p.allowed('node',a,studio,project,department) for a in ('create','delete','reorder'))
                or any(p.allowed('node',a,studio,project,node=n['id']) for n in project_records(self.store,project,department) for a in ('view','delete'))):
            raise PermissionError('无此部门节点查看权限')
        with self.store.connection() as db:
            revision,items=read_config(db,project,department)
        return {'revision':revision,'nodes':[n for n in items if not n['archived']],
                'archived':[n for n in items if n['archived']]}

    def catalog(self,studio,project):
        from server.core.permissions import Policy
        self.store.check_project(studio,project)
        p=Policy(self.store)
        if not p.allowed('project','view',studio,project) and not p.visible_nodes(studio,project):
            raise PermissionError('无此项目查看权限')
        departments=copy.deepcopy(DEPARTMENTS)
        for d in departments:
            items=project_records(self.store,project,d['id'])
            active=[n for n in items if not n['archived']]
            d['nodes']=[n['definition'] for n in active]
            d['node_keys']=[n['id'] for n in active]
            # Definitions are navigation metadata, not workspace contents or Skill.
            d['archived_nodes']=[{'id':n['id'],'definition':n['definition']} for n in items if n['archived']]
        from server.core.project_content import apply_content
        return {'departments':apply_content(self.store,studio,project,departments)}

    def save(self,studio,project,department,value):
        from server.core.permissions import Policy
        self.store.check_project(studio,project)
        template_nodes(department)
        if not isinstance(value,dict) or type(value.get('revision')) is not int or not isinstance(value.get('nodes'),list):
            raise ValueError('节点配置格式无效')
        incoming=value['nodes']
        if len(incoming)>100: raise ValueError('每个部门最多100个节点')
        p=Policy(self.store)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            revision,old=read_config(db,project,department)
            if revision!=value['revision']: raise ValueError('节点配置版本已变化，请重新加载')
            active={n['id']:n for n in old if not n['archived']}
            archived={n['id']:n for n in old if n['archived']}
            seen=set();items=[];created=[]
            for row in incoming:
                if not isinstance(row,dict): raise ValueError('节点格式无效')
                key=row.get('id')
                if key:
                    if isinstance(key,str) and key in archived and row.get('restore') is True and key not in seen:
                        p.require('node','create',studio=studio,project=project,department=department)
                        if row.get('definition')!=archived[key]['definition']: raise ValueError('恢复时不能修改原节点定义')
                        seen.add(key);items.append({**archived[key],'archived':False});created.append(key)
                        continue
                    if not isinstance(key,str) or key not in active or key in seen: raise ValueError('节点ID重复或不属于当前项目部门')
                    seen.add(key)
                    if row.get('definition')!=active[key]['definition']: raise ValueError('此入口不能修改已有节点定义')
                    items.append(active[key])
                else:
                    p.require('node','create',studio=studio,project=project,department=department)
                    definition=row.get('definition')
                    if not isinstance(definition,list) or len(definition)!=7 or any(not isinstance(s,str) or not 1<=len(s.strip())<=2000 for s in definition):
                        raise ValueError('请完整填写节点名称、用途、交付和验收条件，每项最多2000字')
                    if len(definition[0].strip())>60: raise ValueError('节点名称最多60字')
                    key=department+':custom-'+uuid.uuid4().hex
                    items.append({'id':key,'definition':[s.strip() for s in definition],'archived':False});created.append(key)
            removed=set(active)-seen
            for key in removed:
                p.require('node','delete',studio=studio,project=project,department=department,node=key)
                busy=db.execute("SELECT 1 FROM department_jobs WHERE project_id=? AND node=? AND status IN ('queued','running')",(project,key)).fetchone()
                if department=='testing':
                    busy=busy or db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",(project,)).fetchone()
                if busy: raise ValueError('节点存在排队或运行中任务，暂不能删除')
            old_order=[n['id'] for n in old if n['id'] in seen and not n['archived']]
            new_order=[n['id'] for n in items if n['id'] in seen and n['id'] in active]
            if old_order!=new_order:
                p.require('node','reorder',studio=studio,project=project,department=department)
            if not created and not removed and old_order==new_order:
                # A no-op still requires a management grant; it cannot become a write bypass.
                if not any(p.allowed('node',a,studio,project,department) for a in ('create','delete','reorder')):
                    raise PermissionError('无节点管理权限')
            history=[{**n,'archived':True} for n in old if n['id'] not in seen and (n['archived'] or n['id'] in removed)]
            db.execute('''INSERT INTO project_node_configs VALUES(?,?,?,?) ON CONFLICT(project_id,department)
                DO UPDATE SET revision=excluded.revision,nodes=excluded.nodes''',
                (project,department,revision+1,json.dumps(items+history,ensure_ascii=False)))
            db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',
                (user_id(),studio,'project_nodes_changed',json.dumps({'project_id':project,'department':department,
                 'from_revision':revision,'to_revision':revision+1,'created':created,'archived':sorted(removed),'order':[n['id'] for n in items]},ensure_ascii=False)))
        return self.get(studio,project,department)
