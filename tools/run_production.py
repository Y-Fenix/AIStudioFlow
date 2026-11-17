#!/usr/bin/env python3
"""Operate production runs through public services, without starting web workers.

`create` only persists a delegated run. Only `run` dispatches models/tools.
Use a dedicated database; never run against a database served by another process.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from server.store import Store
from server.core.identity import current_user
from server.core.integrations import AdapterRegistry
from server.core.production_runs import ProductionRuns


def compact(run):
    return {key:run.get(key) for key in ('id','studio_id','project_id','name','status','summary','progress','error','gaps','allowed_actions')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,type=Path,help='Dedicated database, not concurrently served')
    parser.add_argument('--actor',default='local')
    parser.add_argument('--studio')
    parser.add_argument('--project')
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('create',help='Persist a run; no models/tools are dispatched')
    create.add_argument('--new-project')
    create.add_argument('--name')
    text=create.add_mutually_exclusive_group(required=True)
    text.add_argument('--brief');text.add_argument('--brief-file',type=Path)
    create.add_argument('--request-id')
    for command in ('status','run','pause','resume','retry','cancel'):
        command_parser=sub.add_parser(command)
        command_parser.add_argument('--id',required=True)
        if command=='status':command_parser.add_argument('--full',action='store_true')
    args=parser.parse_args()
    token=current_user.set(args.actor)
    service=None
    try:
        store=Store(args.database)
        studio=args.studio or store.studios()[0]['id']
        project=args.project
        if args.command=='create' and args.new_project:
            if project:parser.error('Choose --project or --new-project')
            project=store.create_project(args.new_project,studio)['id']
        if not project:parser.error('--project is required unless create --new-project is used')
        service=ProductionRuns(store,AdapterRegistry().load_modules())
        if args.command=='create':
            brief=args.brief if args.brief is not None else args.brief_file.read_text(encoding='utf-8')
            run=service.create(studio,project,{'brief':brief,'name':args.name,'request_id':args.request_id,'delegation':True})
        elif args.command=='status':
            run=service.get(studio,project,args.id)
            print(json.dumps(run if args.full else compact(run),ensure_ascii=False,indent=2));return 0
        elif args.command!='run':run=service.action(studio,project,args.id,args.command)
        else:
            other=[r for r in service.listing(studio,project)['runs'] if r['id']!=args.id and r['status'] in ('queued','running')]
            if other:raise ValueError('Dedicated run command requires other queued/running runs in this project to be paused')
            run=service.get(studio,project,args.id)
            if run['status'] not in ('queued','running'):raise ValueError('Run must be queued; use resume/retry explicitly for paused/failed runs')
            previous=None
            try:
                while run['status'] in ('queued','running'):
                    snapshot=compact(run)
                    if snapshot!=previous:print(json.dumps(snapshot,ensure_ascii=False),flush=True);previous=snapshot
                    if not service.advance(studio,project,args.id):break
                    run=service.get(studio,project,args.id)
            except KeyboardInterrupt:
                run=service.action(studio,project,args.id,'pause')
                print(json.dumps(compact(run),ensure_ascii=False,indent=2),flush=True);return 130
            print(json.dumps(compact(run),ensure_ascii=False,indent=2),flush=True)
            return 0 if run['status']=='completed' else 1
        print(json.dumps(compact(run),ensure_ascii=False,indent=2));return 0
    except (ValueError,KeyError,PermissionError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr);return 1
    finally:
        if service:service.shutdown.set()
        current_user.reset(token)


if __name__=='__main__':raise SystemExit(main())
