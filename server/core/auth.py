"""Session authentication; password accounts are the default, OAuth is legacy opt-in."""
import hashlib
import ipaddress
import json
import os
import secrets
import time
import uuid
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from server.core.identity import user_id


class AuthenticationRequired(PermissionError): pass


def digest(value): return hashlib.sha256(value.encode()).hexdigest()


def cookie_value(headers, key):
    jar=SimpleCookie()
    try:jar.load(headers.get('Cookie',''));return jar[key].value if key in jar else ''
    except Exception:return ''


class Authentication:
    def __init__(self, store, local_development=False): self.store=store;self.path=store.path.with_name('team-auth.json');self.local_development=local_development

    def config(self):
        if not self.path.exists():return {'mode':'local' if self.local_development else 'password','public_url':'','allowed_tenants':[],'allow_all_tenants':False}
        try:
            value=json.loads(self.path.read_text())
            if value.get('mode') not in ('local','team','password'):raise ValueError()
            return value
        except (ValueError,OSError):raise ValueError('认证配置文件无效，请由服务器管理员修复')

    def status(self, private=False):
        c=self.config()
        from server.core.local_accounts import LocalAccounts
        setup=LocalAccounts(self.store).setup_required()
        return {k:v for k,v in c.items() if k not in ('client_secret',)} | {'configured':not setup if c['mode']=='password' else bool(c.get('client_id') and c.get('client_secret') and c.get('public_url')),'setup_required':setup if c['mode']=='password' else False,'registration_open':c.get('registration_open',True) is True,'has_client_secret':bool(c.get('client_secret')),'config_file':str(self.path) if private else None}

    def save(self, value):
        from server.core.permissions import Policy
        Policy(self.store).require('platform','manage')
        c=self.config();mode=value.get('mode','local');base=value.get('public_url','').rstrip('/');client=value.get('client_id','').strip();secret=value.get('client_secret') or c.get('client_secret','');tenants=value.get('allowed_tenants',[])
        if mode not in ('local','team','password') or not isinstance(tenants,list) or not all(isinstance(x,str) and len(x)<200 for x in tenants):raise ValueError('认证配置格式无效')
        parsed=urlsplit(base)
        if base and (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.username):raise ValueError('对外地址必须是完整站点地址，不带路径或账号')
        if parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1'):raise ValueError('团队访问必须配置 HTTPS；可由 Mac 上的反向代理提供')
        if mode=='team':
            if not client or not secret or not base:raise ValueError('团队模式需要飞书应用 ID、Secret 和固定对外地址')
            if value.get('allow_all_tenants') is not True and not tenants:raise ValueError('请配置允许的企业，或显式允许所有企业登记')
            with self.store.connection() as db:
                if not db.execute("SELECT 1 FROM users WHERE tenant_key!='local' AND global_role='project_lead' AND status='active'").fetchone():raise ValueError('先用飞书登录登记账号，再由本机负责人任命平台负责人，最后启用团队模式')
        data={'mode':mode,'public_url':base,'registration_open':value.get('registration_open',True) is True}
        if mode!='password':data.update({'client_id':client,'client_secret':secret,'allowed_tenants':list(dict.fromkeys(tenants)), 'allow_all_tenants':value.get('allow_all_tenants') is True})
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_name('.team-auth-'+uuid.uuid4().hex+'.tmp')
        try:
            fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
            os.replace(temp,self.path)
        finally:
            if temp.exists():temp.unlink()
        with self.store.connection() as db:
            if c['mode']!=mode:db.execute('DELETE FROM auth_sessions')
            db.execute('INSERT INTO team_audit(actor,action,detail) VALUES(?,?,?)',(user_id(),'auth_configured','认证配置已更新；不记录密钥'))
        return self.status(True)

    @staticmethod
    def direct_loopback(headers, peer):
        try:loopback=ipaddress.ip_address(peer).is_loopback
        except ValueError:loopback=False
        host=urlsplit('//'+headers.get('Host','')).hostname
        return loopback and host in ('127.0.0.1','localhost','::1') and not any(
            headers.get(key) for key in ('X-Forwarded-For','Forwarded','X-Forwarded-Host','X-Forwarded-Proto'))

    def identity(self, headers, peer):
        token=cookie_value(headers,'studioflow_session')
        if token:
            with self.store.connection() as db:
                r=db.execute('SELECT u.id,u.status FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',(digest(token),time.time())).fetchone()
                password_mode=self.config()['mode']=='password'
                if r and r['status']!='disabled' and (not password_mode or db.execute('SELECT 1 FROM local_credentials WHERE user_id=?',(r['id'],)).fetchone()):return r['id']
            raise AuthenticationRequired('登录已过期或账号已禁用，请重新登录')
        if self.config()['mode']=='local':
            if self.direct_loopback(headers,peer):return 'local'
        raise AuthenticationRequired('请先登录')

    def session(self, actor):
        with self.store.connection() as db:
            row=db.execute('SELECT u.id,u.name,u.tenant_key,u.status,u.global_role,c.username FROM users u LEFT JOIN local_credentials c ON c.user_id=u.id WHERE u.id=?',(actor,)).fetchone()
            if not row:raise AuthenticationRequired('账号不存在')
            return {'user':dict(row),'mode':self.config()['mode']}

    def begin(self):
        c=self.config()
        if c['mode']=='password':raise ValueError('当前使用本地账号登录，飞书登录已停用')
        if not c.get('client_id') or not c.get('client_secret') or not c.get('public_url'):raise ValueError('请先由本机负责人配置飞书登录')
        state=secrets.token_urlsafe(32);browser=secrets.token_urlsafe(32)
        with self.store.connection() as db:
            db.execute('DELETE FROM auth_states WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO auth_states VALUES(?,?,?)',(digest(state),digest(browser),time.time()+600))
        return 'https://accounts.feishu.cn/open-apis/authen/v1/authorize?'+urlencode({'client_id':c['client_id'],'redirect_uri':c['public_url']+'/auth/feishu/callback','response_type':'code','state':state}),browser

    def request_json(self, url, data=None, token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['Authorization']='Bearer '+token
        try:
            with urlopen(Request(url,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=20) as r:
                raw=r.read(1024*1024+1)
            if len(raw)>1024*1024:raise ValueError('飞书响应过大')
            result=json.loads(raw)
        except (HTTPError,URLError,TimeoutError,ValueError) as exc:raise ValueError('飞书认证请求失败，请检查应用配置与网络后重新登录') from exc
        if result.get('code',0)!=0 or result.get('error'):raise ValueError('飞书拒绝认证请求，请检查应用权限、安装范围和回调地址')
        return result

    def callback(self, state, code, browser):
        if self.config()['mode']=='password':raise ValueError('当前使用本地账号登录，飞书登录已停用')
        if not all(isinstance(x,str) and x for x in (state,code,browser)):raise ValueError('登录参数缺失，请重新登录')
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM auth_states WHERE state_hash=?',(digest(state),)).fetchone()
            db.execute('DELETE FROM auth_states WHERE state_hash=?',(digest(state),))
        if not row or row['expires']<time.time() or not secrets.compare_digest(row['browser_hash'],digest(browser)):raise ValueError('登录校验已过期或不匹配，请重新登录')
        c=self.config()
        tokens=self.request_json('https://open.feishu.cn/open-apis/authen/v2/oauth/token',{'grant_type':'authorization_code','client_id':c['client_id'],'client_secret':c['client_secret'],'code':code,'redirect_uri':c['public_url']+'/auth/feishu/callback'})
        access=tokens.get('access_token')
        if not isinstance(access,str) or not access:raise ValueError('飞书未返回访问令牌')
        info=self.request_json('https://open.feishu.cn/open-apis/authen/v1/user_info',token=access).get('data',{})
        tenant=info.get('tenant_key');openid=info.get('open_id');name=info.get('name')
        if not all(isinstance(x,str) and 0<len(x)<300 for x in (tenant,openid,name)):raise ValueError('飞书用户或企业标识缺失')
        if not c.get('allow_all_tenants') and tenant not in c.get('allowed_tenants',[]):raise PermissionError('当前飞书企业未获准登记')
        session=secrets.token_urlsafe(48)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM users WHERE tenant_key=? AND open_id=?',(tenant,openid)).fetchone()
            actor=row['id'] if row else uuid.uuid4().hex
            if row and row['status']=='disabled':raise PermissionError('账号已禁用')
            if not row:
                db.execute('INSERT INTO users(id,tenant_key,open_id,name) VALUES(?,?,?,?)',(actor,tenant,openid,name))
                db.execute("INSERT INTO user_preferences(user_id,active_role,default_workspace) VALUES(?,'qa','testing')",(actor,))
            else:db.execute('UPDATE users SET name=? WHERE id=?',(name,actor))
            db.execute('DELETE FROM auth_sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO auth_sessions(token_hash,user_id,expires) VALUES(?,?,?)',(digest(session),actor,time.time()+43200))
            db.execute('INSERT INTO team_audit(actor,action,detail) VALUES(?,?,?)',(actor,'feishu_login','飞书登录；'+tenant))
        return session,actor

    def promote_owner(self, actor, confirmed):
        from server.core.permissions import Policy
        Policy(self.store).require('platform','manage')
        if confirmed is not True:raise ValueError('需要确认任命平台负责人')
        with self.store.connection() as db:
            row=db.execute("SELECT * FROM users WHERE id=? AND tenant_key!='local'",(actor,)).fetchone()
            if not row:raise ValueError('请先让目标用户注册账号')
            db.execute("UPDATE users SET global_role='project_lead',status='active' WHERE id=?",(actor,))
            db.execute("INSERT OR IGNORE INTO studio_memberships SELECT studio_id,?,'studio_owner' FROM studio_memberships WHERE user_id='local'",(actor,))
            db.execute('INSERT INTO team_audit(actor,action,detail) VALUES(?,?,?)',(user_id(),'platform_owner_appointed',json.dumps({'user_id':actor})))
        return {'ok':True}

    def logout(self, headers):
        with self.store.connection() as db:db.execute('DELETE FROM auth_sessions WHERE token_hash=?',(digest(cookie_value(headers,'studioflow_session')),))
