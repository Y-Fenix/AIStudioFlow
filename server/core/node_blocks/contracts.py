"""Trusted department extension registry; imported JSON cannot register a handler."""
import importlib.util
import re
from server.core.node_blocks.schema import TYPES

HANDLERS={}
LOADED=set()
PREFIXES={'product':'PRODUCT','design':'DESIGN','development':'DEV','testing':'QA'}


def register(identity,*,label,fields,execute):
    if not isinstance(identity,str) or not re.fullmatch(r'(product|design|development|testing)\.[a-z][a-z0-9_-]{0,50}',identity):raise ValueError('积木类型必须使用稳定部门前缀')
    if identity in TYPES:raise ValueError('积木类型已注册')
    if not isinstance(label,str) or not 1<=len(label)<=80 or not isinstance(fields,dict) or any(not isinstance(k,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,40}',k) or v not in ('text','bool','list','url') for k,v in fields.items()):raise ValueError('积木属性契约无效')
    if fields.get('label','text')!='text':raise ValueError('展示名称必须使用文本字段')
    if not callable(execute):raise ValueError('真实积木必须提供执行处理器')
    TYPES[identity]={'label':label,'fields':{'label':'text',**fields},'department':identity.split('.')[0]};HANDLERS[identity]=execute


def unregister(identity):
    if identity in HANDLERS:HANDLERS.pop(identity);TYPES.pop(identity,None)


def load_modules():
    from server.studio_catalog import MODULE_ROOT
    for dept,prefix in PREFIXES.items():
        path=MODULE_ROOT/dept/(prefix+'_blocks.py')
        if not path.is_file():continue
        key=str(path.resolve())
        if key in LOADED:continue
        spec=importlib.util.spec_from_file_location(key,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        before=set(HANDLERS)
        try:getattr(module,prefix+'_register_blocks')(register)
        except Exception:
            for identity in set(HANDLERS)-before:unregister(identity)
            raise
        LOADED.add(key)
