'use strict';
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths={grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',layers:'m12 3 10 5-10 5L2 8z M2 12l10 5 10-5 M2 16l10 5 10-5',arrow:'M4 12h16 m-6-6 6 6-6 6',chevron:'m9 5 7 7-7 7',down:'m6 9 6 6 6-6',menu:'M4 6h16 M4 12h16 M4 18h16',close:'m6 6 12 12 M6 18 18 6',plus:'M12 4v16 M4 12h16',search:'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',target:'M21 12a9 9 0 1 1-9-9 M12 8a4 4 0 1 0 4 4 M12 12l9-9 M16 3h5v5',brush:'m14 4 6 6-8 8-6-6z M6 12 3 21l9-3 M13 5l3-3 6 6-3 3',code:'m8 6-6 6 6 6 m8-12 6 6-6 6 M14 3l-4 18',shield:'m12 2 9 4v6c0 6-9 10-9 10S3 18 3 12V6z m-4 10 3 3 5-6',chart:'M4 3v18h17 M8 16l4-5 4 2 5-8',file:'M14 2H5v20h14V7z M14 2v6h5 M8 12h8 M8 16h6',folder:'M3 5h7l2 3h9v13H3z',spark:'m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3z',settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3l1-1h4l1 3 3 1 3 2-1 3v3l1 3-3 2-3 1-1 2h-4l-1-3-3-1-3-2 1-3v-3L3 8l3-2 3-1z',download:'M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5',upload:'M12 16V3 m-5 5 5-5 5 5 M4 16v5h16v-5',clock:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 7v6l4 2',check:'m5 12 4 4L19 6',link:'m10 13 4-4 M8 16l-2 2a3.5 3.5 0 0 1-5-5l5-5a3.5 3.5 0 0 1 5 0 M16 8l2-2a3.5 3.5 0 0 1 5 5l-5 5a3.5 3.5 0 0 1-5 0',play:'m8 4 13 8-13 8z',book:'M3 3h7l2 2 2-2h7v17h-7l-2 2-2-2H3z M12 5v17',info:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 11v6 M12 7v1',bell:'M5 16h14l-2-3V8a5 5 0 0 0-10 0v5z M10 20h4',coins:'M20 7c0 3-16 3-16 0s16-3 16 0 M4 7v5c0 3 16 3 16 0V7 M4 12v5c0 3 16 3 16 0v-5',people:'M15 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0 M3 21v-4c0-5 16-5 16 0v4 M18 3a4 4 0 0 1 0 8 M21 21v-4c0-2-1-3-3-4',flag:'M5 22V3c5-5 9 5 15 0v11c-6 5-10-5-15 0',refresh:'M20 7a9 9 0 1 0 1 9 M20 2v6h-6'};
function icon(name,extra=''){return `<svg class="icon ${extra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||paths.layers}"/></svg>`}
const button=(label,action,cls='',ico='')=>`<button class="${cls}" data-action="${action}">${ico?icon(ico):''}${label}</button>`;
const tag=(t,c='')=>`<span class="tag ${c}">${t}</span>`;
function heroArt(){return `<div class="hero-art" aria-hidden="true"><div class="orbit"></div><div class="orbit second"></div><div class="art-card"><div class="eyebrow" style="font-size:7px">IDEA → PRODUCT</div><div class="art-square">${icon('target')}</div><div class="art-line"></div><div class="art-line" style="width:90%"></div><div class="art-line" style="width:50%"></div></div><div class="art-card front"><div style="font-size:8px;letter-spacing:1px">READY TO BUILD</div><div class="art-square">${icon('layers')}</div><div class="art-line" style="width:85%"></div><div class="art-line" style="width:65%"></div></div><div class="art-badge">${icon('spark','small-icon')} 人的判断 × Agent 的执行</div></div>`}
const state={catalog:null,studios:[],studio:null,project:null,prefs:null,summary:{nodes:[],tasks:[]},
 view:'overview',dept:'product',node:0,workspace:null,departmentJob:null,jobPollTimer:null,modal:null,dirty:false,loading:false,saving:false,
 collapsed:localStorage.getItem('studioflow-collapsed')==='true',model:null,skills:{},skillFilter:'all',capabilities:null,session:null,integrations:[],departmentUI:{},departmentUIWarnings:new Set()};
