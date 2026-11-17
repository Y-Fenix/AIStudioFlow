"""Versioned testing batches and immutable local case sets; no external effects."""
import copy
import hashlib
import json
import uuid
from server.core.permissions import Policy
from server.core.identity import user_id


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def version_of(db, task_id):
    row=db.execute('''SELECT v.id,v.name FROM testing_batch_versions b
        JOIN testing_versions v ON v.id=b.version_id WHERE b.task_id=? AND NOT EXISTS(SELECT 1 FROM testing_library_deleted d WHERE d.kind='version' AND d.resource_id=v.id)''',(task_id,)).fetchone()
    return dict(row) if row else None


def capture(db, task_id, kind, skill=None):
    """Called inside the original write transaction. Never mutates prior snapshots."""
    task=dict(db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone())
    artifact=json.loads(task['artifacts']).get('0')
    if not isinstance(artifact,dict) or not artifact.get('cases'):return
    previous=db.execute('SELECT * FROM testing_case_snapshots WHERE task_id=? ORDER BY rowid DESC LIMIT 1',(task_id,)).fetchone()
    requirements=[dict(r) for r in db.execute('''SELECT * FROM requirements r WHERE task_id=? AND archived=0
        AND version=(SELECT MAX(s.version) FROM requirements s WHERE s.task_id=r.task_id AND s.source=r.source) ORDER BY rowid''',(task_id,))]
    for r in requirements:r['metadata']=json.loads(r['metadata'])
    if skill is None:
        # Keep the Skill captured with these cases, not a later library override.
        prior=json.loads(previous['payload']) if previous else None
        prior_artifact=prior['artifact'] if prior else {}
        if prior and prior_artifact.get('node_skill_sha256')==artifact.get('node_skill_sha256'):
            skill=prior['skill']
        elif kind!='migration':
            from server.core.skill_library import bound_skill
            skill=bound_skill(db,task['project_id'],'testing:0',json.loads(task['node_skills']).get('0',{}),task_id)
            if artifact.get('node_skill_sha256') and hashlib.sha256(skill.get('content','').encode()).hexdigest()!=artifact['node_skill_sha256']:
                skill={'name':'原生成 Skill 正文不可还原','sha256':artifact['node_skill_sha256'],'content':''}
        else:skill={'name':'旧用例原生成 Skill 未记录','sha256':artifact.get('node_skill_sha256',''),'content':''}
    version=version_of(db,task_id)
    state='confirmed' if task['stage']>0 else 'draft'
    payload={'artifact':artifact,'requirements':requirements,'skill':skill,'baseline':json.loads(task['binding']),
             'version':version,'case_status':state}
    signature=hashlib.sha256(encode(payload).encode()).hexdigest()
    if previous and previous['signature']==signature:return
    db.execute('''INSERT INTO testing_case_snapshots(id,project_id,task_id,task_revision,case_status,
        case_count,signature,payload,capture_kind,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)''',
        (uuid.uuid4().hex,task['project_id'],task_id,task['revision'],state,len(artifact['cases']),signature,encode(payload),kind,user_id()))


