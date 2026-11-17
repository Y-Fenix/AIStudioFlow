/* Declarative builder and durable flow runner. Uploaded JSON is never evaluated. */
(function(root){
'use strict';
const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={input:'资料输入',ai:'AI / Skill 任务',checklist:'检查清单',template:'交付模板',review:'人工审核',tool:'工具入口',node:'部门节点',task:'自定义节点',boundary:'手动继续',manual:'人工交付',testing:'测试证据核对',adapter:'部门执行器'};
function make(type,id){const defaults={input:{label:'输入资料',required:true},ai:{label:'AI 整理',prompt:'根据输入整理交付，逐项列出证据与缺口。'},checklist:{label:'质量检查',items:['已核对来源和版本']},template:{label:'交付报告',text:'# 交付报告\n\n{{previous}}'},review:{label:'负责人确认交付与证据'},tool:{label:'外部工具',url:'https://example.com'}};return {id,type,config:{...(defaults[type]||{})}}}
function reorder(items,from,to){const copy=items.slice();if(!Number.isInteger(from)||!Number.isInteger(to)||from<0||from>=copy.length||to<0||to>copy.length)return copy;const [item]=copy.splice(from,1);copy.splice(to>from?to-1:to,0,item);return copy}
function validateDraft(value,types,flow){
 if(value?.schema_version!==1||!Array.isArray(value.blocks)||value.blocks.length>30)throw Error('模板格式不支持');
 const seen=new Set();for(const b of value.blocks){
  if(!b||Object.keys(b).some(k=>!['id','type','config'].includes(k))||typeof b.id!=='string'||!/^[-a-zA-Z0-9_]{1,80}$/.test(b.id)||seen.has(b.id)||!types[b.type]||['node','task'].includes(b.type)&&!flow||!b.config||typeof b.config!=='object'||Array.isArray(b.config))throw Error('积木 ID、类型或属性无效');seen.add(b.id);
  for(const [key,v] of Object.entries(b.config)){const t=types[b.type].fields[key];if(!t||t==='bool'&&typeof v!=='boolean'||t==='list'&&(!Array.isArray(v)||!v.length||v.length>50||v.some(x=>typeof x!=='string'||!x.trim()||x.length>1000))||['text','url'].includes(t)&&(typeof v!=='string'||v.length>16000))throw Error('积木属性格式无效');if(t==='blocks')validateDraft({schema_version:1,blocks:v},types,false);if(t==='url'){const u=new URL(v);if(u.protocol!=='https:'||u.username||u.password)throw Error('工具只接受无凭据 HTTPS 地址')}}
  for(const key of ({ai:['prompt'],template:['text'],checklist:['items'],tool:['url'],node:['node'],task:['blocks']}[b.type]||[]))if(!b.config[key]?.length)throw Error('缺少积木必需属性');
  if(b.type==='template'&&[...b.config.text.matchAll(/{{\s*(.*?)\s*}}/g)].some(m=>!['input','previous'].includes(m[1])))throw Error('模板变量无效');
 }
 return structuredClone(value.blocks);
}
const btn=(label,action,cls='')=>`<button class="${cls}" data-builder="${action}">${escape(label)}</button>`;
const uid=()=> 'b_'+(root.crypto?.randomUUID?.()||Date.now()+'_'+Math.random().toString(36).slice(2)).replaceAll('-','');
const status={queued:'排队中',running:'运行中',waiting_user:'待你操作',completed:'已完成',failed:'失败',interrupted:'运行中断',cancelled:'已取消'};
root.NodeBuilder={
 host:null,data:null,flows:[],templates:[],runs:[],selected:0,dirty:false,mode:'node',department:'product',path:'',timer:null,
 setup(host){this.host=host;root.WorkflowPages?.setup({builder:this,host})},
 async openFlowEditor(flow){
  this.dispose();this.mode='flow';this.flowEditor=true;this.taskEditing=false;this.runtimeOnly=false;this.path=this.host.path();this.department=this.host.department();this.node=this.host.node();this.readOnly=false;
  const collection=await this.host.api(this.path+'/custom-flows');this.types=collection.types;this.flows=collection.items;
  this.data=flow?.id?await this.host.api(this.path+'/custom-flows/'+flow.id):{name:'新建工作流',description:'',revision:0,blocks:[],sources:[]};this.data.types=this.types;
  if(this.data.nodes?.some(n=>!n.permissions?.view||!n.permissions?.edit||!n.permissions?.skill_view))throw Error('部分节点或 Skill 无权查看、编辑；请先联系负责人授权');
  this.templates=(await this.host.api('/api/studios/'+this.host.studio()+'/block-templates?department='+this.department)).items;
  this.runs=[];this.currentRun=null;this.selected=0;this.dirty=false;this.host.dirty(false);this.host.show();
 },
 async startWorkflow(flow,input){
  this.data=flow;this.currentRun=await this.host.api(this.path+'/block-runs',{flow:flow.id,revision:flow.revision,input});
  await this.refreshRuns();return this.currentRun;
 },
 bindRuntime(){
  this.abort?.abort();this.abort=new AbortController();
  document.querySelector('#content')?.addEventListener('click',event=>{
   const button=event.target.closest('[data-builder]');if(!button||button.disabled)return;
   event.stopPropagation();this.action(button.dataset.builder).catch(error=>this.host.toast(error.message));
  },{signal:this.abort.signal});
 },
 async open(mode='node',identity='',runtimeOnly=false){
  if(!this.host.path())throw Error('请先选择项目');if(mode==='flow'){this.dispose();this.mode='flow';this.flowEditor=false;return root.WorkflowPages.open(identity)}this.flowEditor=false;this.runtimeOnly=runtimeOnly;
  this.dispose();const h=this.host;this.mode=mode;this.path=h.path();this.department=h.department();this.busy=false;this.node=h.node();this.data=null;this.currentRun=null;this.dirty=false;this.selected=0;h.dirty(false);
  if(mode==='node'){this.data=await h.api(this.path+'/node-blueprint?node='+encodeURIComponent(this.node));this.data.name=h.nodeName()}
  else{
   const r=await h.api(this.path+'/custom-flows');this.flows=r.items;this.types=r.types;
   this.data=identity?structuredClone(this.flows.find(x=>x.id===identity)):{name:'我的自定义流',revision:0,blocks:[],sources:[]};
  }
  if(mode==='flow')this.data.types=this.types;
  try{this.templates=(await h.api('/api/studios/'+h.studio()+'/block-templates?department='+this.department)).items}catch(e){this.templates=[]}
  this.runs=(await h.api(this.path+'/block-runs')).items;this.currentRun=this.runs.find(r=>mode==='flow'?r.flow_id===this.data.id:r.node===this.node)||null;h.show();this.mount();
 },
 dispose(){clearTimeout(this.timer);this.timer=null;this.abort?.abort();root.WorkflowPages?.dispose()},
 current(){return this.host.path()===this.path&&this.host.isShown()},
 page(){
  if(this.mode==='flow'&&!this.flowEditor)return root.WorkflowPages.page();
  if(!this.data)return '<section class="panel empty-state">正在读取搭建器…</section>';
  const flow=this.mode==='flow',d=this.data,p=this.host.permissions(this.department),nodes=this.host.nodes();this.access=p;this.editable=this.taskEditing?p.flowEdit:flow?(d.id?p.flowEdit:p.flowCreate):p.nodeEdit;
  return `${this.runtimeOnly?`<div class="between builder-workspace-title"><h1>${escape(d.name)}</h1>${btn('编辑积木配置','edit')}</div>`:''}<div class="builder-editor" ${this.runtimeOnly?'hidden':''}><div class="page-heading"><div><div class="eyebrow">${flow?'CUSTOM WORKFLOWS':'NODE BUILDER'}</div><h1>${flow?'自定义流':'搭建节点'}</h1><p>${flow?'拖入任意部门节点，按顺序交付与执行。':'把资料、AI、清单与审核组合成团队节点。'} 配置版本 ${d.revision}${this.dirty?' · 未保存':''}</p></div><div class="row">${flow?btn('返回流程','return-flow'):this.taskEditing?btn('返回流程编辑','return-task'):''}${btn('预览','preview')}${btn('导入 JSON','import')}${!flow&&!this.taskEditing?btn('节点 Skill','skill'):''}${btn('导出 JSON','export')}${btn('保存并应用','save','primary')}</div></div>
  ${flow?`<section class="panel builder-flow-list"><div class="row">${btn('返回工作流列表','return-list')}</div><label>工作流名称<input data-builder-name value="${escape(d.name)}" maxlength="100"></label><label>流程说明<input data-builder-description value="${escape(d.description||'')}" maxlength="1000"></label></section>`:`<div class="builder-node-banner">当前节点：${escape(d.name)} · 保存后可从此处运行，不覆盖原节点交付记录。</div>`}
  <div class="builder-layout" data-editable="${this.editable}"><aside class="panel builder-library"><h2>功能积木</h2><p class="small muted">拖到画布，或点击添加</p>${[...Object.keys(labels).filter(t=>flow?t==='task':!['task','boundary','node','manual','testing','adapter'].includes(t)),...Object.keys(d.types||{}).filter(t=>!flow&&t.includes('.')&&d.types[t].department===this.department)].map(t=>`<div class="builder-palette-item" draggable="true" data-block-type="${t}"><span>${escape(labels[t]||d.types?.[t]?.label||t)}</span>${btn('+','add:'+t)}</div>`).join('')}
   ${flow?`<details open><summary>部门节点</summary>${nodes.map(n=>`<div class="builder-palette-item" draggable="true" data-node-key="${escape(n.id)}"><span><small>${escape(n.department)}</small>${escape(n.name)}</span>${btn('+','node:'+n.id)}</div>`).join('')}</details>`:''}
   <details open><summary>团队模板 · ${escape(this.host.departmentName(this.department))}</summary>${flow?`<label>模板所属部门<select id="builder-template-department">${this.host.departments().map(d=>`<option value="${d.id}" ${d.id===this.department?'selected':''}>${escape(d.title)}</option>`).join('')}</select></label>`:''}<p class="small muted">同工作室同部门共享；结构快照，不包含运行数据</p>${this.templates.filter(t=>flow?t.kind==='flow':t.kind!=='flow').map(t=>`<div class="builder-template"><b>${escape(t.name)}</b><small>v${t.revision} · ${escape(t.author)}</small><div class="row">${btn('添加','template:'+t.id)}${p.templateEdit?btn('新版本','version:'+t.id):''}${p.templateDelete?btn('归档','archive-template:'+t.id):''}</div></div>`).join('')||'<p class="muted small">尚无共享模板</p>'}${p.templateCreate?btn('保存为团队模板','publish'):''}</details>
  </aside><section class="panel builder-canvas" aria-label="节点画布"><h2>${flow?'流程画布':'节点内容'}</h2><p class="small muted">按箭头顺序执行；人工步骤会暂停等待操作</p>${d.blocks.map((b,i)=>`${this.dropzone(i)}<article class="builder-block ${this.selected===i?'selected':''}" data-block-index="${i}" draggable="true" tabindex="0" aria-label="${escape(labels[b.type]||b.type)} ${i+1}"><div class="between"><span class="eyebrow">${String(i+1).padStart(2,'0')} · ${escape(labels[b.type]||b.type)}</span><span class="builder-grip" aria-hidden="true">⠿</span></div><h3>${escape(b.config.label||labels[b.type])}</h3><p>${escape(this.summary(b))}</p><div class="row">${btn('↑','up:'+i)}${btn('↓','down:'+i)}${btn('复制','copy:'+i)}${btn('删除','remove:'+i)}${b.type==='task'?btn('编辑节点内容','edit-task:'+i):''}</div></article><div class="builder-arrow" aria-hidden="true">↓</div>`).join('')}${this.dropzone(d.blocks.length)}${!d.blocks.length?'<div class="builder-empty">将左侧积木拖到这里<br>也可以点击积木右侧 ＋'+btn('使用默认组合','default')+'</div>':''}</section>
   <aside class="panel builder-properties"><h2>积木属性</h2>${this.properties(d.blocks[this.selected])}${d.sources?.length?`<p class="small muted">模板快照：${d.sources.map(x=>escape(x.department+' / '+x.id.slice(0,8)+' v'+x.revision)).join('、')}</p>`:''}<div class="builder-hint">AI 使用平台当前启用的模型。工具入口打开外部页面；所有人工确认都保留。</div></aside></div>
   </div><section class="panel builder-run-panel"><div class="between"><div><h2>运行与交付</h2><p class="small muted">每次运行使用保存后的快照；未保存修改不参与执行。</p></div>${btn('刷新记录','refresh')}</div><div class="field"><label>本次输入 / 来源与版本</label><textarea id="builder-run-input" placeholder="提供真实资料或上游交付"></textarea></div>${btn(flow?'运行工作流':'运行节点','start','primary')}<div class="builder-run-tabs">${this.runTabs()}</div><div id="builder-run-detail">${this.runMarkup()}</div></section><input id="builder-json-file" type="file" accept=".json" hidden>`;
 },
 dropzone(i){return `<div class="builder-drop" data-drop-index="${i}" aria-label="插入位置 ${i+1}"></div>`},
 summary(b){return b.type==='task'?(b.config.blocks?.length||0)+' 个内部积木':b.type==='ai'?b.config.prompt:b.type==='checklist'?(b.config.items||[]).join(' · '):b.type==='template'?b.config.text:b.type==='node'?b.config.node:b.type==='tool'?b.config.url:b.config.required?'必填资料':'等待人工操作'},
 properties(b){if(!b)return '<p class="muted">选择画布中的积木，编辑它的配置。</p>';
  const field=(key,label,value,area=false)=>`<div class="field"><label>${label}</label><${area?'textarea':'input'} data-block-prop="${key}" ${area?'':`value="${escape(value)}"`}>${area?escape(value):''}${area?'</textarea>':''}</div>`;
  let html=field('label','显示名称',b.config.label||'');
  if(b.type==='input')html+=`<label class="builder-check"><input type="checkbox" data-block-prop="required" ${b.config.required?'checked':''}> 必填</label>`;
  if(b.type==='ai')html+=field('prompt','AI 任务指令',b.config.prompt,true)+'<p class="small muted">自动使用当前节点 Skill 快照；在自定义流直接添加的 AI 积木仅使用本条指令。</p>';
  if(b.type==='checklist')html+=field('items','检查项（每行一条，全部勾选后继续）',(b.config.items||[]).join('\n'),true);
  if(b.type==='template')html+=field('text','交付模板',b.config.text,true)+'<p class="small muted">支持 {{input}} 本次输入、{{previous}} 上一步交付</p>';
  if(b.type==='tool')html+=field('url','无凭据 HTTPS 工具地址',b.config.url)+'<p class="small muted">这是外链入口，平台不会假装已调用工具。</p>';
  if(['node','task'].includes(b.type))html+=field('description','节点说明',b.config.description||'',true)+`<label class="builder-check"><input type="checkbox" data-block-prop="auto_next" ${b.config.auto_next?'checked':''}> 完成后自动执行下一节点</label>`;
  if(b.type==='node')html+=`<p>稳定节点 ID：<code>${escape(b.config.node)}</code></p><p class="small muted">运行时固定节点蓝图与 Skill 快照。没有执行器的节点等待人工交付；测试节点核对真实批次。</p>`;
  if(b.type.includes('.')){for(const [key,kind] of Object.entries(this.data.types?.[b.type]?.fields||{})){if(key==='label')continue;if(kind==='bool')html+=`<label class="builder-check"><input type="checkbox" data-block-prop="${key}" ${b.config[key]?'checked':''}>${escape(key)}</label>`;else html+=field(key,key,Array.isArray(b.config[key])?b.config[key].join('\n'):b.config[key]||'',true)}}
  return html;
 },
 runTabs(){return this.runs.filter(r=>this.mode==='flow'?r.flow_id===this.data.id:r.node===this.node).map(r=>{const current=r.id===this.currentRun?.id?this.currentRun:r;return btn((status[current.status]||current.status)+' · '+r.id.slice(0,8),'run:'+r.id)}).join('')},
 runMarkup(group=''){const r=this.currentRun;if(!r)return '<p class="muted">选择运行记录，或启动一次新运行。</p>';const s=r.steps[r.cursor];
  const timeline=r.steps.map((s,i)=>group&&s.group!==group?'':`<div class="builder-run-step ${i===r.cursor?'current':''}"><b>${i+1}. ${escape(s.config.label||labels[s.type]||s.type)}</b><span>${i<r.cursor?'已完成':i===r.cursor?(status[r.status]||r.status):'未开始'}</span>${s.acknowledgement?`<p>操作人：${escape(s.actor)} · ${escape(s.acknowledgement)}</p>`:''}${s.evidence?.length||s.gaps?.length?`<details><summary>证据与缺口</summary><pre>${escape(JSON.stringify({evidence:s.evidence,gaps:s.gaps},null,2))}</pre></details>`:''}${s.quality&&typeof s.quality==='object'?`<details class="builder-quality"><summary>本次交付检查</summary><p class="small muted">结构与来源检查不等于事实核验。</p><dl><dt>输出契约</dt><dd>${escape(s.quality.contract||'未返回')}</dd><dt>结构检查项</dt><dd>${escape(s.quality.sections_checked??'未返回')}</dd><dt>来源引用检查项</dt><dd>${escape(s.quality.source_quotes_checked??'未返回')}</dd><dt>事实核验</dt><dd>${s.quality.fact_checked===true?'执行器报告已核验；仍需人工审阅':'未进行事实核验'}</dd></dl></details>`:''}${s.output?`<details><summary>查看交付</summary><pre>${escape(s.output)}</pre></details>`:''}</div>`).join('');
  let action='';if(!this.readOnly&&r.status==='waiting_user'&&s&&(!group||s.group===group)){
   if(s.type==='checklist')action=`<div id="builder-run-checks">${s.config.items.map((x,i)=>`<label class="builder-check"><input type="checkbox" ${r.draft?.[i]?'checked':''}>${escape(x)}</label>`).join('')}</div>`;
   else action=`<label>${escape(s.type==='testing'?'真实测试批次 ID':s.type==='review'?'审核依据':s.type==='manual'?'人工交付内容':'本步骤输入')}<textarea id="builder-step-value" placeholder="${s.type==='testing'?'先在测试工作台完成对应节点，再填写批次 ID':'填写真实资料或确认依据'}">${escape(typeof r.draft==='string'?r.draft:'')}</textarea></label>`;
   if(s.type==='tool')action=`<p><a href="${escape(s.config.url)}" target="_blank" rel="noopener noreferrer">打开 ${escape(s.config.label||s.config.url)} ↗</a></p>`+action;
   if(s.type==='testing')action=btn('进入测试工作台','open-testing')+action;
   action=s.type==='boundary'?btn('继续下一节点','continue','primary'):action+btn('保存填写进度','save-draft')+btn(s.type==='review'?'人工确认并继续':'保存并继续','submit','primary');
  }
  return `<div class="builder-run-status"><b>${status[r.status]||escape(r.status)}</b><span>步骤 ${Math.min(r.cursor+1,r.steps.length)} / ${r.steps.length}</span><small>${escape(r.model?.model||'当前模型')} · ${escape(r.model?.effort||'默认强度')}</small></div>${r.error?`<p class="builder-error">${escape(r.error)}</p>`:''}${['failed','interrupted'].includes(r.status)?`<p class="small muted">${r.status==='interrupted'?'本次运行已中断；':''}先核对错误、输入、Skill 与模型连接，再手动重试当前步骤。需要修改输入或规则时，保存后启动新运行。</p>`:''}<p class="wb-progress" data-builder-progress ${r.status==='running'&&r.progress&&(!group||s?.group===group)?'':'hidden'}>${escape(root.StudioWorkbench?.progressSummary(r.progress)||'')}</p><div class="builder-run-timeline">${timeline}</div><div class="builder-step-action">${action}</div><div class="row">${!this.readOnly&&(!group||s?.group===group)&&['failed','interrupted'].includes(r.status)?btn('重试当前步骤','retry'):''}${!this.readOnly&&!['completed','cancelled'].includes(r.status)?btn('取消运行','cancel'):''}</div>${(!group&&r.output)?`<details ${r.status==='completed'?'open':''}><summary>最终 / 最近交付</summary><pre class="builder-result">${escape(r.output)}</pre>${btn('导出交付','export-result')}${r.status==='completed'&&r.node?btn('保存为节点待审核交付','publish-result','primary')+btn('审阅节点交付','review-deliverable'):''}</details>`:''}`;
 },
 mount(){if(this.mode==='flow'&&!this.flowEditor){root.WorkflowPages.mount();this.bindRuntime();this.schedule();return}this.abort?.abort();this.abort=new AbortController();const el=document.querySelector('#content');if(!el||!this.current())return;const signal=this.abort.signal;
  const runDetail=el.querySelector('#builder-run-detail');if(runDetail&&this.currentRun){runDetail.dataset.run=this.currentRun.id;runDetail.dataset.cursor=String(this.currentRun.cursor);runDetail.dataset.status=this.currentRun.status}const p=this.access,flow=this.mode==='flow';for(const b of el.querySelectorAll('[data-builder]')){const a=b.dataset.builder.split(':')[0];let reason='';if(['save','add','node','default','up','down','copy','remove','import','template'].includes(a)&&!this.editable)reason='需要节点编辑或工作流编辑权限';if(['add','node','default','copy','template'].includes(a)&&!flow&&!this.taskEditing&&!p.contentCreate)reason='需要内容新增权限';if(a==='remove'&&!flow&&!this.taskEditing&&!p.contentDelete)reason='需要内容删除权限';if(a==='start'&&!(flow?p.flowExecute:p.nodeExecute))reason='需要执行权限';if(a==='archive-flow'&&!p.flowDelete)reason='需要工作流删除权限';if(reason){b.disabled=true;b.title=reason}}for(const field of el.querySelectorAll('[data-block-prop],[data-builder-name]'))field.disabled=!this.editable;
  el.querySelector('#builder-template-department')?.addEventListener('change',async e=>{try{this.department=e.target.value;this.templates=(await this.host.api('/api/studios/'+this.host.studio()+'/block-templates?department='+this.department)).items;this.redraw()}catch(x){this.host.toast(x.message)}},{signal});
  el.addEventListener('click',e=>{const b=e.target.closest('[data-builder]');if(b){e.stopPropagation();this.action(b.dataset.builder).catch(x=>this.host.toast(x.message));return}const card=e.target.closest('[data-block-index]');if(card){this.selected=Number(card.dataset.blockIndex);this.redraw()}},{signal});
  el.addEventListener('input',e=>{const key=e.target.dataset.blockProp;if(key){const b=this.data.blocks[this.selected];b.config[key]=e.target.type==='checkbox'?e.target.checked:(key==='items'||this.data.types?.[b.type]?.fields[key]==='list')?e.target.value.split('\n').filter(Boolean):e.target.value;this.change();const card=el.querySelector(`[data-block-index="${this.selected}"]`);card.querySelector('h3').textContent=b.config.label||labels[b.type];card.querySelector('p').textContent=this.summary(b)}if(e.target.matches('[data-builder-description]')){this.data.description=e.target.value;this.change()}if(e.target.matches('[data-builder-name]')){this.data.name=e.target.value;this.change()}},{signal});
  el.addEventListener('keydown',e=>{const card=e.target.closest('[data-block-index]');if(card&&e.target===card&&(e.key==='Enter'||e.key===' ')){e.preventDefault();this.selected=Number(card.dataset.blockIndex);this.redraw()}},{signal});
  el.addEventListener('dragstart',e=>{const item=e.target.closest('[data-block-type],[data-block-index],[data-node-key]');if(!item||!this.editable)return;e.dataTransfer.setData('application/studioflow-block',JSON.stringify(item.dataset));e.dataTransfer.effectAllowed='copyMove'},{signal});
  el.addEventListener('dragover',e=>{const zone=e.target.closest('[data-drop-index]');if(zone){e.preventDefault();zone.classList.add('over')}},{signal});
  el.addEventListener('dragleave',e=>e.target.closest('[data-drop-index]')?.classList.remove('over'),{signal});
  el.addEventListener('drop',e=>{const zone=e.target.closest('[data-drop-index]');if(!zone||!this.editable)return;e.preventDefault();zone.classList.remove('over');try{const item=JSON.parse(e.dataTransfer.getData('application/studioflow-block')),index=Number(zone.dataset.dropIndex);if(item.blockIndex!==undefined)this.data.blocks=reorder(this.data.blocks,Number(item.blockIndex),index);else this.insert(item.nodeKey?{id:uid(),type:'node',config:{node:item.nodeKey,label:this.host.nodes().find(n=>n.id===item.nodeKey)?.name||item.nodeKey,auto_next:false}}:make(item.blockType,uid()),index);this.change();this.redraw()}catch(x){this.host.toast('拖入的数据无效')}},{signal});
  el.querySelector('#builder-json-file')?.addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>200000)throw Error('模板最大200KB');const v=JSON.parse(await file.text());this.data.blocks=validateDraft(v,this.data.types,this.mode==='flow');this.data.sources=[];this.change();this.redraw()}catch(x){this.host.toast(x.message)}},{signal});this.schedule();
 },
 change(){this.dirty=true;this.host.dirty(true)},
 redraw(){this.host.render();this.mount()},
 insert(b,index=this.data.blocks.length){if(this.data.blocks.length>=30)throw Error('最多30个积木');if(!this.editable||(this.mode!=='flow'&&!this.taskEditing&&!this.access.contentCreate))throw Error('没有新增内容权限');this.data.blocks.splice(index,0,b);this.selected=index;this.change()},
 async action(code){
  if(this.busy)return;
  this.busy=true;
  const runtimeAction=['submit','save-draft','retry','cancel','continue','publish-result'].includes(code);
  const controls=runtimeAction?[...(root.document?.querySelectorAll('#builder-run-detail [data-builder]')||[])].map(button=>({button,disabled:button.disabled,label:button.textContent,busy:button.getAttribute('aria-busy')})):[];
  for(const {button} of controls){button.disabled=true;if(button.dataset.builder===code){button.setAttribute('aria-busy','true');button.textContent='处理中…'}}
  try{return await this.perform(code)}finally{
   this.busy=false;
   for(const {button,disabled,label,busy} of controls){if(!button.isConnected)continue;button.disabled=disabled;button.textContent=label;if(busy===null)button.removeAttribute('aria-busy');else button.setAttribute('aria-busy',busy)}
  }
 },
 async perform(code){const [a,...args]=code.split(':'),arg=args.join(':'),i=Number(arg),h=this.host,api=h.api;
  if(!this.current())return;
  if(a==='return-task'){if(this.dirty&&!confirm('放弃节点内部未保存的修改？'))return;this.data=this.taskParent;this.mode='flow';this.taskEditing=false;this.dirty=false;this.host.dirty(false);this.redraw();return}
  else if(a==='return-flow'||a==='return-list'){if(this.dirty&&!confirm('放弃未保存的配置？'))return;return this.open('flow',a==='return-flow'?this.data.id||'':'')}
  else if(a==='edit-task'){this.taskParent=this.data;this.taskIndex=i;this.data={name:this.taskParent.blocks[i].config.label||'自定义节点',blocks:structuredClone(this.taskParent.blocks[i].config.blocks),revision:this.taskParent.revision,types:this.types};this.taskEditing=true;this.mode='task';this.dirty=false;this.host.dirty(false);this.redraw()}
  else if(a==='edit'){this.runtimeOnly=false;this.redraw()}
  else if(a==='open-testing'){const s=this.currentRun?.steps[this.currentRun.cursor];if(s?.node)this.host.openTesting(s.node)}
  else if(a==='skill'){await h.openSkill(this.node)}
  else if(a==='default'){for(const type of ['input','ai','checklist','template','review'])this.insert(make(type,uid()));this.redraw()}
  else if(a==='add'){this.insert(arg==='task'?{id:uid(),type:'task',config:{label:'自定义节点',auto_next:false,blocks:[make('input',uid()),make('ai',uid()),make('review',uid())]}}:make(arg,uid()));this.redraw()}
  else if(a==='node'){const n=h.nodes().find(n=>n.id===arg);this.insert({id:uid(),type:'node',config:{node:arg,label:n?.name||arg,auto_next:false}});this.redraw()}
  else if(a==='up'||a==='down'){this.data.blocks=reorder(this.data.blocks,i,a==='up'?i-1:i+2);this.selected=a==='up'?Math.max(0,i-1):Math.min(this.data.blocks.length-1,i+1);this.change();this.redraw()}
  else if(a==='copy'){const b=structuredClone(this.data.blocks[i]);b.id=uid();this.insert(b,i+1);this.redraw()}
  else if(a==='remove'){this.data.blocks.splice(i,1);this.selected=Math.max(0,Math.min(this.selected,this.data.blocks.length-1));this.change();this.redraw()}
  else if(a==='preview')h.modal('节点预览',this.data.blocks.map(b=>`<section class="builder-preview"><h3>${escape(b.config.label||labels[b.type])}</h3>${b.type==='input'?'<textarea placeholder="资料输入"></textarea>':b.type==='checklist'?b.config.items.map(x=>`<label class="builder-check"><input type="checkbox">${escape(x)}</label>`).join(''):`<pre>${escape(this.summary(b))}</pre>`}</section>`).join('')||'<p>暂无积木</p>');
  else if(a==='save'){if(this.taskEditing){this.taskParent.blocks[this.taskIndex].config.blocks=structuredClone(this.data.blocks);this.data=this.taskParent;this.mode='flow';this.taskEditing=false;this.change();this.redraw();return}this.busy=true;try{const v=this.mode==='flow'?await api(this.path+'/custom-flows',{id:this.data.id,revision:this.data.revision,name:this.data.name,description:this.data.description||'',blocks:this.data.blocks,sources:this.data.sources||[]}):await api(this.path+'/node-blueprint?node='+encodeURIComponent(this.node),{revision:this.data.revision,blocks:this.data.blocks,sources:this.data.sources||[]});this.data={...this.data,...v};this.dirty=false;h.dirty(false);if(this.mode==='flow'){this.flowEditor=false;await root.WorkflowPages.open(v.id);h.toast('流程已保存，下一次运行生效');return}this.redraw();h.toast('已保存并应用；尚未运行')}finally{this.busy=false}}
  else if(a==='new'||a==='load'){if(this.dirty&&!confirm('放弃未保存的配置？'))return;await this.open('flow',a==='load'?arg:'')}
  else if(a==='export')this.download({schema_version:1,kind:this.mode,blocks:this.data.blocks},this.data.name+'.json');
  else if(a==='import')document.querySelector('#builder-json-file').click();
  else if(a==='publish'||a==='version'){const title=prompt('团队模板名称',a==='version'?this.templates.find(t=>t.id===arg)?.name:this.data.name);if(!title)return;const old=this.templates.find(t=>t.id===arg);await api('/api/studios/'+h.studio()+'/block-templates',{id:a==='version'?arg:undefined,kind:this.mode,department:this.department,name:title,revision:old?.revision||0,blocks:this.data.blocks,sources:this.data.sources||[]});this.templates=(await api('/api/studios/'+h.studio()+'/block-templates?department='+this.department)).items;this.redraw();h.toast('模板已共享给本部门')}
  else if(a==='template'){const t=await api('/api/studios/'+h.studio()+'/block-templates?department='+this.department+'&id='+arg);if(this.data.blocks.length+t.blocks.length>30)throw Error('组合超过30块');if(t.kind==='flow'&&this.mode!=='flow')throw Error('流程模板只能添加到自定义流');this.data.sources=[...(this.data.sources||[]),{id:t.id,department:t.department,revision:t.revision}];t.blocks.forEach(b=>{b.id=uid();this.insert(b)});this.redraw()}
  else if(a==='archive-template'){const t=this.templates.find(t=>t.id===arg);if(!confirm('归档共享模板？已有节点不受影响。'))return;await api('/api/studios/'+h.studio()+'/block-templates',{action:'archive',id:arg,department:this.department,revision:t.revision});this.templates=this.templates.filter(t=>t.id!==arg);this.redraw()}
  else if(a==='archive-flow'){if(!confirm('归档工作流？历史运行保留。'))return;await api(this.path+'/custom-flows',{action:'archive',id:this.data.id,revision:this.data.revision});await this.open('flow')}
  else if(a==='start'){if(this.taskEditing)throw Error('请先保存节点内容与流程，再从流程首页运行');if(this.dirty)throw Error('请先保存配置');if(this.mode==='flow'&&!this.data.id)throw Error('请先保存工作流');const input=document.querySelector('#builder-run-input').value;this.currentRun=await api(this.path+'/block-runs',{[this.mode==='flow'?'flow':'node']:this.mode==='flow'?this.data.id:this.node,revision:this.data.revision,input});await this.refreshRuns();this.updateRun()}
  else if(a==='run'){this.currentRun=await api(this.path+'/block-runs/'+arg);this.updateRun()}
  else if(a==='refresh'){await this.refreshRuns();if(this.currentRun)this.currentRun=await api(this.path+'/block-runs/'+this.currentRun.id);this.updateRun()}
  else if(['submit','save-draft','retry','cancel','continue'].includes(a)){const r=this.currentRun;if(!r)return;let value;if(a==='submit'||a==='save-draft'){const step=r.steps[r.cursor];value=step.type==='checklist'?[...document.querySelectorAll('#builder-run-checks input')].map(x=>x.checked):document.querySelector('#builder-step-value')?.value||''}this.currentRun=await api(this.path+'/block-runs/'+r.id,{revision:r.revision,action:a,value});this.updateRun()}
  else if(a==='review-deliverable'){await h.reviewDeliverable(this.node)}
  else if(a==='publish-result'){await api(this.path+'/block-runs/'+this.currentRun.id+'/publish',{revision:this.currentRun.revision});h.toast('已保存为待审核交付');await h.reviewDeliverable(this.node)}
  else if(a==='export-result')this.download(this.currentRun.output,this.data.name+'.md');
 },
 async refreshRuns(){this.runs=(await this.host.api(this.path+'/block-runs'+(this.mode==='flow'&&this.data?.id?'?flow='+this.data.id:''))).items},
 updateRun(){if(this.mode==='flow'&&!this.flowEditor){root.WorkflowPages.updateRun(this.currentRun);this.schedule();return}const target=document.querySelector('#builder-run-detail');if(target){
  const field=target.querySelector('#builder-step-value'),checks=[...target.querySelectorAll('#builder-run-checks input')],run=this.currentRun;
  const sameStep=target.dataset.run===run?.id&&target.dataset.cursor===String(run?.cursor),draft=sameStep&&field?{value:field.value,start:field.selectionStart,end:field.selectionEnd,focus:document.activeElement===field,scroll:field.scrollTop}:null,checked=sameStep?checks.map(x=>x.checked):null;
  if(sameStep&&target.dataset.status==='waiting_user'&&run?.status==='waiting_user'&&(field||checks.length)){this.schedule();return}
  const top=target.scrollTop;target.innerHTML=this.runMarkup();target.dataset.run=run?.id||'';target.dataset.cursor=String(run?.cursor);target.dataset.status=run?.status||'';
  const next=target.querySelector('#builder-step-value');if(draft&&next){next.value=draft.value;next.setSelectionRange(draft.start,draft.end);next.scrollTop=draft.scroll;if(draft.focus)next.focus({preventScroll:true})}
  if(checked)target.querySelectorAll('#builder-run-checks input').forEach((el,i)=>{el.checked=checked[i]??el.checked});target.scrollTop=top;
 }const tabs=document.querySelector('.builder-run-tabs');if(tabs)tabs.innerHTML=this.runTabs();this.schedule()},
 schedule(){clearTimeout(this.timer);if(!this.current()||!this.currentRun||!['queued','running'].includes(this.currentRun.status))return;const id=this.currentRun.id,path=this.path;this.timer=setTimeout(async()=>{try{const r=await this.host.api(path+'/block-runs/'+id);if(this.current()&&this.path===path&&this.currentRun?.id===id){this.currentRun=r;this.updateRun()}}catch(e){if(this.current()&&this.path===path&&this.currentRun?.id===id){this.host.toast(e.message);this.schedule()}}},900)},
 download(value,name){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([typeof value==='string'?value:JSON.stringify(value,null,2)],{type:typeof value==='string'?'text/markdown':'application/json'}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
};
if(typeof module!=='undefined')module.exports={escape,make,reorder,validateDraft};
})(globalThis);
