"""Local model discovery and application-only selection; never exposes credentials."""
import contextvars,json,os,tomllib,tempfile
from urllib.parse import urlsplit
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from server.responses_model import configured_connection
_selection=contextvars.ContextVar('ai_selection',default=None)
def current_selection():return _selection.get()
@contextmanager
def selection_scope(value):
 token=_selection.set(value)
 try:yield
 finally:_selection.reset(token)
def defaults():
 home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
 try:config=tomllib.loads((home/'config.toml').read_text())
 except FileNotFoundError:config={}
 return {'model':os.environ.get('TESTFLOW_CODEX_MODEL',config.get('model','gpt-6.1-sol')),'effort':os.environ.get('TESTFLOW_CODEX_EFFORT',config.get('model_reasoning_effort','high'))}
def fetch_models(connection):
 url=connection.endpoint.rsplit('/responses',1)[0]+'/models'
 request=Request(url,headers={'Authorization':'Bearer '+connection.key,'Accept':'application/json'})
 try:
  with urlopen(request,timeout=20) as r:raw=r.read(2000001)
  if len(raw)>2000000:raise ValueError('模型列表过大')
  return json.loads(raw)
 except HTTPError as e:raise ValueError('模型列表查询失败：HTTP '+str(e.code)) from None
 except (URLError,TimeoutError,ValueError):raise ValueError('无法读取中转站模型列表，请检查服务连接') from None
