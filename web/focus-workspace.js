/* FOCUS layout enhancement. Keeps existing fields, permissions and operation handlers. */
'use strict';
const FocusWorkspace=(()=>{
 const states=new Map(),pendingProgress=new Set();let active=null;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function capture(){
  if(!active)return;
  const {key,body,dialog,section}=active;
  const state=states.get(key)||{};
  state.scroll=body.scrollTop;state.drawer=dialog.open&&!dialog.classList.contains('is-closing')?section:null;state.diagnosticOpen=!!body.querySelector('.focus-operation[open]');
  state.drawerScroll=dialog.querySelector('.focus-drawer-body')?.scrollTop||0;
  const focus=document.activeElement;
  state.focus=dialog.contains(focus)?(focus.id?{id:focus.id}:focus.tagName==='TEXTAREA'?{textarea:true,start:focus.selectionStart,end:focus.selectionEnd}:null):null;
  states.set(key,state);if(dialog.open)dialog.close();active=null;
 }
 function mountTesting({key,stage,cases,sources,review,hasOutput,jobStatus,jobLabel,job,automation:automationEnabled,duration}){
  const panel=document.querySelector('.qa-workspace-panel'),columns=document.querySelector('.columns');
  if(!panel||!columns)return;
  document.body.classList.add('focus-testing');
  const selector=document.querySelector('.task-selector'),automation=document.querySelector('.qa-automation-bar');
  if(selector&&automation){selector.append(automation);automation.querySelector('.small')?.setAttribute('title',automation.querySelector('.small').textContent);}
  const evidence=document.querySelector('#workflow-insights');
  if(evidence)panel.querySelector(':scope > .panelbody').append(evidence);

  const body=panel.querySelector(':scope > .panelbody'),head=panel.querySelector('.workspace-head');
  const state=states.get(key)||{tab:hasOutput?'cases':'sources',scroll:0};states.set(key,state);
  if(pendingProgress.delete(key)&&job)state.drawer='progress';
  const progress=job&&(['queued','running','failed','interrupted'].includes(job.status)||(job.status==='completed'&&state.drawer==='progress'))?QA_progressModel(job,{now:Date.now()/1000,automation:automationEnabled,duration,sources}):null;
  let progressButton=null;
  if(progress){progressButton=document.createElement('button');progressButton.type='button';progressButton.id='focus-progress-trigger';progressButton.className='focus-progress-bar '+(job.status==='failed'||job.status==='interrupted'?'is-failed':'');progressButton.dataset.focusOpen='progress';progressButton.innerHTML=`<span class="focus-progress-dot"></span><strong>${esc(progress.summary)}</strong><span class="focus-progress-phase">${esc(progress.phase)}</span><span class="focus-progress-link">查看任务详情 →</span>`;columns.before(progressButton);}
  const tools=document.createElement('div');tools.className='focus-utilities';tools.innerHTML='<button type="button" data-focus-open="assistant">节点助手</button><button type="button" data-focus-open="logs">操作日志</button>';
  head.append(tools);
  if(stage===0){
   if(!hasOutput){
    for(const [id,text] of [['cases','尚无测试用例，请先导入需求并生成。'],['review','尚无待确认问题；生成用例后查看范围缺口。']]){
     const empty=document.createElement('section');empty.dataset.focusPane=id;empty.className='focus-empty';empty.textContent=text;body.append(empty);
    }
   }
   panel.classList.add('focus-case-layout');
   const tabs=document.createElement('div');tabs.className='focus-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','用例工作区');
   tabs.innerHTML=[['cases','测试用例',cases],['sources','需求来源',sources],['review','待确认',review]].map(([id,label,n])=>`<button type="button" role="tab" id="focus-tab-${id}" aria-controls="focus-pane-${id}" data-focus-tab="${id}">${label} <span>${n}</span></button>`).join('');
   head.querySelector('h2').after(tabs);
   const select=(id,scroll=true)=>{
    const old=state.tab;state.tab=id;
    tabs.querySelectorAll('[role=tab]').forEach(b=>{const selected=b.dataset.focusTab===id;b.setAttribute('aria-selected',selected);b.tabIndex=selected?0:-1;});
    body.querySelectorAll('[data-focus-pane]').forEach(p=>{p.hidden=p.dataset.focusPane!==id;p.setAttribute('role','tabpanel');p.setAttribute('aria-labelledby','focus-tab-'+p.dataset.focusPane);p.id='focus-pane-'+p.dataset.focusPane});
    const section=body.querySelector('[data-section="'+(id==='review'?'review':'cases')+'"]');if(section)section.open=true;
    if(scroll&&old!==id)body.scrollTop=0;
   };
   tabs.onclick=e=>{const b=e.target.closest('[data-focus-tab]');if(b)select(b.dataset.focusTab)};
   tabs.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const list=[...tabs.querySelectorAll('button')],i=list.indexOf(document.activeElement),n=e.key==='Home'?0:e.key==='End'?list.length-1:(i+(e.key==='ArrowRight'?1:-1)+list.length)%list.length;select(list[n].dataset.focusTab);list[n].focus()};
   select(state.tab,false);
  }
  const status=body.querySelector(':scope > .operation-status');
  if(status){
   const failure=jobStatus==='failed'||jobStatus==='interrupted';
   const button=document.createElement('button');button.type='button';button.dataset.focusOpen='diagnostics';
   button.className='focus-job-status'+(failure?' focus-failure':'');button.textContent='运行详情';
   button.title=jobLabel;button.setAttribute('aria-label','运行详情');
   tools.prepend(button);
  }
  const summary=body.querySelector('.focus-coverage-summary'),caseTools=body.querySelector('.focus-case-tools');
  if(summary&&caseTools){
   const scope=summary.querySelector('p');
   if(scope){const details=document.createElement('details');details.className='focus-scope';details.innerHTML='<summary>范围说明</summary>';details.append(scope);summary.append(details);}
   caseTools.prepend(summary);
  }
  const log=document.querySelector('.operation-log'),memory=document.querySelector('.node-memory');
  const dialog=document.createElement('dialog');dialog.className='focus-drawer';dialog.setAttribute('aria-labelledby','focus-drawer-title');
  dialog.innerHTML='<div class="focus-drawer-head"><div><span class="focus-kicker">WORKSPACE</span><h2 id="focus-drawer-title"></h2></div><button type="button" data-focus-close aria-label="关闭侧栏">关闭 ×</button></div><div class="focus-drawer-body"></div>';
  const content=dialog.querySelector('.focus-drawer-body');
  for(const [name,el] of [['logs',log],['assistant',memory],['diagnostics',status]])if(el){const section=document.createElement('section');section.dataset.focusDrawer=name;section.hidden=true;section.append(el);content.append(section)}
  if(progress){const section=document.createElement('section');section.dataset.focusDrawer='progress';section.hidden=true;section.className='focus-progress-detail';section.innerHTML=`<div class="focus-progress-heading"><h3>${esc(progress.title)}</h3><span class="focus-progress-badge"><i class="focus-progress-dot"></i>${esc(progress.phase)}</span></div><div class="focus-progress-metrics"><div><strong>${esc(progress.duration||'暂无')}</strong><span>任务累计（含排队）</span></div><div><strong class="focus-activity">${esc(progress.response)}</strong><span>活动状态</span></div></div><div class="focus-progress-stages">${progress.stages.map((s,i)=>`<div class="focus-progress-stage is-${esc(s.state)}"><span class="focus-stage-number">${s.state==='done'?'✓':i+1}</span><div><strong>${esc(s.label)}</strong><p>${esc(s.detail)}</p></div></div>`).join('')}</div><div class="focus-progress-next"><strong>${['queued','running'].includes(progress.status)?'当前无需操作':'接下来'}</strong><p>${esc(progress.action)}</p></div>${progress.source?`<div class="focus-progress-source"><strong>当前来源</strong><p>${esc(progress.source)}</p></div>`:''}${status?'<button type="button" id="focus-progress-diagnostics" data-focus-switch="diagnostics">查看运行详情 →</button>':''}`;content.append(section)}
  panel.append(dialog);
  let trigger=null;
  const close=()=>{if(dialog.classList.contains('is-closing'))return;state.drawer=null;if(!dialog.open)return;const finish=()=>{if(dialog.open)dialog.close();dialog.classList.remove('is-closing');trigger?.focus({preventScroll:true})};if(matchMedia('(prefers-reduced-motion: reduce)').matches){finish();return}dialog.classList.add('is-closing');setTimeout(finish,180)};
  const show=(name,restore=false)=>{
   trigger=document.querySelector('[data-focus-open="'+name+'"]')||trigger;active.section=name;state.drawer=name;
   content.querySelectorAll('[data-focus-drawer]').forEach(s=>s.hidden=s.dataset.focusDrawer!==name);
   dialog.querySelector('h2').textContent=name==='logs'?'操作日志':name==='diagnostics'?'运行详情':name==='progress'?'当前任务':'节点助手';
   if(memory&&name==='assistant')memory.open=true;
   if(!dialog.open)dialog.showModal();content.scrollTop=restore?state.drawerScroll||0:0;
   if(restore&&state.focus){const f=state.focus;const el=f.id?document.getElementById(f.id):dialog.querySelector('textarea');if(el){el.focus({preventScroll:true});if(f.textarea)el.setSelectionRange(f.start,f.end)}}
  };
  tools.onclick=e=>{const b=e.target.closest('[data-focus-open]');if(b)show(b.dataset.focusOpen)};
  if(progressButton)progressButton.onclick=()=>show('progress');
  dialog.querySelector('[data-focus-close]').onclick=close;
  dialog.addEventListener('cancel',e=>{e.preventDefault();close()});
  dialog.onclick=e=>{const switcher=e.target.closest('[data-focus-switch]');if(switcher){show(switcher.dataset.focusSwitch);return}if(e.target!==dialog)return;const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close()};
  active={key,body,dialog,section:null};body.scrollTop=state.scroll||0;
  if(state.drawer)show(state.drawer,true);
 }
 function requestProgress(key){pendingProgress.add(key)}
 return {capture,mountTesting,requestProgress};
})();
