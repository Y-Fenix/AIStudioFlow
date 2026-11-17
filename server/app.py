"""仅监听本机的项目工作流 API 与 Web 文件服务。"""
import argparse
import json
import os
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from server.core.public_area.client import RemoteError
from server.store import Store
from server.requirements import review_cases
from server.model import ModelClient
from server.codex_model import CodexModel
from server.jobs import GenerationWorker
from server.connectors.lark import LarkClient
from server.gagasort import inspect_project, execute_logic
from server.triage import triage_report, filter_groups
from server.bugs import prepare_drafts, preview_field_mapping, confirm_existing_records, export_bug_preview, prepare_publication
from server.file_import import parse_file
from server.attribution import suggest_attribution
from server.regression import assess_logic_roots, review_logic_regression
from server.execution import map_cases
from server.connectors.gm import GmClient
from server.publication import PublicationLedger
from server.editor_bridge import preflight as editor_preflight
from server.status_change import StatusChanges

ROOT = Path(__file__).resolve().parent.parent


def create_server(host='127.0.0.1', port=8766, database=None, registry=None, local_development=False, runtime_mode='team'):
    """为测试或本地执行创建独立服务实例。"""
    if runtime_mode not in ('team','personal','public'):raise ValueError('未知部署模式')
    if runtime_mode=='personal' and host not in ('127.0.0.1','localhost','::1'):raise ValueError('个人模式仅允许监听本机')
    if runtime_mode=='public' and local_development:raise ValueError('公区禁止本机免登录绕过')
    default_database = {'team':'data/platform.sqlite','personal':'data/personal/platform.sqlite','public':'data/public-area/platform.sqlite'}[runtime_mode]
    store = Store(database or ROOT / default_database)
    store.runtime_mode=runtime_mode
    from server.core.public_area.schema import migrate as public_migrate
    public_migrate(store)
    publications = PublicationLedger(store)
    status_changes = StatusChanges(store)
    if runtime_mode!='public':
        publications.recover_interrupted()
        status_changes.recover_interrupted()
    from server.ai_models import ModelSettings
    model_settings=ModelSettings(store)
    worker = GenerationWorker(store) if runtime_mode!='public' else None
    from server.studio_workspaces import Workspaces
    workspaces = Workspaces(store)
    from server.core.auth import Authentication, AuthenticationRequired, cookie_value
    from server.core.identity import current_user
    from server.core.gateway import Gateway
    from server.core.permissions import AccessDenied, Policy
    from server.core.routes import dispatch as team_dispatch
    auth = Authentication(store, local_development=local_development)
    if runtime_mode=='public' and auth.config()['mode']!='password':raise ValueError('公区需要账号密码认证')
    from server.core.local_accounts import LocalAccounts, LoginThrottled
    accounts = LocalAccounts(store)
    gateway = Gateway(store)
    from server.core.integrations import AdapterRegistry
    registry = registry or (AdapterRegistry().load_modules() if runtime_mode!='public' else AdapterRegistry())
    from server.core.node_memory import NodeMemoryWorker
    memory_worker = NodeMemoryWorker(store) if runtime_mode!='public' else None
    from server.department_jobs import DepartmentExecutionWorker
    department_worker = DepartmentExecutionWorker(store, registry) if runtime_mode!='public' else None
    from server.core.node_blocks.contracts import load_modules as load_block_modules
    if runtime_mode!='public':load_block_modules()
    from server.core.node_blocks.runtime import BlockWorker
    block_worker = BlockWorker(store, registry) if runtime_mode!='public' else None
    from server.core.node_continuation import ContinuationWorker
    continuation_worker = ContinuationWorker(store, registry) if runtime_mode!='public' else None
    from server.core.testing_automation import TestingAutomation, TestingAutomationWorker
    testing_automation = TestingAutomation(store)
    testing_automation_worker = TestingAutomationWorker(testing_automation) if runtime_mode!='public' else None
    lan_http=auth.config().get('mode')=='password' and auth.config().get('allow_lan_http') is True and auth.config().get('public_url','').startswith('http://')
    if lan_http:
        from server.core.notification_settings import site_url
        site_url(auth.config()['public_url'])
    if host not in ('127.0.0.1','localhost','::1') and (local_development or auth.config()['mode'] not in ('team','password') or not (auth.config().get('public_url','').startswith('https://') or lan_http)):
        raise ValueError('非回环监听需要先配置并启用团队认证')
    from server.core.skill_library import SkillCleanupWorker
    skill_cleanup = SkillCleanupWorker(store) if runtime_mode!='public' else None
    from server.core.notifications import NotificationWorker
    notification_worker = NotificationWorker(store) if runtime_mode!='personal' else None
    from server.core.public_area.maintenance import PublicMaintenance
    public_maintenance = PublicMaintenance(store) if runtime_mode=='public' else None
    from server.core.production_runs import ProductionWorker, dispatch as production_dispatch
    production_worker = ProductionWorker(store, registry) if runtime_mode!='public' else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def send_json(self, code, data, cookies=()):
            data = gateway.filter_response(data, getattr(self, 'team_scope', {}))
            payload = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            for cookie in cookies:self.send_header('Set-Cookie',cookie)
            if code==429:self.send_header('Retry-After','60')
            self.end_headers()
            self.wfile.write(payload)

        def redirect(self, location, cookies=()):
            self.send_response(302)
            self.send_header('Location', location)
            self.send_header('Cache-Control', 'no-store')
            for cookie in cookies: self.send_header('Set-Cookie', cookie)
            self.send_header('Content-Length','0')
            self.end_headers()

        def auth_cookie(self, key, value, max_age):
            secure = '; Secure' if auth.config().get('public_url','').startswith('https:') else ''
            return f'{key}={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}'+secure

        def do_GET(self):
            self.handle_request(False)

        def do_POST(self):
            self.handle_request(True)

        def handle_request(self, write):
            url = urlsplit(self.path)
            parts = url.path.strip('/').split('/')
            identity_token = None
            self.team_scope = {}
            try:
                from server.core.public_area.routes import public_allowed, dispatch as public_dispatch
                from server.core.public_area.service import Conflict
                if runtime_mode=='public' and url.path.startswith('/api/') and not public_allowed(parts,write):
                    raise PermissionError('公区服务器不提供个人工作区、模型或执行接口')
                if parts==['api','runtime'] and not write:return self.send_json(200,{'mode':runtime_mode})
                body = {}
                if write:
                    origin = self.headers.get('Origin')
                    if origin and urlsplit(origin).netloc != self.headers.get('Host'):
                        self.send_json(403, {'error': '拒绝跨站写入'})
                        return
                    if self.headers.get_content_type() != 'application/json':
                        raise ValueError('需要 JSON 请求')
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= (3*1024*1024 if 'public' in parts or 'public-local' in parts else 1048576):
                        raise ValueError('请求大小不合法')
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError('请求必须为对象')
                if runtime_mode=='public' and (url.path.startswith('/auth/feishu/') or parts==['api','admin','auth'] and write and body.get('mode','password')!='password'):raise PermissionError('公区只使用账号密码认证')
                if parts == ['auth','feishu','login'] and not write:
                    public=auth.config().get('public_url','')
                    if public and self.headers.get('Host')!=urlsplit(public).netloc:return self.redirect(public+'/auth/feishu/login')
                    target,browser = auth.begin()
                    return self.redirect(target,[self.auth_cookie('studioflow_oauth',browser,600)])
                if parts == ['auth','feishu','callback'] and not write:
                    query = parse_qs(url.query)
                    session,actor = auth.callback(query.get('state',[''])[0],query.get('code',[''])[0],cookie_value(self.headers,'studioflow_oauth'))
                    return self.redirect('/',[self.auth_cookie('studioflow_session',session,43200),self.auth_cookie('studioflow_oauth','',0)])
                if parts == ['api','auth','public'] and not write:
                    status=auth.status()
                    return self.send_json(200,{'mode':status['mode'],'configured':status['configured'],
                        'setup_required':status['setup_required'],'setup_available':status['setup_required'] and auth.direct_loopback(self.headers,self.client_address[0]),
                        'registration_open':status['registration_open']})
                if write and parts in (['api','auth','setup'],['api','auth','register'],['api','auth','login']):
                    if parts[-1]=='register':return self.send_json(201,accounts.register(body,self.client_address[0]))
                    if parts[-1]=='setup':session,actor=accounts.setup(body,self.headers,self.client_address[0])
                    else:session,actor=accounts.login(body,self.client_address[0])
                    return self.send_json(201 if parts[-1]=='setup' else 200,auth.session(actor),
                        [self.auth_cookie('studioflow_session',session,43200)])
                if parts == ['api','codex-handoff','redeem'] and write:
                    from server.core.skill_handoff import SkillHandoff
                    result=SkillHandoff(store).redeem(body.get('ticket'),body.get('origin'))
                    return self.send_json(200,result)
                is_studio_handoff = (len(parts) == 7 and parts[:2] == ['api','studios'] and
                    parts[3] == 'projects' and parts[5:] == ['workspace','codex-handoff'])
                is_studio_test_handoff = (len(parts) == 8 and parts[:2] == ['api','studios'] and
                    parts[3] == 'projects' and parts[5] == 'tasks' and parts[7] == 'codex-handoff')
                is_legacy_test_handoff = (len(parts) == 6 and parts[:2] == ['api','projects'] and
                    parts[3] == 'tasks' and parts[5] == 'codex-handoff')
                if is_studio_handoff or is_studio_test_handoff or is_legacy_test_handoff:
                    configured=auth.config().get('public_url','').rstrip('/')
                    trusted=configured or ('http://'+self.headers.get('Host',''))
                    requested=body.get('origin')
                    if requested != trusted or (not configured and urlsplit(trusted).hostname not in ('127.0.0.1','localhost','::1')):
                        raise PermissionError('交接来源必须与当前 StudioFlow 地址一致')
                if parts == ['api','auth','logout'] and write:
                    auth.logout(self.headers)
                    self.send_response(200)
                    self.send_header('Set-Cookie',self.auth_cookie('studioflow_session','',0))
                    self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length','11')
                    self.end_headers();self.wfile.write(b'{"ok":true}')
                    return
                if url.path.startswith('/api/'):
                    actor=auth.identity(self.headers,self.client_address[0])
                    identity_token=current_user.set(actor)
                    if parts == ['api','auth','session'] and not write:
                        return self.send_json(200,auth.session(actor))
                    if parts == ['api','auth','password'] and write:
                        result=accounts.change_password(body,self.client_address[0])
                        return self.send_json(200,result,[self.auth_cookie('studioflow_session','',0)])
                    if parts == ['api','admin','users','password'] and write:
                        return self.send_json(200,accounts.reset_password(body))
                    if public_dispatch(self,parts,url.query,body,write,store):return
                    if runtime_mode!='public':
                        from server.core.public_area.local import dispatch as local_public_dispatch
                        if local_public_dispatch(self,parts,url.query,body,write,store):return
                    if production_dispatch(self,parts,body,write,production_worker.service if production_worker else None):return
                    if team_dispatch(self,parts,url.query,body,write,auth,store,registry):return
                    self.team_scope=gateway.authorize(parts,url.query,body,write)
                studio_scope = None
                if len(parts) >= 6 and parts[:2] == ['api','studios'] and parts[3] == 'projects' and parts[5] == 'tasks':
                    studio_scope = parts[2]
                    store.check_project(studio_scope, parts[4])
                    parts = ['api','projects',parts[4],*parts[5:]]
                if parts == ['api','studio-catalog'] and not write:
                    from server.studio_catalog import catalog
                    return self.send_json(200, catalog())
                if parts == ['api','ai-models'] and not write:
                    return self.send_json(200,model_settings.status())
                if parts == ['api','ai-models','discover'] and write:
                    return self.send_json(200,model_settings.discover())
                if parts == ['api','ai-models','custom'] and write:
                    return self.send_json(200,model_settings.save_custom(body))
                if parts == ['api','ai-models','selection'] and write:
                    return self.send_json(200,model_settings.save(body))
                if parts == ['api','ai-models','source'] and write:
                    return self.send_json(200,model_settings.activate(body.get('source')))
                if parts == ['api','studios'] and not write:
                    return self.send_json(200, {'items': store.studios()})
                if parts == ['api','studios'] and write:
                    return self.send_json(201, store.create_studio(body.get('name')))
                if parts == ['api','me','preferences'] and not write:
                    return self.send_json(200, store.preferences())
                if parts == ['api','me','preferences'] and write:
                    return self.send_json(200, store.save_preferences(body))
                if len(parts) == 4 and parts[:2] == ['api','studios'] and parts[3] == 'enter' and write:
                    return self.send_json(200, store.enter_studio(parts[2]))
                if len(parts) == 4 and parts[:2] == ['api','studios'] and parts[3] == 'projects':
                    studio = parts[2]
                    if write:
                        return self.send_json(201, store.create_project(body.get('name'), studio))
                    query = parse_qs(url.query)
                    return self.send_json(200, store.projects(query.get('q',[''])[0], int(query.get('page',['1'])[0]),
                        int(query.get('size',['5'])[0]), studio))
                if len(parts) == 5 and parts[:2] == ['api','studios'] and parts[3] == 'projects' and not write:
                    return self.send_json(200, store.check_project(parts[2], parts[4]))
                if len(parts) == 6 and parts[:2] == ['api','studios'] and parts[3] == 'projects' and parts[5] == 'parse-file' and write:
                    store.check_project(parts[2], parts[4])
                    content, metadata = parse_file(body.get('name'), body.get('data'))
                    return self.send_json(200, {'content': content, 'metadata': metadata})
                if len(parts) == 6 and parts[:2] == ['api','studios'] and parts[3] == 'projects' and parts[5] == 'read-sources' and write:
                    store.check_project(parts[2], parts[4])
                    links = body.get('links')
                    if not isinstance(links, list) or not 1 <= len(links) <= 20 or not all(isinstance(link, str) for link in links):
                        raise ValueError('一次需要1至20个飞书链接')
                    results = []
                    client = LarkClient()
                    for link in dict.fromkeys(links):
                        try:
                            content, metadata = client.requirement(link)
                            results.append({'url': link, 'status': 'imported', 'content': content, 'metadata': metadata})
                        except ValueError as exc:
                            results.append({'url': link, 'status': 'failed', 'error': str(exc)})
                    return self.send_json(200, {'results': results})
                if len(parts) == 6 and parts[:2] == ['api','studios'] and parts[3] == 'projects':
                    if parts[5] == 'enter' and write:
                        return self.send_json(200, store.enter_project(parts[2],parts[4]))
                    if parts[5] == 'summary' and not write:
                        return self.send_json(200, workspaces.summary(parts[2],parts[4]))
                if len(parts) == 6 and parts[:2] == ['api','studios'] and parts[3] == 'projects' and parts[5] == 'workspace':
                    studio, project, node = parts[2], parts[4], parse_qs(url.query).get('node',[''])[0]
                    if not node: raise ValueError('需要节点标识')
                    if write: return self.send_json(200, workspaces.save(studio,project,node,body))
                    return self.send_json(200, workspaces.get(studio,project,node))
                if len(parts) == 7 and parts[:2] == ['api','studios'] and parts[3] == 'projects' and parts[5:7] == ['workspace','skill-export'] and not write:
                    return self.send_json(200,workspaces.get(parts[2],parts[4],parse_qs(url.query).get('node',[''])[0])['skill'])
                if len(parts) == 7 and parts[:2] == ['api','studios'] and parts[3] == 'projects' and parts[5] == 'workspace' and parts[6] == 'decision' and write:
                    return self.send_json(200, workspaces.decide(parts[2],parts[4],parse_qs(url.query).get('node',[''])[0],body))
                if parts == ['api', 'projects']:
                    if write:
                        return self.send_json(201, store.create_project(body.get('name')))
                    query = parse_qs(url.query)
                    return self.send_json(200, store.projects(query.get('q', [''])[0],
                        int(query.get('page', ['1'])[0]), int(query.get('size', ['5'])[0])))
                if parts == ['api', 'gm', 'health'] and not write:
                    return self.send_json(200, GmClient().health())
                if parts == ['api', 'gm', 'resolve'] and write:
                    query = body.get('query')
                    if not isinstance(query, str) or not query.strip() or len(query) > 100:
                        raise ValueError('请输入 GM 项目名称（最多 100 字）')
                    return self.send_json(200, GmClient().call_read('gm_resolve_pg',
                        {'env': body.get('env'), 'query': query.strip()}))
                if parts == ['api', 'gagasort', 'inspect'] and write:
                    return self.send_json(200, inspect_project(body.get('path'), body.get('branch')))
                if len(parts) >= 4 and parts[:2] == ['api', 'projects'] and parts[3] == 'tasks':
                    project = parts[2]
                    store.check_project(studio_scope or store.preferences()['active_studio_id'], project)
                    if len(parts) == 4:
                        if write:
                            return self.send_json(201, store.create_task(project, body.get('title')))
                        return self.send_json(200, {'items': store.tasks(project)})
                    if len(parts) == 5 and not write:
                        snapshot = store.task(project, parts[4])
                        snapshot['status_changes'] = status_changes.list(project, parts[4])
                        if '4' in snapshot['artifacts']:
                            snapshot['artifacts']['4']['publication_ledger'] = publications.list(project, parts[4])
                        return self.send_json(200, snapshot)
                    if len(parts) == 6 and parts[5] == 'archive-requirement' and write:
                        return self.send_json(200,store.archive_requirement(project,parts[4],body.get('requirement_id'),body.get('revision'),body.get('archived')))
                    if len(parts) == 6 and parts[5] == 'reset-node' and write:
                        return self.send_json(200,store.reset_node(project,parts[4],body.get('stage'),
                            body.get('revision'),body.get('reason'),body.get('confirmed')))
                    if len(parts) == 6 and parts[5] == 'cancel-operation' and write:
                        return self.send_json(200,store.cancel_operation(project,parts[4],body.get('job_id'),body.get('revision')))
                    if len(parts) == 6 and parts[5] == 'restore-cancelled' and write:
                        return self.send_json(200,store.restore_cancelled_task(project,parts[4],body.get('revision')))
                    if len(parts) == 6 and write and parts[5] in ('feishu-requirements','file-requirements','referenced-requirements','attachment-requirement'):
                        if store.task(project,parts[4])['status'] in ('cancelled','completed'):
                            raise ValueError('任务已结束，请先重置用例节点或建立新批次')
                    if len(parts) == 6 and parts[5] == 'node-skill':
                        stage=int(parse_qs(url.query).get('stage',['0'])[0])
                        if not 0 <= stage <= 5:
                            raise ValueError('节点不合法')
                        if write:
                            return self.send_json(200,store.save_node_skill(project,parts[4],stage,body.get('content'),body.get('revision'),name=body.get('name')))
                        return self.send_json(200,store.task(project,parts[4])['node_skills'][str(stage)])
                    if len(parts) == 6 and parts[5] == 'publication-ledger' and not write:
                        return self.send_json(200, {'records': publications.list(project, parts[4])})
                    if len(parts) == 6 and parts[5] == 'prepare-status-change' and write:
                        result = status_changes.prepare(project, parts[4], body.get('root_cause_id'),
                            body.get('target_value'), body.get('revision'), LarkClient(), inspect_project)
                        return self.send_json(200, result)
                    if len(parts) == 6 and parts[5] == 'confirm-status-change' and write:
                        result = status_changes.confirm(project, parts[4], body.get('identity'), body.get('preview_hash'),
                            body.get('revision'), body.get('confirmed'), body.get('static_scope_acknowledged'),
                            LarkClient(), inspect_project)
                        return self.send_json(200, result)
                    if len(parts) == 6 and parts[5] == 'reconcile-status-change' and write:
                        return self.send_json(200, status_changes.reconcile(project, parts[4], body.get('identity'), LarkClient()))
                    if len(parts) == 6 and parts[5] == 'editor-preflight' and not write:
                        snapshot = store.task(project, parts[4])
                        if not snapshot['binding']:
                            raise ValueError('请先绑定目标项目与分支')
                        return self.send_json(200, editor_preflight(snapshot['binding']))
                    if len(parts) == 6 and parts[5] == 'bug-export' and not write:
                        snapshot = store.task(project, parts[4])
                        query = parse_qs(url.query)
                        payload, mime, extension = export_bug_preview(snapshot['artifacts'].get('4', {}),
                            query.get('format', ['json'])[0])
                        self.send_response(200)
                        self.send_header('Content-Type', mime + '; charset=utf-8')
                        self.send_header('Content-Disposition', 'attachment; filename="bug-preview.' + extension + '"')
                        self.send_header('Content-Length', str(len(payload)))
                        self.send_header('Cache-Control', 'no-store')
                        self.end_headers()
                        self.wfile.write(payload)
                        return
                    if len(parts) == 6 and parts[5] == 'operation-jobs' and write:
                        return self.send_json(202, store.enqueue_operation(project, parts[4], body.get('kind')))
                    if len(parts) == 6 and parts[5] == 'execution-mapping' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 1 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('节点或版本已变化，请刷新')
                        if '1' not in snapshot['artifacts']:
                            raise ValueError('请先执行测试')
                        if snapshot['artifacts']['1'].get('method') == 'static_code_review':
                            raise ValueError('静态审查按原用例ID关联，不使用人工探针映射')
                        result = map_cases(snapshot['artifacts']['0']['cases'], snapshot['artifacts']['1'], body.get('mappings'))
                        return self.send_json(200, store.record_artifact(project, parts[4], 1, result,
                            expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'case-review' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 0 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('请在用例节点评审当前版本')
                        output = snapshot['artifacts'].get('0')
                        if not output:
                            raise ValueError('请先生成用例')
                        reviewed = review_cases(output, snapshot['requirements'], body.get('decisions'), body.get('decomposition_confirmed'))
                        return self.send_json(200, store.record_artifact(project, parts[4], 0,
                            {**output, 'user_review': reviewed}, expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'check-pending-regression' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 5 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('请在回归节点检查当前关联单据')
                        links = snapshot['artifacts'].get('4', {}).get('linked_records', [])
                        checks = {}
                        for link in links:
                            if link['table_id'] != snapshot['bug_target'].get('table_id'):
                                raise ValueError('关联目标表已变化')
                            prior = link['status_snapshot']
                            checks[link['draft_key']] = LarkClient().read_bug_status(snapshot['bug_target'],
                                link['record_id'], prior['field_id'], prior['pending_value'])
                        result = store.refresh_pending_bugs(project, parts[4], checks, snapshot['revision'])
                        return self.send_json(202 if result['job'] else 200, result)
                    if len(parts) == 6 and parts[5] == 'regression-review' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 5 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('请在回归节点评审当前版本')
                        reviewed = review_logic_regression(snapshot['regression'], body.get('decisions'))
                        binding = snapshot['binding']
                        current = inspect_project(binding['repository'], binding['branch'])
                        if current['code_fingerprint'] != reviewed['code_fingerprint']:
                            raise ValueError('代码已变化，请重新回归')
                        return self.send_json(200, store.record_artifact(project, parts[4], 5,
                            reviewed, expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'regress-logic' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] < 4 or snapshot['status'] in ('cancelled', 'completed'):
                            raise ValueError('请先生成 Bug 草稿')
                        drafts = snapshot['artifacts'].get('4', {}).get('drafts')
                        if not drafts:
                            raise ValueError('尚无需要回归的 Bug 草稿')
                        original_binding = snapshot['binding']
                        current_binding = inspect_project(original_binding['repository'], original_binding['branch'])
                        current_binding['execution_suite'] = original_binding.get('execution_suite', 'business')
                        execution = execute_logic(current_binding, ROOT / 'data/execution-evidence', snapshot['artifacts']['0']['cases'], snapshot['requirements'])
                        result = assess_logic_roots(drafts, snapshot['artifacts']['1'], execution)
                        return self.send_json(200, store.save_logic_regression(project, parts[4], result, snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'bug-target' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['revision'] != body.get('revision'):
                            raise ValueError('任务已变化，请刷新')
                        target = LarkClient().inspect_bug_target(body.get('url'))
                        return self.send_json(200, store.save_bug_target(project, parts[4], target, snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'attribution-suggestions' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 2 or snapshot['status'] in ('cancelled', 'completed'):
                            raise ValueError('当前节点不能分析归因')
                        result = suggest_attribution(snapshot['binding'], snapshot['artifacts']['1'])
                        return self.send_json(200, store.save_attribution(project, parts[4], result, snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'edit-case' and write:
                        return self.send_json(200, store.edit_case(project, parts[4], body.get('case_id'),
                            body.get('changes'), body.get('revision')))
                    if len(parts) == 6 and parts[5] == 'confirm-existing-bugs' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 4 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('节点或版本已变化，请刷新')
                        if body.get('confirmed') is not True:
                            raise ValueError('需要确认根因与已有 Bug 的对应关系')
                        artifact = confirm_existing_records(snapshot['artifacts'].get('4', {}), snapshot['bug_target'])
                        return self.send_json(200, store.record_artifact(project, parts[4], 4,
                            artifact, expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'bug-status' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 4 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('当前仅支持提单节点关联已有 Bug，请刷新')
                        artifact = snapshot['artifacts'].get('4', {})
                        draft = next((d for d in artifact.get('drafts', []) if d['draft_key'] == body.get('draft_key')), None)
                        if draft is None:
                            raise ValueError('请选择对应根因草稿')
                        check = LarkClient().read_bug_status(snapshot['bug_target'], body.get('record_id'),
                            body.get('field_id'), body.get('pending_value'))
                        checks = dict(artifact.get('remote_checks', {}))
                        checks[draft['draft_key']] = check
                        return self.send_json(200, store.record_artifact(project, parts[4], 4,
                            {**artifact, 'remote_checks': checks, 'publication_complete': False, 'linked_records': []}, expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'reconcile-bug-publication' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 4 or snapshot['revision'] != body.get('revision') or body.get('confirmed') is not True:
                            raise ValueError('请明确确认要核对的根因与远端记录')
                        request = publications.reconciliation_request(project, parts[4], body.get('identity'))
                        target = LarkClient().inspect_bug_target(snapshot['bug_target']['url'])
                        check = LarkClient().verify_bug_record(request, target, body.get('record_id'))
                        publications.reconcile(project, parts[4], body.get('identity'), check, snapshot['revision'])
                        latest = store.task(project, parts[4])
                        latest['artifacts']['4']['publication_ledger'] = publications.list(project, parts[4])
                        return self.send_json(200, latest)
                    if len(parts) == 6 and parts[5] == 'publish-bug' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 4 or snapshot['revision'] != body.get('revision') or body.get('confirmed') is not True:
                            raise ValueError('请审核当前版本并明确确认发布')
                        artifact = snapshot['artifacts'].get('4', {})
                        fresh_plan = prepare_publication(artifact, snapshot['bug_target'], body.get('preview_hash'))
                        if artifact.get('publication_plan') != fresh_plan:
                            raise ValueError('请先准备当前发布请求')
                        request = next((r for r in fresh_plan['requests'] if r['request_hash'] == body.get('request_hash')), None)
                        if request is None:
                            raise ValueError('发布请求不属于当前预览')
                        client = LarkClient()
                        fresh_target = client.inspect_bug_target(snapshot['bug_target']['url'])
                        if fresh_target != snapshot['bug_target']:
                            raise ValueError('目标表字段已变化，请重新读取和预览')
                        row = next((r for r in publications.list(project, parts[4]) if r['request_hash'] == request['request_hash']), None)
                        if row is None:
                            raise ValueError('缺少发布台账，请重新准备')
                        claimed = publications.claim(project, parts[4], row['identity'], request['request_hash'], snapshot['revision'])
                        try:
                            response = client.create_bug_record(claimed['request'])
                        except Exception:
                            publications.finish(row['identity'], claimed['attempt'])
                            raise ValueError('发布未取得完整响应；已登记结果不确定，请核对远端，禁止重复创建') from None
                        publications.finish(row['identity'], claimed['attempt'], response)
                        latest = store.task(project, parts[4])
                        if '4' in latest['artifacts']:
                            latest['artifacts']['4']['publication_ledger'] = publications.list(project, parts[4])
                        return self.send_json(200, latest)
                    if len(parts) == 6 and parts[5] == 'prepare-bug-publication' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 4 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('节点或版本已变化，请刷新')
                        artifact = snapshot['artifacts'].get('4', {})
                        plan = prepare_publication(artifact, snapshot['bug_target'], body.get('preview_hash'))
                        ledger = publications.prepare(project, parts[4], snapshot['revision'], plan)
                        return self.send_json(200, store.record_artifact(project, parts[4], 4,
                            {**artifact, 'publication_plan': plan, 'publication_ledger': ledger}, expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'bug-preview' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 4 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('节点或版本已变化，请刷新')
                        artifact = snapshot['artifacts'].get('4', {})
                        preview = preview_field_mapping(artifact.get('drafts', []),
                            snapshot['bug_target'], body.get('mapping'))
                        artifact.pop('publication_plan', None)
                        return self.send_json(200, store.record_artifact(project, parts[4], 4,
                            {**artifact, 'field_preview': preview}, expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'bug-drafts' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 4 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('节点或版本已变化，请刷新')
                        execution = snapshot['artifacts']['1']
                        with store.connection() as db:
                            project_name = db.execute('SELECT name FROM projects WHERE id=?', (project,)).fetchone()['name']
                        environment = {'project': project_name, 'project_id': project,
                                       'code_fingerprint': execution['code_fingerprint'],
                                       'branch': execution.get('branch'), 'commit': execution.get('commit'),
                                       'build': execution.get('build'), 'method': execution.get('method')}
                        result = prepare_drafts(snapshot['artifacts']['3']['groups'], execution['results'],
                                                body.get('observations', []), environment)
                        return self.send_json(200, store.record_artifact(project, parts[4], 4, result,
                            expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] in ('triage', 'filter') and write:
                        snapshot = store.task(project, parts[4])
                        stage = 2 if parts[5] == 'triage' else 3
                        from server.core.project_nodes import testing_filter_merged
                        with store.connection() as db:merged=testing_filter_merged(db,project)
                        recovery=stage==2 and snapshot['stage']==3 and merged
                        if (snapshot['stage'] != stage and not recovery) or snapshot['revision'] != body.get('revision'):
                            raise ValueError('节点或版本已变化，请刷新')
                        if stage == 2:
                            result = triage_report(snapshot['artifacts']['1']['results'],
                                body.get('assignments'), body.get('roots'), body.get('exclusions', []))
                            if merged and 'filing' in body:
                                filing=body['filing']
                                if not isinstance(filing,dict):raise ValueError('提单范围格式错误')
                                result['filing_scope']=filter_groups(result,filing.get('selected'),filing.get('excluded'))
                        else:
                            result = filter_groups(snapshot['artifacts']['2'], body.get('selected'), body.get('excluded'))
                        return self.send_json(200, store.record_artifact(project, parts[4], stage, result,
                            expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'automation':
                        result = testing_automation.save(project, parts[4], body) if write else testing_automation.get(project, parts[4])
                        return self.send_json(200, result)
                    if len(parts) == 6 and parts[5] == 'start-static-review' and write:
                        snapshot = store.task(project, parts[4])
                        binding = snapshot['binding']
                        if not binding:raise ValueError('请先填写仓库路径并绑定指定分支')
                        current = inspect_project(binding['repository'], binding['branch'])
                        current['execution_suite'] = 'static'
                        return self.send_json(202, store.start_static_review(project, parts[4], current, body.get('revision')))
                    if len(parts) == 6 and parts[5] == 'execution-binding' and write:
                        store.task(project, parts[4])
                        binding = inspect_project(body.get('path'), body.get('branch'))
                        suite = body.get('suite', 'static')
                        if suite not in ('static', 'business', 'streakgroup'):
                            raise ValueError('不支持的执行套件')
                        binding['execution_suite'] = suite
                        return self.send_json(200, store.bind_execution(project, parts[4], binding, body.get('revision')))
                    if len(parts) == 6 and parts[5] == 'execute-logic' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 1 or snapshot['status'] in ('cancelled', 'completed'):
                            raise ValueError('当前节点不能执行逻辑探针')
                        from server.ai_models import selection_scope
                        from server.node_skills import skill_scope
                        content=snapshot['node_skills']['1']['content']
                        with selection_scope(model_settings.runtime_selection()),skill_scope(content):
                            result = execute_logic(snapshot['binding'], ROOT / 'data/execution-evidence', snapshot['artifacts']['0']['cases'], snapshot['requirements'])
                        import hashlib
                        result['node_skill_sha256']=hashlib.sha256(content.encode()).hexdigest()
                        return self.send_json(200, store.record_artifact(project, parts[4], 1, result,
                            expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'generation-jobs' and write:
                        return self.send_json(202, store.enqueue_generation(project, parts[4]))
                    if len(parts) == 6 and parts[5] == 'generate' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 0 or snapshot['status'] in ('cancelled', 'completed'):
                            raise ValueError('当前任务不能生成用例')
                        from server.ai_models import selection_scope
                        from server.node_skills import skill_scope
                        content=snapshot['node_skills']['0']['content']
                        with selection_scope(model_settings.runtime_selection()),skill_scope(content):
                            result = model_settings.generation_client().generate(snapshot['requirements'])
                        import hashlib
                        result['node_skill_sha256']=hashlib.sha256(content.encode()).hexdigest()
                        return self.send_json(200, store.record_artifact(project, parts[4], 0, result,
                            expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'requirements' and write:
                        return self.send_json(201, store.import_requirement(project, parts[4], body.get('source'), body.get('content')))
                    if len(parts) == 6 and parts[5] == 'referenced-requirements' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 0 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('请在用例节点读取当前版本引用')
                        parent = next((r for r in snapshot['requirements'] if r['id'] == body.get('requirement_id')), None)
                        if parent is None or parent['metadata'].get('kind') != 'feishu':
                            raise ValueError('请选择已导入的飞书需求')
                        result = LarkClient().referenced_requirements(parent['source'], parent['metadata'])
                        current = store.task(project, parts[4])
                        if current['revision'] != snapshot['revision']:
                            raise ValueError('读取期间任务已变化，未导入引用')
                        for item in result:
                            if item['status'] == 'read':
                                current = store.import_requirement(project, parts[4], item['url'], item['content'],
                                    {**item['metadata'], 'parent_sha256': parent['sha256'],
                                     'parent_revision_id': parent['metadata'].get('revision_id')},
                                    expected_revision=current['revision'])
                        return self.send_json(200, {'task': store.task(project, parts[4]),
                            'results': [{k:v for k,v in item.items() if k not in ('content','metadata')} for item in result],
                            'scope': '仅读取直接Wiki/Docx/Sheets引用；嵌入附件与间接引用仍需检查'})
                    if len(parts) == 6 and parts[5] == 'attachment-requirement' and write:
                        snapshot = store.task(project, parts[4])
                        if snapshot['stage'] != 0 or snapshot['revision'] != body.get('revision'):
                            raise ValueError('节点或版本已变化，请刷新')
                        requirement = next((r for r in snapshot['requirements'] if r['id'] == body.get('requirement_id')), None)
                        if requirement is None:
                            raise ValueError('请选择已读取的需求来源')
                        resource = next((r for r in requirement['metadata'].get('resources', [])
                                         if r.get('kind') == 'source' and r.get('token') == body.get('file_token')), None)
                        if resource is None:
                            raise ValueError('附件不属于已读取的需求，禁止猜测文件token')
                        content, metadata = LarkClient().attachment_requirement(requirement['source'], resource)
                        current = store.task(project, parts[4])
                        if current['revision'] != snapshot['revision']:
                            raise ValueError('读取期间需求已变化，附件结果未保存')
                        return self.send_json(201, store.import_requirement(project, parts[4],
                            requirement['source']+'#attachment='+resource['token'], content,
                            {**metadata, 'parent_revision_id': requirement['metadata'].get('revision_id'),
                             'parent_sha256': requirement['sha256']},
                            expected_revision=snapshot['revision']))
                    if len(parts) == 6 and parts[5] == 'file-requirements' and write:
                        store.task(project, parts[4])
                        content, metadata = parse_file(body.get('name'), body.get('data'))
                        return self.send_json(201, store.import_requirement(project, parts[4], body.get('name'), content, metadata))
                    if len(parts) == 6 and parts[5] == 'feishu-requirements' and write:
                        store.task(project, parts[4])
                        links = body.get('links')
                        if not isinstance(links, list) or not 1 <= len(links) <= 20 or not all(isinstance(link, str) for link in links):
                            raise ValueError('一次需要1至20个飞书链接')
                        results = []
                        client = LarkClient()
                        for link in dict.fromkeys(links):
                            try:
                                content, metadata = client.requirement(link)
                                store.import_requirement(project, parts[4], link, content, metadata)
                                results.append({'url': link, 'status': 'imported', 'gaps': metadata['source_gaps']})
                            except ValueError as exc:
                                results.append({'url': link, 'status': 'failed', 'error': str(exc)})
                        return self.send_json(200, {'results': results, 'task': store.task(project, parts[4])})
                    if len(parts) == 6 and parts[5] == 'decisions' and write:
                        try:
                            snapshot = store.task(project, parts[4])
                            report = snapshot['artifacts'].get('1', {})
                            if body.get('action') == 'confirm' and snapshot['stage'] == 1 and report.get('method') == 'static_code_review':
                                binding = snapshot['binding']
                                current = inspect_project(binding['repository'], binding['branch'])
                                if any(current.get(key) != report.get(key) for key in ('commit', 'code_fingerprint', 'branch')):
                                    raise ValueError('代码已变化，请重新绑定并静态检测')
                            task = store.decide(project, parts[4], body.get('action'), body.get('revision'))
                        except ValueError as exc:
                            return self.send_json(409, {'error': str(exc)})
                        return self.send_json(200, task)
                if not write and not url.path.startswith('/api/'):
                    if url.path.startswith('/departments/'):
                        import re
                        match=re.fullmatch(r'/departments/([a-z][a-z0-9_-]*)/ui\.js',url.path)
                        if match:
                            from server.studio_catalog import DEPARTMENTS, MODULE_ROOT
                            department=next((d for d in DEPARTMENTS if d['id']==match.group(1)),None)
                            if department and department.get('frontend',{}).get('entry')=='ui.js':
                                module_root=(MODULE_ROOT/department['id']).resolve()
                                target=(module_root/'ui.js').resolve()
                                if target.is_relative_to(module_root) and target.is_file():
                                    payload=target.read_bytes()
                                    self.send_response(200)
                                    self.send_header('Content-Type','text/javascript; charset=utf-8')
                                    self.send_header('Content-Length',str(len(payload)))
                                    self.send_header('Cache-Control','no-store')
                                    self.end_headers()
                                    self.wfile.write(payload)
                                    return
                        return self.send_json(404,{'error':'部门前端模块不存在'})
                    filename = 'index.html' if url.path == '/' else url.path.lstrip('/')
                    target = (ROOT / 'web' / filename).resolve()
                    if target.is_relative_to(ROOT / 'web') and target.is_file():
                        payload = target.read_bytes()
                        self.send_response(200)
                        self.send_header('Content-Type', {'html':'text/html', 'css':'text/css',
                            'js':'text/javascript'}.get(target.suffix[1:], 'application/octet-stream') + '; charset=utf-8')
                        self.send_header('Content-Length', str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                        return
                self.send_json(404, {'error': '资源不存在'})
            except RemoteError as exc:
                self.send_json(exc.status if exc.status in (400,401,403,404,409,429) else 502, {'error':str(exc)})
            except Conflict as exc:
                self.send_json(409, {'error':str(exc)})
            except LoginThrottled as exc:
                self.send_json(429, {'error':str(exc)})
            except AuthenticationRequired as exc:
                self.send_json(401, {'error':str(exc)})
            except PermissionError as exc:
                self.send_json(403, {'error':str(exc)})
            except KeyError:
                self.send_json(404, {'error': '项目或任务不存在'})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {'error': str(exc)})
            finally:
                if identity_token is not None: current_user.reset(identity_token)

    class Server(ThreadingHTTPServer):
        def server_close(self):
            for execution_worker in (production_worker,testing_automation_worker,continuation_worker,department_worker,memory_worker,block_worker,skill_cleanup,public_maintenance):
                if execution_worker:execution_worker.close()
            if worker:
                worker.close()
            if notification_worker:notification_worker.close()
            super().server_close()
    return Server((host, port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--database', default=None)
    parser.add_argument('--mode',choices=('team','personal','public'),default='team')
    args = parser.parse_args()
    http = create_server(host=args.host,port=args.port,database=args.database,runtime_mode=args.mode)
    print(f'平台服务：http://{args.host}:{args.port}', flush=True)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()
