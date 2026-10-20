"""Actual node Skill bindings, immutable revisions and an administrator recycle bin."""
import hashlib
import json
import logging
import threading
import time
import uuid

from server.core.identity import user_id
from server.core.permissions import Policy
from server.node_skills import validate
from server.studio_catalog import default_skill

RETENTION_SECONDS=30*24*60*60


def unavailable_skill():
    return {'name':'未配置 Skill','content':'','sha256':'','source_kind':'unconfigured'}


def binding(db,project,node,task=''):
    return db.execute('''SELECT l.* FROM skill_bindings b JOIN skill_library l ON l.id=b.skill_id
        WHERE b.project_id=? AND b.node=? AND b.task_id=?''',(project,node,task)).fetchone()


def bound_skill(db,project,node,fallback,task=''):
    row=binding(db,project,node,task)
    if row: return json.loads(row['skill']) if row['status']=='active' else unavailable_skill()
    return fallback


def legacy_skill(db,store,project,node,task=''):
    if task:
        row=db.execute('SELECT node_skills FROM tasks WHERE id=? AND project_id=?',(task,project)).fetchone()
        if not row: raise KeyError('任务不存在')
        value=json.loads(row['node_skills']).get(node.split(':')[1])
    else:
        row=db.execute('SELECT skill FROM studio_workspaces WHERE project_id=? AND node=?',(project,node)).fetchone()
        value=json.loads(row['skill']) if row and row['skill'] else None
    return value or default_skill(node,store,project)


def append_version(db,store,project,node,skill,note,*,task='',now=None):
    """Called within the caller's write transaction, after its authorization/version checks."""
    now=time.time() if now is None else now
    current=binding(db,project,node,task)
    if current is None or current['status']!='active':
        key=uuid.uuid4().hex
        baseline=legacy_skill(db,store,project,node,task)
        db.execute('INSERT INTO skill_library(id,project_id,node,task_id,skill) VALUES(?,?,?,?,?)',
                   (key,project,node,task,json.dumps(baseline,ensure_ascii=False)))
        db.execute('INSERT INTO skill_bindings VALUES(?,?,?,?) ON CONFLICT(project_id,node,task_id) DO UPDATE SET skill_id=excluded.skill_id',
                   (project,node,task,key))
        db.execute('INSERT INTO skill_versions VALUES(?,0,?,NULL,NULL,?)',
                   (key,json.dumps(baseline,ensure_ascii=False),'变更前规则；旧导入的操作者与时间未记录'))
        revision=1
    else:key=current['id'];revision=current['revision']+1
    actor=user_id()
    db.execute('UPDATE skill_library SET skill=?,revision=?,uploader_id=?,updated_at=? WHERE id=?',
               (json.dumps(skill,ensure_ascii=False),revision,actor,now,key))
    db.execute('INSERT INTO skill_versions VALUES(?,?,?,?,?,?)',
               (key,revision,json.dumps(skill,ensure_ascii=False),actor,now,note))
    return key


