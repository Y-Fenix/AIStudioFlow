'use strict';
(function(root){
 function model(job={},options={}){
  let p=job.progress||{};if(typeof p==='string'){try{p=JSON.parse(p)}catch{p={}}}
  if(!p||typeof p!=='object')p={};
  const number=v=>Number.isFinite(v)&&v>=0?v:null;
  const label=({queued:'排队等待执行',running:'正在执行',completed:'执行完成',failed:'执行失败',interrupted:'执行中断',waiting_user:'等待处理',cancelled:'已取消'})[job.status]||'等待状态更新';
  const counts=Number.isFinite(p.completed)&&Number.isFinite(p.total)&&p.total>0?` · ${p.completed} / ${p.total}`:'';
  let detail=({'queued':'任务已提交，正在等待执行。','running':'任务正在处理，等待可观察活动。','completed':'请查看节点产物。','waiting_user':'需要处理当前节点后继续。'})[job.status]||'请查看运行记录。';
  if(job.status==='running'){
   const parts=[],phase=({preparing:'正在准备执行。',started:'模型请求已发出，等待可观察响应。',running:'模型请求进行中。',completed:'本次模型调用已完成，节点仍在处理交付。',retrying:'连接暂时异常，正在重试。',idle_timeout:'等待模型活动超时，请查看运行记录。'})[p.state];
   if(phase)parts.push(phase);
   if(p.state==='retrying'&&number(p.attempt)>0&&number(p.max_attempts)>0)parts.push(`重试 ${p.attempt} / ${p.max_attempts}`);
   if(number(p.events_received)>0){
    parts.push(`已观察到 ${p.events_received} 个模型事件`);
    const age=number(p.seconds_since_response),updated=number(p.progress_updated_at),now=number(options.now)??Date.now()/1000;
    if(age!==null)parts.push(`距最近可观察事件 ${Math.floor(age+(updated!==null?Math.max(0,now-updated):0))} 秒`);
   }
   if(number(p.assistant_chars)>0)parts.push(`已观察助手输出 ${p.assistant_chars} 字符`);
   if(number(p.tool_calls)!==null)parts.push(`已调用工具 ${p.tool_calls} 次`);
   if(number(p.commands_completed)!==null)parts.push(`已结束命令 ${p.commands_completed} 次`);
   if(parts.length)detail=parts.join(' · ');
  }
  return {summary:label+counts,detail:job.error||detail};
 }
 let dialog,key,trigger,timer;
 function close(immediate=false){if(!dialog?.open)return;clearTimeout(timer);const finish=()=>{if(dialog?.open)dialog.close();dialog?.classList.remove('is-closing');trigger?.focus({preventScroll:true})};if(immediate||root.matchMedia?.('(prefers-reduced-motion: reduce)').matches)finish();else{dialog.classList.add('is-closing');timer=setTimeout(finish,180)}}
 function ensure(){if(dialog)return;dialog=document.createElement('dialog');dialog.className='run-progress-drawer';dialog.setAttribute('aria-labelledby','run-progress-title');dialog.innerHTML='<header><div><small>WORKSPACE</small><h2 id="run-progress-title">当前任务</h2></div><button type="button" aria-label="关闭运行详情">×</button></header><div class="run-progress-body"><h3></h3><div class="run-progress-status" role="status"></div><section><strong>运行状态</strong><p></p></section><p class="run-progress-hint">关闭此窗口不会终止任务。</p></div>';document.body.append(dialog);dialog.querySelector('button').onclick=()=>close();dialog.addEventListener('cancel',e=>{e.preventDefault();close()});dialog.addEventListener('click',e=>{if(e.target===dialog)close()})}
 function update(k,job){if(k!==key||!dialog?.open)return;const m=model(job);dialog.querySelector('.run-progress-status').textContent=m.summary;dialog.querySelector('section p').textContent=m.detail}
 function open(k,title,job){ensure();clearTimeout(timer);dialog.classList.remove('is-closing');key=k;trigger=document.activeElement;dialog.querySelector('h3').textContent=title||'节点任务';if(!dialog.open)dialog.showModal();update(k,job)}
 function reset(){close(true);key=null}
 const api={model,open,update,reset};if(typeof module!=='undefined')module.exports=api;root.RunProgress=api;
})(globalThis);
