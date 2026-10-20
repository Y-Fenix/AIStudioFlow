"""复用本机指定 gm-mcp HTTP 配置；只允许明确列出的只读工具。"""
import json
import os
import tomllib
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit


class GmClient:
    READ_TOOLS = {'gm_health', 'gm_query_game_list', 'gm_resolve_pg', 'gm_resolve_server'}

    def __init__(self):
        home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
        try:
            config = tomllib.loads((home / 'config.toml').read_text())
            server = config.get('mcp_servers', {}).get('gm-mcp', {})
        except (OSError, ValueError):
            raise ValueError('无法读取本机 GM MCP 配置') from None
        self.url = server.get('url')
        if server.get('enabled', True) is False or not isinstance(self.url, str) or urlsplit(self.url).scheme not in ('http', 'https'):
            raise ValueError('尚未配置可用的 GM MCP HTTP 服务')
        self.headers = dict(server.get('http_headers', {}))
        for name, variable in server.get('env_http_headers', {}).items():
            if variable in os.environ:
                self.headers[name] = os.environ[variable]
        variable = server.get('bearer_token_env_var')
        if variable:
            if not os.environ.get(variable):
                raise ValueError('GM MCP 授权环境变量未配置')
            self.headers['Authorization'] = 'Bearer ' + os.environ[variable]
        self.session = None
        self.protocol = None

    def _post(self, body):
        headers = {**self.headers, 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        if self.protocol:
            headers['MCP-Protocol-Version'] = self.protocol
        try:
            with urlopen(Request(self.url, data=json.dumps(body).encode(), headers=headers), timeout=30) as response:
                raw = response.read(2000001)
                self.session = response.headers.get('Mcp-Session-Id', self.session)
                kind = response.headers.get('Content-Type', '')
            if len(raw) > 2000000:
                raise ValueError('GM MCP 响应过大')
            if 'id' not in body and not raw.strip():
                return {}
            if 'text/event-stream' in kind:
                messages = [json.loads(line[5:].strip()) for line in raw.decode().splitlines() if line.startswith('data:')]
                result = next((m for m in messages if m.get('id') == body.get('id')), None)
            else:
                result = json.loads(raw)
            if not isinstance(result, dict) or result.get('error'):
                raise ValueError('GM MCP 协议返回错误')
            return result.get('result', {})
        except HTTPError as exc:
            raise ValueError(f'GM MCP 请求失败（HTTP {exc.code}）') from None
        except (URLError, TimeoutError):
            raise ValueError('GM MCP 不可达或超时') from None
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError('GM MCP 响应格式不合法') from None

    def call_read(self, name, arguments):
        if name not in self.READ_TOOLS:
            raise ValueError('此连接器仅允许只读检查')
        if name != 'gm_health' and arguments.get('env') not in ('test', 'release'):
            raise ValueError('必须明确选择 GM 环境，不能默认')
        info = self._post({'jsonrpc':'2.0','id':1,'method':'initialize',
                           'params':{'protocolVersion':'2024-11-05','capabilities':{},
                                     'clientInfo':{'name':'testflow','version':'0.1'}}})
        self.protocol = info.get('protocolVersion')
        self._post({'jsonrpc':'2.0','method':'notifications/initialized'})
        result = self._post({'jsonrpc':'2.0','id':2,'method':'tools/call',
                             'params':{'name':name,'arguments':arguments}})
        if result.get('isError'):
            raise ValueError('GM 工具读取失败；未执行写入')
        texts = [c.get('text','') for c in result.get('content',[]) if c.get('type') == 'text']
        try:
            return result.get('structuredContent') or json.loads('\n'.join(texts))
        except (TypeError, ValueError):
            raise ValueError('GM 工具未返回结构化数据') from None

    def health(self):
        data = self.call_read('gm_health', {})
        if not isinstance(data, dict):
            raise ValueError('GM 健康响应不合法')
        return {key: data.get(key) for key in ('name','version','adminReachable','adminStatus')}
