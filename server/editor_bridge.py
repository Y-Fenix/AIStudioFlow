"""本地Editor邮箱协议；未连接/未就绪时不创建运行请求。"""
import hashlib
import json
import time
import uuid
from pathlib import Path

MAILBOX = Path(__file__).resolve().parents[1]/'data/editor-bridge'


def preflight(binding, mailbox=MAILBOX):
    from server.gagasort import inspect_project
    current=inspect_project(binding['repository'],binding['branch'])
    if current['code_fingerprint'] != binding['code_fingerprint'] or current['commit'] != binding['commit']:
        raise ValueError('代码已变化，请重新绑定')
    path=Path(mailbox)/'heartbeat.json'
    try:
        heartbeat=json.loads(path.read_text())
    except (OSError,ValueError):
        return {'connected':False,'ready':False,'reason':'Editor桥接未连接；需要安装并在Editor菜单手动连接'}
    try:
        fresh=0 <= time.time()-heartbeat['unix'] <= 5
        project=Path(heartbeat['projectRoot']).resolve() == Path(current['project_root']).resolve()
        runner=Path(current['project_root'])/'Assets/Editor/Tools/TEST/TEST_RealGameUiSmokeWindow.cs'
        source_hash=hashlib.sha256(runner.read_bytes()).hexdigest()
        matches=heartbeat['runnerSha256'] == source_hash
    except (KeyError,TypeError,OSError,ValueError):
        return {'connected':False,'ready':False,'reason':'Editor桥接心跳格式无效'}
    if not fresh or not project or not matches:
        return {'connected':False,'ready':False,'reason':'Editor心跳过期、项目不一致或运行器代码已变化'}
    ready=heartbeat.get('playing') is True and heartbeat.get('paused') is False and heartbeat.get('compiling') is False
    return {'connected':True,'ready':ready,'reason':'已连接，等待用户确认执行设置冒烟' if ready else '需要已运行且未暂停、未编译的Play Mode',
            'runner_sha256':source_hash,'project_root':current['project_root'],'mode':'settings_smoke',
            'scope':'仅复用既有设置冒烟；不含GM或连胜分组验证，不自动启动Unity'}


def submit(binding, mailbox=MAILBOX):
    import fcntl
    mailbox=Path(mailbox)
    if not mailbox.is_dir():
        raise ValueError('Editor邮箱尚未连接')
    with (mailbox/'.dispatch.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _submit_locked(binding, mailbox)


def _submit_locked(binding, mailbox):
    mailbox=Path(mailbox)
    state=preflight(binding,mailbox)
    if not state['ready']:
        raise ValueError(state['reason'])
    # 一个邮箱串行；异常任务必须人工核对，绝不自动重跑。
    for request in [*mailbox.glob('*.request.json'),*mailbox.glob('*.claimed.json')]:
        identity=request.name.split('.')[0]
        result=mailbox/(identity+'.result.json')
        try: terminal=json.loads(result.read_text()).get('status') in ('completed','rejected')
        except (OSError,ValueError): terminal=False
        if not terminal:raise ValueError('Editor邮箱已有未完成或结果不确定的请求')
    identity=uuid.uuid4().hex
    request={'id':identity,'mode':'settings_smoke','projectRoot':state['project_root'],
             'runnerSha256':state['runner_sha256'],'expiresUnix':int(time.time())+30}
    temporary=mailbox/(identity+'.tmp')
    temporary.write_text(json.dumps(request,ensure_ascii=False))
    temporary.replace(mailbox/(identity+'.request.json'))
    return {'id':identity,'status':'submitted','mode':'settings_smoke',
            'code_fingerprint':binding['code_fingerprint'],'scope':state['scope']}
