"""Strict, inert publication format. No archive extraction, executable HTML or paths."""
import base64
import hashlib
import json
import re
from pathlib import PurePosixPath

MAX_PACKAGE=2*1024*1024
MAX_ATTACHMENT=700000
KINDS=('result','test_cases','bug_draft','skill','workflow','requirement')
EXTENSIONS={'.txt','.md','.json','.csv','.png','.jpg','.jpeg','.pdf','.docx','.xlsx'}


def encode(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def sha(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def redact(value):
    if isinstance(value,str):
        value=re.sub(r'(?i)\b[A-Z]:[\\/][^\s\u4e00-\u9fff<>"\x00]+','[本机路径已隐藏]',value)
        value=re.sub(r'(?<![:/\w])/(?:Users|home|var|private|tmp|Volumes|mnt|opt|etc|root|srv|data|workspace)/[^\s\u4e00-\u9fff<>"\x00]+','[本机路径已隐藏]',value)
        value=re.sub(r'file://[^\s<>"\x00]+','[本机路径已隐藏]',value)
        return value
    if isinstance(value,list):return [redact(v) for v in value]
    if isinstance(value,dict):return {k:redact(v) for k,v in value.items()}
    return value


def text(value,name,limit,empty=False):
    if not isinstance(value,str) or len(value.encode())>limit or (not empty and not value.strip()):
        raise ValueError(name+'格式或长度不合法')
    return value


def validate(raw):
    required={'schema_version','title','description','version_id','department','node','kind','source','content','attachments'}
    if not isinstance(raw,dict) or not required.issubset(raw) or set(raw)-required-{'includes'} or type(raw.get('schema_version')) is not int or raw['schema_version']!=1:
        raise ValueError('发布包格式不合法或包含未允许的字段')
    if len(encode(raw).encode())>MAX_PACKAGE:raise ValueError('发布包不得超过 2MB，请拆分发布')
    p=json.loads(encode(raw))
    if 'includes' in p and (not isinstance(p['includes'],list) or any(i not in ('requirements','skill','workflow','attachments') for i in p['includes'])):raise ValueError('附带内容类别不合法')
    for key,limit in [('title',240),('description',4000),('version_id',80),('department',40),('node',160),('content',1200000)]:
        text(p[key],key,limit,empty=key in ('description','content'))
    if p['kind'] not in KINDS:raise ValueError('不支持的交付物类型')
    s=p['source']
    if not isinstance(s,dict) or set(s)!={'id','revision','digest'} or type(s.get('revision')) is not int or s['revision']<0:
        raise ValueError('来源修订不合法')
    text(s.get('id'),'来源 ID',160)
    if not isinstance(s.get('digest'),str) or not re.fullmatch('[a-f0-9]{64}',s['digest']):raise ValueError('来源指纹不合法')
    if not isinstance(p['attachments'],list) or len(p['attachments'])>10:raise ValueError('附件最多 10 个')
    names=set()
    for a in p['attachments']:
        if not isinstance(a,dict) or set(a)!={'name','data','sha256'}:raise ValueError('附件格式不合法')
        name=text(a['name'],'附件名',160)
        if '/' in name or '\\' in name or ':' in name or any(ord(c)<32 for c in name) or name in ('.','..') or name in names:
            raise ValueError('附件名不合法或重复')
        names.add(name)
        if PurePosixPath(name).suffix.lower() not in EXTENSIONS:raise ValueError('不支持的附件类型')
        try:data=base64.b64decode(a['data'],validate=True)
        except (ValueError,TypeError):raise ValueError('附件编码不合法') from None
        if len(data)>MAX_ATTACHMENT or hashlib.sha256(data).hexdigest()!=a['sha256']:raise ValueError('附件超限或哈希校验失败')
        # Structured text is normalized before final preview; binary files are explicit opt-in.
        if PurePosixPath(name).suffix.lower() in {'.txt','.md','.json','.csv'}:
            try:clean=redact(data.decode('utf-8')).encode('utf-8')
            except UnicodeDecodeError:raise ValueError('文本附件必须为 UTF-8') from None
            a['data']=base64.b64encode(clean).decode();a['sha256']=hashlib.sha256(clean).hexdigest()
    for key in ('title','description','content'):p[key]=redact(p[key])
    p['source']['id']=redact(p['source']['id'])
    return p


def visible(package):
    p=json.loads(encode(package))
    for a in p['attachments']:
        a['size']=len(base64.b64decode(a.pop('data')))
    return p
