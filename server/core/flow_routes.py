"""Shared department instances and read-only node memory HTTP contract."""
from server.core.permissions import Policy


def dispatch(parts,q,body,write,store):
    if len(parts)<6 or parts[:2]!=['api','studios'] or parts[3]!='projects':return False,None
    studio,project=parts[2],parts[4];tail=parts[5:]
    node=q.get('node',[''])[0];flow=q.get('flow',[''])[0];task=q.get('task',[''])[0]
    if tail==['department-flows']:
        from server.core.department_flows import DepartmentFlows
        service=DepartmentFlows(store)
        if write:
            if not isinstance(body,dict):raise ValueError('请求必须是对象')
            result=service.archive(studio,project,body.get('id')) if body.get('action')=='archive' else service.create(studio,project,body)
        else:result=service.listing(studio,project,q.get('department',[''])[0])
        return True,result
    if len(tail)==2 and tail[0]=='department-flows' and not write:
        from server.core.department_flows import DepartmentFlows
        return True,DepartmentFlows(store).get(studio,project,tail[1])
    if tail and tail[0]=='node-memory':
        from server.core.node_memory import NodeMemory
        service=NodeMemory(store);kwargs={'flow':flow,'task':task}
        if tail==['node-memory']:return True,service.ask(studio,project,node,body,**kwargs) if write else service.history(studio,project,node,**kwargs)
        if tail==['node-memory','sources'] and not write:return True,service.context(studio,project,node,**kwargs)
        if tail==['node-memory','catalog'] and not write:return True,service.catalog(studio,project,node,**kwargs)
        if tail==['node-memory','links']:return True,service.link(studio,project,node,body,**kwargs) if write else service.links(studio,project,node,**kwargs)
        raise KeyError('节点记忆接口不存在')
    if flow and tail and tail[0]=='workspace':
        from server.studio_workspaces import Workspaces
        from server.core.department_flows import DepartmentFlows
        with store.connection() as db:DepartmentFlows(store).row(db,studio,project,flow,node,write)
        policy=Policy(store);policy.require('node','view',studio=studio,project=project,node=node)
        service=Workspaces(store)
        if tail==['workspace']:
            if write:policy.require('node','edit',studio=studio,project=project,node=node)
            return True,service.save(studio,project,node,body,flow=flow) if write else service.get(studio,project,node,flow=flow)
        if tail==['workspace','decision'] and write:return True,service.decide(studio,project,node,body,flow=flow)
        if tail==['workspace','skill-export'] and not write:
            policy.require('skill','export',studio=studio,project=project,node=node)
            return True,service.get(studio,project,node,flow=flow)['skill']
        if tail==['workspace','execute'] and write:
            from server.department_jobs import DepartmentExecutionQueue
            # Registry-aware dispatch remains in the main route handler.
            return False,None
        if tail==['workspace','job'] and not write:return False,None
        raise ValueError('此流程暂不支持该操作，请使用流程内保存、执行和审核')
    return False,None
