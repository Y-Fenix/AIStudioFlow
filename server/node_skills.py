"""节点规则是数据，不授权工具、写入或绕过证据门禁。"""
import contextvars
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from server.model import PROMPT

_current=contextvars.ContextVar('node_skill',default='')
NAMES=('用例','执行','归因','筛选','提单','回归')
RULES=(PROMPT,'逐步骤静态审查需求和代码，保留真实源码引用；不启动Unity；缺证据不得通过。',
       '仅依据实际失败和源码证据提供候选根因，不将候选冒充确认。',
       '按确认根因筛选，保留每个排除理由与未决证据。',
       '同根因合并提单；明确静态推导与实机复现；保留条件、步骤、预期、实际、证据。',
       '按原用例及需求版本检查修复；不伪造修复概率；最终状态由用户决定。')

def defaults():
    result={str(i):{'name':NAMES[i], 'content':
            f'---\nname: testflow-stage-{i}\ndescription: {NAMES[i]}节点规则\n---\n\n'+RULES[i]} for i in range(6)}
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))).expanduser()
    for stage,directory,name,bundled in (
        ('0','test-test-case','TEST_Test_Case','cases.md'),
        ('1','test-testcase-codetest','TEST_Test_Codetest','codetest.md')):
        local=home/'skills'/directory/'SKILL.md'
        path=local if local.is_file() else Path(__file__).parent/'skills'/bundled
        content=validate(path.read_text(encoding='utf-8'))
        result[stage]={'name':name,'content':content,'source_kind':'local' if path==local else 'bundled',
                       'source_path':str(path.resolve()),'sha256':hashlib.sha256(content.encode()).hexdigest()}
    return result

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