class SkillLibrary:
    def __init__(self,store,clock=time.time):self.store=store;self.clock=clock;self.policy=Policy(store)

    def _require(self,studio,project,node,action='view'):
        self.store.check_project(studio,project)
        self.policy.require('node','view',studio=studio,project=project,node=node)
        self.policy.require('skill',action,studio=studio,project=project,node=node)

    def _admin(self,studio,project,node):
        self._require(studio,project,node,'delete')
        if not self.policy.can_manage_scope(studio,project):raise PermissionError('只有当前范围管理员可删除、恢复或永久删除 Skill')

    def _actor(self,db,actor,skill):
        if actor:
            row=db.execute('SELECT name FROM users WHERE id=?',(actor,)).fetchone()
            return row['name'] if row else '账号已移除（'+actor+')'
        return '系统默认' if skill.get('source_kind') in ('local','bundled') else '未记录'

    def detail(self,studio,project,node,*,task='',before=None):
        self._require(studio,project,node)
        with self.store.connection() as db:
            row=binding(db,project,node,task)
            raw=json.loads(row['skill']) if row and row['skill'] else legacy_skill(db,self.store,project,node,task)
            skill=raw if not row or row['status']=='active' else unavailable_skill()
            history=[];total=0
            if row:
                total=db.execute('SELECT count(*) FROM skill_versions WHERE skill_id=?',(row['id'],)).fetchone()[0]
                limit=int(before) if before is not None else row['revision']+1
                for version in reversed(db.execute('SELECT * FROM skill_versions WHERE skill_id=? AND version<? ORDER BY version DESC LIMIT 50',(row['id'],limit)).fetchall()):
                    source=json.loads(version['skill'])
                    history.append({'version':version['version'],'uploader':self._actor(db,version['uploader_id'],source),
                                    'updated_at':version['changed_at'],'note':version['note'],'sha256':source.get('sha256','')})
            can_admin=self.policy.can_manage_scope(studio,project) and self.policy.allowed('skill','delete',studio,project,node=node)
            return {'id':row['id'] if row else None,'node':node,'task_id':task,'revision':row['revision'] if row else 0,
                    'status':row['status'] if row else 'active','skill':skill,
                    'description':self.description(skill['content']),
                    'uploader':self._actor(db,row['uploader_id'] if row else None,raw),
                    'updated_at':row['updated_at'] if row else None,'history':history,'history_total':total,
                    'next_before':history[0]['version'] if history and history[0]['version']>0 else None,
                    'permissions':{'import':self.policy.allowed('skill','import',studio,project,node=node),
                                   'export':self.policy.allowed('skill','export',studio,project,node=node),'delete':can_admin}}

    def listing(self,studio,project):
        from server.core.project_nodes import project_records
        self.store.check_project(studio,project)
        if not self.policy.allowed('project','view',studio,project) and not self.policy.visible_nodes(studio,project):
            raise PermissionError('无此项目访问权限')
        items=[]
        for n in project_records(self.store,project):
            if n['archived'] or not self.policy.allowed('skill','view',studio,project,node=n['id']) or not self.policy.allowed('node','view',studio,project,node=n['id']):continue
            item=self.detail(studio,project,n['id'])
            item.pop('history');item.pop('skill');item['node_name']=n['definition'][0]
            items.append(item)
        return {'items':items,'can_recycle':self.policy.can_manage_scope(studio,project)}

    @staticmethod
    def description(content):
        for line in content.splitlines():
            if line.startswith('description:'):return line.partition(':')[2].strip().strip('"\'')[:2000]
        return '未提供描述'

    def _writable(self,db,project,node):
        from server.core.project_content import require_enabled
        from server.core.project_nodes import read_config
        department=node.split(':')[0]
        require_enabled(db,project,department)
        _,nodes=read_config(db,project,department)
        if any(n['id']==node and n['archived'] for n in nodes):
            raise ValueError('节点已归档，历史规则仅供查看')
        busy=db.execute("SELECT 1 FROM department_jobs WHERE project_id=? AND node=? AND status IN ('queued','running')",(project,node)).fetchone()
        if node.startswith('testing:'):
            busy=busy or db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",(project,)).fetchone()
        if busy:raise ValueError('存在引用此 Skill 的排队或运行中任务')

    def import_skill(self,studio,project,node,value):
        self._require(studio,project,node,'import')
        note=value.get('note')
        if not isinstance(note,str) or not 1<=len(note.strip())<=2000:raise ValueError('请填写1至2000字更新说明')
        content=validate(value.get('content'))
        skill={'name':str(value.get('name') or '用户 Skill')[:200],'content':content,'source_kind':'imported','sha256':hashlib.sha256(content.encode()).hexdigest()}
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');self._require(studio,project,node,'import')
            self._writable(db,project,node)
            row=binding(db,project,node)
            if type(value.get('revision')) is not int or value['revision']!=(row['revision'] if row else 0) or value.get('id')!=(row['id'] if row else None):
                raise ValueError('Skill 版本已变化，请刷新')
            append_version(db,self.store,project,node,skill,note.strip(),now=self.clock())
            # Invalidate previous deliverable approval just like importing from the node toolbar.
            existing=db.execute('SELECT deliverable FROM studio_workspaces WHERE project_id=? AND node=?',(project,node)).fetchone()
            if existing:db.execute("UPDATE studio_workspaces SET skill=?,revision=revision+1,status=CASE WHEN trim(deliverable)<>'' THEN 'waiting_user' ELSE 'draft' END,updated_at=CURRENT_TIMESTAMP WHERE project_id=? AND node=?",(json.dumps(skill,ensure_ascii=False),project,node))
            db.execute('INSERT INTO studio_events(project_id,node,action,detail) VALUES(?,?,?,?)',(project,node,'skill_imported','导入 Skill：'+note.strip()))
        return self.detail(studio,project,node)

    def _row(self,db,project,key):
        row=db.execute('SELECT * FROM skill_library WHERE id=? AND project_id=?',(key,project)).fetchone()
        if not row:raise KeyError('Skill 不存在')
        return row

    def _version(self,row,value):
        if type(value.get('revision')) is not int or value['revision']!=row['revision']:raise ValueError('Skill 版本已变化，请刷新')

    def _audit(self,db,studio,project,row,action,actor=None):
        db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',
                   (actor or user_id(),studio,action,json.dumps({'project_id':project,'node':row['node'],'skill_id':row['id']},ensure_ascii=False)))

    def trash_node(self,studio,project,node,value):
        self._admin(studio,project,node)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');self._admin(studio,project,node)
            self._writable(db,project,node)
            row=binding(db,project,node)
            expected=row['revision'] if row else 0
            if type(value.get('revision')) is not int or value['revision']!=expected:
                raise ValueError('Skill 版本已变化，请刷新')
            if value.get('confirmed') is not True:raise ValueError('需要确认移入回收站')
            if row is None:
                baseline=legacy_skill(db,self.store,project,node)
                key=uuid.uuid4().hex
                encoded=json.dumps(baseline,ensure_ascii=False)
                db.execute('INSERT INTO skill_library(id,project_id,node,task_id,skill) VALUES(?,?,?,?,?)',(key,project,node,'',encoded))
                db.execute('INSERT INTO skill_bindings VALUES(?,?,?,?)',(project,node,'',key))
                db.execute('INSERT INTO skill_versions VALUES(?,0,?,NULL,NULL,?)',(key,encoded,'登记现有规则；原上传者与时间没有记录，删除不视为上传'))
                row=self._row(db,project,key)
            return self._trash(db,studio,project,row)

    def trash(self,studio,project,key,value):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=self._row(db,project,key);self._admin(studio,project,row['node']);self._version(row,value)
            if value.get('confirmed') is not True:raise ValueError('需要确认移入回收站')
            self._writable(db,project,row['node'])
            return self._trash(db,studio,project,row)

    def _trash(self,db,studio,project,row):
        if row['status']!='active':raise ValueError('Skill 已删除或不可重复删除')
        key=row['id']
        db.execute("UPDATE skill_library SET status='trashed',revision=revision+1,deleted_at=?,deleted_by=? WHERE id=?",(self.clock(),user_id(),key))
        if not row['task_id']:db.execute('UPDATE studio_workspaces SET skill=?,revision=revision+1 WHERE project_id=? AND node=?',(json.dumps(unavailable_skill(),ensure_ascii=False),project,row['node']))
        self._audit(db,studio,project,row,'skill_trashed')
        return {'id':key,'revision':row['revision']+1,'status':'trashed'}

    def restore(self,studio,project,key,value):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=self._row(db,project,key);self._admin(studio,project,row['node']);self._version(row,value)
            if row['status']!='trashed' or row['deleted_at']+RETENTION_SECONDS<=self.clock():raise ValueError('Skill 不在回收站或已过期')
            current=binding(db,project,row['node'],row['task_id'])
            if current and current['id']!=key and current['status']=='active':raise ValueError('节点已有新的 Skill，不能覆盖；请先处理当前版本')
            db.execute("UPDATE skill_library SET status='active',revision=revision+1,deleted_at=NULL,deleted_by=NULL WHERE id=?",(key,))
            db.execute('INSERT INTO skill_bindings VALUES(?,?,?,?) ON CONFLICT(project_id,node,task_id) DO UPDATE SET skill_id=excluded.skill_id',(project,row['node'],row['task_id'],key))
            self._audit(db,studio,project,row,'skill_restored')
        return self.detail(studio,project,row['node'],task=row['task_id'])

    def purge(self,studio,project,key,value):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=self._row(db,project,key);self._admin(studio,project,row['node']);self._version(row,value)
            if value.get('confirmed') is not True:raise ValueError('需要明确确认永久删除')
            if row['status']!='trashed':raise ValueError('只能永久删除回收站中的 Skill')
            self._purge(db,studio,project,row)
        return {'ok':True}

    def _purge(self,db,studio,project,row,actor=None):
        db.execute("UPDATE skill_library SET status='deleted',skill=NULL,revision=revision+1 WHERE id=?",(row['id'],))
        db.execute('DELETE FROM skill_versions WHERE skill_id=?',(row['id'],))
        self._audit(db,studio,project,row,'skill_permanently_deleted',actor)

    def purge_expired(self):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT l.*,p.studio_id FROM skill_library l JOIN projects p ON p.id=l.project_id WHERE l.status='trashed' AND l.deleted_at<=?",(self.clock()-RETENTION_SECONDS,)).fetchall()
            for row in rows:self._purge(db,row['studio_id'],row['project_id'],row,'system:skill-retention')
            return len(rows)

    def recycle_bin(self,studio,project):
        self.store.check_project(studio,project)
        if not self.policy.can_manage_scope(studio,project):raise PermissionError('只有管理员可管理回收站')
        self.purge_expired()
        with self.store.connection() as db:
            rows=db.execute("SELECT * FROM skill_library WHERE project_id=? AND status='trashed' ORDER BY deleted_at DESC",(project,)).fetchall()
            return {'items':[{'id':r['id'],'node':r['node'],'task_id':r['task_id'],'revision':r['revision'],
                    'name':json.loads(r['skill'])['name'],'deleted_at':r['deleted_at'],'expires_at':r['deleted_at']+RETENTION_SECONDS,
                    'deleted_by':self._actor(db,r['deleted_by'],{}),'can_delete':self.policy.allowed('skill','delete',studio,project,node=r['node'])}
                    for r in rows if self.policy.allowed('skill','view',studio,project,node=r['node'])]}

    def export(self,studio,project,key,version=None):
        with self.store.connection() as db:
            row=self._row(db,project,key);self._require(studio,project,row['node'],'export')
            if row['status']=='deleted':raise KeyError('Skill 已永久删除')
            if version is None:return json.loads(row['skill'])
            v=db.execute('SELECT skill FROM skill_versions WHERE skill_id=? AND version=?',(key,version)).fetchone()
            if not v:raise KeyError('版本不存在')
            return json.loads(v['skill'])


class SkillCleanupWorker:
    def __init__(self,store):
        self.stop=threading.Event();self.library=SkillLibrary(store)
        self.library.purge_expired()
        self.thread=threading.Thread(target=self.run,name='skill-retention',daemon=True);self.thread.start()

    def run(self):
        while not self.stop.wait(60):
            try:self.library.purge_expired()
            except Exception:logging.exception('Skill recycle-bin cleanup failed; will retry')

    def close(self):self.stop.set();self.thread.join(timeout=5)
