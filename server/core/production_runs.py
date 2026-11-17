"""Durable, explicitly delegated production orchestration using trusted executors.

Completed steps are checkpoints. In-flight model/tool work may finish after pause;
its result is not approved or advanced until the delegated run resumes. Restarts
pause runs rather than replaying potentially side-effecting builders.
"""
import hashlib
import json
import logging
import sqlite3
from pathlib import Path
import threading
import uuid
import zipfile
from server.core.identity import current_user, user_id
from server.core.permissions import Policy


class RunStopped(Exception):
    pass


def migrate(store):
    with store.connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS production_runs (
          id TEXT PRIMARY KEY,studio_id TEXT NOT NULL,project_id TEXT NOT NULL REFERENCES projects(id),
          actor TEXT NOT NULL,name TEXT NOT NULL,brief TEXT NOT NULL,status TEXT NOT NULL,
          request_id TEXT NOT NULL DEFAULT '',delegation TEXT NOT NULL,steps TEXT NOT NULL,
          artifacts TEXT NOT NULL DEFAULT '[]',gaps TEXT NOT NULL DEFAULT '[]',
          qa_result TEXT NOT NULL DEFAULT '{}',build_result TEXT NOT NULL DEFAULT '{}',summary TEXT NOT NULL DEFAULT '',error TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE UNIQUE INDEX IF NOT EXISTS production_request ON production_runs(project_id,actor,request_id) WHERE request_id!='';
        CREATE TABLE IF NOT EXISTS production_events (
          id INTEGER PRIMARY KEY,run_id TEXT NOT NULL REFERENCES production_runs(id),
          action TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        if 'qa_result' not in {r['name'] for r in db.execute('PRAGMA table_info(production_runs)')}:
            db.execute("ALTER TABLE production_runs ADD COLUMN qa_result TEXT NOT NULL DEFAULT '{}'")


class ProductionRuns:
    def __init__(self, store, registry, builder=None, source_reviewer=None, model_factory=None):
        self.store,self.registry,self.builder=store,registry,builder
        self.source_reviewer,self.model_factory=source_reviewer,model_factory
        self.lock=threading.Lock()
        self.shutdown=threading.Event()
        migrate(store)
        self.root=(store.path.parent/'production-artifacts').resolve()

    def _require(self, studio, project, *, write=False):
        self.store.check_project(studio,project)
        for department in ('product','design','development'):
            for i in range(4):
                for action in (('view','edit','execute','approve') if write else ('view',)):
                    Policy(self.store).require('node',action,studio=studio,project=project,node=f'{department}:{i}')
        for i in (0,1,2,4,5):
            for action in (('view','edit','execute','approve') if write else ('view',)):
                Policy(self.store).require('node',action,studio=studio,project=project,node=f'testing:{i}')

    def _row(self, studio, project, identity):
        self.store.check_project(studio,project)
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM production_runs WHERE id=? AND studio_id=? AND project_id=?',(identity,studio,project)).fetchone()
        if row is None:raise KeyError('生产流程不存在')
        return dict(row)

    def _event(self, db, identity, action, detail):
        db.execute('INSERT INTO production_events(run_id,action,detail) VALUES(?,?,?)',(identity,action,str(detail)[:4000]))

    def _require_create(self, studio, project):
        self._require(studio,project,write=True)
        for department in ('product','design','development'):
            Policy(self.store).require('department','edit',studio=studio,project=project,department=department)
            Policy(self.store).require('node','create',studio=studio,project=project,department=department)

    def create(self, studio, project, value):
        self._require_create(studio,project)
        if value.get('delegation') is not True:raise ValueError('需要明确授权自动运行及委托审核 delegation=true')
        brief=value.get('brief') or value.get('idea')
        if not isinstance(brief,str) or not 1<=len(brief.strip())<=24000:raise ValueError('游戏想法须为1至24000字')
        name=value.get('name') or brief.strip()[:60]
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:raise ValueError('名称须为1至120字')
        request=str(value.get('request_id') or '')[:120]
        if request:
            with self.store.connection() as db:prior=db.execute('SELECT id FROM production_runs WHERE project_id=? AND actor=? AND request_id=?',(project,user_id(),request)).fetchone()
            if prior:return self.get(studio,project,prior['id'])
        from server.studio_catalog import node_definition
        for d in ('product','design','development'):
            for i in range(4):
                if self.registry.get(f'{d}:{i}',store=self.store,project=project) is None:raise ValueError('缺少真实部门执行器：'+d)
        identity=uuid.uuid4().hex
        steps=[]
        for d in ('product','design','development'):
            for i in range(4):
                node=f'{d}:{i}'
                definition=node_definition(node,self.store,project)
                steps.append({'id':node,'node_id':node,'department':d,'name':definition[2][0], 'status':'pending','output':'','error':None,'flow_id':'','job_id':'','started_at':None,'finished_at':None})
        for node,title in (('development:build','真实工程与APK构建'),('testing:0','生成结构化用例'),('testing:1','执行源码与构建检查'),('testing:2','归因真实发现'),('testing:4','准备内部缺陷草稿'),('testing:5','核对回归适用性')):
            steps.append({'id':node,'node_id':'development:3' if node.startswith('development') else node,'department':node.split(':')[0],'name':title,'status':'pending','output':'','error':None,'started_at':None,'finished_at':None})
        delegation={'actor':user_id(),'automatic_execution':True,'automatic_review':True,'external_publish':False,'scope':'this production run only'}
        with self.store.connection() as db:
            try:
                db.execute('INSERT INTO production_runs(id,studio_id,project_id,actor,name,brief,status,request_id,delegation,steps) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (identity,studio,project,user_id(),name.strip(),brief.strip(),'queued',request,json.dumps(delegation),json.dumps(steps,ensure_ascii=False)))
            except sqlite3.IntegrityError:
                prior=db.execute('SELECT id FROM production_runs WHERE project_id=? AND actor=? AND request_id=?',(project,user_id(),request)).fetchone() if request else None
                if prior is None:raise
                identity=prior['id']
            else:self._event(db,identity,'delegation','用户明确委托自动执行与审核；不等于人工质量验收，不授权Git或外部发布')
        return self.get(studio,project,identity)

    def get(self, studio, project, identity):
        self._require(studio,project)
        row=self._row(studio,project,identity)
        for key in ('steps','artifacts','gaps','delegation'):row[key]=json.loads(row[key])
        row.pop('build_result',None);row['qa']=json.loads(row.pop('qa_result','{}'));row.pop('actor',None)
        with self.store.connection() as db:row['events']=[dict(r) for r in db.execute('SELECT action,detail,created_at FROM production_events WHERE run_id=? ORDER BY id',(identity,))]
        row['stages']=row['steps']
        complete=sum(s['status']=='completed' for s in row['steps'])
        active=next((s for s in row['steps'] if s['status']!='completed'),None)
        row['progress']={'completed':complete,'total':len(row['steps']),'current':active['name'] if active else None}
        writable=True
        try:self._require(studio,project,write=True)
        except PermissionError:writable=False
        actions={'queued':['pause','cancel'],'running':['pause','cancel'],'paused':['resume','cancel'],'failed':['retry','cancel'],'completed':[],'cancelled':[]}
        row['allowed_actions']=actions[row['status']] if writable else []
        row['capabilities']={'manage':writable}
        for artifact in row['artifacts']:
            artifact.pop('path',None)
            artifact['download_url']=f'/api/studios/{studio}/projects/{project}/production-runs/{identity}/artifacts/{artifact["id"]}'
        return row

    def listing(self, studio, project):
        self._require(studio,project)
        with self.store.connection() as db:ids=[r['id'] for r in db.execute('SELECT id FROM production_runs WHERE studio_id=? AND project_id=? ORDER BY rowid DESC LIMIT 100',(studio,project))]
        items=[self.get(studio,project,i) for i in ids]
        can_create=True
        try:self._require_create(studio,project)
        except PermissionError:can_create=False
        return {'items':items,'runs':items,'can_create':can_create,'readiness':{'delegation_required':True,'external_research':False,'figma_write':False,'git_write':False}}

    def action(self, studio, project, identity, action):
        self._require(studio,project,write=True)
        self._row(studio,project,identity)
        if action in ('resume','retry') and self.lock.locked():raise ValueError('当前步骤仍在停止中，请稍后恢复')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=dict(db.execute('SELECT * FROM production_runs WHERE id=?',(identity,)).fetchone())
            permitted={'pause':('queued','running'),'resume':('paused',),'retry':('failed',),'cancel':('queued','running','paused','failed')}
            if action not in permitted or row['status'] not in permitted[action]:raise ValueError('当前状态不能执行此动作')
            status={'pause':'paused','resume':'queued','retry':'queued','cancel':'cancelled'}[action]
            steps=json.loads(row['steps'])
            if action in ('resume','retry'):
                for step in steps:
                    if step['status'] in ('running','failed'):step.update(status='pending',error=None)
            db.execute('UPDATE production_runs SET status=?,steps=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?',(status,json.dumps(steps,ensure_ascii=False),identity))
            self._event(db,identity,action,'操作者 '+user_id()+'；当前外部调用可能延迟停止，后续节点不会派发')
        return self.get(studio,project,identity)

    def recover(self):
        with self.store.connection() as db:
            rows=db.execute("SELECT * FROM production_runs WHERE status='running'").fetchall()
            for row in rows:
                db.execute("UPDATE production_runs SET status='paused',error='服务中断；确认后恢复未完成步骤',updated_at=CURRENT_TIMESTAMP WHERE id=?",(row['id'],))
                self._event(db,row['id'],'interrupted','服务重启，未自动重放当前工具步骤')
                steps=json.loads(row['steps']);step=next((s for s in steps if s['status']!='completed'),None)
                if step:self._notify(db,dict(row),step,'interrupted')
        return len(rows)

    def artifact(self, studio, project, identity, artifact_id):
        self._require(studio,project)
        row=self._row(studio,project,identity)
        entry=next((a for a in json.loads(row['artifacts']) if a['id']==artifact_id),None)
        if entry is None:raise KeyError('产物不存在')
        path=Path(entry['path']).resolve()
        if not path.is_relative_to(self.root/identity) or not path.is_file():raise KeyError('产物文件不可用')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('产物已变化，拒绝下载')
        return path

    def _checkpoint(self, identity):
        if self.shutdown.is_set():raise RunStopped()
        with self.store.connection() as db:row=db.execute('SELECT status FROM production_runs WHERE id=?',(identity,)).fetchone()
        if row['status'] not in ('running',):raise RunStopped()

    def _save_steps(self, identity, steps, **extra):
        fields={'steps':json.dumps(steps,ensure_ascii=False),**extra}
        with self.store.connection() as db:
            db.execute('UPDATE production_runs SET '+','.join(k+'=?' for k in fields)+',updated_at=CURRENT_TIMESTAMP WHERE id=?',(*fields.values(),identity))

    def _flow(self, row, step, steps):
        from server.core.department_flows import DepartmentFlows
        existing=next((s.get('flow_id') for s in steps if s['department']==step['department'] and s.get('flow_id')),None)
        if not existing:existing=DepartmentFlows(self.store).create(row['studio_id'],row['project_id'],{'department':step['department'],'name':'生产 '+row['id'][:8]+' '+row['name'][:50]})['id']
        for s in steps:
            if s['department']==step['department']:s['flow_id']=existing
        self._save_steps(row['id'],steps)
        return existing

    def _document(self, row, step, steps):
        from server.studio_workspaces import Workspaces
        from server.core.integrations import ExecutionService
        workspace=Workspaces(self.store);studio,project=row['studio_id'],row['project_id'];node=step['node_id']
        flow=self._flow(row,step,steps)
        current=workspace.get(studio,project,node,flow=flow)
        # A previously finished adapter call is recoverable without another model call.
        if current['status'] not in ('waiting_user','approved'):
            preceding=[s for s in steps[:steps.index(step)] if s['output']]
            inputs=row['brief']+'\n\n生产约束：严格保持用户指定玩法，构建可玩的离线Android原型，不得偷换成其他游戏类型；缺少外部材料明确记录假设。用户已委托原型参数决策，未指定参数选择可实现的默认值并记录，不能写成反复等待人工批准。禁止Git写入、Figma修改或外部发布。\n'
            inputs+='\n\n'.join(s['name']+'\n'+s['output'] for s in preceding[-3:])
            current=workspace.save(studio,project,node,{'revision':current['revision'],'inputs':inputs[:180000]},flow=flow,origin='agent')
            result=ExecutionService(self.store,self.registry).execute(studio,project,node,current['revision'],flow=flow)
            current=result['workspace']
            step['gaps']=result.get('gaps',[])
            self._save_steps(row['id'],steps)
        self._checkpoint(row['id'])
        self._require(studio,project,write=True)
        # Delegation is recorded distinctly; never label an automated review human.
        if current['status']!='approved':
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                changed=db.execute("UPDATE flow_workspaces SET status='approved',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE flow_id=? AND node=? AND revision=? AND status='waiting_user'",(flow,node,current['revision'])).rowcount
                if not changed:raise ValueError('交付修订已变化，停止委托审核')
                db.execute('INSERT INTO flow_events(flow_id,node,action,detail) VALUES(?,?,?,?)',(flow,node,'delegated_review','生产流程显式委托审核；非人工验收，run='+row['id']))
        step['output']=current['deliverable']
        with self.store.connection() as db:self._notify(db,row,step,'completed')

    def _build(self, row, step, steps):
        from server.ai_models import ModelSettings
        from server.core.integrations import ModelCapability
        from server.studio_workspaces import Workspaces
        builder=self.builder
        if builder is None:
            from departments.development.DEV_game_builder import DEV_build_game
            builder=DEV_build_game
        studio,project=row['studio_id'],row['project_id']
        flow=next(s['flow_id'] for s in steps if s['id']=='development:3')
        skill=Workspaces(self.store).get(studio,project,'development:3',flow=flow)['skill']['content']
        settings=ModelSettings(self.store)
        model=ModelCapability(settings.generation_client(),settings.runtime_selection(),skill)
        root=self.root/row['id']/('build-attempt-'+uuid.uuid4().hex)
        root.parent.mkdir(parents=True,exist_ok=True)
        def progress(value):
            self._checkpoint(row['id']);self._require(studio,project,write=True)
            summary=value.get('message') or value.get('stage') if isinstance(value,dict) else value
            if not isinstance(summary,str) or not summary.strip():summary='正在构建游戏工程'
            with self.store.connection() as db:
                db.execute('UPDATE production_runs SET summary=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(summary[:2000],row['id']))
        result=builder(root,row['brief']+'\n\n'+steps[11]['output'],progress=progress,check_cancelled=lambda:self._checkpoint(row['id']),model=model)
        self._checkpoint(row['id']);self._require(studio,project,write=True)
        if not isinstance(result,dict):raise ValueError('构建器未返回有效结果')
        artifacts=[]
        for artifact in result.get('artifacts',[]):
            path=Path(artifact['path']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():raise ValueError('构建产物越界或不存在')
            artifacts.append({'id':uuid.uuid4().hex,'name':path.name,'kind':artifact.get('kind','file'),'path':str(path),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        step['output']='真实构建返回 '+str(len(artifacts))+' 项产物；测试检查将在下一节点验证'
        step['gaps']=result.get('gaps',[])
        self._save_steps(row['id'],steps,artifacts=json.dumps(artifacts,ensure_ascii=False),build_result=json.dumps(result,ensure_ascii=False))

    def _notify(self, db, row, step, event):
        from server.core.notifications import enqueue
        current=db.execute('SELECT steps FROM production_runs WHERE id=?',(row['id'],)).fetchone()
        steps=json.loads(current['steps'])
        completed=sum(s['status']=='completed' for s in steps)
        if event=='completed' and not any(s['id']==step['id'] and s['status']=='completed' for s in steps):completed+=1
        summary='生产运行 '+row['name']+'；'+step['name']+'；步骤完成 '+str(completed)+'/'+str(len(steps))+'。'
        summary+='显式委托审核，非人工质量验收；请核对真实证据和未验证项。' if event=='completed' else ('服务中断，生产运行已暂停；未自动重放当前工具步骤。' if event=='interrupted' else '节点失败，后续自动执行已停止；请查看生产运行错误和日志。')
        payload={'production_run_id':row['id'],'production_summary':summary}
        enqueue(self.store,db,row['project_id'],step['node_id'],'production:'+row['id']+':'+step['id']+(':'+event if event!='completed' else ''),event,payload,flow_id=step.get('flow_id',''),origin='production')

    def _qa_model(self, row, node):
        if self.model_factory:return self.model_factory(node)
        from server.ai_models import ModelSettings
        from server.core.integrations import ModelCapability
        from server.studio_workspaces import Workspaces
        settings=ModelSettings(self.store)
        skill=Workspaces(self.store).get(row['studio_id'],row['project_id'],node)['skill']
        return ModelCapability(settings.generation_client(),settings.runtime_selection(),skill['content'])

    def _qa_artifact(self, row, name, value):
        root=self.root/row['id']/'testing';root.mkdir(parents=True,exist_ok=True)
        path=root/name;path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
        self._register_evidence(row,path)

    def _register_evidence(self,row,path):
        path=path.resolve()
        if not path.is_relative_to(self.root/row['id']) or not path.is_file():raise ValueError('测试证据产物越界或不存在')
        with self.store.connection() as db:
            artifacts=json.loads(db.execute('SELECT artifacts FROM production_runs WHERE id=?',(row['id'],)).fetchone()[0])
            artifacts=[a for a in artifacts if a.get('name')!=path.name]
            artifacts.append({'id':uuid.uuid4().hex,'name':path.name,'kind':'testing_evidence','path':str(path),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            db.execute('UPDATE production_runs SET artifacts=? WHERE id=?',(json.dumps(artifacts,ensure_ascii=False),row['id']))

    def _source_evidence_archive(self,row,directory):
        if not directory:return
        directory=Path(directory).resolve()
        if not directory.is_relative_to(self.root/row['id']) or not directory.is_dir():raise ValueError('源码审查证据目录越界或不存在')
        archive=self.root/row['id']/'testing'/'qa-source-evidence.zip'
        archive.parent.mkdir(parents=True,exist_ok=True)
        paths=[p for p in directory.rglob('*.json') if not p.is_symlink() and p.is_file() and p.resolve().is_relative_to(directory)]
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
            for path in sorted(paths):output.write(path,path.relative_to(directory))
        self._register_evidence(row,archive)

    def _testing(self, row, step, steps):
        from server.requirements import validate_cases
        with self.store.connection() as db:
            stored=db.execute('SELECT build_result,qa_result FROM production_runs WHERE id=?',(row['id'],)).fetchone()
        build=json.loads(stored['build_result']);qa=json.loads(stored['qa_result'])
        node=step['node_id']
        from server.studio_workspaces import Workspaces
        qa_workspace=Workspaces(self.store).get(row['studio_id'],row['project_id'],node)
        step['skill_sha256']=qa_workspace['skill']['sha256'];step['input_revision']=qa_workspace['revision']
        self._save_steps(row['id'],steps)
        if node=='testing:0':
            source=row['brief']+'\n\n'+steps[3]['output']+'\n\n实际构建规格：'+json.dumps(build.get('spec',{}),ensure_ascii=False)
            coverage=('覆盖旋转、连接闭环判断、提示、重开、通关反馈、下一关、关卡进度保存及边界与生命周期。不得引入配对或倒计时要求。'
                      if build.get('spec',{}).get('game_type')=='loop' else
                      '覆盖开始、配对成功/不成功、倒计时、胜利/失败、重开、边界与生命周期。')
            prompt='根据资料生成真实可审查测试用例，不能声称已执行。返回JSON {points:[{id,title,requirement_id:"production-requirement",quote:连续逐字原文}],cases:[{id,title,preconditions:[非空文字],point_ids:[测试点ID],steps:[{action,expected}]}],gaps:[{point_id,reason}],ambiguities:[文字]}。'+coverage+'不得凭空引入广告/IAP/联网。资料：\n'+source
            from departments.testing.QA_generation_recovery import QA_request_validated
            model=self._qa_model(row,node)
            qa['cases']=QA_request_validated(model.request_json,prompt,
                lambda candidate:validate_cases(candidate,[{'id':'production-requirement','content':source}]),
                check_cancelled=lambda:self._checkpoint(row['id']),
                diagnostic=lambda update:self._qa_progress(row,update),label='生产测试用例')
            self._checkpoint(row['id']);self._require(row['studio_id'],row['project_id'],write=True)
            if not qa['cases']['cases']:raise ValueError('生产测试链没有生成可执行用例')
            self._qa_artifact(row,'test-cases.json',qa['cases'])
            step['output']=json.dumps(qa['cases'],ensure_ascii=False,indent=2)
            step['gaps']=['用例结构与来源引用已校验，不等于需求覆盖完整或客户端实测通过']
        elif node=='testing:1':
            checks=build.get('checks',[])
            if not checks or any(c.get('passed') is not True or not c.get('evidence') for c in checks):raise ValueError('真实检查缺失或失败，不能宣称测试通过')
            if not build.get('artifacts'):raise ValueError('构建无可下载产物')
            reviewer=self.source_reviewer
            if reviewer is None:
                try:
                    from server.static_review import QA_review_generated_workspace
                    reviewer=QA_review_generated_workspace
                except ImportError:raise ValueError('生产源码逐用例审查尚未接入，不能以构建检查冒充测试部门完成')
            source_root=Path(build.get('project_path') or Path(build['artifacts'][0]['path']).parent.parent).resolve()
            if not source_root.is_relative_to(self.root/row['id']):raise ValueError('测试源码目录越界')
            review=reviewer(source_root,qa['cases']['cases'],model=self._qa_model(row,node),progress=lambda p:self._qa_progress(row,p),check_cancelled=lambda:self._checkpoint(row['id']))
            if not isinstance(review,dict) or not isinstance(review.get('findings'),list):raise ValueError('源码审查结果须提供findings列表')
            self._checkpoint(row['id']);self._require(row['studio_id'],row['project_id'],write=True)
            self._source_evidence_archive(row,review.get('evidence'))
            qa['execution']={'checks':checks,'source_review':review,'boundary':'真实构建/JVM检查与逐用例源码审查；不自动等同客户端实测'}
            self._qa_artifact(row,'test-execution.json',qa['execution'])
            step['output']=json.dumps(qa['execution'],ensure_ascii=False,indent=2)
            step['gaps']=[*build.get('gaps',[]),*review.get('gaps',[])]
        elif node=='testing:2':
            findings=qa['execution']['source_review']['findings']
            # Only source-supported defects can enter attribution/drafts. Gaps are risks.
            defects=[f for f in findings if f.get('status') in ('failed','defect') and f.get('evidence')]
            qa['attribution']={'findings':defects,'status':'requires_review' if defects else 'no_supported_defects','boundary':'保留实际发现，未自动推断共同根因；无可归因项不生成虚构缺陷'}
            step['output']=json.dumps(qa['attribution'],ensure_ascii=False,indent=2)
            self._qa_artifact(row,'test-attribution.json',qa['attribution'])
        elif node=='testing:4':
            defects=qa['attribution']['findings']
            qa['bugs']={'drafts':[{'id':'production-bug-'+str(i+1),'title':f.get('title','源码审查发现'),'finding':f,'status':'internal_draft','published':False,'reproduction_provenance':'static_inference'} for i,f in enumerate(defects)],'status':'drafts_ready' if defects else 'not_applicable','reason':'仅内部草稿，未调用飞书工单发布' if defects else '没有证据支持的缺陷，无须提单'}
            step['output']=json.dumps(qa['bugs'],ensure_ascii=False,indent=2)
            self._qa_artifact(row,'internal-bug-drafts.json',qa['bugs'])
        elif node=='testing:5':
            defects=qa['bugs']['drafts']
            qa['regression']={'status':'awaiting_fix' if defects else 'not_applicable','reason':'存在缺陷但无修复版本，未伪造回归通过' if defects else '无已确认缺陷及修复版本，回归不适用','passed':None}
            step['output']=json.dumps(qa['regression'],ensure_ascii=False,indent=2)
            if defects:step['gaps']=['存在内部缺陷草稿，尚未修复与回归，不得作为质量通过版本发行']
            self._qa_artifact(row,'regression-status.json',qa['regression'])
        self._checkpoint(row['id']);self._require(row['studio_id'],row['project_id'],write=True)
        latest=Workspaces(self.store).get(row['studio_id'],row['project_id'],node)
        if latest['revision']!=qa_workspace['revision'] or latest['skill']['sha256']!=qa_workspace['skill']['sha256']:raise ValueError('测试期间节点或Skill已变化，拒绝委托审核')
        with self.store.connection() as db:
            db.execute('UPDATE production_runs SET qa_result=? WHERE id=?',(json.dumps(qa,ensure_ascii=False),row['id']))
            self._event(db,row['id'],'delegated_review',node+'：生产运行内测试链；非旧批次已执行，非人工质量验收')

    def _qa_progress(self,row,value):
        self._checkpoint(row['id'])
        if isinstance(value,dict):
            import math
            labels={
                'preparing':'正在准备执行', 'started':'模型请求已启动',
                'running':'正在调查项目源码' if value.get('execution_engine')=='project_agent' else '正在生成交付',
                'retrying':'正在重试模型请求', 'completed':'本次模型响应已完成',
                'case_completed':'用例校验完成', 'validation_repair':'正在修正输出格式',
                'validation_failed':'输出格式校验未通过', 'idle_timeout':'等待模型响应超时',
                'start_failed':'模型请求启动失败', 'cli_failed':'项目审查执行失败',
                'invalid_json':'模型输出格式待修正', 'output_too_large':'模型输出超过限制',
                'incomplete_response':'模型响应不完整'}
            state=value.get('state')
            status=labels.get(state,'正在执行') if isinstance(state,str) else '正在执行'
            label=value.get('step_name') or value.get('title')
            parts=[(label.strip()[:120]+'：' if isinstance(label,str) and label.strip() else '')+status]
            def count(key):
                number=value.get(key)
                return number if type(number) is int and 0<=number<=10**12 else None
            elapsed=value.get('elapsed_seconds')
            if type(elapsed) in (int,float) and math.isfinite(elapsed) and 0<=elapsed<=10**12:
                seconds=int(elapsed);hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
                duration=(str(hours)+'小时' if hours else '')+(str(minutes)+'分' if minutes else '')+str(seconds)+'秒'
                parts.append('已耗时 '+duration)
            chars=count('assistant_chars')
            if chars is not None:parts.append('已接收 '+str(chars)+' 字')
            elif count('events_received') is not None:parts.append('已接收 '+str(count('events_received'))+' 条响应事件')
            for key,title in (('tool_calls','工具调用'),('commands_completed','命令完成')):
                if count(key) is not None:parts.append(title+' '+str(count(key))+' 次')
            completed,total=count('completed'),count('total')
            if completed is not None and total is not None and completed<=total:
                parts.append('已校验 '+str(completed)+'/'+str(total)+' 条')
            for key,title in (('reviewed_count','本次审查'),('checkpoint_reused_count','复用')):
                if count(key) is not None:parts.append(title+' '+str(count(key))+' 条')
            attempt,maximum=count('validation_attempt'),count('validation_max_attempts')
            if attempt is not None and maximum is not None and 1<=attempt<=maximum:
                parts.append('第 '+str(attempt)+'/'+str(maximum)+' 次校验')
            elif count('attempt') is not None and count('max_attempts') is not None and 1<=count('attempt')<=count('max_attempts'):
                parts.append('第 '+str(count('attempt'))+'/'+str(count('max_attempts'))+' 次请求')
            summary='；'.join(parts)
        elif isinstance(value,str) and not value.lstrip().startswith(('{','[')):
            summary=value
        else:summary='正在执行'
        with self.store.connection() as db:db.execute('UPDATE production_runs SET summary=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(summary[:2000],row['id']))

    def _model_progress(self,row,step,update):
        if not isinstance(update,dict):return
        keys=('state','elapsed_seconds','events_received','assistant_chars','tool_calls','commands_completed',
              'execution_engine','attempt','max_attempts','completed','total','reviewed_count','checkpoint_reused_count')
        safe={key:update[key] for key in keys if key in update}
        safe['step_name']=step['name']
        self._qa_progress(row,safe)

    def run_once(self):
        if not self.lock.acquire(blocking=False):return False
        try:return self._run_once()
        finally:self.lock.release()

    def advance(self, studio, project, identity):
        """Advance one selected run without claiming another project's queued work."""
        self._require(studio,project,write=True);self._row(studio,project,identity)
        if not self.lock.acquire(blocking=False):return False
        try:return self._run_once(identity)
        finally:self.lock.release()

    def _run_once(self, identity=None):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            query="SELECT * FROM production_runs WHERE status IN ('queued','running')"
            if identity:query+=' AND id=?'
            row=db.execute(query+' ORDER BY rowid LIMIT 1',(identity,) if identity else ()).fetchone()
            if row is None:return False
            row=dict(row)
            db.execute("UPDATE production_runs SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=?",(row['id'],))
        token=current_user.set(row['actor']);steps=json.loads(row['steps'])
        step=next((s for s in steps if s['status']!='completed'),None)
        try:
            self._require(row['studio_id'],row['project_id'],write=True)
            self._checkpoint(row['id'])
            if step is None:return False
            step.update(status='running',error=None)
            with self.store.connection() as db:
                step['started_at']=db.execute('SELECT CURRENT_TIMESTAMP').fetchone()[0]
                self._event(db,row['id'],'step_started',step['id'])
            self._save_steps(row['id'],steps)
            from server.codex_model import diagnostic_scope
            with diagnostic_scope(lambda update:self._model_progress(row,step,update)):
                if step['id']=='development:build':self._build(row,step,steps)
                elif step['department']=='testing':self._testing(row,step,steps)
                else:self._document(row,step,steps)
            self._checkpoint(row['id'])
            step.update(status='completed')
            with self.store.connection() as db:step['finished_at']=db.execute('SELECT CURRENT_TIMESTAMP').fetchone()[0]
            gaps=list(dict.fromkeys(str(g) for s in steps for g in s.get('gaps',[])))
            self._save_steps(row['id'],steps,gaps=json.dumps(gaps,ensure_ascii=False))
            with self.store.connection() as db:
                self._event(db,row['id'],'step_completed',step['id'])
                if step['id']=='development:build' or step['department']=='testing':
                    self._notify(db,row,step,'completed')
                if all(s['status']=='completed' for s in steps):db.execute("UPDATE production_runs SET status='completed',summary='生产链完成；请核对产物、检查证据与未验证项',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",(row['id'],))
        except RunStopped:
            # Preserve finished workspaces/build attempt on disk; explicit resume
            # retries only the unfinished step, never completed checkpoints.
            pass
        except Exception as exc:
            logging.getLogger(__name__).exception('Production run failed: %s',row['id'])
            message=str(exc) if isinstance(exc,(ValueError,PermissionError)) else '执行器内部错误；请检查本机服务日志'
            if step:step.update(status='failed',error=message)
            self._save_steps(row['id'],steps)
            with self.store.connection() as db:
                db.execute("UPDATE production_runs SET status='failed',error=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",(message,row['id']))
                self._event(db,row['id'],'failed',message)
                if step:
                    self._notify(db,row,step,'failed')
        finally:current_user.reset(token)
        return True


class ProductionWorker:
    def __init__(self, store, registry):
        self.service=ProductionRuns(store,registry);self.service.recover()
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True,name='production-runs')
        self.thread.start()
    def run(self):
        while not self.stop.is_set():
            try:
                if not self.service.run_once():self.stop.wait(.5)
            except Exception:
                logging.getLogger(__name__).exception('Production worker iteration failed');self.stop.wait(1)
    def close(self):
        self.stop.set();self.service.shutdown.set();self.thread.join(timeout=2)


def dispatch(handler, parts, body, write, service):
    if len(parts)<6 or parts[:2]!=['api','studios'] or parts[3]!='projects' or parts[5]!='production-runs':return False
    if service is None:raise PermissionError('当前部署模式不运行生产链')
    studio,project=parts[2],parts[4]
    if len(parts)==6:
        result=service.create(studio,project,body) if write else service.listing(studio,project)
        handler.send_json(201 if write else 200,result);return True
    if len(parts)==7:
        result=service.action(studio,project,parts[6],body.get('action')) if write else service.get(studio,project,parts[6])
        handler.send_json(200,result);return True
    if len(parts)==9 and parts[7]=='artifacts' and not write:
        import mimetypes
        from urllib.parse import quote
        path=service.artifact(studio,project,parts[6],parts[8]);payload=path.read_bytes()
        handler.send_response(200)
        handler.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        handler.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(path.name))
        handler.send_header('Content-Length',str(len(payload)))
        handler.send_header('Cache-Control','no-store')
        handler.send_header('X-Content-Type-Options','nosniff')
        handler.end_headers();handler.wfile.write(payload);return True
    raise KeyError('生产流程接口不存在')
