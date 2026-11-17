"""Authenticated immutable project publications. Publication never executes a node."""
import json
import re
import sqlite3
import time
import uuid
from server.core.identity import user_id
from server.core.permissions import Policy
from server.core.public_area.schema import migrate
from server.core.public_area.packages import validate,encode,sha,visible,text


class Conflict(ValueError):pass


class PublicArea:
    def __init__(self,store):
        self.store=store;self.policy=Policy(store);migrate(store)

    def cleanup(self):
        with self.store.connection() as db:
            db.execute('UPDATE public_operations SET package=NULL WHERE result IS NULL AND expires<?',(time.time(),))

    def scope(self,studio,project):
        with self.store.connection() as db:row=db.execute('SELECT status FROM users WHERE id=?',(user_id(),)).fetchone()
        if not row or row['status']!='active':raise PermissionError('账号待审批或已禁用')
        self.store.check_project(studio,project)
        self.policy.require('project','view',studio=studio,project=project)

    def require(self,action,studio,project,department='',node=''):
        self.scope(studio,project)
        self.policy.require('publication',action,studio=studio,project=project,department=department,node=node)

    def versions(self,studio,project,value=None):
        self.scope(studio,project)
        if value is None:
            with self.store.connection() as db:
                return {'items':[dict(r) for r in db.execute('SELECT * FROM public_versions WHERE project_id=? ORDER BY created_at DESC,rowid DESC',(project,))]}
        self.policy.require('project','edit',studio=studio,project=project)
        name=text(value.get('name'),'版本名称',100).strip();key=uuid.uuid4().hex
        try:
            with self.store.connection() as db:
                db.execute('INSERT INTO public_versions(id,project_id,name,created_by) VALUES(?,?,?,?)',(key,project,name,user_id()))
        except sqlite3.IntegrityError:raise ValueError('该项目版本已存在') from None
        return {'id':key,'name':name,'project_id':project}

    def coordinate(self,studio,project,p,action):
        from server.studio_catalog import node_definition
        d,_,_=node_definition(p['node'],self.store,project)
        if d['id']!=p['department']:raise ValueError('节点不属于所选部门')
        self.require(action,studio,project,p['department'],p['node'])
        if p['kind']=='skill' or 'skill' in p.get('includes',[]):self.policy.require('skill','export',studio=studio,project=project,department=p['department'],node=p['node'])
        with self.store.connection() as db:
            if not db.execute('SELECT 1 FROM public_versions WHERE id=? AND project_id=?',(p['version_id'],project)).fetchone():raise ValueError('版本不属于当前项目')

    def _operation(self,db,studio,project,operation):
        row=db.execute('SELECT * FROM public_operations WHERE actor=? AND operation_id=? AND studio_id=? AND project_id=?',
            (user_id(),operation,studio,project)).fetchone()
        if not row:raise KeyError('发布操作不存在')
        return dict(row)

    def status(self,studio,project,operation):
        self.scope(studio,project)
        with self.store.connection() as db:r=self._operation(db,studio,project,operation)
        if r['result']:
            result=json.loads(r['result'])
            # A stale successful operation cannot bypass withdrawal or current access.
            self.detail(studio,project,result['id'],result['revision'])
            return result
        p=json.loads(r['package']) if r['package'] else None
        if p:self.coordinate(studio,project,p,'create')
        return {'operation_id':operation,'status':'staged' if p and r['expires']>time.time() else 'expired'}

    def stage(self,studio,project,body):
        operation=text(body.get('operation_id'),'操作 ID',100)
        if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',operation):raise ValueError('操作 ID 不合法')
        p=validate(body.get('package'));self.coordinate(studio,project,p,'create')
        item=body.get('publication_id') or '';rev=body.get('expected_revision')
        if not isinstance(item,str) or len(item)>100 or type(rev) is not int or rev<0 or bool(item)!=(rev>0):raise ValueError('公区修订不合法')
        digest=sha({'package':p,'publication_id':item,'expected_revision':rev})
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE public_operations SET package=NULL WHERE result IS NULL AND expires<?',(time.time(),))
            existing=db.execute('SELECT * FROM public_operations WHERE actor=? AND operation_id=?',(user_id(),operation)).fetchone()
            if existing:
                if existing['studio_id']!=studio or existing['project_id']!=project or existing['sha256']!=digest:raise Conflict('操作 ID 已用于其他内容，请重新预览')
                if existing['result']:
                    result=json.loads(existing['result']);self.detail(studio,project,result['id'],result['revision']);return result
                db.execute('UPDATE public_operations SET package=?,expires=? WHERE actor=? AND operation_id=?',(encode(p),time.time()+86400,user_id(),operation))
            else:
                if item:self._update_check(db,studio,project,item,rev,p)
                db.execute('INSERT INTO public_operations VALUES(?,?,?,?,?,?,?,?,NULL,?)',
                    (user_id(),operation,studio,project,encode(p),digest,item,rev,time.time()+86400))
        return {'operation_id':operation,'status':'staged'}

    def _update_check(self,db,studio,project,item,revision,p):
        row=db.execute('SELECT * FROM public_items WHERE id=? AND studio_id=? AND project_id=?',(item,studio,project)).fetchone()
        if not row:raise KeyError('发布条目不存在')
        if row['author_id']!=user_id():raise PermissionError('只能更新自己发布的内容')
        if row['withdrawn'] or row['revision']!=revision:raise Conflict('公区内容已更新或撤下，请刷新后重新确认')
        if any(row[k]!=p[k] for k in ('department','node','kind')):raise ValueError('发布新修订不能更换节点或内容类型')

    def commit(self,studio,project,operation):
        self.scope(studio,project)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            r=self._operation(db,studio,project,operation)
            if r['result']:
                result=json.loads(r['result']);self.detail(studio,project,result['id'],result['revision']);return result
            if not r['package'] or r['expires']<=time.time():raise Conflict('暂存已过期，请重新预览并确认')
            p=json.loads(r['package']);self.coordinate(studio,project,p,'create')
            item=r['publication_id'] or uuid.uuid4().hex;revision=r['expected_revision']+1
            if r['publication_id']:
                self._update_check(db,studio,project,item,r['expected_revision'],p)
                db.execute('UPDATE public_items SET revision=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(revision,item))
            else:
                db.execute('INSERT INTO public_items(id,studio_id,project_id,author_id,department,node,kind,revision) VALUES(?,?,?,?,?,?,?,?)',
                    (item,studio,project,user_id(),p['department'],p['node'],p['kind'],revision))
            db.execute('INSERT INTO public_revisions(item_id,revision,version_id,title,description,package) VALUES(?,?,?,?,?,?)',
                (item,revision,p['version_id'],p['title'],p['description'],encode(p)))
            result={'id':item,'revision':revision,'author_id':user_id(),'operation_id':operation,'status':'published'}
            db.execute('UPDATE public_operations SET result=?,package=NULL WHERE actor=? AND operation_id=?',(encode(result),user_id(),operation))
            db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',
                (user_id(),studio,'public_published',encode({'project_id':project,'id':item,'revision':revision})))
            self._notify(db,studio,project,p,item,revision)
            return result

    def _notify(self,db,studio,project,p,item,revision):
        # Same durable outbox as team notifications; notification errors never re-run a node.
        from server.core.notifications import enqueue
        enqueue(self.store,db,project,p['node'],f'public:{item}:{revision}','public_published',
            {'notification_summary':f'公区发布：{p["title"]} · 修订 {revision}',
             'public_item':item},origin='publication')

    def _read(self,db,studio,project,item,revision=None,action='view'):
        row=db.execute('SELECT i.*,u.name AS author_name FROM public_items i JOIN users u ON u.id=i.author_id WHERE i.id=? AND i.studio_id=? AND i.project_id=? AND i.withdrawn=0',(item,studio,project)).fetchone()
        if not row:raise KeyError('条目不存在或已撤下')
        self.require(action,studio,project,row['department'],row['node'])
        rev=row['revision'] if revision is None else revision
        if type(rev) is not int or rev<1:raise ValueError('修订不合法')
        data=db.execute('SELECT * FROM public_revisions WHERE item_id=? AND revision=?',(item,rev)).fetchone()
        if not data:raise KeyError('修订不存在')
        return dict(row),dict(data)

    def detail(self,studio,project,item,revision=None):
        self.scope(studio,project)
        with self.store.connection() as db:
            row,data=self._read(db,studio,project,item,revision)
            revisions=[dict(r) for r in db.execute('SELECT revision,title,created_at FROM public_revisions WHERE item_id=? ORDER BY revision DESC',(item,))]
        return {**row,'revision':data['revision'],'created_at':data['created_at'],'package':visible(json.loads(data['package'])),
            'revisions':revisions,'can_download':self.policy.allowed('publication','export',studio,project,row['department'],row['node']),
            'can_withdraw':self.policy.allowed('publication','delete',studio,project,row['department'],row['node']) and (row['author_id']==user_id() or self.policy.can_manage_scope(studio,project))}

    def attachment(self,studio,project,item,revision,index):
        self.scope(studio,project)
        with self.store.connection() as db:
            _,data=self._read(db,studio,project,item,revision,'export')
        attachments=json.loads(data['package'])['attachments']
        if type(index) is not int or not 0<=index<len(attachments):raise KeyError('附件不存在')
        return attachments[index]

    def export(self,studio,project,item,revision):
        with self.store.connection() as db:_,data=self._read(db,studio,project,item,revision,'export')
        return {'id':item,'revision':revision,'package':json.loads(data['package'])}

    def listing(self,studio,project,query):
        self.scope(studio,project)
        page=max(1,int(query.get('page',1)));size=int(query.get('size',10))
        if size not in (5,10,20,50):raise ValueError('分页大小不合法')
        filters={k:query.get(k,'') for k in ('version_id','department','node','author_id','kind','q')}
        with self.store.connection() as db:
            rows=db.execute('''SELECT i.*,r.title,r.description,r.version_id,r.created_at,u.name AS author_name,v.name AS version_name
              FROM public_items i JOIN public_revisions r ON r.item_id=i.id AND r.revision=i.revision
              JOIN users u ON u.id=i.author_id JOIN public_versions v ON v.id=r.version_id
              WHERE i.studio_id=? AND i.project_id=? AND i.withdrawn=0 ORDER BY i.updated_at DESC,i.rowid DESC''',(studio,project)).fetchall()
        items=[]
        for row in rows:
            r=dict(row)
            if not self.policy.allowed('publication','view',studio,project,r['department'],r['node']):continue
            if any(v and (v.lower() not in (r['title']+' '+r['description']).lower() if k=='q' else r[k]!=v) for k,v in filters.items()):continue
            items.append(r)
        total=len(items);pages=max(1,(total+size-1)//size);page=min(page,pages)
        return {'items':items[(page-1)*size:page*size],'total':total,'page':page,'pages':pages,'size':size}

    def withdraw(self,studio,project,item,revision):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');row,_=self._read(db,studio,project,item,action='delete')
            if row['author_id']!=user_id() and not self.policy.can_manage_scope(studio,project):raise PermissionError('只能撤下自己的发布')
            if type(revision) is not int or revision!=row['revision']:raise Conflict('条目已更新，请刷新后撤下')
            db.execute('UPDATE public_items SET withdrawn=1 WHERE id=?',(item,))
            db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',(user_id(),studio,'public_withdrawn',encode({'project_id':project,'id':item,'revision':revision})))
        return {'ok':True}