def migrate(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS testing_versions (
        id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),name TEXT NOT NULL,
        name_key TEXT NOT NULL,created_by TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(project_id,name_key));
      CREATE TABLE IF NOT EXISTS testing_batch_versions (
        task_id TEXT PRIMARY KEY REFERENCES tasks(id),version_id TEXT NOT NULL REFERENCES testing_versions(id));
      CREATE TABLE IF NOT EXISTS testing_case_snapshots (
        id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),task_id TEXT NOT NULL REFERENCES tasks(id),
        task_revision INTEGER NOT NULL,case_status TEXT NOT NULL,case_count INTEGER NOT NULL,
        signature TEXT NOT NULL,payload TEXT NOT NULL,capture_kind TEXT NOT NULL,created_by TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP);
      CREATE INDEX IF NOT EXISTS testing_snapshot_task ON testing_case_snapshots(task_id);
      CREATE INDEX IF NOT EXISTS testing_snapshot_project ON testing_case_snapshots(project_id);
      CREATE TABLE IF NOT EXISTS testing_library_deleted(kind TEXT NOT NULL,resource_id TEXT NOT NULL,project_id TEXT NOT NULL,deleted_by TEXT NOT NULL,deleted_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(kind,resource_id));
      CREATE TABLE IF NOT EXISTS testing_library_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    ''')
    # One-time additive backfill; old task revisions and content remain untouched.
    if not db.execute("SELECT 1 FROM testing_library_meta WHERE key='backfilled'").fetchone():
        for row in db.execute('SELECT id FROM tasks').fetchall():capture(db,row['id'],'migration')
        db.execute("INSERT INTO testing_library_meta VALUES('backfilled','1')")


class TestingLibrary:
    def __init__(self,store):self.store=store

    def _check(self,studio,project,write=False,copying=False):
        self.store.check_project(studio,project)
        policy=Policy(self.store);scope={'studio':studio,'project':project}
        policy.require('node','view',node='testing:0',**scope)
        if write:
            policy.require('node','edit',node='testing:0',**scope)
            policy.require('content','create',department='testing',**scope)
        if copying:
            for resource,actions in [('node',('export','import')),('skill',('view','export','import'))]:
                for action in actions:policy.require(resource,action,node='testing:0',**scope)

    def _delete_check(self,studio,project):
        self._check(studio,project)
        Policy(self.store).require('content','delete',studio=studio,project=project,department='testing')
        Policy(self.store).require('node','delete',studio=studio,project=project,node='testing:0')

    def set_unassigned_version(self,studio,project,value):
        self._check(studio,project,True)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("""SELECT t.id FROM tasks t WHERE t.project_id=? AND NOT EXISTS(SELECT 1 FROM testing_batch_versions b WHERE b.task_id=t.id)
                AND NOT EXISTS(SELECT 1 FROM testing_library_deleted d WHERE d.kind='batch' AND d.resource_id=t.id)""",(project,)).fetchall()
            if not rows:raise ValueError('没有待设置版本的历史批次，请刷新')
            self._idle(db,[r['id'] for r in rows])
            version=self._version(db,project,value)
            for row in rows:
                db.execute('INSERT INTO testing_batch_versions VALUES(?,?)',(row['id'],version['id']))
                self.store._event(db,row['id'],'version_assigned','为历史批次设置项目版本：'+version['name'],0)
        return {'version':version,'count':len(rows)}

    def _idle(self,db,ids):
        for tid in ids:
            if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')",(tid,)).fetchone():raise ValueError('批次正在排队或运行，暂不能删除或变更版本')
            if db.execute("SELECT 1 FROM node_questions WHERE scope=? AND status IN ('queued','running')",('task:'+tid,)).fetchone():raise ValueError('节点助手正在排队或运行，请稍后重试')
            for table in ('publications','status_changes'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone() and db.execute('SELECT 1 FROM '+table+" WHERE task_id=? AND status='sending'",(tid,)).fetchone():raise ValueError('飞书请求正在发送，请稍后重试')

    def _delete_state(self,db,project,kind,identity):
        if db.execute('SELECT 1 FROM testing_library_deleted WHERE kind=? AND resource_id=?',(kind,identity)).fetchone():raise KeyError('内容已删除')
        if kind=='version':
            row=db.execute("SELECT name FROM testing_versions WHERE id=? AND project_id=? AND NOT EXISTS(SELECT 1 FROM testing_library_deleted d WHERE d.kind='version' AND d.resource_id=testing_versions.id)",(identity,project)).fetchone()
            if row is None:raise KeyError('版本不属于项目')
            rows=[dict(r) for r in db.execute('SELECT t.id,t.title,t.revision FROM tasks t JOIN testing_batch_versions b ON b.task_id=t.id WHERE t.project_id=? AND b.version_id=? ORDER BY t.id',(project,identity))]
            name=row['name']
        elif kind=='batch':
            row=self.store._task(db,project,identity);name=row['title'];rows=[{k:row[k] for k in ('id','title','revision')}]
            if db.execute('SELECT 1 FROM department_flows WHERE task_id=? AND archived=0',(identity,)).fetchone():raise ValueError('批次已绑定独立流程，请先归档该流程后再删除')
        else:raise ValueError('删除类型无效')
        self._idle(db,[r['id'] for r in rows])
        return {'kind':kind,'id':identity,'name':name,'batches':rows}

    def delete_preview(self,studio,project,kind,identity):
        self._delete_check(studio,project)
        with self.store.connection() as db:state=self._delete_state(db,project,kind,identity)
        return {**state,'token':hashlib.sha256(encode(state).encode()).hexdigest()}

    def delete(self,studio,project,kind,identity,value):
        self._delete_check(studio,project)
        if value.get('confirmed') is not True:raise ValueError('请在二次确认框中确认删除')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');state=self._delete_state(db,project,kind,identity)
            if value.get('token')!=hashlib.sha256(encode(state).encode()).hexdigest():raise ValueError('删除范围已变化，请重新确认')
            db.execute('INSERT INTO testing_library_deleted(kind,resource_id,project_id,deleted_by) VALUES(?,?,?,?)',(kind,identity,project,user_id()))
            if kind=='version':
                db.execute('DELETE FROM testing_batch_versions WHERE version_id=?',(identity,))
                db.execute('UPDATE testing_versions SET name_key=? WHERE id=?',('deleted:'+identity,identity))
                for row in state['batches']:self.store._event(db,row['id'],'version_deleted','删除项目版本：'+state['name']+'；批次保留为未分配版本',0)
            else:
                db.execute("UPDATE testing_automation SET enabled=0 WHERE task_id=?",(identity,))
                self.store._event(db,identity,'batch_deleted','删除测试批次：'+state['name']+'；历史证据保留',0)
        return {'deleted':True,'kind':kind,'id':identity}

    def _new_version(self,db,project,name):
        if not isinstance(name,str) or not 1<=len(name.strip())<=60:raise ValueError('版本名称须为1至60字')
        name=name.strip()
        if db.execute('SELECT 1 FROM testing_versions WHERE project_id=? AND name_key=?',(project,name.casefold())).fetchone():
            raise ValueError('版本已存在，请选择已有版本')
        value={'id':uuid.uuid4().hex,'name':name}
        db.execute('INSERT INTO testing_versions(id,project_id,name,name_key,created_by) VALUES(?,?,?,?,?)',
                   (value['id'],project,name,name.casefold(),user_id()))
        return value

    def create_version(self,studio,project,name):
        self._check(studio,project,True)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');return self._new_version(db,project,name)

    def versions(self,studio,project):
        self._check(studio,project)
        with self.store.connection() as db:
            return {'items':[dict(r) for r in db.execute("SELECT v.id,v.name,(SELECT COUNT(*) FROM testing_batch_versions b WHERE b.version_id=v.id AND NOT EXISTS(SELECT 1 FROM testing_library_deleted x WHERE x.kind='batch' AND x.resource_id=b.task_id)) AS batch_count FROM testing_versions v WHERE v.project_id=? AND NOT EXISTS(SELECT 1 FROM testing_library_deleted d WHERE d.kind='version' AND d.resource_id=v.id) ORDER BY v.rowid DESC",(project,))]}

    def rename_version(self,studio,project,identity,value):
        self._check(studio,project,True)
        name=value.get('name')
        if not isinstance(name,str) or not 1<=len(name.strip())<=60:raise ValueError('版本名称须为1至60字')
        name=name.strip()
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT name FROM testing_versions WHERE id=? AND project_id=? AND NOT EXISTS(SELECT 1 FROM testing_library_deleted d WHERE d.kind='version' AND d.resource_id=testing_versions.id)",(identity,project)).fetchone()
            if row is None:raise KeyError('版本不属于当前项目')
            if row['name']!=value.get('expected_name'):raise ValueError('版本名称已变化，请刷新后重试')
            if db.execute('SELECT 1 FROM testing_versions WHERE project_id=? AND name_key=? AND id<>?',(project,name.casefold(),identity)).fetchone():raise ValueError('版本名称已存在')
            db.execute('UPDATE testing_versions SET name=?,name_key=? WHERE id=?',(name,name.casefold(),identity))
            for task in db.execute('SELECT task_id FROM testing_batch_versions WHERE version_id=?',(identity,)).fetchall():
                self.store._event(db,task['task_id'],'version_renamed','版本重命名：'+row['name']+' → '+name,0)
        return {'id':identity,'name':name}

    def batches(self,studio,project,version_id=''):
        self._check(studio,project)
        return {'items':[t for t in self.store.tasks(project) if not version_id or (not t['version_id'] if version_id=='unassigned' else t['version_id']==version_id)]}

    def rename_batch(self,studio,project,identity,value):
        self._check(studio,project,True)
        title=value.get('title')
        if not isinstance(title,str) or not 1<=len(title.strip())<=120:raise ValueError('批次名称须为1至120字')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');row=self.store._task(db,project,identity)
            if row['title']!=value.get('expected_title'):raise ValueError('批次名称已变化，请刷新后重试')
            db.execute('UPDATE tasks SET title=? WHERE id=?',(title.strip(),identity))
            self.store._event(db,identity,'batch_renamed','批次重命名：'+row['title']+' → '+title.strip(),0)
        return {'id':identity,'title':title.strip()}

    def _version(self,db,project,value):
        if value.get('version_id'):
            if value.get('version_name'):raise ValueError('已有版本与新版本只能选择一种')
            row=db.execute("SELECT id,name FROM testing_versions WHERE id=? AND project_id=? AND NOT EXISTS(SELECT 1 FROM testing_library_deleted d WHERE d.kind='version' AND d.resource_id=testing_versions.id)",(value['version_id'],project)).fetchone()
            if row is None:raise KeyError('版本不属于当前项目')
            return dict(row)
        return self._new_version(db,project,value.get('version_name'))

    def create_batch(self,studio,project,value):
        if not isinstance(value,dict):raise ValueError('请求必须是对象')
        copying=bool(value.get('snapshot_id'));self._check(studio,project,True,copying)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshot=None
            if copying:
                row=db.execute('SELECT payload FROM testing_case_snapshots WHERE id=? AND project_id=?',(value['snapshot_id'],project)).fetchone()
                if row is None:raise KeyError('用例快照不属于当前项目')
                snapshot=json.loads(row['payload'])
                if not snapshot['skill'].get('content') and value.get('use_current_skill') is not True:
                    raise ValueError('此旧快照未保存原 Skill，请明确同意使用当前默认 Skill 后再复制')
            version=self._version(db,project,value)
            t=self.store.create_task(project,value.get('title'),connection=db);tid=t['id']
            db.execute('INSERT INTO testing_batch_versions VALUES(?,?)',(tid,version['id']))
            if snapshot:
                id_map={r['id']:uuid.uuid4().hex for r in snapshot['requirements']}
                # Preserve source gaps/provenance and remap exact source ID references.
                def remap(v):
                    if isinstance(v,str):return id_map.get(v,v)
                    if isinstance(v,list):return [remap(x) for x in v]
                    if isinstance(v,dict):return {k:remap(x) for k,x in v.items()}
                    return v
                for r in snapshot['requirements']:
                    db.execute('INSERT INTO requirements(id,task_id,source,version,content,sha256,metadata) VALUES(?,?,?,?,?,?,?)',
                       (id_map[r['id']],tid,r['source'],1,r['content'],r['sha256'],encode(remap(r['metadata']))))
                artifact=remap(copy.deepcopy(snapshot['artifact']));artifact.pop('user_review',None)
                from server.requirements import validate_cases
                requirements=[dict(r) for r in db.execute('SELECT * FROM requirements WHERE task_id=?',(tid,))]
                artifact=validate_cases(artifact,requirements)
                artifact['copied_from_snapshot']=value['snapshot_id']
                skills=json.loads(t['node_skills'])
                chosen=snapshot['skill'] if snapshot['skill'].get('content') else skills['0']
                skills['0']=chosen
                db.execute('UPDATE tasks SET artifacts=?,node_skills=?,revision=revision+1 WHERE id=?',
                           (encode({'0':artifact}),encode(skills),tid))
                from server.core.skill_library import append_version
                append_version(db,self.store,project,'testing:0',chosen,'复制历史用例时显式导入 Skill 为独立版本',task=tid)
                capture(db,tid,'copied',chosen)
                self.store._event(db,tid,'case_copied','从历史用例快照复制为独立草稿；未继承审核、执行、Bug 或回归结论',0)
            self.store._event(db,tid,'version_assigned','测试批次归属版本：'+version['name'],0)
        return self.store.task(project,tid)

    def assign_version(self,studio,project,task_id,value):
        self._check(studio,project,True)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE');task=self.store._task(db,project,task_id)
            if type(value.get('revision')) is not int or value['revision']!=task['revision']:raise ValueError('批次已更新，请刷新后重试')
            if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')",(task_id,)).fetchone():raise ValueError('后台任务进行中，暂不能变更版本')
            version=self._version(db,project,value)
            db.execute('INSERT INTO testing_batch_versions VALUES(?,?) ON CONFLICT(task_id) DO UPDATE SET version_id=excluded.version_id',(task_id,version['id']))
            db.execute('UPDATE tasks SET revision=revision+1 WHERE id=?',(task_id,))
            self.store._event(db,task_id,'version_assigned','测试批次归属版本：'+version['name'],0)
        return self.store.task(project,task_id)

    def listing(self,studio,project,*,page=1,size=20,q='',version_id='',status=''):
        self._check(studio,project)
        if type(page) is not int or page<1 or type(size) is not int or size not in (10,20,50,100):raise ValueError('分页参数无效')
        if status not in ('','draft','confirmed'):raise ValueError('用例状态无效')
        where=["s.project_id=?","NOT EXISTS(SELECT 1 FROM testing_library_deleted d WHERE d.kind='batch' AND d.resource_id=t.id)"];args=[project]
        if q:where.append('instr(lower(t.title),?)>0');args.append(q.casefold())
        if version_id:where.append('b.version_id IS NULL' if version_id=='unassigned' else 'b.version_id=?');args.extend([] if version_id=='unassigned' else [version_id])
        if status:where.append('s.case_status=?');args.append(status)
        sql='''FROM testing_case_snapshots s JOIN tasks t ON t.id=s.task_id
            LEFT JOIN testing_batch_versions b ON b.task_id=t.id LEFT JOIN testing_versions v ON v.id=b.version_id AND NOT EXISTS(SELECT 1 FROM testing_library_deleted d WHERE d.kind='version' AND d.resource_id=v.id)
            WHERE s.rowid=(SELECT MAX(x.rowid) FROM testing_case_snapshots x WHERE x.task_id=s.task_id) AND '''+' AND '.join(where)
        with self.store.connection() as db:
            total=db.execute('SELECT COUNT(*) '+sql,args).fetchone()[0]
            items=[dict(r) for r in db.execute('''SELECT s.id AS snapshot_id,s.task_id,t.title,t.stage,t.status AS task_status,
                s.case_status,s.case_count,s.task_revision,s.created_at,v.id AS version_id,v.name AS version_name '''+sql+
                ' ORDER BY s.rowid DESC LIMIT ? OFFSET ?',args+[size,(page-1)*size])]
        return {'items':items,'total':total,'page':page,'size':size}

    def detail(self,studio,project,snapshot_id):
        self._check(studio,project)
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM testing_case_snapshots WHERE id=? AND project_id=?',(snapshot_id,project)).fetchone()
            if row is None:raise KeyError('用例快照不属于当前项目')
            result=dict(row);payload=json.loads(result.pop('payload'));result.update(payload)
            result['history']=[dict(r) for r in db.execute('SELECT id,task_revision,case_status,case_count,created_at FROM testing_case_snapshots WHERE task_id=? ORDER BY rowid DESC',(row['task_id'],))]
        policy=Policy(self.store)
        if not policy.allowed('skill','view',studio,project,node='testing:0'):result['skill']={'name':'无 Skill 查看权限','content':''}
        if not policy.allowed('node','view',studio,project,node='testing:1'):result['baseline']={}
        return result


def dispatch(parts,q,body,write,store):
    if len(parts)>=6 and parts[:2]==['api','studios'] and parts[3]=='projects':studio,project,tail=parts[2],parts[4],parts[5:]
    elif len(parts)>=4 and parts[:2]==['api','projects']:studio,project,tail=store.preferences()['active_studio_id'],parts[2],parts[3:]
    else:return False,None,None
    if not tail or tail[0]!='testing-library':return False,None,None
    if write and not isinstance(body,dict):raise ValueError('请求必须是对象')
    service=TestingLibrary(store);tail=tail[1:]
    if tail==['unassigned-version'] and write:result=service.set_unassigned_version(studio,project,body)
    elif len(tail)==3 and tail[0] in ('versions','batches') and tail[2] in ('delete-preview','delete'):
        kind='version' if tail[0]=='versions' else 'batch'
        if tail[2]=='delete-preview' and not write:result=service.delete_preview(studio,project,kind,tail[1])
        elif tail[2]=='delete' and write:result=service.delete(studio,project,kind,tail[1],body)
        else:raise KeyError('删除接口不存在')
    elif tail==['versions']:result=service.create_version(studio,project,body.get('name')) if write else service.versions(studio,project)
    elif len(tail)==3 and tail[0]=='versions' and tail[2]=='rename' and write:result=service.rename_version(studio,project,tail[1],body)
    elif tail==['batches']:result=service.create_batch(studio,project,body) if write else service.batches(studio,project,q.get('version',[''])[0])
    elif len(tail)==3 and tail[0]=='batches' and tail[2]=='rename' and write:result=service.rename_batch(studio,project,tail[1],body)
    elif len(tail)==3 and tail[0]=='batches' and tail[2]=='version' and write:result=service.assign_version(studio,project,tail[1],body)
    elif tail==['cases'] and not write:result=service.listing(studio,project,page=int(q.get('page',['1'])[0]),size=int(q.get('size',['20'])[0]),q=q.get('q',[''])[0],version_id=q.get('version',[''])[0],status=q.get('status',[''])[0])
    elif len(tail)==2 and tail[0]=='cases' and not write:result=service.detail(studio,project,tail[1])
    else:raise KeyError('用例库接口不存在')
    return True,result,{'studio':studio,'project':project}