const statusText={not_started:'未开始',draft:'草稿',waiting_user:'待你审核',approved:'已确认',rejected:'已退回',completed:'已结束',cancelled:'已取消'};
const tone=d=>`--dept:${d.color};--tint:${d.tint}`;
const departments=()=>state.projectCatalog?.departments||state.catalog?.departments||[];
const catalogKey=(d,i)=>ProjectNodeKeys.key(d,i);
const legacyTestingNode=()=>ProjectNodeKeys.testingStage(nodeKey())!==null;
function nodeManagementButton(){const c=state.capabilities?.node_management?.[state.dept];return state.project&&(c&&Object.values(c).some(Boolean)||department()?.nodes.some((_,i)=>state.capabilities?.nodes[catalogKey(department(),i)]?.delete))?button('管理节点','manage-nodes','','settings'):''}
const department=()=>departments().find(d=>d.id===state.dept);
const nodeKey=()=>catalogKey(department(),state.node);
const root=()=>'/api/studios/'+state.studio.id+'/projects/'+state.project.id;
const heading=(title,desc,extra='',label='')=>`<div class="page-heading"><div>${label?`<div class="eyebrow">${esc(label)}</div>`:''}<h1>${esc(title)}</h1><p>${esc(desc)}</p></div>${extra}</div>`;
const continuationUI=NodeContinuationUI.create({api,onError:message=>toast(message),onUpdate:updateContinuationLogs,onChanged:context=>{
 const frame=document.querySelector('#testing-frame');frame?.contentWindow.postMessage({type:'studioflow:continuation-update',path:context.path},location.origin);
 toast('自动继续设置已保存；不补跑历史节点');
}});
function updateContinuationLogs(context){
 if(state.view!=='department'||!state.workspace||!state.project||context.path!==root()||context.department!==state.dept)return;
 const el=document.querySelector('.log-body');if(!el)return;
 const base=state.workspace.events,extra=context.events.filter(e=>e.node===nodeKey()&&!base.some(b=>b.action===e.action&&b.detail===e.detail&&b.created_at===e.created_at));
 const html=[...base,...extra].sort((a,b)=>a.created_at.localeCompare(b.created_at)).map(event=>`<div class="log-entry"><time>${beijing(event.created_at)}</time>${esc(event.detail)}</div>`).join('')||'<div class="log-entry">当前节点暂无操作记录。</div>';
 if(el.innerHTML!==html){const top=el.scrollTop;el.innerHTML=html;el.scrollTop=top}
}
function continuationBetween(d,index){return index<d.nodes.length-1?continuationUI.render(catalogKey(d,index),catalogKey(d,index+1)):''}
async function loadDepartmentUI(id){
 if(Object.hasOwn(state.departmentUI,id))return state.departmentUI[id];
 const d=departments().find(item=>item.id===id);if(d?.frontend?.entry!=='ui.js'){state.departmentUI[id]=null;return null}
 try{const loaded=await import(`/departments/${encodeURIComponent(id)}/ui.js`),ui=loaded.default;if(!ui||typeof ui!=='object'||['renderHome','renderWorkspace','mountHome','mountWorkspace'].some(key=>ui[key]!==undefined&&typeof ui[key]!=='function'))throw Error('模块导出格式无效');state.departmentUI[id]=ui;return ui}
 catch(error){state.departmentUI[id]=null;if(!state.departmentUIWarnings.has(id)){state.departmentUIWarnings.add(id);console.error('部门 UI 模块加载失败',id,error);toast(departments().find(item=>item.id===id)?.title+'前端模块加载失败，已使用公共工作区')}return null}
}
function departmentExtension(slot,d,index=state.node,workspace=state.workspace){
 const ui=state.departmentUI[d?.id],render=ui?.[slot];if(typeof render!=='function')return '';
 const context=DepartmentUIContract.createContext({department:d,studio:state.studio,project:state.project,nodeIndex:index,workspace});
 try{const markup=DepartmentUIContract.render(ui,slot,context);return markup?`<section class="panel department-owned-slot ${slot==='renderHome'?'home-module-slot':''}" data-department="${esc(d.id)}" data-department-slot="${slot}">${markup}</section>`:''}
 catch(error){console.error('部门 UI 渲染失败',d.id,slot,error);return ''}
}
let disposeDepartmentUI=()=>{};
function mountDepartmentUI(){
 if(!['home','department'].includes(state.view))return;
 const d=department(),home=state.view==='home',slot=home?'Home':'Workspace';
 const element=$(`[data-department-slot="render${slot}"]`);
 if(!element)return;
 const sequence=navSequence,projectId=state.project?.id,studioId=state.studio?.id;
 const context=DepartmentUIContract.createContext({department:d,studio:state.studio,project:state.project,nodeIndex:home?0:state.node,workspace:home?null:state.workspace});
 disposeDepartmentUI=DepartmentUIContract.mount(state.departmentUI[d.id],'mount'+slot,{
  element,context,notify:toast,
  isCurrent:()=>element.isConnected&&navSequence===sequence&&state.dept===d.id&&state.view===(home?'home':'department')&&state.project?.id===projectId&&state.studio?.id===studioId,
  readDraft:home?undefined:()=>({inputs:$('#node-inputs').value,deliverable:$('#node-deliverable').value}),
  updateDraft:home?undefined:patch=>{
   if(state.saving||state.loading)throw Error('正在保存或切换节点，请稍后再改草稿');
   if(!state.capabilities?.nodes[nodeKey()]?.edit)throw Error('无此节点编辑权限');
   for(const [key,value] of Object.entries(patch))$(key==='inputs'?'#node-inputs':'#node-deliverable').value=value;
   markDirty();
  },
  onError:error=>{console.error('部门 UI 交互失败',d.id,error);toast(d.title+'交互模块异常，公共工作区仍可使用')}
 });
}
async function api(path,body){const response=await fetch(path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await response.json();if(!response.ok){const error=Error(data.error||'请求失败');error.status=response.status;throw error}return data}
let toastTimer;
function toast(message){clearTimeout(toastTimer);$('#toast-root').innerHTML=`<div class="toast">${esc(message)}</div>`;toastTimer=setTimeout(()=>$('#toast-root').innerHTML='',4500)}
let modalScroll=0,modalFocus=null;
function modal(title,html,footer=''){
 if(!state.modal){modalFocus=document.activeElement;modalScroll=scrollY;const width=document.body.getBoundingClientRect().width;Object.assign(document.body.style,{position:'fixed',top:-modalScroll+'px',width:width+'px',overflow:'hidden'})}
 state.modal=true;$('#modal-root').innerHTML=`<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="modal-head"><h2>${esc(title)}</h2>${button('','close','ghost icon-button','close')}</div><div class="modal-body">${html}</div>${footer?`<div class="modal-foot">${footer}</div>`:''}</section></div>`;
 requestAnimationFrame(()=>$('.modal [data-action="close"]')?.focus());
}
function closeModal(){if(!state.modal)return;discardAction=null;++searchSequence;state.modal=null;$('#modal-root').innerHTML='';Object.assign(document.body.style,{position:'',top:'',width:'',overflow:''});window.scrollTo(0,modalScroll);modalFocus?.focus({preventScroll:true})}
function beijing(value){if(!value)return '—';return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'medium',hour12:false}).format(new Date(value.includes('T')?value:value.replace(' ','T')+'Z'))}
function confirmNavigation(callback){if(state.saving){toast('正在保存，请稍候');return}if(!state.dirty){Promise.resolve(callback()).catch(e=>toast(e.message));return}modal('还有未保存的修改','<p>离开会丢失当前编辑，已保存的版本会保留。</p>',button('继续编辑','close')+button('放弃修改并离开','discard','primary'));discardAction=callback}
let discardAction=null,navSequence=0;
function nodeContext(){return {path:root(),key:nodeKey(),department:state.dept,node:state.node,sequence:navSequence}}
function sameNode(context){return state.view==='department'&&state.project&&root()===context.path&&nodeKey()===context.key&&navSequence===context.sequence}
async function goHome(){const home=state.prefs.default_workspace;if(home==='overview'){state.view='overview';state.workspace=null;render()}else await openHome(home)}
async function openHome(departmentId){
 const d=departments().find(item=>item.id===departmentId);
 if(!d)throw Error('部门首页不存在');if(d.enabled===false){state.view='content';await ProjectContentUI.load();render();return}
 clearTimeout(state.jobPollTimer);state.jobPollTimer=null;++navSequence;
 state.view='home';state.dept=departmentId;state.node=0;state.workspace=null;state.departmentJob=null;state.testTask=null;state.testStage=undefined;
 const sequence=navSequence;if(state.project)await continuationUI.load(root(),departmentId);else continuationUI.clear();
 await loadDepartmentUI(departmentId);if(sequence!==navSequence)return;render();
}
function sideAndTop(){
 const nav=(text,view,ico,count)=>`<button class="nav-item ${state.view===view?'active':''}" data-action="view:${view}" title="${text}">${icon(ico)}<span class="label">${text}</span>${count?`<span class="count">${count}</span>`:''}</button>`;
 const pending=state.summary.nodes.filter(n=>n.status==='waiting_user').length+state.summary.tasks.filter(t=>t.status==='waiting_user').length;
 const role=state.catalog.roles.find(r=>r.id===state.prefs.active_role);
 $('#sidebar').innerHTML=`<div class="brand"><div class="brand-mark">${icon('layers')}</div><span>StudioFlow<span style="color:#94a085">.</span></span></div><button class="workspace-label" data-action="studios" title="选择工作室"><span class="avatar">S</span><span class="studio-name">${esc(state.studio?.name||'选择工作室')}</span>${icon('down','small-icon')}</button><div class="sidebar-project-actions">${button('新增项目','new-project','','plus')}${button('选择项目','projects','','folder')}</div><div class="nav-label">WORKSPACE</div>${state.prefs.default_workspace!=='overview'?nav('部门首页','home','grid'):''}${nav('项目总览','overview','layers')}${nav('项目产物','artifacts','folder')}${nav('待我决策','decisions','flag',pending)}<div class="nav-label">AGENT DEPARTMENTS</div>${departments().filter(d=>d.enabled!==false).map(d=>`<button class="nav-item ${['department','home'].includes(state.view)&&state.dept===d.id?'active':''}" data-action="home:${d.id}" title="${esc(d.title)}" style="${tone(d)}"><i class="dept-dot"></i><span class="label">${d.title}</span></button>`).join('')}<div class="nav-label">RESOURCES</div>${nav('Skill 工作台','skills','spark')}${nav('工作台内容','content','layers')}${nav('连接与模型','settings','settings')}${nav('外观主题','themes','brush')}${nav('权限后台','admin','people')}<div class="nav-spacer"></div><div class="sidebar-note"><strong>你的方法，就是竞争力</strong>每个节点都有默认 Skill<br>导入团队自己的工作方法</div><button class="user" data-action="user-settings"><span class="avatar">我</span><div><span class="small">${esc(role?.name)}</span><small>首页：${workspaceLabel(state.prefs.default_workspace)}</small></div>${icon('down')}</button>`;
 const currentLabel=['department','home'].includes(state.view)?department().title+(state.view==='home'?' · 首页':''):({overview:'项目总览',artifacts:'项目产物',decisions:'待我决策',skills:'Skill 工作台',content:'工作台内容',settings:'连接与模型',themes:'外观主题',admin:'权限后台'})[state.view];
 $('#topbar').innerHTML=`<div class="breadcrumb">${button('','toggle-sidebar','ghost icon-button','menu')}<button class="studio-trigger" data-action="studios">${esc(state.studio?.name||'工作室')}</button><span class="separator">/</span><button class="project-trigger" data-action="projects"><span class="project-logo">${esc(state.project?.name?.[0]||'+')}</span><span class="project-name">${esc(state.project?.name||'选择项目')}</span>${icon('down','small-icon')}</button><span class="separator">/</span><span class="page-crumb">${currentLabel}</span></div><div class="top-actions">${button('主题','view:themes','theme-trigger','brush')}${button('AI 模型','view:settings','ai-status','spark')}<button class="user-settings-trigger" data-action="user-settings" title="用户设置" aria-label="用户设置"><span class="avatar">我</span><span class="identity-label">${esc(role?.name)}</span>${icon('down','small-icon')}</button></div>`;
 document.body.classList.toggle('collapsed',state.collapsed);
}
function workspaceLabel(key){return key==='overview'?'项目总览':departments().find(d=>d.id===key)?.title||key}
function emptyProject(){return `${heading('先进入工作室，再开始一个项目。','工作室是最外层；项目的资料、Skill 与决策分别保存。')}<section class="panel empty-state">${icon('folder')}<h3>${esc(state.studio?.name||'尚未选择工作室')}</h3><p>当前工作室尚未选择项目。</p><div class="row" style="justify-content:center;margin-top:20px">${button('新增项目','new-project','primary','plus')}${button('选择项目','projects')}</div></section>`}
function nodeStatus(d,i){const key=catalogKey(departments().find(item=>item.id===d),i),stage=ProjectNodeKeys.testingStage(key);if(stage!==null){const t=state.summary.tasks[0];return !t?'not_started':stage<t.stage?'approved':stage===t.stage?t.status:'not_started'}return state.summary.nodes.find(n=>n.node===key)?.status||'not_started'}
function departmentHome(){
 const d=department(),ui=departmentExtension('renderHome',d,0,null),nodes=d.nodes;
 const approved=state.summary.nodes.filter(n=>n.node.startsWith(d.id+':')&&n.status==='approved').length;
 const pending=state.summary.nodes.filter(n=>n.node.startsWith(d.id+':')&&n.status==='waiting_user').length;
 const total=d.id==='testing'?state.summary.tasks.length:nodes.length;
 const pendingTotal=d.id==='testing'?state.summary.tasks.filter(t=>t.status==='waiting_user').length:pending;
 const headline=d.homepage.headline,description=d.homepage.description,focus=d.homepage.focus;
 const homeLabel=d.id==='testing'?'测试工作流':`${d.title}工作区`;
 const nodeCards=nodes.map((n,i)=>{
  const status=nodeStatus(d.id,i),tone=status==='approved'?'green':status==='waiting_user'?'amber':'',isLast=i===nodes.length-1;
  return `<button class="panel home-node" style="--dept:${d.color}" data-action="node:${d.id}:${i}"><span class="between"><span class="node-ordinal">${String(i+1).padStart(2,'0')} / ${String(nodes.length).padStart(2,'0')}</span>${tag(statusText[status]||'未开始',tone)}</span><div class="node-title">${icon(d.icon)}<h3>${esc(n[0])}</h3>${isLast?'':icon('arrow')}</div><p>${esc(n[1])}</p><footer><span>${esc(n[2])}</span><span>${isLast?'进入节点':'进入节点 →'}</span></footer></button>${continuationBetween(d,i)}`;
 }).join('');
 const primaryAction=state.project?(nodes.length?button('打开首个节点',`node:${d.id}:0`,'lime','arrow'):nodeManagementButton()):button('选择项目','projects','lime','arrow');
 const heroDetail=state.project?`围绕「${esc(state.project.name)}」组织${esc(d.title)}工作。资料、技能与决策按项目和节点独立保存。`:'先从左侧选择项目，进入部门工作台。';
 const checkpointTitle=state.project?'项待你决策':'准备好开始协作';
 const checkpointText=state.project?`${approved} 个节点已确认；${total} 个相关任务或节点。`:'选择项目后显示当前部门进度和交付状态。';
 const focusRows=focus.map((x,i)=>`<div><span>0${i+1}</span><b>${esc(x)}</b></div>`).join('');
 const toolLinks=(d.tools||[]).map(tool=>`<a class="tool-link" href="${esc(tool.url)}" target="_blank" rel="noopener noreferrer">${icon('link','small-icon')}<span>${esc(tool.label)}</span>${icon('arrow','small-icon')}</a>`).join('');
 const adapterSlots=(d.tool_adapters||[]).map(adapter=>`<div class="adapter-slot"><span>${esc(adapter.label)}</span>${tag(adapter.status==='connected'?'已连接':'适配器插槽 · 未配置',adapter.status==='connected'?'green':'')}</div>`).join('');
 const ownedSlot=(d.content_items||[]).length?ui+`<section class="panel department-content"><div class="panel-title"><h2>部门资料与交付</h2>${button('管理内容','view:content')}</div>${d.content_items.map(n=>`<article><span class="eyebrow">${({note:'WORKSPACE NOTE',source:'REQUIREMENT SOURCE',deliverable:'DELIVERABLE'})[n.kind]}</span><h3>${esc(n.title)}</h3><p>${esc(n.body.slice(0,500))}</p></article>`).join('')}</section>`:ui;
 return `${heading(d.title+'工作台',description,button('项目总览','view:overview','','layers'),d.en)}<div class="department-hero-grid"><section class="department-hero" data-department="${esc(d.id)}" style="--dept:${d.color}"><div class="hero-kicker"><i class="live-square"></i>${esc(d.en)}<span>/</span>${esc(state.project?.name||'选择项目')}</div>${DepartmentMarks.hero(d.id)}<h2>${esc(headline)}</h2><p>${heroDetail}</p><div class="hero-cta">${primaryAction}<span>${esc(homeLabel)} · ${nodes.length} 个工作节点</span></div><div class="hero-bottom"><span>${esc(state.studio?.name||'工作室')}</span><span>${state.project?esc(state.project.name):'尚未选择项目'}</span></div></section><section class="panel home-checkpoint"><div class="between"><span class="eyebrow">${state.project?'PROJECT SIGNAL':'WORKSPACE'}</span>${tag(state.project?'当前项目':'等待选择',state.project?'green':'')}</div><strong>${state.project?String(pendingTotal).padStart(2,'0'):'—'}</strong><h3>${checkpointTitle}</h3><p>${checkpointText}</p>${button(state.project?'查看部门交付':'选择项目',state.project?'view:artifacts':'projects','','arrow')}</section></div><div class="section-heading"><div class="row"><h2>${esc(d.title)}节点</h2><span class="tiny muted">按流程逐步推进</span></div><div class="row"><span>${nodes.length} 个工作节点 · Skill 可导入导出</span>${nodeManagementButton()}</div></div><div class="home-node-grid has-continuation" style="--dept:${d.color}">${nodeCards}</div><div class="lower-grid home-lower"><section class="panel"><div class="panel-title"><h2>部门工作重点</h2>${tag('默认方法')}</div><div class="home-focus">${focusRows}</div><div class="panel-link"><span>每个节点可独立维护输入、交付物与 Skill。</span>${nodes.length?button('进入首个节点',`node:${d.id}:0`):''}</div></section><section class="panel"><div class="panel-title"><h2>工具入口</h2>${tag('部门专属')}</div><div class="department-tool-links">${toolLinks||'<span class="small muted">本部门尚未登记工具网站。</span>'}</div>${adapterSlots?`<div class="adapter-slots"><h3>API 适配器</h3>${adapterSlots}<p class="small muted">适配器凭据由平台管理员配置，状态不会在未接通时标记为已连接。</p></div>`:''}<div class="panel-link"><span>链接只打开对应服务网站，不代表 API 已授权。</span>${button('AI 与连接设置','view:settings')}</div></section></div>${ownedSlot}`;
}
function overview(){
 const pending=state.summary.nodes.filter(n=>n.status==='waiting_user'),pendingTasks=state.summary.tasks.filter(t=>t.status==='waiting_user'),pendingCount=pending.length+pendingTasks.length,artifacts=state.summary.nodes.filter(n=>n.has_deliverable);
 return `${heading('把想法，推进成一款游戏。','一个项目，五个部门；每次交付，都有依据和下一步。',button('查看全链路','pipeline','','layers'),'YOUR GAME STUDIO')}<div class="hero-grid"><section class="hero"><div class="hero-copy"><div class="eyebrow">${esc(state.project.name)} / PROJECT WORKSPACE</div><h2>从好点子，到值得做。</h2><p>先确认玩家为什么玩、产品如何赚钱。<br>让调研、设计与实现围绕同一个目标推进。</p>${button('进入产品工作区','dept:product','lime','arrow')}</div>${heroArt()}</section><section class="panel gate-card"><div class="between"><span class="eyebrow">NEXT DECISION</span>${tag('人工决策','amber')}</div><h3>${pendingCount?'有 '+pendingCount+' 项交付或测试待审核':'每次投入前，确认范围与证据'}</h3><p>当前保存 ${artifacts.length} 份部门交付物。<br>测试批次 ${state.summary.tasks.length} 个。</p><div class="gate-foot"><span>来自当前项目真实记录</span>${button('审阅','view:decisions','','arrow')}</div></section></div><div class="section-heading"><div class="row"><h2>部门协作</h2><span class="tiny muted">从机会到增长</span></div><span>${departments().reduce((sum,d)=>sum+d.nodes.length,0)} 个节点 · 可替换 Skill</span></div><div class="department-cards">${departments().filter(d=>d.enabled!==false).map((d,i)=>`<button class="panel department-card" style="${tone(d)}" data-action="dept:${d.id}"><div class="card-top"><div class="dept-symbol">${icon(d.icon)}</div><span>0${i+1}</span></div><h3>${d.title}</h3><p>${d.desc}</p><div class="step-bars">${d.nodes.map((_,j)=>`<i class="${nodeStatus(d.id,j)==='approved'?'done':nodeStatus(d.id,j)==='waiting_user'?'current':''}"></i>`).join('')}</div><div class="card-foot"><span>${d.nodes.length} 个工作节点</span><span>进入 →</span></div></button>`).join('')}</div><div class="lower-grid"><section class="panel"><div class="panel-title"><h2>需要你的判断</h2>${tag(pendingCount+' 项待决策')}</div>${pendingCount?decisionRows(pending.slice(0,3),false)+testDecisionRows(pendingTasks.slice(0,Math.max(0,3-pending.length))):decisionRows([])}<div class="panel-link"><span>确认来源、版本与交付缺口</span>${button('全部决策 →','view:decisions')}</div></section><section class="panel"><div class="panel-title"><h2>商业验证</h2>${tag('由项目定义')}</div><div class="business-list">${[['people','目标用户与使用动机'],['coins','变现模式与成本上限'],['chart','留存 / LTV / 获客成本']].map(x=>`<div class="business-item"><span class="row">${icon(x[0],'small-icon')}${x[1]}</span><strong>待核实</strong></div>`).join('')}</div><div class="panel-link"><span>证据决定投入；缺数据时不填造指标</span>${button('进入迭代决策 →','node:growth:3')}</div></section></div>`;
}
function definition(key){const [id,token]=key.split(':'),d=departments().find(d=>d.id===id),index=d.nodes.findIndex((_,i)=>catalogKey(d,i)===key);const n=index>=0?d.nodes[index]:d.archived_nodes?.find(n=>n.id===key)?.definition||state.catalog.departments.find(d=>d.id===id)?.nodes[Number(token)];return {d,n:n||['已归档节点','','历史产物'],index}}
function decisionRows(rows,showEmpty=true){return rows.length?rows.map(row=>{const {d,n,index}=definition(row.node);return `<div class="decision-row"><div class="decision-icon" style="${tone(d)}">${icon(d.icon)}</div><div><h3>${esc(n[1])}</h3><p>${d.title} · 版本 ${row.revision} · ${beijing(row.updated_at)}</p></div>${button(index<0?'查看历史':'审阅',index<0?'node-history:'+row.node:`node:${d.id}:${index}`)}</div>`}).join(''):showEmpty?'<div class="panel-content small muted">暂无待审核交付物或测试批次。</div>':''}
function testDecisionRows(rows){return rows.map(t=>`<div class="decision-row"><div class="decision-icon">${icon('shield')}</div><div><h3>${esc(t.title)}</h3><p>测试部门 · ${esc(state.catalog.departments.find(d=>d.id==='testing').nodes[t.stage][0])}</p></div>${button('进入测试','test-task:'+t.id)}</div>`).join('')}
function decisions(){const nodes=state.summary.nodes.filter(n=>n.status==='waiting_user'),tasks=state.summary.tasks.filter(t=>t.status==='waiting_user');return heading('关键决策，集中处理。','只显示当前项目的待审核交付物和测试批次。')+`<section class="panel">${decisionRows(nodes,!tasks.length)}${testDecisionRows(tasks)}</section>`}
function artifacts(){return heading('项目产物，一处追溯。','当前项目已保存的部门交付物与测试批次。')+`<section class="panel">${state.summary.nodes.filter(n=>n.has_deliverable).map(row=>{const {d,n,index}=definition(row.node);return `<div class="artifact-row">${icon('file')}<div><h3>${esc(n[2])}</h3><p>${d.title} / ${esc(n[0])} · 版本 ${row.revision}</p></div>${tag(statusText[row.status])}<span class="small muted">${beijing(row.updated_at)}</span>${button('查看',index<0?'node-history:'+row.node:`node:${d.id}:${index}`)}</div>`}).join('')||'<div class="panel-content small muted">暂无部门交付物。</div>'}${state.summary.tasks.map(t=>`<div class="artifact-row">${icon('shield')}<div><h3>${esc(t.title)}</h3><p>测试工作流 · 版本 ${t.revision}</p></div>${tag(statusText[t.status]||t.status)}<span></span>${button('查看','test-task:'+t.id)}</div>`).join('')}</section>`}
function pipeline(){modal('项目全链路',`<div class="stack">${departments().map(d=>`<div><h3 style="margin-bottom:12px">${esc(d.title)}</h3><div class="row" style="flex-wrap:wrap">${d.nodes.map((n,i)=>button(esc(n[0]),`goto:${d.id}:${i}`)).join('<span class="muted">→</span>')}</div></div>`).join('')}</div>`)}
function departmentPage(){const d=department();const title=heading(d.title,d.desc,`<div class="row">${nodeManagementButton()}${button('全链路','pipeline','','layers')}</div>`);
 if(d.id==='testing'&&(state.testTask||legacyTestingNode())){const query=new URLSearchParams({studio:state.studio.id,project:state.project.id,embed:'1',theme:StudioThemes.current()});if(state.testTask)query.set('task',state.testTask);if(state.testStage!==undefined)query.set('stage',state.testStage);return title+`<iframe id="testing-frame" class="testing-frame" title="测试六节点工作区" src="/testing.html?${query}"></iframe>`}
 const w=state.workspace;if(!w)return title+'<div class="panel empty-state">正在读取节点…</div>';
 const n=d.nodes[state.node],job=state.departmentJob?.node===nodeKey()?state.departmentJob:null,jobActive=['queued','running'].includes(job?.status),skillControls=DepartmentUIContract.skillControls(state.capabilities,nodeKey());return title+`<nav class="workflow-strip has-continuation" style="--dept:${d.color}">${d.nodes.map((n,i)=>`<button class="workflow-step ${state.node===i?'active':''}" data-action="node:${d.id}:${i}"><span class="row"><span class="step-index">${i+1}</span><b>${esc(n[0])}</b></span><span class="small">${statusText[nodeStatus(d.id,i)]||'未开始'}</span></button>${continuationBetween(d,i)}`).join('')}</nav><div class="workspace-grid"><section class="panel node-panel"><div class="node-head"><h2>${esc(n[1])}</h2><div class="node-skill-inline"><button class="skill-label" data-action="skill">${icon('spark')}${w.skill.source_kind==='imported'?'已导入':'默认 Skill'} · ${esc(w.skill.name)}</button><div class="skill-actions">${skillControls.export?button('在 Codex 使用','handoff-skill','','spark'):''}${button('选择 Skill','select-skill','','spark')}${button('导入 Skill','import-skill','','upload')}${button('导出 Skill','export-skill','','download')}</div></div>${tag(statusText[w.status],w.status==='approved'?'green':w.status==='waiting_user'?'amber':'')}</div><div class="panel-content"><p class="node-description">${esc(n[3])}</p><div class="io-heading">输入资料<span>${esc(n[5])}</span></div><div class="import-choice">${button('飞书链接','toggle-links','','link')}${button('本地文件','toggle-files','','upload')}</div><div id="links-zone" class="input-zone" hidden><textarea id="source-links" placeholder="每行一个飞书需求链接"></textarea><p>本节点暂支持读取飞书正文；其他网页请粘贴已核实的内容。</p>${button('只读导入','import-links')}</div><div id="files-zone" class="input-zone" hidden><input id="source-file" type="file" accept=".md,.txt,.docx,.xlsx"><p>支持 TXT / Markdown / DOCX / XLSX，最大 700KB。</p></div><div id="import-feedback" class="small"></div><div class="field"><label for="node-inputs">输入内容 / 来源与版本</label><textarea id="node-inputs" class="node-input" placeholder="提供资料和来源，或在此整理上游已确认产物。">${esc(w.inputs)}</textarea></div><div class="io-heading">交付物<span>${esc(n[6])}</span></div><p class="small muted">此节点当前支持人工整理与审核。研究、生图、代码修改等专用工具尚未接通。</p><div class="field"><label for="node-deliverable">${esc(n[2])} · Markdown / 文字</label><textarea id="node-deliverable" class="deliverable-input" placeholder="粘贴或编写真实交付物；保存后再确认。">${esc(w.deliverable)}</textarea></div><div class="row">${button('导出交付物','export-deliverable','','download')}${button('从已确认上游导入','upstream','','layers')}</div></div>${departmentExtension('renderWorkspace',d,state.node,w)}<div class="node-bottom"><span><span id="save-status">版本 ${w.revision} · ${w.updated_at?'保存于 '+beijing(w.updated_at):'尚未保存'}</span><br><span id="department-job-status" class="small muted">${departmentJobLabel(job)}</span></span><div class="row">${button('重置节点','reset-node')}${!nodeKey().includes(':custom-')&&state.integrations.some(x=>x.department===d.id&&x.adapter==='registered')?`<button data-action="run-node" class="${jobActive?'disabled':''}" ${jobActive?'disabled':''}>${icon('play')}${jobActive?'正在执行':'运行本节点'}</button>`:''}${button('保存修改','save-node','primary','check')}</div></div></section><aside class="node-rail"><section class="panel rail-card"><span class="eyebrow">HUMAN CHECKPOINT</span><h3>${esc(n[4])}</h3><p>当前交付物、来源与版本由你审核。更新输入或 Skill 后需要重新确认。</p><div class="decision-point"><b>交付给下一节点</b><br>${esc(state.node<d.nodes.length-1?d.nodes[state.node+1][0]:departments()[departments().indexOf(d)+1]?.title||'产品部门 · 下一轮迭代')}<br>版本 ${w.revision}</div>${button('审阅并决定','review-node')}</section><section class="panel node-logs"><div class="panel-title"><h2>操作日志</h2><span class="tiny muted">北京时间</span></div><div class="log-body">${w.events.map(event=>`<div class="log-entry"><time>${beijing(event.created_at)}</time>${esc(event.detail)}</div>`).join('')||'<div class="log-entry">当前节点暂无操作记录。</div>'}</div></section></aside></div>`;
}
function skillsPage(){return SkillWorkbench.page()}
function render({keepScroll=false}={}){if(!state.catalog||!state.prefs)return;const y=scrollY;disposeDepartmentUI();disposeDepartmentUI=()=>{};sideAndTop();$('#content').innerHTML=state.view==='themes'?StudioThemes.page():state.view==='admin'?TeamAdmin.page():state.view==='settings'?settingsPage():state.view==='home'?departmentHome():!state.project?emptyProject():state.view==='overview'?overview():state.view==='department'?departmentPage():state.view==='skills'?skillsPage():state.view==='content'?ProjectContentUI.page():state.view==='artifacts'?artifacts():decisions();applyCapabilities();mountDepartmentUI();if(keepScroll)window.scrollTo(0,y);else window.scrollTo(0,0)}
async function reloadSummary(){if(!state.project){state.projectCatalog=null;state.summary={nodes:[],tasks:[]};return}const path=root(),[data,capabilities,catalog]=await Promise.all([api(path+'/summary'),api('/api/me/capabilities?studio='+state.studio.id+'&project='+state.project.id),api(path+'/node-catalog')]);if(state.project&&root()===path){state.summary=data;state.capabilities=capabilities;state.projectCatalog=catalog}}
async function openDepartment(d,n=0){
 const def=departments().find(x=>x.id===d);if(!def||!def.nodes[n])throw Error('节点不存在');if(def.enabled===false)throw Error('当前项目已停用此部门，请在工作台内容中启用');
 if(!state.project){await pickerOpen('projects');return}
 clearTimeout(state.jobPollTimer);state.jobPollTimer=null;const sequence=++navSequence;state.view='department';state.dept=d;state.node=n;state.workspace=null;state.departmentJob=null;state.dirty=false;await continuationUI.load(root(),d);await loadDepartmentUI(d);if(sequence!==navSequence)return;
 state.testTask=null;if(d==='testing')state.testStage=ProjectNodeKeys.testingStage(nodeKey());
 render();if(!state.project||(d==='testing'&&legacyTestingNode()))return;
 try{const w=await api(root()+'/workspace?node='+encodeURIComponent(nodeKey()));if(sequence!==navSequence)return;state.workspace=w;state.departmentJob=await api(root()+'/workspace/job?node='+encodeURIComponent(nodeKey()));render();if(['queued','running'].includes(state.departmentJob?.status))pollDepartmentJob(nodeContext())}
 catch(error){if(sequence===navSequence){$('#content').innerHTML+=`<p role="alert">${esc(error.message)} ${button('重试','node:'+d+':'+n)}</p>`}throw error}
}
function pollDepartmentJob(context){
 clearTimeout(state.jobPollTimer);
 state.jobPollTimer=setTimeout(async()=>{
  try{
   const job=await api(context.path+'/workspace/job?node='+encodeURIComponent(context.key));
   if(!sameNode(context))return;
   state.departmentJob=job;
   const label=$('#department-job-status');if(label)label.textContent=departmentJobLabel(job);
   if(['queued','running'].includes(job?.status)){pollDepartmentJob(context);return}
   if(job?.status==='completed'){
    state.workspace=await api(context.path+'/workspace?node='+encodeURIComponent(context.key));
    await reloadSummary();if(!sameNode(context))return;render({keepScroll:true});toast('执行完成，交付物等待人工审核');
   }else if(job&&['failed','interrupted'].includes(job.status)){
    render({keepScroll:true});toast(job.error||'部门执行未完成');
   }
  }catch(error){if(sameNode(context))toast('读取执行状态失败：'+error.message)}
 },1000);
}
function departmentJobLabel(job){return !job?'尚无执行记录':({queued:'任务排队中',running:'Agent 正在执行',completed:'执行完成，等待人工审核',failed:'执行失败：'+(job.error||'未知错误'),interrupted:'服务重启中断：'+(job.error||'未自动重试')})[job.status]||job.status}
async function chooseStudio(id,showProjects=true){
 const sequence=++navSequence,prefs=await api('/api/studios/'+id+'/enter',{});if(sequence!==navSequence)return;
 state.prefs=prefs;state.studio=state.studios.find(s=>s.id===id);state.project=null;state.projectCatalog=null;state.testTask=null;state.testStage=undefined;state.workspace=null;state.dirty=false;state.summary={nodes:[],tasks:[]};
 closeModal();state.view='overview';state.capabilities=await api('/api/me/capabilities?studio='+id);render();
 if(prefs.project_id){try{const saved=await api('/api/studios/'+id+'/projects/'+prefs.project_id);if(sequence===navSequence)await chooseProject(saved)}catch(error){if(sequence===navSequence)toast(error.message)}}
 if(showProjects&&state.studio?.id===id)await pickerOpen('projects');
}
async function chooseProject(p){
 if(!p)return;const sequence=++navSequence,studio=state.studio.id,prefs=await api('/api/studios/'+studio+'/projects/'+p.id+'/enter',{});
 if(sequence!==navSequence)return;
 state.prefs=prefs;state.project=p;state.testTask=null;state.testStage=undefined;state.workspace=null;state.dirty=false;
 await reloadSummary();if(sequence!==navSequence)return;closeModal();await goHome();
}
let picker={kind:'studios',query:'',page:1},searchSequence=0;
async function pickerOpen(kind){picker={kind,query:'',page:1};const canCreate=DepartmentUIContract.canCreateEntity(kind,state.capabilities);const create=canCreate?button(kind==='studios'?'新增工作室':'新增项目',kind==='studios'?'new-studio':'new-project','primary','plus'):'';const footer=`<span>每页 5 个</span>`;const searchPlaceholder=kind==='studios'?'搜索工作室名称':'筛选项目名称';const toolbar=`<div class="project-picker-toolbar"><input id="picker-search" type="search" aria-label="${searchPlaceholder}" placeholder="${searchPlaceholder}">${create}</div>`;modal(kind==='studios'?'选择工作室':'选择项目',`<p>${kind==='studios'?'工作室位于项目外层，进入后管理它的项目。':'仅显示当前工作室的项目。'}</p>${toolbar}<div id="picker-results"></div>`,footer);await loadPicker()}
async function loadPicker(){
 const sequence=++searchSequence,{kind,query,page}=picker;let result;
 if(kind==='studios'){const list=state.studios.filter(s=>s.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()));const pages=Math.max(1,Math.ceil(list.length/5));picker.page=Math.max(1,Math.min(page,pages));result={total:list.length,items:list.slice((picker.page-1)*5,picker.page*5)}}
 else result=await api('/api/studios/'+state.studio.id+'/projects?size=5&page='+page+'&q='+encodeURIComponent(query));
 if(sequence!==searchSequence||!$('#picker-results'))return;
 const pages=Math.max(1,Math.ceil(result.total/5));if(picker.page>pages){picker.page=pages;return loadPicker()}
 $('#picker-results').innerHTML=`<div class="project-results">${result.items.map(item=>`<button class="project-result ${item.id===(kind==='studios'?state.studio?.id:state.project?.id)?'active':''}" data-action="pick-${kind}:${esc(item.id)}"><span class="project-info"><span class="project-logo">${esc(item.name[0])}</span><span><h3>${esc(item.name)}</h3><p>${kind==='studios'?'进入工作室':'进入项目'}</p></span></span>${icon('chevron')}</button>`).join('')||'<p class="small muted">没有找到结果。</p>'}</div><div class="pagination"><span>共 ${result.total} 个</span><div class="row"><button data-action="picker-page:-1" ${picker.page<=1?'disabled':''} aria-label="上一页">‹</button><span>${picker.page} / ${pages}</span><button data-action="picker-page:1" ${picker.page>=pages?'disabled':''} aria-label="下一页">›</button></div></div>`;picker.items=result.items;
}
function createForm(kind){if(kind==='project'&&!state.studio)return toast('请先进入工作室');modal(kind==='studio'?'新增工作室':'新增项目',`<p>${kind==='project'?'所属工作室：'+esc(state.studio.name):'创建后进入工作室，再新增项目。'}</p><div class="field"><label for="entity-name">${kind==='studio'?'工作室':'项目'}名称</label><input id="entity-name" maxlength="60" autocomplete="off"></div>`,`<span>保存在本机数据库</span>${button('创建并进入','create-'+kind,'primary','plus')}`)}
async function createEntity(kind){const name=$('#entity-name').value.trim();if(!name)return toast('请填写名称');if(kind==='studio'){const item=await api('/api/studios',{name});state.studios= (await api('/api/studios')).items;await chooseStudio(item.id,false);await pickerOpen('projects')}else{const item=await api('/api/studios/'+state.studio.id+'/projects',{name});await chooseProject(item)}toast('已创建'+(kind==='studio'?'工作室':'项目'))}
function userSettings(){modal('用户设置',`<p>当前账号：${esc(state.session?.user.name||'本机负责人')} · ${esc(state.session?.user.username||state.session?.user.tenant_key||'local')}</p><p>身份决定部门首页的展示。资源访问与操作权限由负责人在权限后台分配；修改首页身份不会获得额外权限。</p><div class="field"><label for="user-role">我的身份</label><select id="user-role">${state.catalog.roles.map(r=>`<option value="${r.id}" ${r.id===state.prefs.active_role?'selected':''}>${r.name}</option>`).join('')}</select></div><div class="field"><label>默认首页工作区</label><div id="home-preview" class="info-strip">${workspaceLabel(state.prefs.default_workspace)}</div></div>`,`<div>${state.session?.user.username?button('修改密码','change-password'):''}${button('退出登录','logout')}</div>${button('保存并进入首页','save-user','primary','check')}`)}
async function saveUser(){state.prefs=await api('/api/me/preferences',{active_studio_id:state.studio.id,role:$('#user-role').value});closeModal();await goHome();toast('身份与默认首页已保存')}
async function saveNode(patch){
 if(state.saving)throw Error('正在保存，请稍候');if(!state.workspace)throw Error('节点尚未读取');
 const context={path:root(),key:nodeKey()},revision=state.workspace.revision;
 const data=patch&&Object.hasOwn(patch,'skill')&&!state.dirty?patch:{inputs:$('#node-inputs')?.value??state.workspace.inputs,deliverable:$('#node-deliverable')?.value??state.workspace.deliverable,...patch};
 state.saving=true;document.querySelectorAll('.node-panel textarea,.node-panel button').forEach(el=>el.disabled=true);
 try{const updated=await api(context.path+'/workspace?node='+encodeURIComponent(context.key),{...data,revision});
 if(!state.project||root()!==context.path||nodeKey()!==context.key)return null;
 state.workspace=updated;state.dirty=false;await reloadSummary();render({keepScroll:true});return updated;
 }finally{state.saving=false;document.querySelectorAll('.node-panel textarea,.node-panel button').forEach(el=>el.disabled=false)}
}
function showSkill(){
 const w=state.workspace;
 const controls=DepartmentUIContract.skillControls(state.capabilities,nodeKey());
 if(!controls.view){toast('无 Skill 查看权限');return}
 modal('当前节点 Skill',`<p>${w.skill.source_kind==='imported'?'当前项目导入的规则':'内置默认规则'} · ${esc(w.skill.name)}</p><pre class="skill-text">${esc(w.skill.content)}</pre>`,`<span>仅修改本节点，历史审批不会自动通过</span><div class="row">${button('恢复默认','restore-skill')}${button('选择 Skill','select-skill','','spark')}${button('导入 Skill','import-skill','','upload')}${button('导出 Skill','export-skill','primary','download')}</div>`);
 applyCapabilities();
}
async function openSkillPicker(){
 if(!state.workspace||state.saving)return;
 const controls=DepartmentUIContract.skillControls(state.capabilities,nodeKey());
 if(!controls.view||!controls.import)return toast('需要当前节点的 Skill 查看和导入权限');
 if(state.dirty)return toast('请先保存当前编辑，再选择 Skill');
 const context=nodeContext(),revision=state.workspace.revision;
 const current=()=>sameNode(context)&&state.workspace?.revision===revision;
 await StudioSkillPicker.open({api,path:context.path,department:state.dept,target:department().nodes[state.node][0],modal,close:closeModal,isCurrent:current,
  save:async(skill,source,isOpen)=>{
   if(!current())throw Error('当前节点已变化，请重新打开');
   const saved=await saveNode({skill,skill_note:'从 Skill 工作台选择：'+source+' / '+skill.name});
   if(saved&&sameNode(context)){if(isOpen())closeModal();toast('Skill 已选择并保存')}
  }
 });
}
function download(text,name,type='text/markdown'){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type:type+';charset=utf-8'}));a.href=url;a.download=name.replace(/[\\/:*?"<>|]/g,'_');a.click();setTimeout(()=>URL.revokeObjectURL(url),500)}
function reviewNode(){if(state.dirty)return toast('请先保存修改，再审阅当前版本');const w=state.workspace;if(!w.deliverable.trim())return toast('请先保存交付物');if(w.status==='approved')return toast('此版本已确认；修改后可重新审核');modal('审阅节点交付',`<p>当前交付版本 ${w.revision}。确认后，后续节点可导入此版本的交付物。</p><pre class="skill-text">${esc(w.deliverable)}</pre><div class="field"><label for="decision-reason">决策理由</label><textarea id="decision-reason" maxlength="2000" placeholder="确认依据，或需要修改的内容"></textarea></div>`,`<span>最终决定由你作出</span><div class="row">${button('退回修改','decide:reject')}${button('确认交付','decide:approve','primary','check')}</div>`)}
async function decideNode(action){if(state.saving)return;const context=nodeContext(),body={revision:state.workspace.revision,action,reason:$('#decision-reason').value};state.saving=true;try{const result=await api(context.path+'/workspace/decision?node='+encodeURIComponent(context.key),body);if(!sameNode(context))return;state.workspace=result;closeModal();await reloadSummary();render({keepScroll:true});toast(action==='approve'?'当前版本已确认':'已退回修改')}finally{state.saving=false}}
async function upstream(){if(state.dirty)return toast('请先保存当前编辑');const items=state.summary.nodes.filter(n=>n.status==='approved'&&n.node!==nodeKey());modal('选择已确认的交付物',items.length?`<div class="stack">${items.map(n=>{const item=definition(n.node);return button(esc(item.d.title+' / '+item.n[0])+' · v'+n.revision,'take-upstream:'+n.node)}).join('')}</div>`:'<p>当前项目暂无其他已确认的交付物。</p>')}
async function takeUpstream(d,n){const context=nodeContext(),w=await api(context.path+'/workspace?node='+d+':'+n);if(!sameNode(context))return;if(w.status!=='approved')throw Error('上游版本已变化，请重新审核');const def=definition(w.node);await saveNode({inputs:state.workspace.inputs+`\n\n## 上游：${def.d.title} / ${def.n[0]} · 版本 ${w.revision}\n${w.deliverable}`});closeModal();toast('已将已确认上游交付物保存到输入')}
async function importLocal(file){if(!file)return;const context=nodeContext();if(file.size>700000)throw Error('文件不得超过700KB');let text;if(/\.(txt|md)$/i.test(file.name))text=await file.text();else if(/\.(docx|xlsx)$/i.test(file.name)){const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));const parsed=await api(context.path+'/parse-file',{name:file.name,data:btoa(binary),node:context.key});text=parsed.content;if(parsed.metadata.source_gaps?.length)text+='\n\n读取缺口：'+parsed.metadata.source_gaps.join('；')}else throw Error('仅支持 TXT、MD、DOCX、XLSX');if(!sameNode(context)||state.saving)return;$('#node-inputs').value+=`\n\n## 文件：${file.name}\n${text}`;$('#import-feedback').textContent=file.name+' · 已读取，保存后生效';$('#import-feedback').className='small import-success';markDirty()}
function markDirty(){state.dirty=true;if($('#save-status'))$('#save-status').textContent='有未保存修改'}
async function importLinks(){const context=nodeContext(),links=$('#source-links').value.split(/\s+/).filter(Boolean);if(!links.length)return toast('请填写飞书链接');const result=await api(context.path+'/read-sources',{links,node:context.key});if(!sameNode(context)||state.saving)return;$('#import-feedback').innerHTML=result.results.map(r=>`<p class="${r.status==='imported'?'import-success':'import-failed'}">${esc(r.url)} · ${r.status==='imported'?'读取成功，保存后生效':esc(r.error)}</p>`).join('');result.results.filter(r=>r.status==='imported').forEach(r=>{$('#node-inputs').value+=`\n\n## 来源：${r.url}\n${r.content}\n读取缺口：${(r.metadata.source_gaps||[]).join('；')||'无已报告缺口'}`});if(result.results.some(r=>r.status==='imported'))markDirty()}
function settingsPage(){const selection=state.model||{},editSource=state.modelSource||selection.active_source||'relay';return heading('一次连接，整个工作室使用。','AI 配置由服务端 Mac 读取并供工作室任务使用；用户个人 Mac 的中转站不会自动读取。','','CONNECTIONS')+`<div class="settings-grid"><section class="panel settings-form"><div class="between"><h2>AI 大模型</h2>${tag(selection.active_source==='custom'?'自定义 API':'服务端中转站', 'green')}</div><p>来源互斥。自动读取服务端运行账号的 Codex 配置；不把已保存凭据返回浏览器。保存配置不代表远端连接已验证。</p><div class="connection-options"><button class="connection-option ${editSource!=='custom'?'selected':''}" data-action="model-source:relay"><div class="row">◉ <h3>自动读取服务端配置</h3></div><p>服务端 Mac 的 Codex CLI / 中转站<br>${esc(selection.relay_config_file||'读取中…')}</p></button><button class="connection-option ${editSource==='custom'?'selected':''}" data-action="model-source:custom"><div class="row">◉ <h3>自定义 API</h3></div><p>配置地址与模型；保存后明确切换来源</p></button></div>${editSource==='custom'?customModelForm(selection):relayModelForm(selection)}</section><aside class="settings-connectors"><div class="eyebrow">连接状态</div><section class="panel connector-card"><div class="between"><h3>当前 AI</h3>${tag('已选择','green')}</div><p>生效模型：${esc((selection.active_source==='custom'?selection.custom?.model:selection.selection?.model)||'Codex 默认模型')}<br>推理强度：${esc((selection.active_source==='custom'?selection.custom?.effort:selection.selection?.effort)||'模型默认')}</p>${button('刷新服务端模型','discover-models')}</section><section class="panel connector-card"><div class="between"><h3>飞书</h3>${tag('按节点读取')}</div><p>节点提供只读需求读取入口。Bug 写入仍使用原工作流的审核门禁。</p></section><section class="panel connector-card"><div class="between"><h3>静态代码检测</h3>${tag('不启动 Unity','green')}</div><p>复用测试六节点与已有证据检查，不执行 Git 拉取或提交。</p></section></aside></div>`}
function relayModelForm(m){const models=m.models||[],chosen=m.selection?.model||'';return `<div class="field"><label for="relay-model">本机中转站模型</label><select id="relay-model"><option value="">${models.length?'选择模型':'点击刷新读取模型列表'}</option>${chosen&&!models.some(x=>x.id===chosen)?`<option value="${esc(chosen)}" selected>${esc(chosen)}（当前配置）</option>`:''}${models.map(x=>`<option value="${esc(x.id)}" ${chosen===x.id?'selected':''} ${x.usable===false?'disabled':''}>${esc(x.id)}${x.usable===false?'（接口不兼容）':''}</option>`).join('')}</select></div><div class="field"><label for="relay-effort">推理强度</label><select id="relay-effort"><option value="">模型默认</option>${['low','medium','high','xhigh'].map(x=>`<option value="${x}" ${m.selection?.effort===x?'selected':''}>${x}</option>`).join('')}</select></div><div id="model-message" class="small muted" role="status"></div><button class="primary" data-action="save-relay">保存并启用本机中转站</button>`}
function customModelForm(m){const c=m.custom||{};return `<div class="field"><label for="api-url">API 地址</label><input id="api-url" value="${esc(c.base_url||'')}" placeholder="https://api.example.com/v1"></div><div class="field"><label for="api-protocol">协议</label><select id="api-protocol"><option value="responses" ${c.protocol!=='chat'?'selected':''}>OpenAI Responses</option><option value="chat" ${c.protocol==='chat'?'selected':''}>OpenAI Chat Completions</option></select></div><div class="field"><label for="api-model">模型 ID</label><input id="api-model" value="${esc(c.model||'')}" placeholder="供应商实际模型名称"></div><div class="field"><label for="api-effort">推理强度</label><select id="api-effort">${[['','模型默认'],['low','低'],['medium','中'],['high','高'],['xhigh','超高']].map(([v,t])=>`<option value="${v}" ${v===(c.effort||'')?'selected':''}>${t}</option>`).join('')}</select></div><div class="field"><label for="api-key">API Key ${c.has_api_key?'（已保存，留空保留）':'（保存在本机服务，不发送到浏览器存储）'}</label><input id="api-key" type="password" autocomplete="new-password" placeholder="${c.has_api_key?'留空保留现有密钥':'API Key'}"></div><div id="model-message" class="small muted" role="status"></div><button class="primary" data-action="save-custom">保存并启用自定义 API</button>`}
async function refreshModel(){state.model=await api('/api/ai-models');state.modelSource=state.model.active_source;render({keepScroll:true})}
async function saveRelay(){const message=$('#model-message');try{const model=$('#relay-model').value,effort=$('#relay-effort').value||null;if(!model)throw Error('请选择模型');if((state.model.models||[]).some(m=>m.id===model))await api('/api/ai-models/selection',{model,effort});else{if(model!==state.model.selection.model||effort!==(state.model.selection.effort||null))throw Error('请先刷新模型列表再修改模型或推理强度');await api('/api/ai-models/source',{source:'relay'})}await refreshModel();toast('本机配置已启用')}catch(e){if(message.isConnected)message.textContent=e.message;else toast(e.message)}}
async function saveCustom(){try{await api('/api/ai-models/custom',{base_url:$('#api-url').value,protocol:$('#api-protocol').value,model:$('#api-model').value,effort:$('#api-effort').value||null,api_key:$('#api-key').value});await refreshModel();toast('自定义 API 已启用')}catch(e){$('#model-message').textContent=e.message}}
async function discoverModels(){await api('/api/ai-models/discover',{});await refreshModel();toast('本机返回 '+state.model.models.length+' 个模型')}
function switchSource(source){if(!['relay','custom'].includes(source))return;state.modelSource=source;render({keepScroll:true})}
async function downloadSkill(){const skill=await api(root()+'/workspace/skill-export?node='+encodeURIComponent(nodeKey()));download(skill.content,skill.name+'.md')}
async function handoffSkill(){const context=nodeContext();const result=await api(context.path+'/workspace/codex-handoff?node='+encodeURIComponent(context.key),{origin:location.origin});if(!sameNode(context))return;StudioFlowCodexHandoff.beginCodexHandoff({uri:result.uri,openUri:StudioFlowCodexHandoff.openProtocolUri,onWaiting:()=>toast('正在请求本机 Codex 桥接工具…此时尚未确认接收'),onUnconfirmed:()=>recoverSkillHandoff(context)})}
async function recoverSkillHandoff(context){if(!sameNode(context))return;try{const result=await api(context.path+'/workspace/codex-handoff?node='+encodeURIComponent(context.key),{origin:location.origin,preview:true});if(!sameNode(context))return;const prompt=result.prompt;modal('尚未确认 Codex 接收',`<p>浏览器无法确认本机桥接是否已安装，也无法确认 Codex 是否已粘贴。若 Codex 已出现，请在 Codex 检查内容；否则可复制下面的交接文本，手动粘贴到 Codex。</p><textarea id="codex-handoff-recovery" style="min-height:260px">${esc(prompt)}</textarea>${button('复制交接文本','copy-handoff','','copy')}<p class="small muted">未安装桥接工具：仓库内安装说明为 deploy/mac/codex-bridge/README.md。请安装维护者提供的桥接应用包；使用成品仅需 macOS 13+ 和 Codex 桌面 App。</p>`)}catch(error){toast('桥接未确认，且无法读取 Skill：'+error.message)}}
async function copyHandoff(){try{await navigator.clipboard.writeText(document.getElementById('codex-handoff-recovery').value);toast('交接文本已复制，请手动粘贴到 Codex')}catch{document.getElementById('codex-handoff-recovery').select();toast('自动复制失败，请按 ⌘C 复制选中文本')}}
function importSkill(){const context=nodeContext(),input=document.createElement('input');input.type='file';input.accept='.md,.markdown,text/plain';input.onchange=async()=>{try{const file=input.files?.[0];if(!file)return;if(file.size>100000)return toast('Skill 最大 100KB');const content=await file.text();if(!sameNode(context))return;if(!content.trim())return toast('Skill 内容为空');const saved=await saveNode({skill:{name:file.name.replace(/\.(md|markdown)$/i,''),content}});if(saved){showSkill();toast('Skill 已导入并保存')}}catch(e){toast(e.message)}};input.click()}
async function restoreSkill(){const saved=await saveNode({skill:null});if(saved){showSkill();toast('已恢复默认 Skill')}}
function exportDeliverable(){download(state.workspace.deliverable||'',department().nodes[state.node][2],'text/markdown');toast('交付物已导出')}
function resetNode(){modal('重置节点草稿',`<p>清空当前节点的输入和交付物，保留 Skill。操作日志保留已有操作记录，其他节点不受影响。</p>`,`<span>确认后保存清空结果</span>${button('清空草稿','confirm-reset-node','primary')}`)}
async function confirmResetNode(){await saveNode({inputs:'',deliverable:''});closeModal();toast('节点草稿已清空')}
function saveSettingsEvents(){const select=$('#user-role');if(select)select.onchange=()=>$('#home-preview').textContent=workspaceLabel(state.catalog.roles.find(r=>r.id===select.value).workspace)}
async function handleAction(code){const [action,a,b,c,e]=code.split(':');try{
 if(action==='content'){await ProjectContentUI.action(a,b,c,e);return}
 if(action==='library'){await SkillWorkbench.action(a,b,c);return}
 if(action==='manage-nodes'){confirmNavigation(()=>ProjectNodeManager.open().catch(e=>toast(e.message)));return}
 if(action==='node-manager'){await ProjectNodeManager.action(a,b,c);return}
 if(action==='node-history'){const key=a+':'+b,w=await api(root()+'/workspace?node='+encodeURIComponent(key));modal('节点历史记录',`<p>已归档，只读查看。</p><h3>交付物</h3><pre class="history-text">${esc(w.deliverable||'暂无交付物')}</pre><h3>操作日志 · 北京时间</h3>${w.events.map(e=>`<p>${beijing(e.created_at)} ${esc(e.detail)}</p>`).join('')}`);return}
 if(action==='view'){confirmNavigation(async()=>{if(a==='home')return openHome(state.prefs.default_workspace==='overview'?state.dept:state.prefs.default_workspace);++navSequence;state.view=a;state.workspace=null;state.dirty=false;if(a==='admin')await TeamAdmin.load();if(a==='skills'&&state.project)await SkillWorkbench.load();if(a==='content'&&state.project)await ProjectContentUI.load();render()})}
 else if(action==='logout')await TeamLogin.logout()
 else if(action==='login-refresh')location.reload()
 else if(action==='auth-view')await TeamLogin.show(null,a)
 else if(action==='change-password'){closeModal();TeamLogin.passwordDialog()}
 else if(action==='home')confirmNavigation(()=>openHome(a))
 else if(action==='theme')StudioThemes.select(a)
 else if(action.startsWith('admin-'))await TeamAdmin.action(action,a,b)
 else if(action==='dept')confirmNavigation(()=>openDepartment(a,0))
 else if(action==='node')confirmNavigation(()=>openDepartment(a,Number(b)))
 else if(action==='toggle-sidebar'){state.collapsed=!state.collapsed;localStorage.setItem('studioflow-collapsed',String(state.collapsed));document.body.classList.toggle('collapsed',state.collapsed)}
 else if(action==='studios')confirmNavigation(()=>pickerOpen('studios').catch(e=>toast(e.message)))
 else if(action==='projects')confirmNavigation(()=>pickerOpen(state.studio?'projects':'studios').catch(e=>toast(e.message)))
 else if(action==='close')closeModal()
 else if(action==='new-studio'||action==='new-project')confirmNavigation(()=>createForm(action==='new-studio'?'studio':'project'))
 else if(action==='create-studio'||action==='create-project')await createEntity(action==='create-studio'?'studio':'project')
 else if(action==='pick-studios')await chooseStudio(a)
 else if(action==='pick-projects')await chooseProject(picker.items.find(x=>x.id===a))
 else if(action==='picker-page'){picker.page+=Number(a);await loadPicker()}
 else if(action==='user-settings')confirmNavigation(()=>{userSettings();saveSettingsEvents()})
 else if(action==='save-user'){if(state.dirty)throw Error('请先保存当前节点，再修改身份');await saveUser()}
 else if(action==='discard'){const callback=discardAction;state.dirty=false;closeModal();if(callback)await callback()}
 else if(action==='pipeline')pipeline()
 else if(action==='skill-filter'){state.skillFilter=a;render({keepScroll:true})}
 else if(action==='skill')showSkill()
 else if(action==='select-skill')await openSkillPicker()
 else if(action==='import-skill')importSkill()
 else if(action==='export-skill')await downloadSkill()
 else if(action==='handoff-skill')await handoffSkill()
 else if(action==='copy-handoff')await copyHandoff()
 else if(action==='restore-skill')await restoreSkill()
 else if(action==='toggle-links')$('#links-zone').hidden=!$('#links-zone').hidden
 else if(action==='toggle-files')$('#files-zone').hidden=!$('#files-zone').hidden
 else if(action==='import-links')await importLinks()
 else if(action==='upstream')await upstream()
 else if(action==='take-upstream'){await takeUpstream(a,b)}
 else if(action==='save-node')await saveNode()
 else if(action==='run-node'){if(state.dirty)throw Error('请先保存当前输入');if(['queued','running'].includes(state.departmentJob?.status))return;clearTimeout(state.jobPollTimer);const context=nodeContext(),job=await api(root()+'/workspace/execute?node='+encodeURIComponent(nodeKey()),{revision:state.workspace.revision});if(sameNode(context)){state.departmentJob=job;render({keepScroll:true});if(['queued','running'].includes(job.status))pollDepartmentJob(context);else if(job.status==='completed'){state.workspace=job.result.workspace;await reloadSummary();render({keepScroll:true});toast('执行完成，交付物等待人工审核')}else toast(job.error||'部门执行未完成')}}
 else if(action==='review-node')reviewNode()
 else if(action==='decide')await decideNode(a)
 else if(action==='export-deliverable')exportDeliverable()
 else if(action==='reset-node')resetNode()
 else if(action==='confirm-reset-node')await confirmResetNode()
 else if(action==='model-source')await switchSource(a)
 else if(action==='discover-models')await discoverModels()
 else if(action==='save-relay')await saveRelay()
 else if(action==='save-custom')await saveCustom()
 else if(action==='test-task')confirmNavigation(()=>{++navSequence;state.workspace=null;state.testTask=a;state.testStage=undefined;state.dept='testing';state.view='department';render()})
 else if(action==='goto'){closeModal();confirmNavigation(()=>openDepartment(a,Number(b)).catch(e=>toast(e.message)))}
 }catch(e){toast(e.message)}}
