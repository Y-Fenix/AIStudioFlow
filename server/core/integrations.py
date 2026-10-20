"""Explicit execution extension points. Imported Skills never register Python code."""
from dataclasses import dataclass
from typing import Protocol, Mapping, Any
from server.studio_catalog import node_definition


class ModelAccess(Protocol):
    """Department-facing JSON-only model access; secrets stay in the shared runtime."""
    def request_json(self, prompt: str) -> dict[str, Any]: ...


class GmAccess(Protocol):
    """Project-scoped, explicitly authorized read-only GM MCP access."""
    def call_read(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExecutionContext:
    user_id: str
    studio_id: str
    project_id: str
    node_id: str
    input_revision: int
    skill_sha256: str
    skill_content: str
    inputs: str
    model: ModelAccess
    gm: GmAccess


class GmCapability:
    """Re-checks authorization on every call and never exposes GM write tools."""
    def __init__(self, store, actor, studio, project, node):
        self._store, self._actor = store, actor
        self._studio, self._project, self._node = studio, project, node

    def call_read(self, name, arguments):
        from server.core.permissions import Policy
        from server.connectors.gm import GmClient

        if name not in GmClient.READ_TOOLS:
            raise ValueError('此连接器仅允许只读检查')
        if not isinstance(arguments, dict) or len(str(arguments).encode()) > 32000:
            raise ValueError('GM 参数必须是 JSON 对象')
        # Test was selected by the user for this workspace. Still require the
        # adapter to say so explicitly on every environment-bound operation.
        if name == 'gm_health':
            if arguments:
                raise ValueError('GM 健康检查不接受额外参数')
        elif arguments.get('env') != 'test':
            raise ValueError('每次 GM 调用都必须明确指定 env=test')
        Policy(self._store).require('gm', 'execute', studio=self._studio,
                                   project=self._project, node=self._node,
                                   actor=self._actor)
        return GmClient().call_read(name, arguments)


class ModelCapability:
    """Narrow department-facing model access pinned to one execution snapshot."""
    def __init__(self, client, selection, skill_content):
        self._client = client
        self._selection = dict(selection)
        self._skill_content = skill_content

    def request_json(self, prompt):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 500000:
            raise ValueError('模型提示词须为非空文本，最大500KB')
        from server.ai_models import selection_scope
        from server.node_skills import skill_scope
        with selection_scope(self._selection), skill_scope(self._skill_content):
            result = self._client.request_json(prompt)
        if not isinstance(result, dict):
            raise ValueError('模型必须返回 JSON 对象')
        return result


class DepartmentAdapter(Protocol):
    """Adapters return evidence, outputs and gaps; approval always remains in the shell."""
    def execute(self, context: ExecutionContext) -> Mapping[str, Any]: ...


class AdapterRegistry:
    def __init__(self): self._adapters={}

    def register(self, department, adapter):
        node_definition(department+':0')
        if department in self._adapters:raise ValueError('部门执行器重复注册')
        if not callable(getattr(adapter,'execute',None)):raise TypeError('执行器需实现 execute(context)')
        self._adapters[department]=adapter

    def get(self, node, store=None, project=None):
        department,index,_=node_definition(node,store,project)
        if not isinstance(index,int): return None
        return self._adapters.get(department['id'])

    def load_modules(self):
        """Only trusted repository-owned adapter.py files are loaded, never uploaded Skills."""
        import importlib.util
        from server.studio_catalog import DEPARTMENTS, MODULE_ROOT
        for d in DEPARTMENTS:
            # A scaffold may exist before a department connects its real tools.
            # Only an explicit manifest opt-in makes it an executable adapter;
            # manual departments must remain visible as not_connected.
            if d.get('execution', {}).get('adapter') != 'adapter':
                continue
            path=MODULE_ROOT/d['id']/'adapter.py'
            if not path.is_file():continue
            spec=importlib.util.spec_from_file_location('studio_department_'+d['id'],path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.register(d['id'],module.create_adapter())
        return self

    def status(self):
        from server.studio_catalog import DEPARTMENTS
        return [{'department':d['id'],'adapter':'registered' if d['id'] in self._adapters else 'legacy_testing' if d['id']=='testing' else 'not_connected'} for d in DEPARTMENTS]


class ExecutionService:
    def __init__(self,store,registry):self.store=store;self.registry=registry

    def execute(self,studio,project,node,revision):
        from server.core.identity import user_id
        from server.core.permissions import Policy
        from server.studio_workspaces import Workspaces
        import json
        policy=Policy(self.store)
        with self.store.connection() as db:
            from server.core.project_content import require_enabled
            require_enabled(db,project,node.split(':')[0])
        for action in ('view','edit','execute'):policy.require('node',action,studio=studio,project=project,node=node)
        adapter=self.registry.get(node,store=self.store,project=project)
        if adapter is None:raise ValueError('本部门尚未接入执行器；请由部门负责人实现 adapter.py')
        service=Workspaces(self.store);workspace=service.get(studio,project,node)
        if type(revision) is not int or workspace['revision']!=revision:raise ValueError('输入版本已变化，请刷新')
        from server.ai_models import ModelSettings
        settings=ModelSettings(self.store)
        skill_content=workspace['skill']['content']
        if not skill_content.strip():raise ValueError('未配置 Skill，请先导入或由管理员恢复规则')
        model=ModelCapability(settings.generation_client(),settings.runtime_selection(),skill_content)
        actor=user_id()
        context=ExecutionContext(actor,studio,project,node,revision,workspace['skill']['sha256'],
                                 skill_content,workspace['inputs'],model,
                                 GmCapability(self.store,actor,studio,project,node))
        result=adapter.execute(context)
        if not isinstance(result,dict) or not isinstance(result.get('deliverable'),str):raise ValueError('执行器须返回 deliverable 文字及可选 evidence/gaps 列表')
        if any(not isinstance(result.get(k,[]),list) for k in ('evidence','gaps')):raise ValueError('执行器证据与缺口格式无效')
        if len(json.dumps(result,ensure_ascii=False).encode())>800000:raise ValueError('执行器输出超过 800KB')
        # Recheck revocation and version after execution; never auto-approve generated output.
        for action in ('view','edit','execute'):
            policy.require('node',action,studio=studio,project=project,node=node)
        saved=service.save(studio,project,node,{'revision':revision,'deliverable':result['deliverable']})
        with self.store.connection() as db:
            db.execute('INSERT INTO team_audit(actor,studio_id,action,detail) VALUES(?,?,?,?)',(user_id(),studio,'department_execution',json.dumps({'project_id':project,'node':node,'revision':revision,'evidence':result.get('evidence',[]),'gaps':result.get('gaps',[])},ensure_ascii=False)))
        return {'workspace':saved,'evidence':result.get('evidence',[]),'gaps':result.get('gaps',[])}
