"""Shared department/node catalog; testing continues to use its existing task workflow."""
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit
from server.node_skills import defaults
from server.skill_catalog import github_default

MODULE_ROOT = Path(__file__).resolve().parent.parent / 'departments'


def load_departments(root=MODULE_ROOT):
    """Load team-owned manifests; stable department ordering is a shell concern."""
    items = []
    for key in ('product', 'design', 'development', 'testing', 'growth'):
        path = root / key / 'manifest.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or value.get('id') != key or type(value.get('schema_version')) is not int or value['schema_version'] != 1:
            raise ValueError(f'部门模块协议无效：{key}')
        for field in ('name','title','en','icon','color','tint','desc','owner'):
            if not isinstance(value.get(field),str) or not value[field].strip():
                raise ValueError(f'部门模块字段无效：{key}.{field}')
        homepage=value.get('homepage')
        if (not isinstance(homepage,dict) or any(not isinstance(homepage.get(f),str) or not homepage[f].strip()
                for f in ('headline','description','eyebrow')) or not isinstance(homepage.get('focus'),list)
                or not homepage['focus'] or any(not isinstance(x,str) or not x.strip() for x in homepage['focus'])):
            raise ValueError(f'部门首页协议无效：{key}.homepage')
        execution=value.get('execution')
        if (not isinstance(execution,dict) or execution.get('adapter') not in ('manual','legacy_testing','adapter')
                or type(execution.get('automatic')) is not bool):
            raise ValueError(f'部门执行协议无效：{key}.execution')
        frontend=value.get('frontend',{})
        if (not isinstance(frontend,dict) or set(frontend)-{'entry'}
                or 'entry' in frontend and frontend['entry']!='ui.js'):
            raise ValueError(f'部门前端模块协议无效：{key}')
        tools=value.get('tools',[])
        if not isinstance(tools,list):raise ValueError(f'部门工具入口协议无效：{key}.tools')
        tool_ids=set()
        for tool in tools:
            if (not isinstance(tool,dict) or set(tool)-{'id','label','url'}
                    or any(not isinstance(tool.get(field),str) or not tool[field].strip() for field in ('id','label','url'))
                    or tool['id'] in tool_ids):
                raise ValueError(f'部门工具入口协议无效：{key}.tools')
            parsed=urlsplit(tool['url'])
            if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f'部门工具入口必须使用无凭据的 HTTPS URL：{key}.tools')
            tool_ids.add(tool['id'])
        adapters=value.get('tool_adapters',[])
        if not isinstance(adapters,list):raise ValueError(f'部门工具适配器协议无效：{key}.tool_adapters')
        adapter_ids=set()
        for adapter in adapters:
            if (not isinstance(adapter,dict) or set(adapter)-{'id','label','status','credentials'}
                    or any(not isinstance(adapter.get(field),str) or not adapter[field].strip()
                           for field in ('id','label','status','credentials'))
                    # A department manifest is declarative and cannot attest to a
                    # live API connection. Only platform-side health checks may do so.
                    or adapter['id'] in adapter_ids or adapter['status'] != 'unconfigured'
                    or adapter['credentials']!='platform_admin'):
                raise ValueError(f'部门工具适配器必须由平台管理员配置凭据：{key}.tool_adapters')
            adapter_ids.add(adapter['id'])
        nodes=value.get('nodes')
        if not isinstance(nodes,list) or not nodes or any(not isinstance(n,list) or len(n)!=7
                or any(not isinstance(field,str) or not field.strip() for field in n[:5]) for n in nodes):
            raise ValueError(f'部门节点定义无效：{key}')
        if any(any(not isinstance(n[i],str) or not n[i].strip() for i in (5,6)) for n in nodes):
            raise ValueError(f'部门节点输入输出契约无效：{key}')
        items.append(value)
    return items


DEPARTMENTS = load_departments()
METHODS = json.loads(Path(__file__).with_name('studio_methods.json').read_text(encoding='utf-8'))
ROLES = {'studio_owner': ('工作室负责人', 'overview'), 'product': ('产品', 'product'),
         'design': ('设计', 'design'), 'development': ('开发', 'development'),
         'qa': ('测试', 'testing'), 'growth': ('发行增长', 'growth')}


def node_definition(key, store=None, project=None, *, connection=None):
    if store is not None and project:
        from server.core.project_nodes import project_records
        for record in project_records(store,project,connection=connection):
            if record['id']==key:
                department=next(d for d in DEPARTMENTS if d['id']==key.split(':')[0])
                token=key.split(':',1)[1]
                return department, int(token) if token.isdigit() else token, record['definition']
        raise ValueError('节点标识无效')
    for department in DEPARTMENTS:
        for index, node in enumerate(department['nodes']):
            if key == f'{department["id"]}:{index}':
                return department, index, node
    raise ValueError('节点标识无效')


def default_skill(key, store=None, project=None):
    department, index, node = node_definition(key,store,project)
    if not isinstance(index,int):
        from server.core.project_nodes import custom_skill
        return custom_skill(key,node)
    if department['id'] == 'testing':
        return copy.deepcopy(defaults()[str(index)])
    return github_default(key)


def catalog():
    return {'departments': DEPARTMENTS,
            'roles': [{'id': key, 'name': value[0], 'workspace': value[1]} for key, value in ROLES.items()]}
