"""Custom Responses gateways: explicit text-only SSE, no CLI agent envelope or tools."""
import json,os,tempfile,time,tomllib,subprocess,sys
from dataclasses import dataclass,field
from pathlib import Path
from urllib.parse import urlsplit
from server.processes import run as run_process

@dataclass
class Connection:
    endpoint:str
    key:str=field(repr=False)
    protocol:str="responses"

def configured_connection():
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    try:config=tomllib.loads((home/'config.toml').read_text())
    except FileNotFoundError:return None
    provider=config.get('model_provider')
    if not provider or provider=='openai':return None
    definition=config.get('model_providers',{}).get(provider,{})
    if definition.get('wire_api')!='responses' or not definition.get('base_url'):return None
    endpoint=definition['base_url'].rstrip('/')+'/responses'
    parsed=urlsplit(endpoint)
    local_http=parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1')
    if (parsed.scheme!='https' and not local_http) or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('远端模型服务必须使用HTTPS；HTTP仅允许本机回环地址')
    key=os.environ.get(definition.get('env_key','')) if definition.get('env_key') else None
    if not key:
        try:key=json.loads((home/'auth.json').read_text()).get('OPENAI_API_KEY')
        except (FileNotFoundError,json.JSONDecodeError):return None
    # OAuth credentials remain managed by CLI; never send them to a new destination.
    if not key:return None
    if any(c in key for c in '\r\n'):raise ValueError('模型认证配置格式错误')
    return Connection(endpoint,key)

class Events:
    def __init__(self,path):
        self.path=path;self.offset=0;self.pending=b'';self.text='';self.completed=None
        self.count=0;self.progress=0;self.last=None;self.failed=False
    def sample(self,final=False):
        if not self.path.exists():return
        with self.path.open('rb') as f:
            f.seek(self.offset);raw=f.read(2000001);self.offset=f.tell()
        self.pending+=raw
        if len(self.pending)>2000000:raise ValueError('模型流式响应过大')
        lines=self.pending.split(b'\n');self.pending=lines.pop()
        if final and self.pending:
            lines.append(self.pending);self.pending=b''
        for line in lines:
            if not line.startswith(b'data:'):continue
            try:e=json.loads(line[5:].strip())
            except (ValueError,UnicodeError):continue
            if not isinstance(e,dict):continue
            self.count+=1;kind=e.get('type');self.last=kind
            if kind in ('response.created','response.in_progress','response.output_item.added','response.output_text.delta','response.output_text.done','response.output_item.done','response.reasoning_summary_text.delta','response.reasoning_text.delta','response.completed'):
                self.progress+=1
            if kind=='response.output_text.delta':self.text+=e.get('delta','')
            if len(self.text)>2000000:raise ValueError('模型返回内容过大')
            if kind=='response.completed':self.completed=e.get('response')
            if kind in ('error','response.failed','response.incomplete'):self.failed=True

def request_json(connection,prompt,model,effort,timeout,callback):
    from server.codex_model import GatewayFailure
    started=time.monotonic();last_response=started;last_tick=started
    def emit(state,**extra):
        if callback:callback({'state':state,'transport':'responses_http','requested_model':model,'effort':effort,
            'timeout_kind':'inactivity','idle_timeout_seconds':timeout,'elapsed_seconds':round(time.monotonic()-started,2),
            'input_chars':len(prompt),'events_received':events.count,'assistant_chars':len(events.text),
            'progress_events':events.progress,'last_event':events.last,
            'seconds_since_response':round(time.monotonic()-last_response,1),**extra})
    with tempfile.TemporaryDirectory(prefix='testflow-responses-') as folder:
        p=Path(folder);headers=p/'headers';body=p/'request.json';output=p/'response.sse';status=p/'status';errors=p/'stderr'
        headers.write_text('Authorization: Bearer '+connection.key+'\nContent-Type: application/json\nAccept: text/event-stream\n');headers.chmod(0o600)
        payload={'model':model,'input':prompt,**({'reasoning':{'effort':effort}} if effort else {}),'stream':True,'store':False}
        if connection.protocol=='chat':payload={'model':model,'messages':[{'role':'user','content':prompt}],'stream':True,**({'reasoning_effort':effort} if effort else {})}
        body.write_text(json.dumps(payload,ensure_ascii=False));body.chmod(0o600)
        command=[sys.executable,str(Path(__file__).with_name('responses_worker.py')),
                 '--headers',str(headers),'--request',str(body),'--output',str(output),
                 '--endpoint',connection.endpoint]+(['--protocol','chat'] if connection.protocol=='chat' else [])
        events=Events(output);marker=0
        def probe():
            nonlocal marker,last_response
            events.sample()
            if events.failed:raise GatewayFailure('模型服务流式响应失败或未完成',retryable=True)
            changed=events.progress!=marker;marker=events.progress
            if changed:last_response=time.monotonic()
            return changed
        def tick():
            nonlocal last_tick
            if time.monotonic()-last_tick>=10:last_tick=time.monotonic();emit('running')
        emit('started')
        try:
            with status.open('w') as out,errors.open('w') as err:
                result=run_process(command,stdout=out,stderr=err,text=True,check=False,
                    idle_timeout=timeout,activity_probe=probe,on_tick=tick)
        except subprocess.TimeoutExpired:
            events.sample();emit('idle_timeout')
            raise GatewayFailure(f'模型服务连续{timeout}秒没有新响应（Responses HTTP）',retryable=True) from None
        events.sample(final=True);codes=status.read_text().splitlines();code=codes[-1].strip() if codes else ''
        if result.returncode or code!='200':
            # Never forward provider payloads, HTTP headers, tokens or requirement text.
            emit('cli_failed',upstream_error_code=int(code) if code.isdigit() else None)
            raise GatewayFailure('模型服务请求失败：HTTP '+(code if code.isdigit() else 'unknown')+' / transport',
                retryable=code in ('000','408','429','500','502','503','504') or (not code and bool(result.returncode)))
        if events.failed or not events.completed or events.completed.get('status')!='completed':
            emit('incomplete_response',response_status=(events.completed or {}).get('status'))
            raise GatewayFailure('模型服务返回未完成的响应，未保存为结果',retryable=True)
        texts=[c.get('text','') for item in events.completed.get('output',[]) if item.get('type')=='message' and item.get('role')=='assistant'
               for c in item.get('content',[]) if c.get('type')=='output_text']
        text=''.join(texts) or events.text
        if len(text)>2000000:raise ValueError('模型返回内容过大')
        try:value=json.loads(text)
        except ValueError:emit('invalid_json');raise ValueError('模型返回内容不是合法JSON') from None
        if not isinstance(value,dict):raise ValueError('模型必须返回JSON对象')
        emit('completed',output_bytes=len(text.encode()));return value
