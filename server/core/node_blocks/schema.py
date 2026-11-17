"""Versioned data-only block contract. No uploaded executable code."""
import copy
import json
import re
from urllib.parse import urlsplit

TYPES = {
    'input': {'label':'资料输入', 'fields':{'label':'text','required':'bool'}},
    'ai': {'label':'AI / Skill 任务', 'fields':{'label':'text','prompt':'text'}},
    'checklist': {'label':'检查清单', 'fields':{'label':'text','items':'list'}},
    'template': {'label':'交付模板', 'fields':{'label':'text','text':'text'}},
    'review': {'label':'人工审核', 'fields':{'label':'text'}},
    'tool': {'label':'外部工具入口', 'fields':{'label':'text','url':'url'}},
    'node': {'label':'部门节点', 'fields':{'node':'text','label':'text','description':'text','inputs':'text','skill':'text','skill_name':'text','auto_next':'bool'}},
    'task': {'label':'自定义节点', 'fields':{'label':'text','description':'text','inputs':'text','skill':'text','skill_name':'text','auto_next':'bool','blocks':'blocks'}},
}


def validate_blocks(value, *, flow=False):
    if not isinstance(value,list) or len(value)>30 or len(json.dumps(value,ensure_ascii=False).encode())>200000:
        raise ValueError('积木最多30个，配置最大200KB')
    seen=set()
    for b in value:
        if not isinstance(b,dict) or set(b)-{'id','type','config'}:raise ValueError('积木格式无效')
        identity=b.get('id');kind=b.get('type');config=b.get('config')
        if not isinstance(identity,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',identity) or identity in seen:raise ValueError('积木ID无效或重复')
        seen.add(identity)
        if not isinstance(kind,str) or kind not in TYPES or kind in ('node','task') and not flow:raise ValueError('积木类型未注册或不能嵌套节点')
        if not isinstance(config,dict) or set(config)-set(TYPES[kind]['fields']):raise ValueError('积木属性未注册')
        for k,v in config.items():
            field=TYPES[kind]['fields'][k]
            if field=='blocks':
                validate_blocks(v)
                if any(TYPES[child['type']].get('department') for child in v):raise ValueError('自定义节点不能直接使用部门私有积木')
            elif field=='bool':
                if type(v) is not bool:raise ValueError('必填属性须为布尔值')
            elif field=='list':
                if not isinstance(v,list) or not 1<=len(v)<=50 or any(not isinstance(x,str) or not x.strip() or len(x)>1000 for x in v):raise ValueError('清单须有1至50个非空条目')
            elif not isinstance(v,str) or len(v)>16000:raise ValueError('积木文字格式无效或过长')
            elif field=='url':
                u=urlsplit(v)
                if u.scheme!='https' or not u.hostname or u.username or u.password:raise ValueError('工具只接受无凭据 HTTPS 地址')
        for field in {'ai':'prompt','template':'text','tool':'url','node':'node'}.get(kind,'').split():
            if not config.get(field,'').strip():raise ValueError('请填写积木必需属性：'+field)
        if kind=='checklist' and not config.get('items'):raise ValueError('检查清单不能为空')
        if kind=='task' and not config.get('blocks'):raise ValueError('自定义节点至少需要一个内部积木')
        if kind=='template' and any(x not in ('input','previous') for x in re.findall(r'{{\s*(.*?)\s*}}',config['text'])):raise ValueError('模板只支持 {{input}} 和 {{previous}}')
    return copy.deepcopy(value)


def migrate(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS node_blueprints(project_id TEXT NOT NULL REFERENCES projects(id),node TEXT NOT NULL,
        revision INTEGER NOT NULL,blocks TEXT NOT NULL,updated_by TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(project_id,node));
    CREATE TABLE IF NOT EXISTS block_templates(id TEXT PRIMARY KEY,studio_id TEXT NOT NULL REFERENCES studios(id),
        department TEXT NOT NULL,name TEXT NOT NULL,revision INTEGER NOT NULL,archived INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS block_template_versions(template_id TEXT NOT NULL REFERENCES block_templates(id),
        revision INTEGER NOT NULL,blocks TEXT NOT NULL,author TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(template_id,revision));
    CREATE TABLE IF NOT EXISTS custom_flows(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
        name TEXT NOT NULL,revision INTEGER NOT NULL,blocks TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,
        author TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS block_runs(id TEXT PRIMARY KEY,studio_id TEXT NOT NULL,project_id TEXT NOT NULL,
        flow_id TEXT NOT NULL DEFAULT '',node TEXT NOT NULL DEFAULT '',actor TEXT NOT NULL,status TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 0,cursor INTEGER NOT NULL DEFAULT 0,snapshot TEXT NOT NULL,
        results TEXT NOT NULL DEFAULT '[]',input TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
    ''')

    if 'progress' not in {r['name'] for r in db.execute('PRAGMA table_info(block_runs)')}:
        db.execute('ALTER TABLE block_runs ADD COLUMN progress TEXT')
    if 'draft' not in {r['name'] for r in db.execute('PRAGMA table_info(block_runs)')}:
        db.execute("ALTER TABLE block_runs ADD COLUMN draft TEXT NOT NULL DEFAULT 'null'")

    if 'kind' not in {r['name'] for r in db.execute('PRAGMA table_info(block_templates)')}:
        db.execute("ALTER TABLE block_templates ADD COLUMN kind TEXT NOT NULL DEFAULT 'node'")

    for table in ('node_blueprints','custom_flows'):
        if 'sources' not in {r['name'] for r in db.execute('PRAGMA table_info('+table+')')}:
            db.execute("ALTER TABLE "+table+" ADD COLUMN sources TEXT NOT NULL DEFAULT '[]'")
    if 'description' not in {r['name'] for r in db.execute('PRAGMA table_info(custom_flows)')}:
        db.execute("ALTER TABLE custom_flows ADD COLUMN description TEXT NOT NULL DEFAULT ''")