class ModelSettings:
 def __init__(self,store):
  self.store=store
  with store.connection() as db:db.execute('CREATE TABLE IF NOT EXISTS ai_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
 def read(self,key,fallback=None):
  with self.store.connection() as db:row=db.execute('SELECT value FROM ai_settings WHERE key=?',(key,)).fetchone()
  return json.loads(row['value']) if row else fallback
 def write(self,key,value):
  with self.store.connection() as db:db.execute('INSERT OR REPLACE INTO ai_settings VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
 def selection(self):return self.read('selection',defaults())
 def activate(self,source):
  if source not in ('relay','custom'):raise ValueError('模型来源无效')
  if source=='custom' and not self.custom():raise ValueError('请先保存自定义 API 配置')
  self.write('active_source',source)
  return self.status()
 def discover(self):
  connection=configured_connection()
  if not connection:raise ValueError('未识别到带API凭据的本机中转配置；请先配置Codex模型服务')
  raw=fetch_models(connection);rows=raw.get('data') if isinstance(raw,dict) else None
  if not isinstance(rows,list):raise ValueError('中转站模型列表格式不正确')
  home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
  try:cached=json.loads((home/'models_cache.json').read_text()).get('models',[])
  except (OSError,ValueError):cached=[]
  capabilities={m.get('slug'):[v.get('effort') for v in m.get('supported_reasoning_levels',[]) if isinstance(v,dict)] for m in cached if isinstance(m,dict)}
  models=[];seen=set()
  for item in rows:
   if not isinstance(item,dict):continue
   name=item.get('id')
   if not isinstance(name,str) or not name or len(name)>200 or name in seen:continue
   seen.add(name)
   efforts=item.get('supported_reasoning_efforts',item.get('reasoning_efforts',[]))
   if not isinstance(efforts,list):efforts=[]
   source='中转站声明'
   if not efforts and capabilities.get(name):efforts=capabilities[name];source='本机Codex能力缓存（中转支持未验证）'
   if not efforts and 'openai-response' in item.get('supported_endpoint_types',[]) and not ('image' in name.lower()):
    efforts=['low','medium','high'];source='Responses参数选项（中转支持未确认）'
   efforts=[v for v in ('low','medium','high','xhigh') if v in efforts]
   endpoints=item.get('supported_endpoint_types',[])
   usable=not endpoints or 'openai-response' in endpoints
   if 'image' in name.lower():usable=False
   models.append({'id':name,'efforts':efforts,'capability_source':source if efforts else '能力未确认','usable':usable})
  if not models:raise ValueError('中转站没有返回可用模型')
  result={'endpoint':connection.endpoint.rsplit('/responses',1)[0],'models':models,'selection':self.selection()}
  self.write('catalog',result);return result
 def custom_path(self):return Path(self.store.path).resolve().parent/'ai-model-custom.json'
 def custom(self):
  try:return json.loads(self.custom_path().read_text())
  except FileNotFoundError:return {}
 def runtime_selection(self):
  # 来源和中转模型在同一个数据库快照内读取，避免切换时读到半套设置。
  with self.store.connection() as db:
   rows={r['key']:json.loads(r['value']) for r in db.execute("SELECT key,value FROM ai_settings WHERE key IN ('active_source','selection')")}
  source=rows.get('active_source','relay')
  if source not in ('relay','custom'):raise ValueError('模型来源无效，请重新保存模型设置')
  if source=='custom':
   value=self.custom()
   if not value:raise ValueError('自定义模型配置文件不存在')
   return {**value,'source':'custom'}
  return {**rows.get('selection',defaults()),'source':'relay'}
 def generation_client(self):
  # Web入口统一采用界面所选来源，旧TESTFLOW_MODEL_PROVIDER不能绕过设置。
  from server.codex_model import CodexModel
  return CodexModel()
 def status(self):
  home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
  custom=self.custom();safe={k:v for k,v in custom.items() if k!='api_key'}
  return {**self.read('catalog',{'models':[],'endpoint':''}),'selection':self.selection(),
   'active_source':self.read('active_source','relay'),'custom':{**safe,'has_api_key':bool(custom.get('api_key'))},
   'config_file':str(self.custom_path()),'relay_config_file':str(home/'config.toml'),
   'relay_auth_file':str(home/'auth.json'),'selection_file':str(Path(self.store.path).resolve())}
 def save_custom(self,value):
  url=value.get('base_url','').strip().rstrip('/')
  parsed=urlsplit(url)
  if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or (parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1'))):
   raise ValueError('接口地址须使用HTTPS；本机localhost/127.0.0.1可使用HTTP')
  protocol=value.get('protocol','responses')
  if protocol not in ('responses','chat'):raise ValueError('接口协议不支持')
  model=value.get('model','').strip();effort=value.get('effort') or None
  if not model or len(model)>200 or any(c in model for c in '\r\n'):raise ValueError('请填写有效模型名称')
  if effort not in (None,'low','medium','high','xhigh'):raise ValueError('推理强度无效')
  key=value.get('api_key') or self.custom().get('api_key','')
  if not isinstance(key,str) or any(c in key for c in '\r\n'):raise ValueError('API Key格式错误')
  result={'base_url':url,'protocol':protocol,'model':model,'effort':effort,'api_key':key}
  path=self.custom_path();path.parent.mkdir(parents=True,exist_ok=True)
  fd,tmp=tempfile.mkstemp(prefix='.ai-custom-',dir=path.parent)
  try:
   with os.fdopen(fd,'w') as f:json.dump(result,f,ensure_ascii=False,indent=2)
   os.chmod(tmp,0o600);os.replace(tmp,path)
  finally:
   if os.path.exists(tmp):os.unlink(tmp)
  self.write('active_source','custom');return self.status()

 def save(self,value):
  catalog=self.read('catalog',{});row=next((r for r in catalog.get('models',[]) if r['id']==value.get('model')),None)
  if not row:raise ValueError('请先刷新并选择中转站实际返回的模型')
  if row.get('usable') is False:raise ValueError('该模型未声明支持文本Responses接口，不能用于测试用例生成')
  effort=value.get('effort') or None
  if effort is not None and effort not in row['efforts']:raise ValueError('该模型未声明支持所选推理强度')
  selected={'model':row['id'],'effort':effort}
  with self.store.connection() as db:
   db.executemany('INSERT OR REPLACE INTO ai_settings VALUES (?,?)',[
    ('selection',json.dumps(selected)),('active_source',json.dumps('relay'))])
  return selected
