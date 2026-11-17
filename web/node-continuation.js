/* Shared shell/test controls. Only the server dispatches continuation work. */
(function(root){
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function nodeState(status,jobStatus){
  if(['approved','completed'].includes(status))return {value:'confirmed',label:'已确认',indicator:'confirmed'};
  if(status!=='cancelled'&&['queued','running','failed','interrupted'].includes(jobStatus))status=jobStatus;
  const states={
   waiting_user:['待人工确认','waiting'],running:['进行中','running'],queued:['排队中','running'],
   failed:['执行失败','failed'],interrupted:['执行中断','failed'],draft:['草稿','pending'],cancelled:['已取消','pending'],
  };
  const entry=states[status];
  return entry?{value:'current',label:entry[0],indicator:entry[1]}:{value:'pending',label:'未开始',indicator:'pending'};
 }
 function markup(edge,busy=false){
  if(!edge)return '';
  const label=`${edge.source_name} → ${edge.target_name}：自动执行`,blocked=!edge.editable||!edge.available;
  const delegated=edge.source?.startsWith('testing:')&&['testing:0','testing:1','testing:2'].includes(edge.source)&&['testing:1','testing:2','testing:4'].includes(edge.target);
  const explanation=edge.reason||(blocked?'没有来源节点的编辑权限，请联系负责人授权':delegated?'开启：本节点运行完成后自动处理必要决策并运行下一步；范围缺口保留为风险。缺少仓库、权限或证据会明确暂停；关闭的连接不会推进，不自动发布飞书 Bug。':'开启：当前节点完成并通过必要审核后，资料和权限齐全才自动执行下一步。关闭：等待手动继续。不会跳过审核或自动发布 Bug。');
  return `<span class="node-continuation ${edge.enabled?'is-on':''} ${blocked?'is-blocked':''}" data-continuation-source="${esc(edge.source)}" data-continuation-target="${esc(edge.target)}" title="${esc(explanation)}"><span class="continuation-arrow" aria-hidden="true">→</span><button type="button" class="continuation-switch" role="switch" aria-label="${esc(label)}" aria-checked="${!!edge.enabled}" aria-disabled="${blocked}" aria-busy="${busy}" ${busy?'disabled':''}><span class="continuation-track" aria-hidden="true"><i></i></span><span class="continuation-caption">${edge.enabled?'自动执行':'手动继续'}</span>${blocked?'<span class="continuation-help">查看原因</span>':''}</button><span class="continuation-reason" role="status" hidden>${esc(explanation)}</span></span>`;
 }
 function create({api,onError=()=>{},onChanged=()=>{},onUpdate=()=>{}}){
  let context=null,config=null,sequence=0,busy=false,busySource=null;
  function paint(){
   if(context&&config)onUpdate({...context,events:config.events||[]});
   document.querySelectorAll('[data-continuation-source]').forEach(el=>{
    const edge=config?.edges.find(e=>e.source===el.dataset.continuationSource&&e.target===el.dataset.continuationTarget);
    if(!edge)return;
    const template=document.createElement('template');template.innerHTML=markup(edge,busy&&busySource===edge.source);const next=template.content.firstElementChild;
    el.className=next.className;el.title=next.title;
    const button=el.querySelector('button'),newButton=next.querySelector('button');
    for(const name of ['aria-label','aria-checked','aria-disabled','aria-busy'])button.setAttribute(name,newButton.getAttribute(name));
    button.disabled=newButton.disabled;
    const caption=button.querySelector('.continuation-caption'),text=newButton.querySelector('.continuation-caption').textContent;
    if(caption.textContent!==text)caption.textContent=text;
    const help=button.querySelector('.continuation-help'),newHelp=newButton.querySelector('.continuation-help');
    if(newHelp&&!help)button.append(newHelp);else if(help&&!newHelp)help.remove();
    el.querySelector('.continuation-reason').textContent=next.querySelector('.continuation-reason').textContent;
   });
  }
  async function load(path,department){
   const ticket=++sequence;context={path,department};config=null;busy=false;
   document.querySelectorAll('.continuation-switch').forEach(button=>button.disabled=true);
   const result=await api(path+'/node-continuation?department='+encodeURIComponent(department));
   if(ticket!==sequence)return false;
   config=result;paint();return true;
  }
  function render(source,target){return markup(config?.edges.find(e=>e.source===source&&e.target===target),busy&&busySource===source)}
  async function refresh(){
   if(!context||busy)return;
   const current=context,ticket=sequence;
   const result=await api(current.path+'/node-continuation?department='+encodeURIComponent(current.department));
   if(context===current&&ticket===sequence){config=result;paint()}
  }
  document.addEventListener('keydown',event=>{
   const button=event.target.closest('.continuation-switch');
   if(button&&[' ','Enter'].includes(event.key)){event.preventDefault();event.stopImmediatePropagation();if(!button.disabled&&!event.repeat)button.click()}
  },true);
  document.addEventListener('click',async event=>{
   const button=event.target.closest('.continuation-switch'),element=button?.closest('[data-continuation-source]');
   if(!element)return;
   event.preventDefault();event.stopImmediatePropagation();
   if(button.getAttribute('aria-disabled')==='true'){
    const reason=element.querySelector('.continuation-reason');reason.hidden=false;onError(reason.textContent);return;
   }
   if(button.disabled)return;
   const edge=config?.edges.find(e=>e.source===element.dataset.continuationSource&&e.target===element.dataset.continuationTarget);
   if(!edge||!context||busy)return;
   const current=context,ticket=++sequence;busy=true;busySource=edge.source;paint();
   try{
    const updated=await api(current.path+'/node-continuation?department='+encodeURIComponent(current.department),{revision:config.revision,source:edge.source,target:edge.target,enabled:!edge.enabled});
    if(context===current&&ticket===sequence){config=updated;onChanged(current)}
   }catch(error){if(context===current&&ticket===sequence){onError(error.message);try{await refreshAfterConflict(current,ticket)}catch{}}}
   finally{if(context===current&&ticket===sequence){busy=false;paint()}}
  },true);
  async function refreshAfterConflict(current,ticket){const result=await api(current.path+'/node-continuation?department='+encodeURIComponent(current.department));if(context===current&&ticket===sequence)config=result}
  window.addEventListener('focus',()=>refresh().catch(e=>onError(e.message)));
  window.addEventListener('message',event=>{if(event.origin===location.origin&&event.data?.type==='studioflow:continuation-update'&&event.data.path===context?.path)refresh().catch(e=>onError(e.message))});
  const timer=setInterval(()=>{if(!document.hidden&&document.querySelector('[data-continuation-source]'))refresh().catch(()=>{})},3500);
  window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
  return {load,render,refresh,events:()=>config?.events||[],clear(){++sequence;context=null;config=null}};
 }
 root.NodeContinuationUI={markup,create,nodeState};
 if(typeof module!=='undefined')module.exports=root.NodeContinuationUI;
})(globalThis);
