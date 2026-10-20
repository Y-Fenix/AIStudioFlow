"""按完整资料分批设计，检查点只复用相同输入及规则；不把部分结果冒充完成。"""
import contextvars
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from server.model import PROMPT
from server.requirements import validate_cases
from server.processes import check_cancelled,cancellation_scope,current_cancellation_check
from server.codex_model import diagnostic_scope,current_diagnostic
from server.node_skills import current_skill

_checkpoint=contextvars.ContextVar('generation_checkpoint',default=None)
_progress=contextvars.ContextVar('generation_progress',default=None)
VERSION='bounded-generation-v4-gateway-window'

@contextmanager
def generation_scope(folder,progress=None):
    a=_checkpoint.set(Path(folder));b=_progress.set(progress)
    try:yield
    finally:_checkpoint.reset(a);_progress.reset(b)

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts=[];self.deleted=0;self.spans=[];self.line_offsets=[0]
    def feed(self,data):
        self.line_offsets=[0]
        for line in data.splitlines(keepends=True):self.line_offsets.append(self.line_offsets[-1]+len(line))
        super().feed(data)
    def handle_starttag(self,tag,attrs):
        if tag=='del':self.deleted+=1
    def handle_endtag(self,tag):
        if tag=='del':self.deleted=max(0,self.deleted-1)
    def handle_data(self,data):
        if not self.deleted:
            self.parts.append(data)
            line,col=self.getpos();start=self.line_offsets[line-1]+col
            self.spans.append((start,start+len(data)))
    def handle_entityref(self,name):self.handle_data('&'+name+';')
    def handle_charref(self,name):self.handle_data('&#'+name+';')

def original_quote(quote,raw):
    if quote in raw:return quote
    parser=TextParser();parser.feed(raw)
    text='';mapping=[]
    for part,(start,end) in zip(parser.parts,parser.spans):
        if not part.strip():continue
        if text:text+='\n';mapping.append(None)
        text+=part;mapping.extend(range(start,end))
    index=text.find(quote)
    if index<0:raise ValueError('测试点引用无法追溯到原始资料')
    positions=[v for v in mapping[index:index+len(quote)] if v is not None]
    if not positions:raise ValueError('测试点引用没有原文证据')
    return raw[positions[0]:positions[-1]+1]

def chunks(requirements,limit=1000):
    rows=[]
    for requirement in requirements:
        metadata=requirement.get('metadata',{})
        content=requirement['content']
        if metadata.get('kind')=='feishu' and content.lstrip().startswith('<'):
            parser=TextParser();parser.feed(content)
            content='\n'.join(p for p in parser.parts if p.strip()) or content
        for start in range(0,len(content),limit):
            rows.append({'id':requirement['id'],'source':requirement.get('source',''),
                         'content':content[start:start+limit], 'offset':start,'total_chars':len(content),
                         'context_before':content[max(0,start-600):start],
                         'context_after':content[start+limit:start+limit+600],
                         'metadata':{k:metadata[k] for k in ('effective_source_gaps','source_gaps','referenced_by','deleted_block_count') if k in metadata}})
    return rows

