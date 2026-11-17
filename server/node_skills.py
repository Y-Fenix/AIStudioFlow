"""节点规则是数据，不授权工具、写入或绕过证据门禁。"""
import contextvars
from contextlib import contextmanager
from server.skill_catalog import github_default

_current=contextvars.ContextVar('node_skill',default='')
NAMES=('用例','执行','归因','筛选','提单','回归')
def defaults():
    return {str(i):github_default(f'testing:{i}') for i in range(6)}

def validate(content):
    if not isinstance(content,str) or not content.strip() or len(content.encode())>100000:
        raise ValueError('Skill须为非空UTF-8 Markdown，最大100KB')
    return content

@contextmanager
def skill_scope(content):
    token=_current.set(content)
    try: yield
    finally: _current.reset(token)

def current_skill(): return _current.get()
