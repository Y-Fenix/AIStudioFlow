"""Scoped versioned templates, applied blueprints and project flows."""
import json
import re
import uuid
from server.core.identity import user_id
from server.core.permissions import Policy
from server.core.node_blocks.schema import validate_blocks, TYPES
from server.core.project_nodes import project_records
from server.studio_catalog import DEPARTMENTS


def encode(value):return json.dumps(value,ensure_ascii=False)


def revision(value, current):
    if not isinstance(value,dict) or type(value.get('revision')) is not int or value['revision']!=current:raise ValueError('配置版本已变化，请重新加载，勿覆盖他人修改')


def body(value):
    if not isinstance(value,dict):raise ValueError('配置须为对象')
    if value.get('id') is not None and (not isinstance(value['id'],str) or not re.fullmatch(r'[a-f0-9]{32}',value['id'])):raise ValueError('配置 ID 格式无效')
    return value


def name(value):
    s=value.get('name')
    if not isinstance(s,str) or not 1<=len(s.strip())<=100:raise ValueError('名称须为1至100字')
    return s.strip()


class Builder:
    def __init__(self,store):self.store=store;self.policy=Policy(store)

    def scope(self,studio,project):self.store.check_project(studio,project)

    def node_scope(self,studio,project,node,action='view'):
        self.scope(studio,project)
        self.policy.require('node',action,studio=studio,project=project,node=node)
        if not any(n['id']==node and not n['archived'] for n in project_records(self.store,project)):raise ValueError('节点不存在或已归档')
        from server.core.project_content import require_enabled
        with self.store.connection() as db:require_enabled(db,project,node.split(':')[0])

    def audit(self,db,studio,action,detail):
        db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',(user_id(),studio,action,encode(detail)))

    def blueprint(self,studio,project,node):
        self.node_scope(studio,project,node)
        with self.store.connection() as db:r=db.execute('SELECT * FROM node_blueprints WHERE project_id=? AND node=?',(project,node)).fetchone()
        return {'node':node,'revision':r['revision'] if r else 0,'blocks':json.loads(r['blocks']) if r else [],'types':TYPES,'sources':json.loads(r['sources']) if r else []}

    def save_blueprint(self,studio,project,node,value):
        self.node_scope(studio,project,node,'edit')
        if not isinstance(value,dict):raise ValueError('配置须为对象')
        blocks=validate_blocks(value.get('blocks'))
        sources=self.sources(studio,value,node.split(':')[0])
        if any(TYPES[b['type']].get('department',node.split(':')[0])!=node.split(':')[0] for b in blocks):raise ValueError('不能使用其他部门私有积木')
        if node.startswith('testing:') and node.split(':')[1].isdigit():raise ValueError('测试固定节点使用专用证据工作台；请新增自定义节点搭建')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM node_blueprints WHERE project_id=? AND node=?',(project,node)).fetchone()
            revision(value,row['revision'] if row else 0)
            old=json.loads(row['blocks']) if row else [];old_ids={(b['id'],b['type']) for b in old};new_ids={(b['id'],b['type']) for b in blocks}
            for condition,action in ((bool(new_ids-old_ids),'create'),(bool(old_ids-new_ids),'delete')):
                if condition:self.policy.require('content',action,studio=studio,project=project,department=node.split(':')[0])
            if db.execute("SELECT 1 FROM block_runs WHERE project_id=? AND node=? AND status IN ('queued','running','waiting_user')",(project,node)).fetchone():raise ValueError('节点有未结束运行，请先取消')
            if db.execute("SELECT 1 FROM department_jobs WHERE project_id=? AND node=? AND status IN ('queued','running')",(project,node)).fetchone():raise ValueError('节点正在执行')
            db.execute('INSERT INTO node_blueprints(project_id,node,revision,blocks,updated_by) VALUES(?,?,?,?,?) ON CONFLICT(project_id,node) DO UPDATE SET revision=excluded.revision,blocks=excluded.blocks,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP',
                       (project,node,value['revision']+1,encode(blocks),user_id()))
            db.execute('UPDATE node_blueprints SET sources=? WHERE project_id=? AND node=?',(encode(sources),project,node))
            db.execute("UPDATE studio_workspaces SET status='draft',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE project_id=? AND node=?",(project,node))
            self.audit(db,studio,'blueprint_saved',{'project_id':project,'node':node,'revision':value['revision']+1})
        return self.blueprint(studio,project,node)

    def template_scope(self,studio,department,action):
        if not isinstance(department,str) or department not in {d['id'] for d in DEPARTMENTS}:raise ValueError('部门无效')
        # A template is shared across projects; project-only grants never suffice.
        self.policy.require('block',action,studio=studio,department=department)
        if not any(s['id']==studio for s in self.store.studios()):raise KeyError('工作室不存在')

    def sources(self,studio,value,department=None):
        sources=value.get('sources',[])
        if not isinstance(sources,list) or len(sources)>30:raise ValueError('模板来源格式无效')
        for source in sources:
            if not isinstance(source,dict) or set(source)!={'id','department','revision'} or not isinstance(source['id'],str) or not isinstance(source['department'],str) or type(source['revision']) is not int or source['revision']<1:raise ValueError('模板来源格式无效')
            if department and source['department']!=department:raise ValueError('模板来源不属于本部门')
            self.template_scope(studio,source['department'],'view')
            with self.store.connection() as db:
                if not db.execute('SELECT 1 FROM block_template_versions v JOIN block_templates t ON t.id=v.template_id WHERE t.studio_id=? AND t.department=? AND t.id=? AND v.revision=?',(studio,source['department'],source['id'],source['revision'])).fetchone():raise ValueError('模板来源版本不存在')
        return sources

    def templates(self,studio,department):
        self.template_scope(studio,department,'view')
        with self.store.connection() as db:
            rows=db.execute('SELECT t.*,v.author,v.created_at FROM block_templates t JOIN block_template_versions v ON v.template_id=t.id AND v.revision=t.revision WHERE t.studio_id=? AND t.department=? AND t.archived=0 ORDER BY t.name,t.id',(studio,department)).fetchall()
        return {'items':[dict(r) for r in rows]}

    def template(self,studio,department,identity,version=None):
        self.template_scope(studio,department,'view')
        with self.store.connection() as db:
            t=db.execute('SELECT * FROM block_templates WHERE id=? AND studio_id=? AND department=? AND archived=0',(identity,studio,department)).fetchone()
            if not t:raise KeyError('模板不存在')
            r=db.execute('SELECT * FROM block_template_versions WHERE template_id=? AND revision=?',(identity,version or t['revision'])).fetchone()
        if not r:raise KeyError('模板版本不存在')
        return {**dict(t),'revision':r['revision'],'blocks':json.loads(r['blocks']),'author':r['author'],'created_at':r['created_at']}

    def save_template(self,studio,value):
        body(value);department=value.get('department');identity=value.get('id')
        self.template_scope(studio,department,'edit' if identity else 'create')
        self.template_scope(studio,department,'view')
        kind=value.get('kind','node')
        if not isinstance(kind,str) or kind not in ('node','flow'):raise ValueError('模板类别无效')
        blocks=validate_blocks(value.get('blocks'),flow=kind=='flow');title=name(value)
        if kind=='flow' and any(TYPES[b['type']].get('department') for b in blocks):raise ValueError('流程模板请通过部门节点引用私有积木')
        if any(TYPES[b['type']].get('department',department)!=department for b in blocks):raise ValueError('不能共享其他部门私有积木')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM block_templates WHERE id=? AND studio_id=? AND department=? AND archived=0',(identity,studio,department)).fetchone() if identity else None
            if identity and not old:raise KeyError('模板不存在')
            revision(value,old['revision'] if old else 0)
            if old and old['kind']!=kind:raise ValueError('模板类别不可改变')
            identity=identity or uuid.uuid4().hex;rev=value['revision']+1
            db.execute('INSERT INTO block_templates(id,studio_id,department,name,revision,kind) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,revision=excluded.revision',(identity,studio,department,title,rev,kind))
            db.execute('INSERT INTO block_template_versions(template_id,revision,blocks,author) VALUES(?,?,?,?)',(identity,rev,encode(blocks),user_id()))
            self.audit(db,studio,'block_template_saved',{'department':department,'template':identity,'revision':rev})
        return self.template(studio,department,identity)

    def archive_template(self,studio,value):
        body(value);department=value.get('department');self.template_scope(studio,department,'delete')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM block_templates WHERE id=? AND studio_id=? AND department=? AND archived=0',(value.get('id'),studio,department)).fetchone()
            if not r:raise KeyError('模板不存在')
            revision(value,r['revision']);db.execute('UPDATE block_templates SET archived=1,revision=revision+1 WHERE id=?',(r['id'],))
            self.audit(db,studio,'block_template_archived',{'department':department,'template':r['id']})
        return {'archived':True}

    def flows(self,studio,project):
        self.scope(studio,project);self.policy.require('workflow','view',studio=studio,project=project)
        with self.store.connection() as db:rows=db.execute('SELECT * FROM custom_flows WHERE project_id=? AND archived=0 ORDER BY updated_at DESC,id',(project,)).fetchall()
        return {'items':[self._flow_data(studio,project,dict(r)) for r in rows],'types':TYPES}

    def flow(self,studio,project,identity):
        self.scope(studio,project);self.policy.require('workflow','view',studio=studio,project=project)
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM custom_flows WHERE project_id=? AND id=?',(project,identity)).fetchone()
        if not row:raise KeyError('工作流不存在')
        return self._flow_data(studio,project,dict(row))

    def _flow_data(self,studio,project,row):
        from server.core.node_blocks.flow_nodes import groups,coordinate,DEFAULT_SKILL
        from server.studio_workspaces import Workspaces
        blocks=json.loads(row['blocks']);nodes=[]
        for g in groups(blocks):
            scope=dict(studio=studio,project=project,node=coordinate(row['id'],g['id']))
            permissions={a:self.policy.allowed('workflow_node',a,**scope) for a in ('view','edit','execute')}
            permissions.update({'skill_'+a:self.policy.allowed('workflow_skill',a,**scope) for a in ('view','edit','import','export')})
            source=g['source_node'];default=DEFAULT_SKILL;default_name='默认任务 Skill'
            if source:
                permissions={k:v and self.policy.allowed('skill' if k.startswith('skill_') else 'node',k.removeprefix('skill_'),studio=studio,project=project,node=source) for k,v in permissions.items()}
                try:
                    self.node_scope(studio,project,source)
                    if permissions['skill_view']:
                        w=Workspaces(self.store).get(studio,project,source);default=w['skill']['content'];default_name=w['skill']['name']
                except (ValueError,KeyError,PermissionError):permissions={k:False for k in permissions}
            if not permissions['view']:
                nodes.append({'id':g['id'],'name':'无权查看此节点','kind':g['kind'],'source_node':'','blocks':[],'inputs':'','auto_next':g['auto_next'],'permissions':permissions,'description':'联系负责人授权'})
                for b in blocks:
                    if b['id'] in g['block_ids']:b['config']={'label':'无权查看此节点'}
                continue
            config=g.pop('config');skill={'name':config.get('skill_name') or default_name,'content':config.get('skill',default),'source':'override' if 'skill' in config else 'default'}
            if not permissions['skill_view']:
                skill['content']=''
                for b in blocks:
                    if b['id'] in g['block_ids']:
                        b['config'].pop('skill',None);b['config'].pop('skill_name',None)
            g.update(skill=skill,permissions=permissions,delivery='真实测试批次证据' if source.startswith('testing:') else '节点交付物')
            nodes.append(g)
        with self.store.connection() as db:
            latest=db.execute('SELECT id,flow_id,status,created_at,updated_at FROM block_runs WHERE project_id=? AND flow_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(project,row['id'])).fetchone()
        return {**row,'blocks':blocks,'sources':json.loads(row['sources']),'nodes':nodes,'last_run':dict(latest) if latest else None}

    def save_flow(self,studio,project,value):
        body(value);self.scope(studio,project);self.policy.require('workflow','edit' if value.get('id') else 'create',studio=studio,project=project)
        self.policy.require('workflow','view',studio=studio,project=project)
        blocks=validate_blocks(value.get('blocks'),flow=True);title=name(value);sources=self.sources(studio,value)
        description=value.get('description','')
        if not isinstance(description,str) or len(description)>1000:raise ValueError('流程说明最多1000字')
        for b in blocks:
            if TYPES[b['type']].get('department'):raise ValueError('部门私有积木请通过所属部门节点加入流程')
            if b['type']=='node':self.node_scope(studio,project,b['config']['node'])
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM custom_flows WHERE id=? AND project_id=? AND archived=0',(value.get('id'),project)).fetchone()
            if value.get('id') and not old:raise KeyError('工作流不存在')
            revision(value,old['revision'] if old else 0);identity=value.get('id') or uuid.uuid4().hex
            from server.core.node_blocks.flow_nodes import groups,coordinate
            raw_previous=json.loads(old['blocks']) if old else []
            previous={g['id']:g for g in groups(raw_previous)} if old else {}
            if old:
                # A user without Skill view receives a redacted flow. Missing
                # Skill fields mean "unchanged" on save; restore the stored
                # value before comparing and persisting the new flow.
                old_blocks={(b['id'],b['type']):b for b in raw_previous}
                for current in blocks:
                    prior=old_blocks.get((current['id'],current['type']))
                    if not prior:continue
                    scope=dict(studio=studio,project=project,node=coordinate(identity,current['id']))
                    skill_visible=self.policy.allowed('workflow_skill','view',**scope)
                    if prior['type']=='node':
                        skill_visible=skill_visible and self.policy.allowed('skill','view',studio=studio,project=project,node=prior['config']['node'])
                    if skill_visible:continue
                    for field in ('skill','skill_name'):
                        if field not in current['config'] and field in prior['config']:
                            current['config'][field]=prior['config'][field]
            following={g['id']:g for g in groups(blocks)}
            for key in set(previous)|set(following):
                before=previous.get(key);after=following.get(key)
                if before==after:continue
                scope=dict(studio=studio,project=project,node=coordinate(identity,key) if before else '')
                self.policy.require('workflow_node','edit',**scope)
                if not before or not after:
                    self.policy.require('workflow_node','create' if after else 'delete',**scope)
                if (before or {}).get('config',{}).get('skill')!=(after or {}).get('config',{}).get('skill'):
                    self.policy.require('workflow_skill','edit',**scope)
                    source=(after or before)['source_node']
                    if source:self.policy.require('skill','edit',studio=studio,project=project,node=source)
                if after and after['source_node']:
                    self.policy.require('node','edit',studio=studio,project=project,node=after['source_node'])
            db.execute('INSERT INTO custom_flows(id,project_id,name,revision,blocks,author) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,revision=excluded.revision,blocks=excluded.blocks,updated_at=CURRENT_TIMESTAMP',
                (identity,project,title,value['revision']+1,encode(blocks),user_id()))
            db.execute('UPDATE custom_flows SET sources=?,description=? WHERE id=?',(encode(sources),description,identity))
            self.audit(db,studio,'custom_flow_saved',{'project_id':project,'flow':identity,'revision':value['revision']+1})
        return self.flow(studio,project,identity)

    def archive_flow(self,studio,project,value):
        body(value);self.scope(studio,project);self.policy.require('workflow','delete',studio=studio,project=project)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');r=db.execute('SELECT * FROM custom_flows WHERE id=? AND project_id=? AND archived=0',(value.get('id'),project)).fetchone()
            if not r:raise KeyError('工作流不存在')
            revision(value,r['revision']);db.execute('UPDATE custom_flows SET archived=1,revision=revision+1 WHERE id=?',(r['id'],))
            self.audit(db,studio,'custom_flow_archived',{'project_id':project,'flow':r['id']})
        return {'archived':True}
