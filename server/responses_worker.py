"""Isolated HTTP reader so the parent can cancel blocked connects/reads safely."""
import argparse,json,sys,urllib.request,urllib.error
from pathlib import Path

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--request',required=True)
    parser.add_argument('--protocol',default='responses');parser.add_argument('--headers',required=True);parser.add_argument('--endpoint',required=True);args=parser.parse_args()
    headers={}
    for line in Path(args.headers).read_text().splitlines():
        key,_,value=line.partition(':');headers[key]=value.strip()
    request=urllib.request.Request(args.endpoint,data=Path(args.request).read_bytes(),headers=headers)
    try:
        with urllib.request.urlopen(request,timeout=1800) as response:
            print(response.status,flush=True)
            with Path(args.output).open('wb',buffering=0) as out:
                while True:
                    line=response.readline()
                    if not line:break
                    if args.protocol!='chat':out.write(line);continue
                    if not line.startswith(b'data:'):continue
                    data=line[5:].strip()
                    if data==b'[DONE]':continue
                    try:event=json.loads(data)
                    except (ValueError,UnicodeError):continue
                    if event.get('error'):
                        out.write(b'data: {"type":"response.failed"}\n\n');continue
                    for choice in event.get('choices',[]):
                        delta=choice.get('delta',{}).get('content')
                        if isinstance(delta,str):
                            out.write(('data: '+json.dumps({'type':'response.output_text.delta','delta':delta})+'\n\n').encode())
                        reason=choice.get('finish_reason')
                        if reason:
                            kind='response.completed' if reason=='stop' else 'response.incomplete'
                            out.write(('data: '+json.dumps({'type':kind,'response':{'status':'completed' if reason=='stop' else 'incomplete','output':[]}})+'\n\n').encode())
    except urllib.error.HTTPError as exc:
        print(exc.code,flush=True);return 1
    except Exception:
        print('000',flush=True);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
