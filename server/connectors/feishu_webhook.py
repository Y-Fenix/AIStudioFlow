"""Feishu group bot transport. Never follows redirects or exposes response secrets."""
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError, URLError

class DeliveryRejected(ValueError): pass
class DeliveryUnknown(ValueError): pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

urlopen = build_opener(NoRedirect()).open

def validate_webhook(url):
    if not isinstance(url, str): raise ValueError('需要飞书群机器人 Webhook')
    p=urlsplit(url)
    if (p.scheme!='https' or p.netloc!='open.feishu.cn' or p.query or p.fragment
            or not re.fullmatch(r'/open-apis/bot/v2/hook/[a-zA-Z0-9-]{20,100}', p.path)):
        raise ValueError('Webhook 必须是 open.feishu.cn 的完整 HTTPS 群机器人地址')
    return url

def signing(secret, timestamp):
    return base64.b64encode(hmac.new((str(timestamp)+'\n'+secret).encode(), b'', hashlib.sha256).digest()).decode()

def send_card(config, card):
    payload={'msg_type':'interactive','card':card}
    if config.get('secret'):
        timestamp=str(int(time.time()));payload.update(timestamp=timestamp,sign=signing(config['secret'],timestamp))
    request=Request(validate_webhook(config['webhook']), data=json.dumps(payload,ensure_ascii=False).encode(),
                    headers={'Content-Type':'application/json; charset=utf-8'},method='POST')
    try:
        with urlopen(request,timeout=15) as response: raw=response.read(65537)
    except HTTPError as exc:
        if 400<=exc.code<500:raise DeliveryRejected('飞书拒绝请求：HTTP '+str(exc.code)) from None
        raise DeliveryUnknown('飞书 HTTP 响应不确定：'+str(exc.code)+'；请核对群消息后补发') from None
    except (URLError,TimeoutError,OSError):
        raise DeliveryUnknown('网络响应不确定；可能已送达，请核对群消息后补发') from None
    try:
        if len(raw)>65536:raise ValueError()
        value=json.loads(raw)
    except (ValueError,TypeError):raise DeliveryUnknown('飞书响应格式异常；请核对群消息后补发') from None
    if not isinstance(value,dict):raise DeliveryUnknown('飞书响应缺少结果')
    code=value.get('code',value.get('StatusCode'))
    if type(code) is not int:raise DeliveryUnknown('飞书未返回明确业务状态')
    if code!=0:raise DeliveryRejected('飞书拒绝消息，业务码 '+str(code)+'；请检查机器人安全设置')
