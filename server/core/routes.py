"""Shared team HTTP routes, intentionally outside department implementations."""
from urllib.parse import parse_qs
from server.core.permissions import Policy
from server.core.admin import Administration
from server.core.identity import user_id


def dispatch(handler, parts, query, body, write, auth, store, registry):
    policy=Policy(store);admin=Administration(store);q=parse_qs(query);studio=q.get('studio',[''])[0];project=q.get('project',[''])[0]
    result=None;matched=True
    if len(parts)==6 and parts[:2]==['api','projects'] and parts[3]=='tasks' and parts[5]=='codex-handoff' and write:
        from server.core.skill_handoff import SkillHandoff
        stage=int(q.get('stage',['-1'])[0])
        result=SkillHandoff(store).create_testing(store.preferences()['active_studio_id'],parts[2],parts[4],stage,body.get('origin'),preview=body.get('preview') is True)
    elif len(parts)==8 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5]=='tasks' and parts[7]=='codex-handoff' and write:
        from server.core.skill_handoff import SkillHandoff
        result=SkillHandoff(store).create_testing(parts[2],parts[4],parts[6],int(q.get('stage',['-1'])[0]),body.get('origin'),preview=body.get('preview') is True)
    elif len(parts)==7 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5:]==['workspace','codex-handoff'] and write:
        from server.core.skill_handoff import SkillHandoff
        result=SkillHandoff(store).create(parts[2],parts[4],q.get('node',[''])[0],body.get('origin'),preview=body.get('preview') is True,expected_sha256=body.get('expected_sha256'))
    elif len(parts)==6 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5]=='content':
        from server.core.project_content import ProjectContent
        service=ProjectContent(store)
        result=service.change(parts[2],parts[4],body) if write else service.get(parts[2],parts[4])
    elif len(parts)>=6 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5]=='skills':
        from server.core.skill_library import SkillLibrary
        service=SkillLibrary(store);node=q.get('node',[''])[0]
        if len(parts)==6:
            result=service.import_skill(parts[2],parts[4],node,body) if write else service.detail(parts[2],parts[4],node,before=q.get('before',[None])[0]) if node else service.listing(parts[2],parts[4])
        elif len(parts)==7 and parts[6]=='trash' and write:
            result=service.trash_node(parts[2],parts[4],node,body)
        elif len(parts)==7 and parts[6]=='recycle-bin' and not write:
            result=service.recycle_bin(parts[2],parts[4])
        elif len(parts)==8 and parts[7]=='export' and not write:
            version=q.get('version',[None])[0]
            result=service.export(parts[2],parts[4],parts[6],int(version) if version is not None else None)
        elif len(parts)==8 and parts[7] in ('restore','purge') and write:
            result=getattr(service,parts[7])(parts[2],parts[4],parts[6],body)
        else:raise KeyError('Skill 接口不存在')
    elif len(parts)==6 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5] in ('nodes','node-catalog'):
        from server.core.project_nodes import ProjectNodes
        service=ProjectNodes(store)
        if parts[5]=='node-catalog':
            if write: raise ValueError('项目节点目录只读')
            result=service.catalog(parts[2],parts[4])
        else:
            department=q.get('department',[''])[0]
            result=service.save(parts[2],parts[4],department,body) if write else service.get(parts[2],parts[4],department)
    elif len(parts)==6 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5]=='node-continuation':
        from server.core.node_continuation import NodeContinuation
        service=NodeContinuation(store,registry);department=q.get('department',[''])[0]
        result=service.save(parts[2],parts[4],department,body) if write else service.get(parts[2],parts[4],department)
    elif parts==['api','me','capabilities'] and not write:
        if studio and not any(s['id']==studio for s in store.studios()):raise KeyError('工作室不存在')
        if project:store.check_project(studio,project)
        result=policy.capabilities(studio,project)
    elif parts==['api','admin','project-connection']:result=admin.project_connection(body.get('studio_id',studio),body.get('project_id',project),body if write else None)
    elif parts==['api','integrations'] and not write:
        with store.connection() as db:
            row=db.execute('SELECT status FROM users WHERE id=?',(user_id(),)).fetchone()
        if not row or row['status']!='active':raise PermissionError('账号待审批')
        result={'items':registry.status()}
    elif len(parts)==7 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5:7]==['workspace','execute'] and write:
        from server.department_jobs import DepartmentExecutionQueue
        result=DepartmentExecutionQueue(store,registry).enqueue(parts[2],parts[4],q.get('node',[''])[0],body.get('revision'))
    elif len(parts)==7 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5:7]==['workspace','job'] and not write:
        from server.department_jobs import DepartmentExecutionQueue
        result=DepartmentExecutionQueue(store,registry).latest(parts[2],parts[4],q.get('node',[''])[0])
    elif len(parts)==7 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5]=='department-jobs' and not write:
        from server.department_jobs import DepartmentExecutionQueue
        result=DepartmentExecutionQueue(store,registry).get(parts[2],parts[4],parts[6])
    elif parts==['api','admin','overview'] and not write:result=admin.overview(studio,project)
    elif parts==['api','admin','members'] and write:result=admin.member(body)
    elif parts==['api','admin','rules'] and write:result=admin.rule(body)
    elif len(parts)==5 and parts[:3]==['api','admin','rules'] and parts[4]=='revoke' and write:result=admin.revoke(parts[3])
    elif parts==['api','admin','users','status'] and write:result=admin.user_status(body)
    elif parts==['api','admin','archive'] and write:result=admin.archive(body.get('studio_id',''),body.get('project_id',''),body.get('confirmed'),body.get('name'))
    elif parts==['api','admin','auth']:
        policy.require('platform','manage');result=auth.save(body) if write else auth.status(True)
    elif parts==['api','admin','owner'] and write:result=auth.promote_owner(body.get('user_id'),body.get('confirmed'))
    elif len(parts)==7 and parts[:2]==['api','studios'] and parts[3]=='projects' and parts[5:]==['workspace','execute'] and write:
        from server.core.integrations import ExecutionService
        result=ExecutionService(store,registry).execute(parts[2],parts[4],q.get('node',[''])[0],body.get('revision'))
    else:matched=False
    if matched:
        # Shared routes are dispatched before the legacy gateway. Keep their
        # project identity attached so nested job/workspace payloads are redacted
        # using the requesting user's latest permissions as well.
        if len(parts)>=5 and parts[:2]==['api','studios'] and parts[3]=='projects':
            handler.team_scope={'studio':parts[2],'project':parts[4]}
        code=202 if parts[5:7]==['workspace','execute'] and write else 200
        handler.send_json(code,result)
    return matched