document.addEventListener('click',event=>{const target=event.target.closest('[data-action]');if(target){event.preventDefault();if(!target.disabled)handleAction(target.dataset.action)}else if(event.target.classList.contains('modal-backdrop'))closeModal()});
document.addEventListener('input',event=>{if(event.target.id==='picker-search'){picker.query=event.target.value;picker.page=1;loadPicker().catch(e=>toast(e.message))}if(event.target.id==='node-inputs'||event.target.id==='node-deliverable'){markDirty()}});
document.addEventListener('change',async event=>{if(event.target.id==='source-file'){try{await importLocal(event.target.files[0])}catch(e){toast(e.message)}}});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&state.modal){event.preventDefault();closeModal();return}if(state.modal){if(event.key==='Tab'){const items=[...$('.modal').querySelectorAll('button,input,select,textarea,a[href]')].filter(x=>!x.disabled&&!x.hidden),first=items[0],last=items.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}return;}if((event.metaKey||event.ctrlKey)&&event.key==='s'&&state.dirty){event.preventDefault();saveNode().catch(e=>toast(e.message))}});
async function boot(){try{
 state.session=await api('/api/auth/session');if(state.session.user.status!=='active'){await TeamLogin.show(state.session);return}
 document.body.classList.remove('auth-mode');
 state.catalog=await api('/api/studio-catalog');state.integrations=(await api('/api/integrations')).items;state.studios=(await api('/api/studios')).items;state.prefs=await api('/api/me/preferences');
 state.studio=state.studios.find(x=>x.id===state.prefs.active_studio_id)||state.studios[0]||null;
 if(!state.studio){if(state.session.user.id!=='local'&&state.session.user.global_role!=='project_lead'){await TeamLogin.show(state.session);return}state.capabilities=await api('/api/me/capabilities');render();return}
 if(state.prefs.active_studio_id!==state.studio.id)state.prefs=await api('/api/studios/'+state.studio.id+'/enter',{});
 try{state.model=await api('/api/ai-models')}catch(error){toast('模型配置暂不可读：'+error.message)}
 state.capabilities=await api('/api/me/capabilities?studio='+state.studio.id);
 const saved=state.prefs.project_id;
 if(saved)state.project=await api('/api/studios/'+state.studio.id+'/projects/'+saved);
 else state.project=(await api('/api/studios/'+state.studio.id+'/projects?size=5')).items[0]||null;
 if(state.project){state.prefs=await api(root()+'/enter',{});await reloadSummary()}
 await goHome();
 }catch(e){if(e.status===401){await TeamLogin.show();return}$('#content').innerHTML=`<section class="panel empty-state"><h3>工作室加载失败</h3><p>${esc(e.message)}</p><button onclick="location.reload()">重试</button></section>`}}

StudioThemes.apply();
boot();

window.addEventListener('beforeunload',event=>{if(state.dirty||state.saving){event.preventDefault();event.returnValue=''}});
window.addEventListener('message',async event=>{
 const data=event.data,frame=$('#testing-frame');
 if(event.origin!==location.origin||event.source!==frame?.contentWindow||data?.type!=='studioflow:test-update'||data.studio!==state.studio?.id||data.project!==state.project?.id)return;
 state.testTask=data.task;state.testStage=data.stage;
 try{await reloadSummary();sideAndTop()}catch(error){toast(error.message)}
});
