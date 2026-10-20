/* Shared shell/test controls. Only the server dispatches continuation work. */
(function(root){
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function markup(edge,busy=false){
  if(!edge)return '';
  const label=`${edge.source_name} → ${edge.target_name}：自动继续`;
  const explanation=edge.reason||'开启：当前节点完成并通过必要审核后，资料和权限齐全才自动执行下一步。关闭：等待手动继续。不会跳过审核或自动发布 Bug。';
  return `<span class="node-continuation ${edge.enabled?'is-on':''}" data-continuation-source="${esc(edge.source)}" data-continuation-target="${esc(edge.target)}" title="${esc(explanation)}"><span class="continuation-arrow" aria-hidden="true">→</span><button type="button" class="continuation-switch" role="switch" aria-label="${esc(label)}" aria-checked="${!!edge.enabled}" ${!edge.editable||!edge.available||busy?'disabled':''}><span class="continuation-track" aria-hidden="true"><i></i></span><span class="continuation-caption">${busy?'保存中':edge.enabled?'自动继续':'手动继续'}</span></button></span>`;
 }
 function create({api,onError=()=>{},onChanged=()=>{},onUpdate=()=>{}}){
  let context=null,config=null,sequence=0,busy=false;
  function paint(){
   if(context&&config)onUpdate({...context,events:config.events||[]});
   document.querySelectorAll('[data-continuation-source]').forEach(el=>{
    const edge=config?.edges.find(e=>e.source===el.dataset.continuationSource&&e.target===el.dataset.continuationTarget);
    const focus=el.contains(document.activeElement);
    if(edge){el.outerHTML=markup(edge,busy);if(focus)document.querySelectorAll('[data-continuation-source]').forEach(n=>{if(n.dataset.continuationSource===edge.source)n.querySelector('button')?.focus({preventScroll:true})})}
   });
  }
  async function load(path,department){
   const ticket=++sequence;context={path,department};config=null;
   document.querySelectorAll('.continuation-switch').forEach(button=>button.disabled=true);
   const result=await api(path+'/node-continuation?department='+encodeURIComponent(department));
   if(ticket!==sequence)return false;
   config=result;paint();return true;
  }
  function render(source,target){return markup(config?.edges.find(e=>e.source===source&&e.target===target),busy)}
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
   if(!element||button.disabled)return;
   event.preventDefault();event.stopImmediatePropagation();
   const edge=config?.edges.find(e=>e.source===element.dataset.continuationSource&&e.target===element.dataset.continuationTarget);
   if(!edge||!context||busy)return;
   const current=context,ticket=++sequence;busy=true;paint();
   try{
    const updated=await api(current.path+'/node-continuation?department='+encodeURIComponent(current.department),{revision:config.revision,source:edge.source,target:edge.target,enabled:!edge.enabled});
    if(context===current&&ticket===sequence){config=updated;onChanged(current)}
   }catch(error){if(context===current&&ticket===sequence){onError(error.message);try{await refreshAfterConflict(current,ticket)}catch{}}}
   finally{busy=false;if(context===current&&ticket===sequence)paint()}
  },true);
  async function refreshAfterConflict(current,ticket){const result=await api(current.path+'/node-continuation?department='+encodeURIComponent(current.department));if(context===current&&ticket===sequence)config=result}
  window.addEventListener('focus',()=>refresh().catch(e=>onError(e.message)));
  window.addEventListener('message',event=>{if(event.origin===location.origin&&event.data?.type==='studioflow:continuation-update'&&event.data.path===context?.path)refresh().catch(e=>onError(e.message))});
  const timer=setInterval(()=>{if(!document.hidden&&document.querySelector('[data-continuation-source]'))refresh().catch(()=>{})},3500);
  window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
  return {load,render,refresh,events:()=>config?.events||[],clear(){++sequence;context=null;config=null}};
 }
 root.NodeContinuationUI={markup,create};
 if(typeof module!=='undefined')module.exports=root.NodeContinuationUI;
})(globalThis);
