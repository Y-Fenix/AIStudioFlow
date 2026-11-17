"""Public data endpoints, dispatched before private workflow APIs."""
from urllib.parse import parse_qs
from server.core.public_area.service import PublicArea


def public_allowed(parts,write):
    if parts[:2]==['api','auth']:return len(parts)==3 and parts[2] in ('public','setup','register','login','logout','session','password')
    if parts in (['api','runtime'],['api','studio-catalog'],['api','me','preferences'],['api','me','capabilities'],['api','studios']):return True
    if parts[:2]==['api','admin']:
        return parts[2:] in (['auth'],['overview'],['members'],['rules'],['users','status'],['users','password'],['archive'],['owner']) or (len(parts)==5 and parts[2]=='rules' and parts[4]=='revoke')
    if parts[:2]!=['api','studios']:return False
    if len(parts) in (4,5,6) and parts[3]=='notifications':return True
    if len(parts)==4 and parts[3] in ('enter','projects'):return True
    if len(parts)>=5 and parts[3]=='projects':
        return len(parts)==5 and not write or parts[5:]==['enter'] and write or parts[5:]==['node-catalog'] and not write or parts[5:6]==['public']
    return False


def dispatch(handler,parts,query,body,write,store):
    if len(parts)<6 or parts[:2]!=['api','studios'] or parts[3]!='projects' or parts[5]!='public':return False
    service=PublicArea(store);s,p=parts[2],parts[4];tail=parts[6:];q={k:v[0] for k,v in parse_qs(query).items()};code=200
    if tail==['versions']:
        result=service.versions(s,p,body if write else None);code=201 if write else 200
    elif tail==['items'] and not write:result=service.listing(s,p,q)
    elif tail==['stage'] and write:result=service.stage(s,p,body)
    elif len(tail)==2 and tail[0]=='operations' and not write:result=service.status(s,p,tail[1])
    elif len(tail)==3 and tail[0]=='operations' and tail[2]=='commit' and write:result=service.commit(s,p,tail[1])
    elif len(tail)==2 and tail[0]=='items' and not write:result=service.detail(s,p,tail[1],int(q['revision']) if 'revision' in q else None)
    elif len(tail)==3 and tail[0]=='items' and tail[2]=='withdraw' and write:result=service.withdraw(s,p,tail[1],body.get('revision'))
    elif len(tail)==3 and tail[0]=='items' and tail[2]=='export' and not write:result=service.export(s,p,tail[1],int(q.get('revision',0)))
    elif len(tail)==4 and tail[0]=='items' and tail[2]=='attachments' and not write:result=service.attachment(s,p,tail[1],int(q.get('revision',0)),int(tail[3]))
    else:raise KeyError('公区接口不存在')
    handler.send_json(code,result);return True
