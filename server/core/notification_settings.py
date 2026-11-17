"""Private local notification configuration, scoped without changing grant semantics."""
import hashlib
import ipaddress
import json
import os
import threading
import uuid
from urllib.parse import urlsplit
from server.core.permissions import Policy
from server.core.identity import user_id
from server.connectors.feishu_webhook import validate_webhook

_lock=threading.RLock()

def site_url(value):
    if not value:return ''
    if not isinstance(value,str):raise ValueError('平台地址格式错误')
    p=urlsplit(value.rstrip('/'))
    if (p.scheme not in ('http','https') or not p.hostname or p.username or p.password
            or p.path or p.query or p.fragment):raise ValueError('平台地址只填写站点，不带路径、账号或参数')
    if p.scheme=='http':
        try:address=ipaddress.ip_address(p.hostname)
        except ValueError:
            if p.hostname!='localhost':raise ValueError('HTTP 只允许本机或公司私有网段 IP')
        else:
            if not (address.is_loopback or address in ipaddress.ip_network('10.0.0.0/8') or address in ipaddress.ip_network('172.16.0.0/12') or address in ipaddress.ip_network('192.168.0.0/16')):
                raise ValueError('HTTP 只允许本机或公司私有网段 IP')
    try:p.port
    except ValueError:raise ValueError('平台端口无效') from None
    return value.rstrip('/')

