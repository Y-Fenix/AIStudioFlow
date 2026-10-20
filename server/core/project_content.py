"""Declarative project content; lifecycle permissions are separate from normal workflow edits."""
import copy
import json
import uuid
from urllib.parse import urlsplit
from server.core.identity import user_id
from server.core.permissions import Policy
from server.studio_catalog import DEPARTMENTS


def read_content(db,project):
    row=db.execute('SELECT * FROM project_content_configs WHERE project_id=?',(project,)).fetchone()
    return {'revision':row['revision'],'items':json.loads(row['items']),'disabled_departments':json.loads(row['disabled_departments'])} if row else {'revision':0,'items':[],'disabled_departments':[]}


def require_enabled(db,project,department):
    if department in read_content(db,project)['disabled_departments']:
        raise ValueError('部门已停用，请由管理员启用后再操作')


def apply_content(store,studio,project,departments):
    with store.connection() as db:value=read_content(db,project)
    for d in departments:
        d['enabled']=d['id'] not in value['disabled_departments']
        rows=[n for n in value['items'] if n['department']==d['id']]
        deleted={n['target'] for n in rows if n['kind']=='hidden' and not n['archived']}
        d['tools']=[t for t in d.get('tools',[]) if 'tool:'+t['id'] not in deleted]
        d['homepage']['focus']=[s for i,s in enumerate(d['homepage']['focus']) if 'focus:'+str(i) not in deleted]
        for row in rows:
            if row['archived']:continue
            if row['kind']=='tool':d['tools'].append({'id':row['id'],'label':row['title'],'url':row['url']})
        d['content_items']=[n for n in rows if not n['archived'] and n['kind'] in ('note','source','deliverable')] if ProjectContent(store)._visible(studio,project,d['id']) else []
    return departments


class ProjectContent:
    def __init__(self,store):self.store=store;self.policy=Policy(store)

    def _visible(self,studio,project,department):
        return (self.policy.allowed('department','view',studio,project,department)
                or any(n.startswith(department+':') for n in self.policy.visible_nodes(studio,project))
                or any(self.policy.allowed('content',a,studio,project,department) for a in ('view','create','delete')))

    def get(self,studio,project):
        self.store.check_project(studio,project)
        with self.store.connection() as db:value=read_content(db,project)
        visible={d['id'] for d in DEPARTMENTS if self._visible(studio,project,d['id'])}
        if not visible:raise PermissionError('无工作台内容查看权限')
        return {**value,'items':[n for n in value['items'] if n['department'] in visible],
                'permissions':{d:{a:self.policy.allowed('content',a,studio,project,d) for a in ('create','delete')} for d in visible}}

    def change(self,studio,project,value):
        self.store.check_project(studio,project)
        action=value.get('action')
        if action not in ('create','delete','restore','disable','enable','hide','unhide'):raise ValueError('内容管理动作无效')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');current=read_content(db,project)
            if type(value.get('revision')) is not int or value['revision']!=current['revision']:raise ValueError('内容版本已变化，请重新加载')
            item=next((n for n in current['items'] if n['id']==value.get('id')),None)
            department=item['department'] if item else value.get('department')
            if department not in {d['id'] for d in DEPARTMENTS}:raise ValueError('部门无效')
            permission='delete' if action in ('delete','disable','hide') else 'create'
            self.policy.require('content',permission,studio=studio,project=project,department=department)
            if action in ('create','hide'):
                if len(current['items'])>=1000:raise ValueError('当前项目内容条目已达1000项，请联系管理员整理')
                kind=value.get('kind') if action=='create' else 'hidden'
                if kind not in ('tool','note','source','deliverable') and not (action=='hide' and kind=='hidden'):raise ValueError('内容类型无效')
                title=value.get('title','');body=value.get('body','');url=value.get('url','')
                if kind=='hidden':
                    target=value.get('target');d=next(d for d in DEPARTMENTS if d['id']==department)
                    targets={'tool:'+t['id'] for t in d.get('tools',[])}|{'focus:'+str(i) for i in range(len(d['homepage']['focus']))}
                    if target not in targets:raise ValueError('默认条目不存在')
                    if any(n.get('target')==target and n['department']==department and not n['archived'] for n in current['items']):raise ValueError('条目已删除')
                    title=target
                if not isinstance(title,str) or not 1<=len(title.strip())<=120 or not isinstance(body,str) or len(body.encode())>100000:raise ValueError('标题需1至120字，内容最大100KB')
                if kind=='tool':
                    if not isinstance(url,str) or len(url)>2048:raise ValueError('工具地址无效')
                    parsed=urlsplit(url)
                    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('工具仅支持无凭据 HTTPS 链接')
                current['items'].append({'id':uuid.uuid4().hex,'department':department,'kind':kind,'title':title.strip(),'body':body,
                                         'url':url if kind=='tool' else '', 'target':value.get('target','') if kind=='hidden' else '',
                                         'archived':False,'created_by':user_id()})
            elif action in ('delete','restore','unhide'):
                if item is None:raise KeyError('条目不存在')
                if item['kind']=='hidden' and action!='unhide':raise ValueError('默认隐藏条目请使用恢复默认操作')
                archived=action in ('delete','unhide')
                if action=='unhide' and item['kind']!='hidden':raise ValueError('只能恢复默认条目')
                if item['archived']==archived:raise ValueError('条目已处于目标状态')
                item['archived']=archived
            else:
                disabled=set(current['disabled_departments'])
                if action=='disable':
                    if department in disabled:raise ValueError('部门已停用')
                    busy=db.execute("SELECT 1 FROM department_jobs WHERE project_id=? AND node LIKE ? AND status IN ('queued','running')",(project,department+':%')).fetchone()
                    if department=='testing':busy=busy or db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",(project,)).fetchone()
                    if busy:raise ValueError('部门存在排队或运行中任务')
                    disabled.add(department)
                else:disabled.discard(department)
                current['disabled_departments']=sorted(disabled)
            db.execute('INSERT INTO project_content_configs VALUES(?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision,items=excluded.items,disabled_departments=excluded.disabled_departments',
                       (project,current['revision']+1,json.dumps(current['items'],ensure_ascii=False),json.dumps(current['disabled_departments'])))
            db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',
                       (user_id(),studio,'project_content_'+action,json.dumps({'project_id':project,'department':department,'id':value.get('id'),'kind':value.get('kind'),'revision':current['revision']+1})))
        return self.get(studio,project)
