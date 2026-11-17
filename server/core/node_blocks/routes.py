"""HTTP entry points; services enforce scope on every operation."""
from server.core.node_blocks.service import Builder
from server.core.node_blocks.runtime import Runs


def dispatch(parts,q,body,write,store,registry):
    if len(parts)<3 or parts[:2]!=['api','studios']:return False,None
    service=Builder(store);studio=parts[2]
    if write and not isinstance(body,dict):raise ValueError('配置须为对象')
    if len(parts)==4 and parts[3]=='block-templates':
        department=q.get('department',[''])[0]
        if write:
            if body.get('action')=='archive':return True,service.archive_template(studio,body)
            return True,service.save_template(studio,body)
        identity=q.get('id',[''])[0];version=q.get('version',[None])[0]
        return True,service.template(studio,department,identity,int(version) if version else None) if identity else service.templates(studio,department)
    if len(parts) not in (6,7,8) or parts[3]!='projects':return False,None
    project=parts[4];resource=parts[5]
    if resource=='node-blueprint' and len(parts)==6:
        node=q.get('node',[''])[0]
        return True,service.save_blueprint(studio,project,node,body) if write else service.blueprint(studio,project,node)
    if resource=='custom-flows' and len(parts)==6:
        return True,(service.archive_flow(studio,project,body) if body.get('action')=='archive' else service.save_flow(studio,project,body)) if write else service.flows(studio,project)
    if resource=='custom-flows' and len(parts)==7 and not write:
        return True,service.flow(studio,project,parts[6])
    if resource=='block-runs':
        if len(parts)==8 and (parts[7]!='publish' or not write):return False,None
        runs=Runs(store,registry)
        if len(parts)==8 and parts[7]=='publish' and write:return True,runs.publish(studio,project,parts[6],body)
        if len(parts)==7:return True,runs.act(studio,project,parts[6],body) if write else runs.get(studio,project,parts[6])
        return True,runs.start(studio,project,body) if write else runs.listing(studio,project,flow=q.get('flow',[None])[0])
    return False,None
