"""Personal snapshots and an explicit, backend-only public-area connection."""
import json
import re
import uuid
from urllib.parse import urlencode,parse_qs
from server.core.identity import user_id
from server.core.permissions import Policy
from server.core.public_area.schema import migrate
from server.core.public_area.packages import encode,sha,validate,visible,redact,text
from server.core.public_area.client import Remote,RemoteError,validate_url
from server.core.public_area.service import Conflict


def coordinate(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):raise ValueError('公区标识不合法')
    return value


def clean(value, *, task_config=False):
    # Export results, never execution traces, credentials or private connection records.
    private={'password','token','api_key','webhook','secret','authorization','repository','binding','local_path','download_url',
             'logs','log','events','stdout','stderr','raw','raw_output','model_output','prompt','messages','requests','environment',
             'quote','source_code','snippet','source_text','publication_plan','publication_ledger','field_preview','remote_checks'}
    # Saved block prompts are user-authored workflow configuration, not model traces.
    if task_config:private.remove('prompt')
    if isinstance(value,dict):return {k:clean(v,task_config=task_config) for k,v in value.items() if k.lower() not in private}
    if isinstance(value,list):return [clean(v,task_config=task_config) for v in value]
    return redact(value)


def qa_result(artifact,stage):
    """Export only known result sections, never a complete task or future trace fields."""
    fields={
        '0':('points','cases','gaps','ambiguities','coverage','generation_method','user_review'),
        '1':('results','counts','method','scope','code_fingerprint','case_mapping','unmapped_cases'),
        '2':('roots','assignments','exclusions','groups','unresolved','suggestions','unanalysed','scope','filing_scope'),
        '3':('groups','result_ids','excluded','scope'),
        '4':('drafts','observations','scope','publication_complete','target_schema_verified'),
        '5':('roots','execution','scope','probability_reason','remote_state_changed'),
    }
    return clean({k:artifact[k] for k in fields[stage] if k in artifact})

