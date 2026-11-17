/* Shared, read-only node assistant. Model replies are always rendered as text. */
'use strict';
const NodeMemoryUI=(()=>{
 let current=null,timer=null,epoch=0,host=null,options=null;
 const drafts=new Map();
 const e=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={queued:'等待回答',running:'正在分析',completed:'已回答',failed:'回答失败',interrupted:'已中断'};
 function dispose(){clearTimeout(timer);timer=null;epoch++;if(host?.isConnected&&current){const field=host.querySelector('textarea');if(field)drafts.set(current,{text:field.value,open:host.open})}host=null;options=null}
 function mount(container,o){
  const key=JSON.stringify([o.path,o.node,o.flow||'',o.task||'']);
  if(host?.isConnected&&current===key)return;
  dispose();current=key;options=o;
  const draft=drafts.get(key)||{};host=document.createElement('details');host.className='node-memory panel';host.open=!!draft.open;
  host.innerHTML=`<summary><span>节点助手</span><span class="memory-summary">记住本流程资料 · 可关联已确认交付</span></summary><div class="memory-body"><p class="memory-hint">回答引用已保存资料；提问不会修改节点、自动审核或发布。资料更新后重新提问。</p><div class="memory-links"><button type="button" data-memory="sources">关联来源</button><span data-memory="source-status"></span></div><div class="memory-source-picker" hidden></div><div class="memory-messages" aria-live="polite"></div><form><label>向当前节点提问<textarea maxlength="8000" rows="2" placeholder="例如：这条需求对应哪些用例？还有哪些证据缺口？">${e(draft.text||'')}</textarea></label><div class="memory-compose"><span role="status" data-memory="status"></span><button type="submit" class="primary" ${o.edit===false?'disabled':''}>发送问题</button></div></form></div>`;
  container.append(host);const local=host,seq=epoch;
  const url=(suffix='')=>o.path+'/node-memory'+suffix+'?'+new URLSearchParams({node:o.node,...(o.flow?{flow:o.flow}:{}),...(o.task?{task:o.task}:{})});
  const valid=()=>seq===epoch&&local.isConnected;
  const error=err=>{if(valid())local.querySelector('[data-memory="status"]').textContent=err.message};
  const save=()=>drafts.set(key,{text:local.querySelector('textarea').value,open:local.open});
  local.addEventListener('toggle',save);local.querySelector('textarea').addEventListener('input',save);
  let pending=false;
  async function refresh(){
   try{const data=await o.api(url());if(!valid())return;
    local.querySelector('[data-memory="status"]').textContent='';
    pending=data.messages.some(m=>['queued','running'].includes(m.status));local.querySelector('button[type="submit"]').disabled=pending||o.edit===false;
    const list=local.querySelector('.memory-messages'),top=list.scrollTop;
    const html=data.messages.map(m=>`<article class="memory-message"><div class="memory-question">${e(m.question||'来源权限已收回')}</div><div class="memory-answer">${e(m.answer||m.error||labels[m.status])}</div><small>${e(labels[m.status]||m.status)}${m.stale?' · 来源已变化，请重新提问':''}</small>${m.sources?.length?`<details><summary>引用资料 · ${m.sources.length}</summary>${m.sources.map(s=>`<p>${e(s.id)} · ${e(s.node)} · 修订 ${e(s.revision)}${s.truncated?' · 已截取':''}</p>`).join('')}</details>`:''}</article>`).join('')||'<p class="memory-hint">当前节点还没有提问记录。</p>';
    if(list.innerHTML!==html){list.innerHTML=html;list.scrollTop=top}
    if(pending)timer=setTimeout(refresh,1500);
   }catch(err){error(err);if(valid())timer=setTimeout(refresh,3500)}
  }
  local.querySelector('form').onsubmit=async ev=>{ev.preventDefault();if(pending)return;const field=local.querySelector('textarea');if(!field.value.trim())return;pending=true;local.querySelector('button[type="submit"]').disabled=true;local.querySelector('[data-memory="status"]').textContent='正在提交…';try{await o.api(url(),{question:field.value});if(!valid())return;field.value='';save();local.querySelector('[data-memory="status"]').textContent='';await refresh()}catch(err){pending=false;error(err);if(valid())local.querySelector('button[type="submit"]').disabled=o.edit===false}};
  local.querySelector('[data-memory="sources"]').onclick=async()=>{
   const picker=local.querySelector('.memory-source-picker');picker.hidden=!picker.hidden;if(picker.hidden)return;
   try{const [catalog,links]=await Promise.all([o.api(url('/catalog')),o.api(url('/links'))]);if(!valid())return;
    const items=[...catalog.items,...links.items.filter(l=>!catalog.items.some(s=>s.node===l.node&&s.flow===l.flow)).map(l=>({...l,flow_name:l.restricted?'来源权限已收回':'已关联来源',title:l.restricted?'可取消关联':'未确认 / 已不可用',unavailable:true}))];
    picker.innerHTML='<p class="memory-hint">跨部门 / 其他流程只引用已确认交付；每次提问读取最新版本。</p>'+items.map((s,i)=>`<label><input type="checkbox" data-source-index="${i}" ${links.items.some(l=>l.node===s.node&&l.flow===s.flow)?'checked':''} ${o.edit===false?'disabled':''}> ${e(s.flow_name)} / ${e(s.title)}${s.revision===undefined?'':' · v'+s.revision}</label>`).join('')+(items.length?'':'<p>暂无可关联的已确认交付。</p>');
    picker.onchange=async ev=>{const input=ev.target;if(!input.matches('[data-source-index]'))return;input.disabled=true;try{await o.api(url('/links'),{...items[Number(input.dataset.sourceIndex)],remove:!input.checked});if(valid())local.querySelector('[data-memory="source-status"]').textContent='来源已保存，下次提问生效'}catch(err){input.checked=!input.checked;error(err)}finally{input.disabled=false}};
   }catch(err){error(err)}
  };
  refresh();
 }
 return {mount,dispose};
})();
