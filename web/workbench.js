/* Shared document workbench. Markdown is deliberately a small, text-only subset. */
(function(root){
 'use strict';
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function safeURL(value){
  if(/[\u0000-\u0020\u007f]/.test(value)||value.startsWith('//'))return false;
  try{const url=new URL(value,'https://workbench.invalid');return ['http:','https:','mailto:'].includes(url.protocol)&&!url.username&&!url.password}catch{return false}
 }
 function inline(value){
  const token=/`([^`]+)`|!\[([^\]]*)\]\(([^\s)]+)\)|\[([^\]]+)\]\(([^\s)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let html='',last=0;
  for(const match of value.matchAll(token)){
   html+=escape(value.slice(last,match.index));last=match.index+match[0].length;
   if(match[1]!==undefined)html+='<code>'+escape(match[1])+'</code>';
   else if(match[2]!==undefined)html+='<span class="wb-image-note">[图片：'+escape(match[2]||'未命名')+' · 未加载]</span>';
   else if(match[4]!==undefined)html+=safeURL(match[5])?'<a href="'+escape(match[5])+'" target="_blank" rel="noopener noreferrer">'+escape(match[4])+'</a>':escape(match[4])+'（链接已禁用）';
   else if(match[6]!==undefined)html+='<strong>'+escape(match[6])+'</strong>';
   else html+='<em>'+escape(match[7])+'</em>';
  }
  return html+escape(value.slice(last));
 }
 function markdown(value){
  const lines=String(value??'').replace(/\r\n?/g,'\n').split('\n');let html='',i=0;
  const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
  while(i<lines.length){const line=lines[i];
   if(/^\s*```/.test(line)){const code=[];i++;while(i<lines.length&&!/^\s*```/.test(lines[i]))code.push(lines[i++]);i++;html+='<pre><code>'+escape(code.join('\n'))+'</code></pre>';continue}
   if(!line.trim()){i++;continue}
   const heading=line.match(/^(#{1,6})\s+(.+)$/);if(heading){html+='<h'+heading[1].length+'>'+inline(heading[2])+'</h'+heading[1].length+'>';i++;continue}
   if(i+1<lines.length&&line.includes('|')&&/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i+1])){
    const header=cells(line);html+='<div class="wb-table"><table><thead><tr>'+header.map(c=>'<th>'+inline(c)+'</th>').join('')+'</tr></thead><tbody>';i+=2;
    while(i<lines.length&&lines[i].includes('|')&&lines[i].trim())html+='<tr>'+cells(lines[i++]).map(c=>'<td>'+inline(c)+'</td>').join('')+'</tr>';
    html+='</tbody></table></div>';continue;
   }
   if(/^\s*[-*+]\s+/.test(line)||/^\s*\d+\.\s+/.test(line)){
    const ordered=/^\s*\d+\./.test(line),tag=ordered?'ol':'ul',pattern=ordered?/^\s*\d+\.\s+/:/^\s*[-*+]\s+/;
    html+='<'+tag+'>';while(i<lines.length&&pattern.test(lines[i]))html+='<li>'+inline(lines[i++].replace(pattern,''))+'</li>';html+='</'+tag+'>';continue;
   }
   if(/^>\s?/.test(line)){html+='<blockquote>'+inline(line.replace(/^>\s?/,''))+'</blockquote>';i++;continue}
   html+='<p>'+inline(line)+'</p>';i++;
  }
  return html||'<p class="muted">暂无交付内容。运行节点或切换编辑后整理交付。</p>';
 }
 function currentReport({job,workspace,node,dirty}){return !dirty&&job?.status==='completed'&&job.node===node&&job.result?.workspace?.revision===workspace?.revision?job.result:null}
 function mergeDraft(previous,draft,next){return Object.fromEntries(['inputs','deliverable'].map(key=>[key,draft[key]===previous?.[key]?next[key]:draft[key]]))}
 function recoveryHint(job){return job?.status==='failed'?'先核对错误、输入、Skill 与模型连接；处理后保存修改，再重新运行。':job?.status==='interrupted'?'本次执行已中断；核对输入、Skill 与模型连接后，手动重新运行。':''}
 function progressSummary(progress,now=Date.now()){
  if(!progress||typeof progress!=='object')return '';
  const seconds=v=>Number.isFinite(v)&&v>=0?Math.floor(v):null;
  const age=seconds(now/1000-progress.progress_updated_at),idle=seconds(progress.seconds_since_response);
  const states={preparing:'准备请求',started:'请求已发出',running:'等待模型完成',retrying:'正在重试连接',idle_timeout:'持续无响应，已触发空闲超时',completed:'模型响应已结束，等待节点校验',invalid_json:'响应格式校验未通过',incomplete_response:'模型响应不完整',cli_failed:'模型连接返回错误',start_failed:'模型连接启动失败',output_too_large:'模型输出超过限制'};
  const parts=[progress.requested_model,progress.effort,states[progress.state]||'等待进度更新'].filter(Boolean);
  if(progress.attempt)parts.push('请求 '+progress.attempt+'/'+(progress.max_attempts||'?'));
  if(seconds(progress.assistant_chars)!==null)parts.push('已接收 '+Math.floor(progress.assistant_chars)+' 字符');
  if(idle!==null)parts.push('距上次有效响应 '+(idle+(age||0))+' 秒');
  if(age!==null&&age>45)parts.push('进度更新已中断 '+age+' 秒，请检查服务连接');
  return parts.join(' · ');
 }
 function homeSummary({project,nodes}){
  const visible=project?nodes.filter(n=>n.capabilities?.view):[];
  const review=visible.find(n=>n.status==='waiting_user'&&n.capabilities.approve);
  const edit=visible.find(n=>n.status!=='approved'&&n.capabilities.edit),inspect=visible.find(n=>n.status!=='approved');
  const next=!project?{kind:'project'}:!visible.length?{kind:'access'}:review?{kind:'review',key:review.key}:edit?{kind:'prepare',key:edit.key}:inspect?{kind:'inspect',key:inspect.key}:{kind:'complete'};
  return {total:visible.length,saved:visible.filter(n=>n.hasDeliverable).length,approved:visible.filter(n=>n.status==='approved').length,pending:visible.filter(n=>n.status==='waiting_user').length,runnable:visible.filter(n=>n.adapter&&n.capabilities.edit&&n.capabilities.execute).length,next};
 }
 const markupCache=new WeakMap();
 function renderMarkup(element,html){
  if(markupCache.get(element)===html)return;
  element.innerHTML=html;markupCache.set(element,html);
 }
 let controller,observer,host;
 function dispose(){controller?.abort();observer?.disconnect();controller=null;observer=null;host=null;root.document?.body.classList.remove('document-workbench')}
 const item=(label,ok,detail)=>'<li><span class="wb-check '+(ok?'ready':'attention')+'">'+(ok?'已具备':'待处理')+'</span><div><b>'+escape(label)+'</b><small>'+escape(detail)+'</small></div></li>';
 function update(){
  if(!host||!root.document?.querySelector('.node-panel'))return;
  const state=host.state(),{workspace:w,job,node,dirty,saving,pending,capabilities:c,adapter}=state;
  if(!w)return;
  const input=document.querySelector('#node-inputs'),output=document.querySelector('#node-deliverable');
  const target=document.querySelector('#wb-readiness');
  target.innerHTML=item('输入资料',!!input.value.trim(),input.value.trim()?input.value.length+' 字符 · 来源真实性需核对':'填写需求、范围及来源')+item('节点 Skill',!!w.skill?.content?.trim(),w.skill?.name||'尚未选择')+item('执行器',adapter,adapter?'已注册 · 运行结果仍须人工审核':'当前节点等待人工整理交付')+item('编辑与执行权限',!!(c.edit&&c.execute),c.edit?(c.execute?'允许保存及执行':'仅可编辑，需执行授权'):'没有节点编辑权限')+item('保存状态',!dirty&&!saving,saving?'正在保存':dirty?'有未保存修改，先保存再运行':'当前草稿与保存版本一致');
  const recovery=document.querySelector('#wb-recovery');recovery.textContent=recoveryHint(job);recovery.hidden=!recovery.textContent;
  const progress=document.querySelector('#wb-progress');progress.textContent=progressSummary(job?.progress);progress.hidden=!progress.textContent||!['queued','running'].includes(job?.status);
  const result=currentReport({job,workspace:w,node,dirty}),report=document.querySelector('#wb-report');
  report.hidden=!result;
  if(result){const quality=result.quality||{};renderMarkup(report,'<h3>本次交付检查</h3><p>版本 '+escape(w.revision)+' · 结构与来源检查不等于事实核验。</p><dl><dt>输出契约</dt><dd>'+escape(quality.contract||'未返回')+'</dd><dt>结构检查项</dt><dd>'+escape(quality.sections_checked??'未返回')+'</dd><dt>来源引用检查项</dt><dd>'+escape(quality.source_quotes_checked??'未返回')+'</dd><dt>事实核验</dt><dd>'+(quality.fact_checked===true?'执行器报告已核验；仍需人工审阅':'未进行事实核验')+'</dd></dl><details><summary>查看证据与缺口</summary><h4>证据</h4><pre>'+escape(JSON.stringify(result.evidence||[],null,2))+'</pre><h4>缺口</h4><pre>'+escape(JSON.stringify(result.gaps||[],null,2))+'</pre></details>')}
  const active=pending||['queued','running'].includes(job?.status),run=document.querySelector('[data-action="run-node"]');
  if(run){run.disabled=!!(saving||active||dirty||!c.edit||!c.execute||!input.value.trim()||!w.skill?.content?.trim());run.setAttribute('aria-busy',String(!!active));run.textContent=pending?'正在提交…':active?'正在执行':'运行本节点'}
  document.querySelectorAll('.node-panel [data-action="save-node"],.node-panel [data-action="reset-node"],.node-panel [data-action="upstream"]').forEach(el=>{el.disabled=!!(saving||!c.edit)});
  document.querySelectorAll('#node-inputs,#node-deliverable').forEach(el=>{el.readOnly=!!(saving||!c.edit)});
  const preview=document.querySelector('#wb-preview');if(!preview.hidden)renderMarkup(preview,markdown(output.value));
  const status=document.querySelector('#save-status');if(status&&!dirty&&!saving)status.textContent='版本 '+w.revision+' · '+(w.updated_at?'保存于 '+host.time(w.updated_at):'尚未保存');
 }
 function mount(options){
  dispose();const panel=document.querySelector('.node-panel');if(!panel)return;host=options;controller=new AbortController();const {signal}=controller;document.body.classList.add('document-workbench');
  const actions=panel.querySelector('.skill-actions');if(actions){const select=actions.querySelector('[data-action="select-skill"]'),tools=[...actions.children].filter(el=>el!==select);actions.innerHTML='';if(select)actions.append(select);const menu=document.createElement('details');menu.className='wb-tools';menu.innerHTML='<summary>Skill 工具</summary><div class="wb-tool-menu"></div>';tools.forEach(el=>menu.lastElementChild.append(el));actions.append(menu)}
  const field=panel.querySelector('#node-deliverable').closest('.field');field.insertAdjacentHTML('afterbegin','<div class="wb-editor-switch" role="group" aria-label="交付物显示方式"><button data-wb-view="preview" aria-pressed="true">预览</button><button data-wb-view="edit" aria-pressed="false">编辑 Markdown</button></div>');
  field.insertAdjacentHTML('beforeend','<article id="wb-preview" class="wb-markdown" aria-label="交付物预览"></article>');const hasOutput=!!panel.querySelector('#node-deliverable').value.trim();panel.querySelector('#node-deliverable').hidden=hasOutput;panel.querySelector('#wb-preview').hidden=!hasOutput;field.querySelectorAll('[data-wb-view]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.wbView===(hasOutput?'preview':'edit'))));
  const rail=document.querySelector('.node-rail');rail.insertAdjacentHTML('afterbegin','<section class="panel wb-readiness"><div class="eyebrow">RUN READINESS</div><h3>运行准备</h3><ul id="wb-readiness"></ul><p id="wb-progress" class="wb-progress" role="status" aria-live="off" hidden></p><p id="wb-recovery" role="status" hidden></p><p>检查资料、规则与权限，再运行；完成后由你决定是否采用。</p></section><section id="wb-report" class="panel wb-report" hidden></section>');
  const extra=field.nextElementSibling;if(extra?.classList.contains('row')){const menu=document.createElement('details');menu.className='wb-document-tools';menu.innerHTML='<summary>交付与资料工具</summary>';extra.before(menu);menu.append(extra)}
  panel.addEventListener('click',event=>{const button=event.target.closest('[data-wb-view]');if(!button)return;const preview=button.dataset.wbView==='preview';panel.querySelector('#node-deliverable').hidden=preview;panel.querySelector('#wb-preview').hidden=!preview;field.querySelectorAll('[data-wb-view]').forEach(el=>el.setAttribute('aria-pressed',String(el===button)));update();if(!preview)panel.querySelector('#node-deliverable').focus()},{signal});
  document.addEventListener('keydown',event=>{if(event.key!=='Escape'||document.querySelector('.modal'))return;const open=panel.querySelector('details[open]');if(open){event.preventDefault();open.open=false;open.querySelector('summary').focus()}},{signal});
  document.addEventListener('click',event=>{panel.querySelectorAll('.wb-tools[open]').forEach(menu=>{if(!menu.contains(event.target))menu.open=false})},{signal});
  const footer=panel.querySelector('.node-bottom');
  const measure=()=>{if(!panel.isConnected)return;const rect=panel.getBoundingClientRect();footer.style.left=rect.left+'px';footer.style.width=rect.width+'px';panel.style.paddingBottom=(footer.offsetHeight+24)+'px';document.documentElement.style.setProperty('--wb-footer-height',footer.offsetHeight+'px')};
  observer=new ResizeObserver(measure);observer.observe(panel);observer.observe(footer);window.addEventListener('resize',measure,{signal});measure();update();
 }
 root.StudioWorkbench={markdown,currentReport,mergeDraft,homeSummary,recoveryHint,progressSummary,mount,update,dispose};
 if(typeof module!=='undefined')module.exports={markdown,currentReport,mergeDraft,homeSummary,recoveryHint,progressSummary,safeURL};
})(globalThis);
