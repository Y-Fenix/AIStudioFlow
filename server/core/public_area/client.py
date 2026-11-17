"""Fixed-endpoint connector. Sessions never reach the browser; redirects are rejected."""
import ipaddress
import json
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from server.core.public_area.packages import encode

class RemoteError(Exception):
    def __init__(self,message,status=0):super().__init__(message);self.status=status

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def validate_url(value,allow_lan_http=False):
    if not isinstance(value,str):raise ValueError('请填写公区服务器地址')
    u=urlsplit(value.rstrip('/'))
    if (u.scheme not in ('https','http') or not u.hostname or u.username or u.password or u.path or u.query or u.fragment
        or any(c.isspace() or ord(c)<32 for c in value)):raise ValueError('公区地址只填写站点，不带路径、账号或参数')
    try:u.port
    except ValueError:raise ValueError('公区地址端口不合法') from None
    try:address=ipaddress.ip_address(u.hostname)
    except ValueError:address=None
    if address and (address.is_link_local or address.is_unspecified or address.is_multicast):raise ValueError('不允许该服务器地址')
    if u.scheme=='http':
        if allow_lan_http is not True:raise ValueError('HTTP 需要明确开启局域网连接')
        from server.core.notification_settings import site_url
        site_url(value)
    return value.rstrip('/')

class Remote:
    def __init__(self,url,session='',allow_lan_http=False):
        self.url=validate_url(url,allow_lan_http);self.session=session;self.cookie=''
    def request(self,path,body=None):
        if not path.startswith('/api/') or path.startswith('//') or '\n' in path:raise ValueError('远端接口不合法')
        headers={'Accept':'application/json','Content-Type':'application/json'}
        if self.session:headers['Cookie']='studioflow_session='+self.session
        req=Request(self.url+path,data=None if body is None else encode(body).encode(),headers=headers,method='GET' if body is None else 'POST')
        try:
            with build_opener(NoRedirect()).open(req,timeout=20) as response:
                jar=SimpleCookie();jar.load(response.headers.get('Set-Cookie',''))
                self.cookie=jar['studioflow_session'].value if 'studioflow_session' in jar else ''
                data=response.read(3*1024*1024+1)
                if len(data)>3*1024*1024:raise RemoteError('公区响应超出限制')
                return json.loads(data)
        except HTTPError as exc:
            try:message=json.loads(exc.read(8192)).get('error','公区拒绝请求')
            except (ValueError,AttributeError):message='公区拒绝请求或返回跳转'
            status=exc.code;exc.close()
            raise RemoteError(str(message)[:500],status) from None
        except (URLError,OSError,ValueError) as exc:raise RemoteError('公区连接中断或返回无效内容；请核对地址和连接状态') from None