class LocalPublic:
    def __init__(self,store):self.store=store;self.policy=Policy(store);migrate(store)
    def scope(self,s,p):
        self.store.check_project(s,p);self.policy.require('project','view',studio=s,project=p)
    def connection(self):
        with self.store.connection() as db:r=db.execute('SELECT * FROM public_connections WHERE actor=?',(user_id(),)).fetchone()
        return {'connected':bool(r),'server_url':r['server_url'] if r else '',
                'user':json.loads(r['remote_user']) if r else None,'allow_lan_http':bool(r['allow_lan_http']) if r else False}
    def client(self):
        with self.store.connection() as db:r=db.execute('SELECT * FROM public_connections WHERE actor=?',(user_id(),)).fetchone()
        if not r:raise ValueError('请先连接公区服务器')
        return Remote(r['server_url'],r['session'],bool(r['allow_lan_http']))
    def connect(self,body,register=False):
        self.policy.require('model','view')  # active identity only; no server administration privilege.
        url=validate_url(body.get('server_url'),body.get('allow_lan_http') is True);remote=Remote(url,allow_lan_http=body.get('allow_lan_http') is True)
        if remote.request('/api/runtime').get('mode')!='public':raise ValueError('目标必须是独立公区服务，请使用 --mode public 启动')
        credentials={k:body.get(k) for k in ('username','password','name')}
        if register:return remote.request('/api/auth/register',credentials)
        result=remote.request('/api/auth/login',credentials)
        if not remote.cookie:raise ValueError('公区未返回有效登录会话')
        remote_user=result['user'];old=self.connection()
        with self.store.connection() as db:
            if old['server_url']!=url or old['user'] and old['user']['id']!=remote_user['id']:db.execute('DELETE FROM public_bindings WHERE actor=?',(user_id(),))
            db.execute('INSERT OR REPLACE INTO public_connections VALUES(?,?,?,?,?)',(user_id(),url,remote.cookie,encode(remote_user),int(body.get('allow_lan_http') is True)))
        return self.connection()
    def disconnect(self):
        try:self.client().request('/api/auth/logout',{})
        except (ValueError,RemoteError):pass
        with self.store.connection() as db:
            db.execute('DELETE FROM public_connections WHERE actor=?',(user_id(),));db.execute('DELETE FROM public_bindings WHERE actor=?',(user_id(),))
        return self.connection()
    def discover(self,query):
        remote=self.client();s=query.get('studio','');p=query.get('project','')
        if not s:return remote.request('/api/studios')
        coordinate(s)
        if not p:return remote.request('/api/studios/'+s+'/projects?'+urlencode({'size':5,'page':query.get('page',1),'q':query.get('q','')}))
        coordinate(p);return remote.request(f'/api/studios/{s}/projects/{p}/public/versions')
    def bind(self,s,p,body):
        self.scope(s,p);remote=self.client()
        rs,rp,rv=[coordinate(body.get(k)) for k in ('studio_id','project_id','version_id')]
        remote.request(f'/api/studios/{rs}/projects/{rp}')
        versions=remote.request(f'/api/studios/{rs}/projects/{rp}/public/versions')['items']
        if not any(v['id']==rv for v in versions):raise ValueError('公区版本不存在')
        with self.store.connection() as db:db.execute('INSERT OR REPLACE INTO public_bindings VALUES(?,?,?,?,?,?)',(user_id(),p,remote.url,rs,rp,rv))
        return self.binding(s,p)
    def binding(self,s,p):
        self.scope(s,p);remote=self.client()
        with self.store.connection() as db:r=db.execute('SELECT * FROM public_bindings WHERE actor=? AND project_id=? AND server_url=?',(user_id(),p,remote.url)).fetchone()
        if not r:raise ValueError('请先绑定公区工作室、项目和版本')
        return {**dict(r),'remote_actor':self.connection()['user']['id']}
    @staticmethod
    def base(binding):return '/api/studios/'+binding['studio_id']+'/projects/'+binding['remote_project_id']+'/public'
    def remote(self,s,p,tail='items',query=None,body=None):
        binding=self.binding(s,p)
        return self.client().request(self.base(binding)+'/'+tail+('?' +urlencode(query) if query else ''),body)
    def sources(self,s,p):
        self.scope(s,p)
        from server.core.project_nodes import project_records
        from server.core.node_blocks.service import Builder
        nodes=[{'node':n['id'],'title':n['definition'][0],'department':n['id'].split(':')[0]} for n in project_records(self.store,p)
               if not n['archived'] and self.policy.allowed('node','export',s,p,node=n['id'])]
        from server.studio_workspaces import Workspaces
        summary=Workspaces(self.store).summary(s,p)
        tasks=[{'id':t['id'],'title':t['title']} for t in summary['tasks']] if any(n['department']=='testing' for n in nodes) else []
        flows=Builder(self.store).flows(s,p)['items'] if self.policy.allowed('workflow','export',s,p) else []
        return {'nodes':nodes,'tasks':tasks,'flows':[{'id':f['id'],'name':f['name']} for f in flows]}
    def snapshot(self,s,p,source,options):
        self.scope(s,p)
        if not isinstance(source,dict):raise ValueError('请选择本机来源')
        node=source.get('node');scope=dict(studio=s,project=p,node=node)
        from server.studio_catalog import node_definition
        d,_,_=node_definition(node,self.store,p)
        self.policy.require('node','export',**scope)
        kind=source.get('type');includes=[];extra=[]
        from server.studio_workspaces import Workspaces
        if kind=='node':
            value=Workspaces(self.store).get(s,p,node);content=value['deliverable'];revision=value['revision'];identity=node
            inputs=value['inputs'];skill=value['skill']['content']
            if not content.strip() and not options.get('include_skill'):raise ValueError('当前节点没有已保存交付物')
        elif kind=='testing':
            if not re.fullmatch(r'testing:[0-5]',node):raise ValueError('请选择测试固定节点')
            value=self.store.task(p,source.get('task_id'));stage=node.split(':')[1];artifact=value['artifacts'].get(stage)
            if artifact is None:raise ValueError('该批次节点尚无结果')
            content=encode(qa_result(artifact,stage));revision=value['revision'];identity=value['id']+':'+node
            inputs=''
            if options.get('include_requirements'):
                self.policy.require('node','export',studio=s,project=p,node='testing:0')
                inputs=encode([{'source':r['source'],'version':r['version'],'content':r['content']} for r in value['requirements']])
            skill=value['node_skills'][stage]['content']
        elif kind=='workflow':
            from server.core.node_blocks.service import Builder
            self.policy.require('workflow','export',studio=s,project=p)
            value=Builder(self.store).flow(s,p,source.get('flow_id'));revision=value['revision'];identity=value['id']
            # A flow exports configuration only after all included node scopes authorize export.
            for n in value['nodes']:
                key='wf:'+value['id']+':'+n['id']
                self.policy.require('workflow_node','export',studio=s,project=p,node=key)
                if n.get('source_node'):self.policy.require('node','export',studio=s,project=p,node=n['source_node'])
                if options.get('include_skill'):
                    self.policy.require('workflow_skill','export',studio=s,project=p,node=key)
                    if n.get('source_node'):self.policy.require('skill','export',studio=s,project=p,node=n['source_node'])
            blocks=json.loads(encode(value['blocks']))
            def select_blocks(items):
                for b in items:
                    config=b.get('config',{})
                    for k in list(config):
                        if ('skill' in k and not options.get('include_skill')) or ('input' in k and not options.get('include_requirements')):config.pop(k)
                    select_blocks(config.get('blocks',[]))
            select_blocks(blocks)
            exported={'name':value['name'],'description':value.get('description',''),'blocks':blocks}
            if options.get('include_skill'):
                exported['skills']=[{'node_id':n['id'],'name':n['skill']['name'],'content':n['skill']['content']} for n in value['nodes']]
            content=encode(clean(exported,task_config=True));inputs='';skill=''
            includes.append('workflow')
        elif kind=='skill':
            value=Workspaces(self.store).get(s,p,node);content='';revision=value['revision'];identity=node;inputs='';skill=value['skill']['content']
        else:raise ValueError('不支持的本机来源')
        if options.get('include_requirements'):
            self.policy.require('node','export',**scope);includes.append('requirements')
            if inputs:extra.append('## 选定的需求 / 输入\n'+inputs)
        if options.get('include_skill') or kind=='skill':
            self.policy.require('skill','export',**scope);includes.append('skill')
            if skill:extra.append('## 选定的 Skill（文本）\n'+skill)
        content='\n\n'.join([content,*extra]).strip()
        # Source digest covers only the selected material; unrelated logs aren't exported.
        return {'content':content,'revision':revision,'identity':identity,'department':d['id'],'node':node,'includes':includes,
                'digest':sha({'revision':revision,'content':content,'includes':includes})}
    def preview(self,s,p,body):
        binding=self.binding(s,p);source=body.get('source');snapshot=self.snapshot(s,p,source,body)
        kind=body.get('kind') or ('skill' if source['type']=='skill' else 'workflow' if source['type']=='workflow' else 'test_cases' if source['type']=='testing' and source['node']=='testing:0' else 'result')
        attachments=body.get('attachments',[])
        package=validate(dict(schema_version=1,title=body.get('title'),description=body.get('description',''),version_id=binding['version_id'],
            department=snapshot['department'],node=snapshot['node'],kind=kind,source={'id':snapshot['identity'],'revision':snapshot['revision'],'digest':snapshot['digest']},
            content=snapshot['content'],includes=snapshot['includes']+(['attachments'] if attachments else []),attachments=attachments))
        identity=uuid.uuid4().hex;target=body.get('publication_id','');expected=body.get('expected_revision',0)
        if target:coordinate(target)
        if type(expected) is not int or expected<0 or bool(target)!=(expected>0):raise ValueError('公区目标修订不合法')
        options={k:body.get(k) is True for k in ('include_requirements','include_skill')}
        with self.store.connection() as db:
            db.execute('INSERT INTO public_drafts(id,actor,project_id,server_url,binding,source,source_hash,package,publication_id,expected_revision) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (identity,user_id(),p,binding['server_url'],encode(binding),encode({'source':source,**options}),snapshot['digest'],encode(package),target,expected))
        return self.draft(s,p,identity)
    def row(self,s,p,identity):
        self.scope(s,p)
        with self.store.connection() as db:r=db.execute('SELECT * FROM public_drafts WHERE id=? AND actor=? AND project_id=?',(identity,user_id(),p)).fetchone()
        if not r:raise KeyError('本机发布草稿不存在')
        return dict(r)
    def draft(self,s,p,identity):
        r=self.row(s,p,identity)
        return {'id':r['id'],'status':r['status'],'error':r['error'],'package':visible(json.loads(r['package'])),
                'publication_id':r['publication_id'],'expected_revision':r['expected_revision'],'result':json.loads(r['result']) if r['result'] else None}
    def drafts(self,s,p):
        self.scope(s,p)
        with self.store.connection() as db:rows=db.execute('SELECT id,status,error,created_at,publication_id,expected_revision,package FROM public_drafts WHERE actor=? AND project_id=? ORDER BY rowid DESC LIMIT 50',(user_id(),p)).fetchall()
        return {'items':[{k:r[k] for k in ('id','status','error','created_at','publication_id','expected_revision')}|{'title':json.loads(r['package'])['title']} for r in rows]}
    def publish(self,s,p,identity,confirmed):
        if confirmed is not True:raise ValueError('请先确认预览内容无误')
        r=self.row(s,p,identity);binding=self.binding(s,p);frozen=json.loads(r['binding'])
        if any(binding[k]!=frozen[k] for k in ('server_url','studio_id','remote_project_id','version_id','remote_actor')):raise Conflict('账号或公区映射已改变，请重新预览')
        remote=self.client();base=self.base(binding);operation='local-'+identity
        def remember(status,result=None,error=''):
            with self.store.connection() as db:db.execute('UPDATE public_drafts SET status=?,result=?,error=? WHERE id=? AND actor=?',(status,encode(result) if result else None,error,identity,user_id()))
        try:
            # Resolve an ambiguous commit before checking a now-changed local source.
            if r['status'] in ('unknown','published'):
                try:
                    result=remote.request(base+'/operations/'+operation)
                    if result['status']=='published':remember('published',result);return result
                except RemoteError as exc:
                    if exc.status!=404:raise
            selection=json.loads(r['source']);snapshot=self.snapshot(s,p,selection['source'],selection)
            if snapshot['digest']!=r['source_hash']:raise Conflict('本机来源已改变，请重新预览后确认')
            result=remote.request(base+'/stage',{'operation_id':operation,'package':json.loads(r['package']),
                'publication_id':r['publication_id'],'expected_revision':r['expected_revision']})
            if result['status']!='published':result=remote.request(base+'/operations/'+operation+'/commit',{})
            remember('published',result);return result
        except RemoteError as exc:
            status='unknown' if not exc.status or exc.status>=500 else 'failed';remember(status,error=str(exc))
            if exc.status==409:raise Conflict(str(exc)) from None
            return {'id':identity,'status':status,'error':str(exc)}
    def copy(self,s,p,item,revision):
        self.scope(s,p);coordinate(item)
        package=self.remote(s,p,'items/'+item+'/export',{'revision':revision})
        validated=validate(package['package']);identity=uuid.uuid4().hex
        self.policy.require('node','import',studio=s,project=p,node=validated['node'])
        with self.store.connection() as db:db.execute('INSERT INTO public_copies(id,actor,project_id,server_url,publication_id,revision,package) VALUES(?,?,?,?,?,?,?)',
            (identity,user_id(),p,self.client().url,item,revision,encode(validated)))
        return {'id':identity,'publication_id':item,'revision':revision,'package':visible(validated),'inert':True}
    def copies(self,s,p,identity=None):
        self.scope(s,p)
        with self.store.connection() as db:rows=db.execute('SELECT * FROM public_copies WHERE actor=? AND project_id=?'+(' AND id=?' if identity else '')+' ORDER BY rowid DESC',(user_id(),p,identity) if identity else (user_id(),p)).fetchall()
        return {'items':[{'id':r['id'],'server_url':r['server_url'],'publication_id':r['publication_id'],'revision':r['revision'],'created_at':r['created_at'],'package':visible(json.loads(r['package'])),'inert':True} for r in rows]}


def dispatch(handler,parts,query,body,write,store):
    if len(parts)<6 or parts[:2]!=['api','studios'] or parts[3]!='projects' or parts[5]!='public-local':return False
    service=LocalPublic(store);s,p=parts[2],parts[4];service.scope(s,p);tail=parts[6:];q={k:v[0] for k,v in parse_qs(query).items()}
    if tail==['connection'] and not write:result=service.connection()
    elif tail==['connect'] and write:result=service.connect(body)
    elif tail==['register'] and write:result=service.connect(body,register=True)
    elif tail==['disconnect'] and write:result=service.disconnect()
    elif tail==['discover'] and not write:result=service.discover(q)
    elif tail==['binding']:result=service.bind(s,p,body) if write else service.binding(s,p)
    elif tail==['sources'] and not write:result=service.sources(s,p)
    elif tail==['preview'] and write:result=service.preview(s,p,body)
    elif tail==['drafts'] and not write:result=service.drafts(s,p)
    elif len(tail)==2 and tail[0]=='drafts' and not write:result=service.draft(s,p,tail[1])
    elif len(tail)==3 and tail[0]=='drafts' and tail[2]=='publish' and write:result=service.publish(s,p,tail[1],body.get('confirmed'))
    elif tail==['copies'] and not write:result=service.copies(s,p)
    elif tail==['copy'] and write:result=service.copy(s,p,body.get('id'),body.get('revision'))
    elif tail[:1]==['remote']:
        endpoint='/'.join(tail[1:]);allowed=not write and (endpoint in ('items','versions') or re.fullmatch(r'items/[a-zA-Z0-9_-]+(?:/export|/attachments/[0-9]+)?',endpoint))
        allowed=allowed or write and re.fullmatch(r'items/[a-zA-Z0-9_-]+/withdraw',endpoint)
        if not allowed:raise KeyError('公区读取接口不存在')
        result=service.remote(s,p,endpoint,q,body if write else None)
    else:raise KeyError('本机公区接口不存在')
    handler.send_json(200,result);return True
