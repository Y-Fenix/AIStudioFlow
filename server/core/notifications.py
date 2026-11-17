"""Transactional node outbox; external delivery always happens after commit."""
import json
import logging
import threading
import uuid
from collections import Counter
from datetime import datetime,timezone,timedelta
from urllib.parse import urlencode
from server.core.notification_settings import NotificationSettings
from server.connectors.feishu_webhook import send_card,DeliveryRejected,DeliveryUnknown

def migrate(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS node_notifications (
            id INTEGER PRIMARY KEY,studio_id TEXT NOT NULL,project_id TEXT NOT NULL,
            node TEXT NOT NULL,task_id TEXT NOT NULL DEFAULT '',event_key TEXT NOT NULL UNIQUE,
            event TEXT NOT NULL,target_hash TEXT NOT NULL,payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS notification_scope ON node_notifications(studio_id,project_id,id);
    ''')

def result_summary(node,artifact,origin):
    if not isinstance(artifact,dict):return '结果已保存，请进入平台审核。'
    if origin=='production' and artifact.get('production_summary'):return str(artifact['production_summary'])[:1200]
    if origin=='publication' and artifact.get('notification_summary'):return str(artifact['notification_summary'])[:1200]
    lines=[]
    if isinstance(artifact.get('cases'),list):lines.append('用例 '+str(len(artifact['cases']))+' 条')
    if isinstance(artifact.get('results'),list):
        results=artifact['results'];counts=Counter(str(r.get('status','unknown')) for r in results if isinstance(r,dict))
        static=artifact.get('method')=='static_code_review'
        lines.append(('静态审查' if static else '检测')+' '+str(len(results))+' 条')
        labels={'passed':'静态证据支持' if static else '检查通过','failed':'发现可达缺陷' if static else '发现异常依据','needs_runtime':'需运行验证','insufficient_evidence':'证据不足','requirement_unclear':'需求待确认'}
        lines.extend(labels.get(k,'其他结论')+' '+str(v) for k,v in counts.items())
        if static:lines.append('静态结论不等于客户端实测通过。')
    for key,label in [('groups','归因分组'),('suggestions','候选归因'),('drafts','Bug 草稿'),('roots','根因'),('gaps','缺口')]:
        if isinstance(artifact.get(key),list):lines.append(label+' '+str(len(artifact[key]))+' 项')
    if artifact.get('publication_complete'):lines.append('发布登记已完成；以平台发布台账为准。')
    if origin=='manual':lines.append('人工提交结果，等待审核。')
    return '；'.join(lines) if lines else '结果已保存，等待人工审核；查看平台获取完整证据。'

def enqueue(store,db,project,node,event_key,event,artifact=None,*,task_id='',origin='agent',duration=None,flow_id=''):
    if getattr(store,'runtime_mode','team')=='personal':return None
    project_row=db.execute('SELECT p.name,p.studio_id,s.name AS studio_name FROM projects p JOIN studios s ON s.id=p.studio_id WHERE p.id=? AND p.archived=0 AND s.archived=0',(project,)).fetchone()
    if not project_row:return None
    studio=project_row['studio_id']
    try:config=NotificationSettings(store).effective(studio,project,node.split(':')[0],node)
    except (ValueError,OSError):
        logging.getLogger(__name__).warning('通知配置不可读；节点结果继续保存')
        return None
    if not config.get('enabled') or not config.get('webhook') or event not in config.get('events',[]):return None
    from server.studio_catalog import node_definition
    try:d,_,definition=node_definition(node,store,project,connection=db);title=definition[0];department=d['title']
    except ValueError:title=node;department=node.split(':')[0]
    task=db.execute('SELECT title FROM tasks WHERE id=? AND project_id=?',(task_id,project)).fetchone() if task_id else None
    payload={'studio':project_row['studio_name'],'project':project_row['name'],'department':department,'node_title':title,
             'batch':task['title'] if task else '', 'summary':result_summary(node,artifact,origin), 'origin':origin,'duration':duration}
    if not flow_id and task_id:
        bound=db.execute('SELECT id,name FROM department_flows WHERE project_id=? AND task_id=?',(project,task_id)).fetchone()
        if bound:flow_id=bound['id']
    if flow_id:
        bound=db.execute('SELECT id,name FROM department_flows WHERE project_id=? AND id=?',(project,flow_id)).fetchone()
        if bound:payload.update(flow_id=bound['id'],flow_name=bound['name'])
    if event=='public_published':payload['public_item']=(artifact or {}).get('public_item','')
    if origin=='production' and isinstance(artifact,dict) and artifact.get('production_run_id'):
        run=db.execute('SELECT id FROM production_runs WHERE id=? AND project_id=? AND studio_id=?',(artifact['production_run_id'],project,studio)).fetchone()
        if run is None:raise ValueError('生产通知不属于当前项目')
        payload['production_run_id']=run['id']
    if event in ('failed','interrupted') and origin not in ('publication','production'):payload['summary']='操作失败或被中断，未产生可确认的完成结果。'
    db.execute('''INSERT OR IGNORE INTO node_notifications(studio_id,project_id,node,task_id,event_key,event,target_hash,payload)
        VALUES(?,?,?,?,?,?,?,?)''',(studio,project,node,task_id,event_key,event,config['target_hash'],json.dumps(payload,ensure_ascii=False)))
    return db.execute('SELECT id FROM node_notifications WHERE event_key=?',(event_key,)).fetchone()['id']

def testing_event(store,db,task_id,stage,event_key,event,artifact=None,**extra):
    row=db.execute('SELECT project_id FROM tasks WHERE id=?',(task_id,)).fetchone()
    if row:return enqueue(store,db,row['project_id'],'testing:'+str(stage),event_key,event,artifact,task_id=task_id,**extra)

def card_for(row,config):
    p=json.loads(row['payload']);event=row['event']
    titles={'completed':'执行完成 · 待审核','manual':'人工提交 · 待审核','failed':'执行失败','interrupted':'执行中断','approved':'人工确认通过','test':'通知连接测试','public_published':'公区内容已发布'}
    if p.get('origin')=='production':titles.update(completed='生产节点完成 · 委托审核',failed='生产节点失败',interrupted='生产节点中断')
    now=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    body='工作室：'+p['studio']+'\n项目：'+p['project']+'\n部门 / 节点：'+p['department']+' / '+p['node_title']
    if p.get('flow_name'):body+='\n流程：'+p['flow_name']
    if p.get('batch'):body+='\n批次：'+p['batch']
    body+='\n'+p['summary']
    if p.get('duration') is not None:body+='\n耗时：'+str(p['duration'])+' 秒'
    if event in ('failed','interrupted'):body+='\n节点未完成，请进入平台查看操作日志。'
    elements=[{'tag':'div','text':{'tag':'plain_text','content':body[:3500]}}]
    if config.get('public_url'):
        query={'studio':row['studio_id'],'project':row['project_id'],'node':row['node']}
        if event=='test':query={'studio':row['studio_id'],'project':row['project_id'],'view':'settings'}
        if event=='public_published':query={'studio':row['studio_id'],'project':row['project_id'],'view':'public','publication':p.get('public_item','')}
        if row['task_id']:query['task']=row['task_id']
        if p.get('flow_id'):query['flow']=p['flow_id']
        if p.get('block_run'):query['block_run']=p['block_run']
        if p.get('block_flow'):query['block_flow']=p['block_flow']
        if p.get('production_run_id'):query={'studio':row['studio_id'],'project':row['project_id'],'view':'production','production_run':p['production_run_id']}
        elements.append({'tag':'action','actions':[{'tag':'button','text':{'tag':'plain_text','content':'查看结果与操作日志'},'type':'primary','url':config['public_url']+'/?'+urlencode(query)}]})
    else:elements.append({'tag':'div','text':{'tag':'plain_text','content':'尚未配置团队访问地址，请在 StudioFlow 内查看结果。'}})
    elements.append({'tag':'note','elements':[{'tag':'plain_text','content':'北京时间 '+now+' · 通知 #'+str(row['id'])}]})
    return {'config':{'wide_screen_mode':True},'header':{'template':'red' if event in ('failed','interrupted') else 'blue',
            'title':{'tag':'plain_text','content':'StudioFlow · '+titles.get(event,'节点提醒')}},'elements':elements}

class NotificationQueue:
    def __init__(self,store):self.store=store;self.settings=NotificationSettings(store)
    def config_for(self,row):
        scope=json.loads(row['payload']).get('config_scope')
        department,node=scope if scope else (row['node'].split(':')[0],row['node'])
        return self.settings.effective(row['studio_id'],row['project_id'],department,node)
    def listing(self,studio,project=''):
        self.settings.authorize(studio,project)
        with self.store.connection() as db:
            rows=db.execute("SELECT id,project_id,node,task_id,event,status,attempts,error,created_at,updated_at,payload FROM node_notifications WHERE studio_id=? AND (?='' OR project_id=?) ORDER BY id DESC LIMIT 50",(studio,project,project)).fetchall()
        return [{k:v for k,v in dict(r).items() if k!='payload'}|{'title':json.loads(r['payload'])['node_title']} for r in rows]
    def claim(self):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM node_notifications WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            if not row:return None
            db.execute("UPDATE node_notifications SET status='sending',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",(row['id'],))
            return dict(row)
    def recover(self):
        with self.store.connection() as db:db.execute("UPDATE node_notifications SET status='unknown',error='服务重启时发送未结束；请核对群消息后补发',updated_at=CURRENT_TIMESTAMP WHERE status='sending'")
    def run_once(self):
        row=self.claim()
        if not row:return False
        status='sent';error=''
        try:
            config=self.config_for(row)
            with self.store.connection() as db:
                active=db.execute('SELECT 1 FROM studios WHERE id=? AND archived=0',(row['studio_id'],)).fetchone()
                if row['project_id']:active=active and db.execute('SELECT 1 FROM projects WHERE id=? AND studio_id=? AND archived=0',(row['project_id'],row['studio_id'])).fetchone()
            if not active or not config.get('enabled') or config['target_hash']!=row['target_hash'] or row['event']!='test' and row['event'] not in config.get('events',[]):
                status='cancelled';error='通知已关闭或目标配置变化，未向新目标转发历史数据'
            else:send_card(config,card_for(row,config))
        except DeliveryRejected as exc:status='failed';error=str(exc)
        except DeliveryUnknown as exc:status='unknown';error=str(exc)
        except Exception:status='unknown';error='通知发送内部异常，请核对群消息与服务日志'
        with self.store.connection() as db:db.execute("UPDATE node_notifications SET status=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='sending'",(status,error,row['id']))
        return True
    def resend(self,studio,project,identity):
        self.settings.authorize(studio,project)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM node_notifications WHERE id=? AND studio_id=? AND project_id=?',(identity,studio,project)).fetchone()
            if not row:raise KeyError('通知不存在')
            if row['status'] in ('pending','sending'):raise ValueError('消息正在排队或发送，请勿重复补发')
            config=self.config_for(row)
            if not config.get('enabled') or row['target_hash']!=config['target_hash']:raise ValueError('原通知目标已停用或更换，不能向新群补发旧结果')
            db.execute("UPDATE node_notifications SET status='pending',error='',updated_at=CURRENT_TIMESTAMP WHERE id=?",(identity,))
            from server.core.identity import user_id
            db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',(user_id(),studio,'notification_resend','显式补发通知 #'+str(identity)))
        return {'id':identity,'status':'pending'}
    def test(self,studio,project='',department='',node=''):
        department=self.settings.department(department,node)
        self.settings.authorize(studio,project,department,node)
        config=self.settings.effective(studio,project,department,node)
        if not config.get('enabled') or not config.get('webhook'):raise ValueError('请先保存并启用 Webhook 配置')
        with self.store.connection() as db:
            s=db.execute('SELECT name FROM studios WHERE id=?',(studio,)).fetchone()
            p=db.execute('SELECT name FROM projects WHERE id=?',(project,)).fetchone() if project else None
            payload={'studio':s['name'],'project':p['name'] if p else '工作室默认','department':department or '平台','node_title':node or '通知配置',
                     'summary':'这是一条连接测试消息，不代表任何节点执行成功。','origin':'test','config_scope':[department,node]}
            key=node or (department+':0' if department else 'platform:0')
            cursor=db.execute('''INSERT INTO node_notifications(studio_id,project_id,node,event_key,event,target_hash,payload)
                VALUES(?,?,?,?,?,?,?)''',(studio,project,key,'test:'+uuid.uuid4().hex,'test',config['target_hash'],json.dumps(payload,ensure_ascii=False)))
        return {'id':cursor.lastrowid,'status':'pending'}

class NotificationWorker:
    def __init__(self,store):
        self.queue=NotificationQueue(store);self.queue.recover();self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        while not self.stop.is_set():
            try:worked=self.queue.run_once()
            except Exception:logging.getLogger(__name__).exception('通知 worker 失败');worked=False
            self.stop.wait(.6 if worked else 1)
    def close(self):self.stop.set();self.thread.join(timeout=17)