class NotificationSettings:
    def __init__(self,store):self.store=store;self.path=store.path.with_name('feishu-notifications.json')
    def read(self):
        try:
            data=json.loads(self.path.read_text())
            if not isinstance(data,dict) or not isinstance(data.get('rules',{}),dict):raise ValueError()
            for key,rule in data.get('rules',{}).items():
                if not isinstance(key,str) or not isinstance(rule,dict):raise ValueError()
                if any(not isinstance(rule.get(k,''),str) for k in ('webhook','secret','public_url','destination_name')):raise ValueError()
                if 'enabled' in rule and type(rule['enabled']) is not bool:raise ValueError()
                if not isinstance(rule.get('events',[]),list):raise ValueError()
            return data
        except FileNotFoundError:return {'rules':{}}
        except (ValueError,OSError):raise ValueError('飞书通知配置无法读取，请由管理员修复') from None
    @staticmethod
    def key(studio,project='',department='',node=''):return '|'.join((studio,project,department,node))
    @staticmethod
    def department(department,node):return department or (node.split(':')[0] if node else '')
    def authorize(self,studio,project='',department='',node=''):
        if not studio or not any(x['id']==studio for x in self.store.studios()):raise KeyError('工作室不存在')
        if project:self.store.check_project(studio,project)
        if department:
            from server.studio_catalog import DEPARTMENTS
            if department not in {d['id'] for d in DEPARTMENTS}:raise ValueError('部门不存在')
        if node:
            if not project:raise ValueError('节点配置需要指定项目')
            from server.studio_catalog import node_definition
            d,_,_=node_definition(node,self.store,project)
            if department and d['id']!=department:raise ValueError('节点与部门不匹配')
        if not Policy(self.store).can_manage_scope(studio,project):raise PermissionError('仅范围负责人可管理飞书通知与发送记录')
    def effective(self,studio,project='',department='',node='',data=None):
        department=self.department(department,node)
        data=self.read() if data is None else data;rules=data.get('rules',{})
        scopes=[(studio,'','','','工作室默认')]
        if project:scopes.append((studio,project,'','','项目配置'))
        if department:scopes.append((studio,project,department,'','部门配置'))
        if node:scopes.append((studio,project,department,node,'节点配置'))
        result={'enabled':False,'events':['completed','failed','interrupted','manual'],'public_url':'','destination_name':'','source':'未配置','webhook':'','secret':''}
        for s,p,d,n,label in scopes:
            rule=rules.get(self.key(s,p,d,n))
            if rule is not None:result.update(rule);result['source']=label
        # Sender identity is pinned in each queued record; a config change cannot redirect old data.
        result['target_hash']=hashlib.sha256((result.get('webhook','')+'\0'+result.get('secret','')).encode()).hexdigest()
        return result
    @staticmethod
    def public(value):
        return {k:v for k,v in value.items() if k not in ('webhook','secret','target_hash')}|{'has_webhook':bool(value.get('webhook')),'has_secret':bool(value.get('secret'))}
    def get(self,studio,project='',department='',node=''):
        department=self.department(department,node)
        self.authorize(studio,project,department,node);data=self.read();key=self.key(studio,project,department,node)
        rule=data.get('rules',{}).get(key)
        with self.store.connection() as db:
            studio_row=db.execute('SELECT name FROM studios WHERE id=?',(studio,)).fetchone()
            project_row=db.execute('SELECT name FROM projects WHERE id=? AND studio_id=?',(project,studio)).fetchone() if project else None
        return {'override':rule is not None,'mode':'independent' if rule is not None else 'inherit' if project and not department and not node else 'default',
                'context':{'studio_name':studio_row['name'],'project_name':project_row['name'] if project_row else ''},
                'rule':self.public(rule) if rule else None,
                'effective':self.public(self.effective(studio,project,department,node,data)), 'config_file':str(self.path)}
    def save(self,studio,project,value,department='',node=''):
        department=self.department(department,node)
        self.authorize(studio,project,department,node)
        if not isinstance(value,dict):raise ValueError('通知配置必须为对象')
        mode=value.get('mode')
        if mode is not None and mode not in ('inherit','independent'):raise ValueError('项目通知模式无效')
        if mode=='independent' and value.get('inherit') is True:raise ValueError('独立配置与继承不能同时启用')
        if mode=='inherit' and (value.get('inherit') is True or any(k in value for k in ('enabled','webhook','secret','clear_secret','public_url','destination_name','events'))):raise ValueError('恢复继承配置时不能同时修改通知内容')
        if mode=='independent' and (not project or department or node):raise ValueError('独立配置模式仅适用于项目范围')
        key=self.key(studio,project,department,node)
        with _lock:
            data=self.read();rules=data.setdefault('rules',{})
            if value.get('inherit') is True or mode=='inherit':
                if not (project or department or node):raise ValueError('工作室默认不能继承')
                rules.pop(key,None)
            else:
                existing=rules.get(key)
                base=dict(existing or self.effective(studio,project,department,node,data))
                if mode=='independent' and not (existing or {}).get('webhook'):
                    base['webhook']='';base['secret']='';base['destination_name']=''
                    if not isinstance(value.get('webhook'),str) or not value['webhook'].strip():raise ValueError('请填写本项目自己的 Webhook')
                for field in ('enabled',):
                    if field in value:
                        if type(value[field]) is not bool:raise ValueError('通知开关需要布尔值')
                        base[field]=value[field]
                for field in ('webhook','secret'):
                    if field in value:
                        raw=value[field]
                        if not isinstance(raw,str) or len(raw)>1000:raise ValueError('凭据格式错误')
                        if raw.strip():
                            if field=='webhook' and raw.strip()!=base.get('webhook',''):
                                base['secret']=''
                            base[field]=raw.strip()
                if value.get('clear_secret') is True:base['secret']=''
                if 'public_url' in value:base['public_url']=site_url(value['public_url'])
                if 'destination_name' in value:
                    destination=value['destination_name']
                    if not isinstance(destination,str) or len(destination)>100:raise ValueError('接收群备注不能超过100个字符')
                    base['destination_name']=destination.strip()
                if 'events' in value:
                    events=value['events']
                    if not isinstance(events,list) or any(e not in ('completed','failed','interrupted','manual','approved','public_published') for e in events):raise ValueError('通知事件无效')
                    base['events']=list(dict.fromkeys(events))
                if mode=='independent' and base.get('enabled') and not base.get('webhook'):raise ValueError('请填写本项目自己的 Webhook')
                if base.get('enabled') or base.get('webhook'):validate_webhook(base.get('webhook'))
                rules[key]={k:v for k,v in base.items() if k not in ('source','target_hash')}
            self.path.parent.mkdir(parents=True,exist_ok=True);temp=self.path.with_name('.notifications-'+uuid.uuid4().hex+'.tmp')
            try:
                fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
                os.replace(temp,self.path)
            finally:temp.unlink(missing_ok=True)
        with self.store.connection() as db:db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',(user_id(),studio,'notification_configured',json.dumps({'project':project,'department':department,'node':node},ensure_ascii=False)))
        return self.get(studio,project,department,node)