def generate(client,requirements):
    if not requirements:raise ValueError('请先导入需求')
    rows=chunks(requirements)
    from server.ai_models import current_selection
    signature=hashlib.sha256(json.dumps([VERSION,requirements,current_skill(),PROMPT,{k:v for k,v in (current_selection() or {}).items() if k!='api_key'},
        os.environ.get('TESTFLOW_CODEX_MODEL','gpt-6.1-sol'),os.environ.get('TESTFLOW_CODEX_EFFORT','high')],
        ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    folder=_checkpoint.get()
    if folder:
        folder=folder/signature;folder.mkdir(parents=True,exist_ok=True)
    combined={k:[] for k in ('points','cases','gaps','ambiguities')}
    summary=[{'id':r['id'],'source':r.get('source',''),'chars':len(r['content'])} for r in requirements]
    workers=int(os.environ.get('TESTFLOW_GENERATION_WORKERS','3'))
    if not 1 <= workers <= 3:raise ValueError('分批并发数必须为1至3')
    check_cancelled()
    parent_cancel=current_cancellation_check();parent_diagnostic=current_diagnostic()
    aborted=threading.Event();finished=set();progress_lock=threading.RLock()
    def batch_progress(index,row,phase,**extra):
        return {'phase':phase,'batch':index+1,'batches':len(rows),'source':row['source'],
                'completed':len(finished),'total':len(rows),**extra}
    def build_batch(index,row):
        with cancellation_scope(lambda: aborted.is_set() or bool(parent_cancel and parent_cancel())):
            return build_batch_body(index,row)
    def build_batch_body(index,row):
        check_cancelled()
        prompt=PROMPT+'\n本次分批设计。前后各600字符是边界上下文，避免切断规则；仅将当前content内规则作为生成目标；context_before/context_after只用于解释边界，不为上下文单独扩增用例。只生成当前片段可证明的测试点，不把同一文档其他片段误判为资料缺失。引用须是片段中连续原文，不跨HTML标签拼接；片段边界不是业务边界。保留具体缺口。所有资料索引：'+json.dumps(summary,ensure_ascii=False)+'\n仅返回紧凑JSON，不缩进、不加格式空白；完整保留必要测试点和可执行断言，不限定用例数量。不执行工具或访问文件。需求数据：\n'+json.dumps([row],ensure_ascii=False)
        source=[{'id':row['id'],'content':row['context_before']+row['content']+row['context_after']}]
        def request(phase,request_prompt):
            callback=_progress.get()
            cache=folder/f'{index:03}-{phase}.json' if folder else None
            with progress_lock:
                if callback:callback(batch_progress(index,row,phase,checkpoint_reused=bool(cache and cache.exists())))
            if cache and cache.exists():
                output=validate_cases(json.loads(cache.read_text()),[next(r for r in requirements if r['id']==row['id'])])
            else:
                def diagnostic(value):
                    with progress_lock:
                        if parent_diagnostic:parent_diagnostic(batch_progress(index,row,phase,**value))
                with diagnostic_scope(diagnostic):
                    output=client.request_json(request_prompt)
                original=next(r for r in requirements if r['id']==row['id'])
                # Audit may retain the canonical HTML span from its candidate.
                if isinstance(output,dict) and isinstance(output.get('points'),list):
                    for point in output['points']:
                        if not isinstance(point,dict):continue
                        quote=point.get('quote')
                        if isinstance(quote,str) and quote not in source[0]['content'] and quote in original['content']:
                            parser=TextParser();parser.feed(quote)
                            rendered='\n'.join(p for p in parser.parts if p.strip())
                            if rendered in source[0]['content']:point['quote']=rendered
                output=validate_cases(output,source)
                for point in output['points']:
                    rendered=point['quote'];canonical=original_quote(rendered,original['content'])
                    if canonical!=rendered:point['rendered_quote']=rendered
                    point['quote']=canonical
                # Canonical references remain exact raw-source substrings, not relaxed evidence.
                validate_cases(output,[original])
                if cache:
                    temp=cache.with_suffix('.tmp');temp.write_text(json.dumps(output,ensure_ascii=False));temp.replace(cache)
            return output
        candidate=request('design',prompt)
        audit_prompt=prompt+'\n反向审计：从本片段原需求逐条检查明确规则、阈值两侧、状态转换、奖励/重复/恢复风险。去除无依据的需求歧义和泛泛预期，保留可观察断言。不要发明规则或用片段外缺资料逃避片段内明确测试点。返回修订后的完整同协议JSON。候选：\n'+json.dumps(candidate,ensure_ascii=False)
        output=request('audit',audit_prompt)
        check_cancelled()
        with progress_lock:
            finished.add(index)
            if _progress.get():_progress.get()(batch_progress(index,row,'audit',checkpoint_reused=False))
        return output
    outputs=[None]*len(rows)
    pool=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='testflow-batch')
    futures={}
    try:
        for index,row in enumerate(rows):
            context=contextvars.copy_context()
            futures[pool.submit(context.run,build_batch,index,row)]=index
        for future in as_completed(futures):outputs[futures[future]]=future.result()
    except BaseException:
        aborted.set()
        for future in futures:future.cancel()
        raise
    finally:pool.shutdown(wait=True,cancel_futures=True)
    for index,output in enumerate(outputs):
        point_ids={p['id']:f'B{index+1}-'+p['id'] for p in output['points']}
        combined['points'].extend({**p,'id':point_ids[p['id']]} for p in output['points'])
        combined['cases'].extend({**c,'id':f'B{index+1}-'+c['id'],'point_ids':[point_ids[p] for p in c['point_ids']]} for c in output['cases'])
        combined['gaps'].extend({**g,'point_id':point_ids[g['point_id']]} for g in output['gaps'])
        combined['ambiguities'].extend(output['ambiguities'])
    # 只合并完全相同的前置及操作/断言，保留全部来源与测试点；不声称语义去重。
    seen={};merged=[]
    for case in combined['cases']:
        key=json.dumps([case['preconditions'],case['steps']],ensure_ascii=False,sort_keys=True)
        if key in seen:
            seen[key]['point_ids']=list(dict.fromkeys(seen[key]['point_ids']+case['point_ids']))
        else:seen[key]=case;merged.append(case)
    combined['cases']=merged
    combined['ambiguities']=list(dict.fromkeys(combined['ambiguities']))
    if len(rows)>1:
        combined['ambiguities'].append('分批设计已汇总全部片段；跨片段和跨文档的耦合覆盖仍需整体审查，不能仅凭片段覆盖宣称完整。')
    result=validate_cases(combined,requirements)
    result['generation_method']='逐片段设计与反向审计；分批检查点可复用，跨片段耦合需整体评审'
    result['generation_batches']={'count':len(rows),'input_hash':signature,'sources':summary,
        'manifest':[{'requirement_id':r['id'],'offset':r['offset'],'chars':len(r['content']),'total_chars':r['total_chars']} for r in rows]}
    callback=_progress.get()
    if callback:callback({'phase':'merged','completed':len(rows),'total':len(rows),'batches':len(rows)})
    return result
