/* Testing-specific UI; persistence and authorization belong to the platform API. */
'use strict';
const QA_CaseLibrary={view:'workspace',versions:[],version:'all',page:1,size:20,q:'',status:'',filterVersion:'',result:null,loading:false,error:'',sequence:0,uiSequence:0,draft:null,detail:null,detailPage:1,pending:false};
function QA_libraryPath(){return '/api/projects/'+project.id+'/testing-library'}
function QA_libraryCanCreate(){return !!(testingCapabilities?.nodes?.['testing:0']?.view&&testingCapabilities?.nodes?.['testing:0']?.edit&&testingCapabilities?.content?.testing?.create)}
function QA_libraryCanDelete(){return !!(testingCapabilities?.nodes?.['testing:0']?.view&&testingCapabilities?.nodes?.['testing:0']?.delete&&testingCapabilities?.content?.testing?.delete)}
function QA_libraryCanCopy(){const n=testingCapabilities?.nodes?.['testing:0']||{};return QA_libraryCanCreate()&&n.export&&n.import&&n.skill_view&&n.skill_export&&n.skill_import}
function QA_libraryOptions(selected,includeAll=false){return (includeAll?'<option value="">全部版本</option><option value="unassigned" '+(selected==='unassigned'?'selected':'')+'>未分配版本</option>':'')+QA_CaseLibrary.versions.map(v=>'<option value="'+v.id+'" '+(selected===v.id?'selected':'')+'>'+escapeHtml(v.name)+'</option>').join('')}
function QA_libraryToolbar(){
 const state=QA_CaseLibrary,allowed=testingCapabilities?.nodes?.['testing:0']?.view;
 const manage='<button class="qa-version-manage" onclick="QA_libraryManage()" '+(!allowed?'disabled title="需要用例节点查看权限"':'')+'>版本管理</button>';
 const nav='<div class="qa-library-nav" aria-label="测试工作区切换"><button type="button" aria-pressed="'+(state.view==='workspace')+'" onclick="QA_libraryShow(\'workspace\')">当前工作台</button><button type="button" aria-pressed="'+(state.view==='library')+'" '+(!allowed?'disabled title="需要用例节点查看权限"':'')+' onclick="QA_libraryShow(\'library\')">用例库</button></div>';
 if(state.view==='library')return '<div class="qa-library-toolbar">'+nav+manage+'<span class="qa-library-explanation">自动保存 · 本地存储 · 不自动上传公区</span><button onclick="QA_libraryNew()" '+(!QA_libraryCanCreate()?'disabled title="需要用例编辑和测试内容创建权限"':'')+'>新建测试批次</button></div>';
 const version=QA_boundFlow?'':'<select class="qa-version-picker" aria-label="工作台版本" onchange="QA_librarySelectVersion(this.value)"><option value="all" '+(state.version==='all'?'selected':'')+'>全部版本</option><option value="unassigned" '+(state.version==='unassigned'?'selected':'')+'>未分配版本</option>'+QA_libraryOptions(state.version)+'</select>';
 const visible=tasks.filter(t=>state.version==='all'||(state.version==='unassigned'?!t.version_id:t.version_id===state.version)||QA_boundFlow);
 return '<div class="qa-library-toolbar">'+nav+version+manage+'<div class="task-selector"><select aria-label="测试批次" onchange="selectTask(this.value)" '+(!visible.length||QA_boundFlow?'disabled':'')+'>'+(visible.length?visible.map(t=>'<option value="'+t.id+'" '+(task?.id===t.id?'selected':'')+'>'+escapeHtml(((state.version==='all'||QA_boundFlow)?(t.version_name||'未分配版本')+' · ':'')+t.title)+'</option>').join(''):'<option>此版本暂无测试批次</option>')+'</select><button onclick="QA_libraryNew()" '+(!QA_libraryCanCreate()?'disabled title="需要用例编辑和测试内容创建权限"':'')+'>新建测试批次</button></div></div>';
}
async function QA_libraryShow(view){
 if(view===QA_CaseLibrary.view)return;
 if(view==='library'){QA_CaseLibrary.draft=QA_captureWorkspaceState();QA_CaseLibrary.view=view;render();await QA_libraryLoad()}
 else{QA_CaseLibrary.view='workspace';render();if(QA_CaseLibrary.draft)QA_restoreWorkspaceState(QA_CaseLibrary.draft)}
}
async function QA_librarySelectVersion(id){
 QA_CaseLibrary.version=id;
 const match=tasks.find(t=>id==='all'||(id==='unassigned'?!t.version_id:t.version_id===id));
 if(match)await selectTask(match.id);else{task=null;render()}
}
async function QA_libraryLoad(){
 if(!project)return;const state=QA_CaseLibrary,p=project.id,seq=++state.sequence;state.loading=true;state.error='';
 const query=new URLSearchParams({page:state.page,size:state.size,q:state.q,version:state.filterVersion,status:state.status});
 try{const [result,versions]=await Promise.all([api(QA_libraryPath()+'/cases?'+query),api(QA_libraryPath()+'/versions')]);if(seq!==state.sequence||project?.id!==p)return;state.result=result;state.versions=versions.items;
  const last=Math.max(1,Math.ceil(result.total/state.size));if(state.page>last){state.page=last;return QA_libraryLoad()}
 }catch(e){if(seq===state.sequence&&project?.id===p){state.error=e.message;state.result=null}}
 finally{if(seq===state.sequence&&project?.id===p){state.loading=false;if(state.view==='library')QA_libraryUpdate()}}
}
function QA_libraryUpdate(){const versionSelect=document.querySelector('[aria-label="用例库版本"]');if(versionSelect)versionSelect.innerHTML=QA_libraryOptions(QA_CaseLibrary.filterVersion,true);const node=document.querySelector('[data-qa-library-content]');if(node)node.innerHTML=QA_libraryContent()}
function QA_librarySearch(){QA_CaseLibrary.q=$('qa-library-search').value;QA_CaseLibrary.page=1;QA_libraryLoad()}
function QA_libraryFilter(field,value){QA_CaseLibrary[field]=field==='size'?Number(value):value;QA_CaseLibrary.page=1;QA_libraryLoad()}
function QA_libraryPage(delta){QA_CaseLibrary.page+=delta;QA_libraryLoad()}
function QA_libraryContent(){
 const state=QA_CaseLibrary,r=state.result;
 if(state.loading&&!r)return '<div class="focus-empty" role="status">正在读取用例库…</div>';
 if(state.error)return '<div class="focus-empty" role="alert">'+escapeHtml(state.error)+' <button onclick="QA_libraryLoad()">重试</button></div>';
 if(!r)return '<div class="focus-empty">进入用例库后自动读取已保存用例。</div>';
 const pages=Math.max(1,Math.ceil(r.total/state.size));
 return '<div class="qa-library-table-wrap"><table data-qa-library-table><thead><tr><th>用例集 / 测试批次</th><th>版本</th><th>用例数</th><th>用例状态</th><th>测试进度</th><th>保存时间</th><th>操作</th></tr></thead><tbody>'+r.items.map(row=>'<tr><td><strong>'+escapeHtml(row.title)+'</strong><small>数据修订 '+row.task_revision+' · 本地快照</small></td><td>'+escapeHtml(row.version_name||'未分配版本')+'</td><td>'+row.case_count+'</td><td><span class="qa-library-state '+(row.case_status==='confirmed'?'confirmed':'')+'">'+(row.case_status==='confirmed'?'已确认':'草稿')+'</span></td><td>'+escapeHtml(row.task_status==='completed'?'已结束':row.task_status==='cancelled'?'已取消':names[row.stage]+'节点')+'</td><td class="qa-library-time">'+escapeHtml(QA_libraryTime(row.created_at))+'</td><td><div class="qa-library-row-actions"><button onclick="QA_libraryOpen(\''+row.task_id+'\')">打开</button><button onclick="QA_librarySnapshot(\''+row.snapshot_id+'\')">查看快照</button><button '+(!QA_libraryCanCopy()?'disabled title="需要用例导入导出及 Skill 查看、导入导出权限"':'')+' onclick="QA_libraryNew(\''+row.snapshot_id+'\')">复制</button><button '+(!QA_libraryCanCreate()?'disabled title="需要用例编辑和测试内容创建权限"':'')+' onclick="QA_libraryAssign(\''+row.task_id+'\')">归属版本</button></div></td></tr>').join('')+(r.items.length?'':'<tr><td colspan="7"><div class="focus-empty"><strong>'+(state.q||state.status||state.filterVersion?'没有符合筛选条件的用例集':'还没有保存的用例集')+'</strong><p>生成或编辑成功后自动保存到这里，草稿也会保留。新批次无需清空旧用例。</p></div></td></tr>')+'</tbody></table></div><div class="qa-library-pagination"><span>共 '+r.total+' 个用例集'+(state.loading?' · 更新中…':'')+'</span><div><label>每页 <select aria-label="每页用例集" onchange="QA_libraryFilter(\'size\',this.value)">'+[10,20,50,100].map(n=>'<option '+(state.size===n?'selected':'')+'>'+n+'</option>').join('')+'</select></label><button aria-label="上一页" '+(state.page<=1||state.loading?'disabled':'')+' onclick="QA_libraryPage(-1)">‹</button><span>'+state.page+' / '+pages+'</span><button aria-label="下一页" '+(state.page>=pages||state.loading?'disabled':'')+' onclick="QA_libraryPage(1)">›</button></div></div>';
}
function QA_libraryTime(value){return value?new Date(value.replace(' ','T')+'Z').toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'—'}
function QA_libraryView(){const s=QA_CaseLibrary;return '<section class="panel qa-library-panel"><div class="qa-library-header"><div><h2>项目用例库</h2><p>生成结果自动保存为草稿；确认与测试进度分别记录。历史快照不会被新版本覆盖。</p></div><button onclick="QA_libraryLoad()">刷新</button></div><div class="qa-library-filters"><input id="qa-library-search" aria-label="搜索用例集" placeholder="搜索用例集 / 批次名称" value="'+escapeHtml(s.q)+'" onkeydown="if(event.key===\'Enter\')QA_librarySearch()"><button onclick="QA_librarySearch()">搜索</button><select aria-label="用例库版本" onchange="QA_libraryFilter(\'filterVersion\',this.value)">'+QA_libraryOptions(s.filterVersion,true)+'</select><select aria-label="用例状态" onchange="QA_libraryFilter(\'status\',this.value)"><option value="">全部用例状态</option><option value="draft" '+(s.status==='draft'?'selected':'')+'>草稿</option><option value="confirmed" '+(s.status==='confirmed'?'selected':'')+'>已确认</option></select></div><div data-qa-library-content>'+QA_libraryContent()+'</div></section>'}
async function QA_libraryOpen(id){
 if(QA_boundFlow&&id!==QA_boundTask){QA_libraryNavigate(id);return}
 QA_CaseLibrary.view='workspace';QA_CaseLibrary.version='all';await selectTask(id);selectedStage=0;render()
}
function QA_libraryNavigate(id){const u=new URL('/',location.origin);u.search=new URLSearchParams({studio:studioId,project:project.id,node:'testing:0',task:id});if(embedded)parent.location.assign(u.href);else location.assign(u.href)}
let QA_libraryForm=null;
async function QA_libraryNew(snapshotId='',assignTask=''){
 if(!QA_libraryCanCreate())return notice('需要用例编辑和测试内容创建权限');
 if(snapshotId&&!QA_libraryCanCopy())return notice('需要用例导入导出及 Skill 查看、导入导出权限');
 const p=project.id,seq=++QA_CaseLibrary.uiSequence;
 try{const v=await api(QA_libraryPath()+'/versions');if(project?.id!==p||seq!==QA_CaseLibrary.uiSequence)return;QA_CaseLibrary.versions=v.items;
  let snapshot=null;if(snapshotId){snapshot=await api(QA_libraryPath()+'/cases/'+snapshotId);if(project?.id!==p||seq!==QA_CaseLibrary.uiSequence)return;}
  QA_libraryForm={project:p,snapshotId,assignTask};
  const selected=task?.version?.id||'';
  modal(assignTask?'归属项目版本':snapshotId?'复制为新测试批次':'新建测试批次',
   '<p class="small muted">'+(assignTask?'归属调整不清空用例，已有历史快照保持原版本信息。':snapshotId?'复制需求、用例与原 Skill 为独立草稿；不继承审核、执行结果、Bug 状态或回归结论。':'新批次从用例节点开始，已有版本与测试批次完整保留。')+'</p>'+
   '<div class="field"><label for="qa-batch-version">项目版本</label><select id="qa-batch-version" onchange="QA_libraryVersionForm()">'+QA_libraryOptions(selected)+'<option value="__new__" '+(!selected?'selected':'')+'>＋ 新建版本</option></select></div>'+
   '<div class="field" id="qa-batch-version-name-field"><label for="qa-batch-version-name">新版本名称</label><input id="qa-batch-version-name" maxlength="60" placeholder="例如：1.1.0"></div>'+
   (assignTask?'':'<div class="field"><label for="qa-batch-title">测试批次名称</label><input id="qa-batch-title" maxlength="120" placeholder="例如：新增关卡 · 第 1 轮"></div>')+
   (snapshot&&!snapshot.skill?.content?'<label class="qa-library-copy-consent"><input type="checkbox" id="qa-copy-current-skill"> 这个旧快照未保存原 Skill。我同意使用当前默认 Skill 作为新批次规则，复制后重新评审。</label>':'')+
   '<p class="small" id="qa-batch-form-error" role="alert"></p><div class="qa-library-form-actions"><button onclick="closeModal()">取消</button><button id="qa-batch-create" class="primary" onclick="QA_librarySubmit()">'+(assignTask?'保存归属':'创建并进入')+'</button></div>');QA_libraryVersionForm();
 }catch(e){notice(e.message)}
}
async function QA_libraryAssign(id){
 const p=project.id,seq=++QA_CaseLibrary.uiSequence;
 try{const t=await api('/api/projects/'+p+'/tasks/'+id);if(project?.id!==p||seq!==QA_CaseLibrary.uiSequence)return;
  await QA_libraryNew('',id);if(QA_libraryForm?.assignTask===id){QA_libraryForm.revision=t.revision;$('qa-batch-version').value=t.version?.id||'__new__';QA_libraryVersionForm()}
 }catch(e){notice(e.message)}
}
function QA_libraryVersionForm(){const field=$('qa-batch-version-name-field');if(field)field.hidden=$('qa-batch-version').value!=='__new__'}
async function QA_librarySubmit(){
 const c=QA_libraryForm;if(!c||QA_CaseLibrary.pending||project?.id!==c.project)return;
 const version=$('qa-batch-version').value,body=version==='__new__'?{version_name:$('qa-batch-version-name').value}:{version_id:version};
 if(!c.assignTask)body.title=$('qa-batch-title').value;
 if(c.snapshotId){body.snapshot_id=c.snapshotId;if($('qa-copy-current-skill'))body.use_current_skill=$('qa-copy-current-skill').checked;}
 if(c.assignTask)body.revision=c.revision;
 QA_CaseLibrary.pending=true;const button=$('qa-batch-create');button.disabled=true;button.textContent='正在保存…';
 try{
  const updated=await api(QA_libraryPath()+'/batches'+(c.assignTask?'/'+c.assignTask+'/version':''),body);
  if(project?.id!==c.project)return;
  const [batchResult,versions]=await Promise.all([api('/api/projects/'+project.id+'/tasks'),api(QA_libraryPath()+'/versions')]);
  tasks=QA_boundFlow?batchResult.items.filter(t=>t.id===QA_boundTask):batchResult.items;QA_CaseLibrary.versions=versions.items;
  if(QA_libraryForm!==c){notice('操作已保存，可从批次列表或用例库查看');return;}
  closeModal();QA_libraryForm=null;
  if(c.assignTask){if(task?.id===c.assignTask)task=updated;render();if(QA_CaseLibrary.view==='library')await QA_libraryLoad();notice('版本归属已保存，历史快照未改写')}
  else if(QA_boundFlow){QA_libraryNavigate(updated.id)}
  else{QA_CaseLibrary.view='workspace';QA_CaseLibrary.version=updated.version.id;QA_CaseLibrary.draft=null;task=updated;selectedStage=0;casePage=1;QA_caseSearch='';render();notice(c.snapshotId?'已复制为独立草稿，请重新评审':'新批次已创建，旧用例完整保留')}
 }catch(e){if(project?.id===c.project&&$('qa-batch-form-error'))$('qa-batch-form-error').textContent=e.message}
 finally{QA_CaseLibrary.pending=false;if(button.isConnected){button.disabled=false;button.textContent=c.assignTask?'保存归属':'创建并进入'}}
}
async function QA_librarySnapshot(id){
 const p=project.id,seq=++QA_CaseLibrary.uiSequence;
 try{const result=await api(QA_libraryPath()+'/cases/'+id);if(project?.id!==p||seq!==QA_CaseLibrary.uiSequence)return;QA_CaseLibrary.detail=result;QA_CaseLibrary.detailPage=1;QA_libraryRenderSnapshot()}catch(e){notice(e.message)}
}
function QA_libraryRenderSnapshot(){
 const d=QA_CaseLibrary.detail;if(!d)return;const cases=d.artifact.cases,start=(QA_CaseLibrary.detailPage-1)*20;
 modal('用例集 · 只读快照','<p class="small muted">'+escapeHtml(d.version?.name||'未分配版本')+' · 数据修订 '+d.task_revision+' · '+(d.case_status==='confirmed'?'已确认':'草稿')+' · 北京时间 '+escapeHtml(QA_libraryTime(d.created_at))+'</p><p class="small muted">这是保存时的内容，不代表测试已通过。打开工作台查看当前批次进度。</p><div class="field"><label for="qa-snapshot-history">历史快照</label><select id="qa-snapshot-history" onchange="QA_librarySnapshot(this.value)">'+d.history.map(h=>'<option value="'+h.id+'" '+(h.id===d.id?'selected':'')+'>数据修订 '+h.task_revision+' · '+(h.case_status==='confirmed'?'已确认':'草稿')+' · '+QA_libraryTime(h.created_at)+'</option>').join('')+'</select></div><details><summary>需求快照 · '+d.requirements.length+' 个来源</summary>'+d.requirements.map(r=>'<details><summary>'+escapeHtml(r.source)+'</summary><pre>'+escapeHtml(r.content)+'</pre></details>').join('')+'</details><details><summary>Skill 快照 · '+escapeHtml(d.skill.name||'未记录')+'</summary><pre>'+escapeHtml(d.skill.content||'未保存原正文，不会假装已还原原 Skill')+'</pre></details><details><summary>代码基线引用</summary><pre>'+escapeHtml(Object.keys(d.baseline).length?JSON.stringify(d.baseline,null,2):'没有可展示的基线；不代表代码已经检测')+'</pre></details><div class="qa-snapshot-cases">'+cases.slice(start,start+20).map(c=>'<details><summary>'+escapeHtml(c.id)+' · '+escapeHtml(c.title)+'</summary><p>前置条件：'+escapeHtml((c.preconditions||[]).join('；'))+'</p><ol>'+c.steps.map(s=>'<li>'+escapeHtml(s.action)+'<br>预期：'+escapeHtml(s.expected)+'</li>').join('')+'</ol></details>').join('')+'</div><div class="qa-library-pagination"><span>共 '+cases.length+' 条 · 每页 20 条</span><div><button '+(start===0?'disabled':'')+' onclick="QA_CaseLibrary.detailPage--;QA_libraryRenderSnapshot()">上一页</button><span>'+QA_CaseLibrary.detailPage+' / '+Math.max(1,Math.ceil(cases.length/20))+'</span><button '+(start+20>=cases.length?'disabled':'')+' onclick="QA_CaseLibrary.detailPage++;QA_libraryRenderSnapshot()">下一页</button></div></div>');
}
function QA_generationBlockedReason(){
 if(!task)return '';
 if(task.stage!==0||taskEnded())return '当前批次'+(taskEnded()?'已结束':'已进入'+names[task.stage]+'节点')+'，这里保留历史需求与用例。生成新版本请新建测试批次。';
 return '';
}
function QA_generationBlockedView(){const reason=QA_generationBlockedReason();return reason?'<div class="qa-generation-notice" data-qa-generation-blocked role="status"><span>'+escapeHtml(reason)+'</span><button onclick="QA_libraryNew()" '+(!QA_libraryCanCreate()?'disabled':'')+'>新建测试批次</button></div>':''}

let QA_versionManager=null;
async function QA_libraryManage(deleteCurrent=false){
 const p=project.id,seq=++QA_CaseLibrary.uiSequence;
 try{
  const [versions,batches]=await Promise.all([api(QA_libraryPath()+'/versions'),api(QA_libraryPath()+'/batches')]);
  if(project?.id!==p||seq!==QA_CaseLibrary.uiSequence)return;
  QA_CaseLibrary.versions=versions.items;
  QA_versionManager={project:p,versions:versions.items,batches:batches.items,version:QA_CaseLibrary.version==='all'?'':QA_CaseLibrary.version,q:'',page:1,editing:null,pending:false,error:''};
  QA_libraryRenderManager();
  if(deleteCurrent&&versions.items.some(v=>v.id===QA_CaseLibrary.version))await QA_libraryDeletePreview('version',QA_CaseLibrary.version);
 }catch(e){notice(e.message)}
}
function QA_libraryRenderManager(){
 const m=QA_versionManager;if(!m||project?.id!==m.project)return;
 if(m.deleting){QA_libraryRenderDelete();return}
 const selected=m.versions.find(v=>v.id===m.version),editable=QA_libraryCanCreate();
 const rows=m.batches.filter(t=>(!m.version||(m.version==='unassigned'?!t.version_id:t.version_id===m.version))&&t.title.toLocaleLowerCase().includes(m.q.toLocaleLowerCase()));
 const pages=Math.max(1,Math.ceil(rows.length/10));m.page=Math.min(m.page,pages);
 const edit=m.editing;
 modal('版本管理','<p class="small muted">项目版本与批次名称独立管理。重命名不改变用例或进度；删除前需再次确认。</p><div class="qa-manager-controls"><label>项目版本<select aria-label="管理版本" onchange="QA_libraryManagerFilter(\'version\',this.value)">'+QA_libraryOptions(m.version,true)+'</select></label><button onclick="QA_libraryManagerEdit(\'version\')" '+((!selected&&m.version!=='unassigned')||!editable||m.pending?'disabled title="请选择一个版本；修改需要用例编辑和测试内容创建权限"':'')+'>'+(m.version==='unassigned'?'设置项目版本':'重命名版本')+'</button>'+(selected?'<button class="qa-delete-action" onclick="QA_libraryDeletePreview(\'version\',\''+selected.id+'\')" '+(!QA_libraryCanDelete()||m.pending?'disabled title="需要节点删除和测试内容删除权限"':'')+'>删除版本</button>':'')+'</div>'+
  (selected?'<p class="small muted">当前版本：<strong>'+escapeHtml(selected.name)+'</strong> · '+rows.length+' 个匹配批次（含未生成用例的批次）</p>':'')+
  (edit?'<div class="qa-manager-edit">'+(edit.kind==='unassigned'?'<p class="small muted">将本项目 '+m.batches.filter(t=>!t.version_id).length+' 个未分配批次归入版本。可输入新版本名，或选择已有版本。</p><select id="qa-manager-existing" aria-label="归入已有项目版本" onchange="QA_versionManager.editing.existing=this.value"><option value="">新建版本（填写下方名称）</option>'+QA_libraryOptions(edit.existing||'')+'</select>':'')+'<label for="qa-manager-name">'+(edit.kind==='unassigned'?'设置项目版本（批次名称保持不变）':edit.kind==='version'?'新版本名称':'新批次名称')+'</label><div><input id="qa-manager-name" maxlength="'+(edit.kind==='batch'?120:60)+'" value="'+escapeHtml(edit.value)+'" '+(m.pending?'disabled':'')+' oninput="QA_versionManager.editing.value=this.value" onkeydown="if(event.key===\'Enter\')QA_libraryManagerSave()"><button class="primary" onclick="QA_libraryManagerSave()" '+(m.pending?'disabled':'')+'>'+(m.pending?'保存中…':'保存名称')+'</button><button onclick="QA_versionManager.editing=null;QA_versionManager.error=\'\';QA_libraryRenderManager()" '+(m.pending?'disabled':'')+'>取消修改</button></div><p role="alert" class="small qa-manager-error">'+escapeHtml(m.error)+'</p></div>':'')+
  '<div class="qa-manager-search"><input id="qa-manager-search" aria-label="搜索测试批次" placeholder="搜索批次名称" value="'+escapeHtml(m.q)+'" onkeydown="if(event.key===\'Enter\')QA_libraryManagerFilter(\'q\',this.value)"><button onclick="QA_libraryManagerFilter(\'q\',document.getElementById(\'qa-manager-search\').value)">搜索批次</button></div><div class="qa-manager-list">'+rows.slice((m.page-1)*10,m.page*10).map(t=>'<div class="qa-manager-batch"><div><strong>'+escapeHtml(t.title)+'</strong><p>'+escapeHtml(t.version_name||'未分配版本')+' · '+(t.status==='completed'?'已结束':t.status==='cancelled'?'已取消':escapeHtml(names[t.stage])+'节点')+'</p></div><div><button onclick="QA_libraryManagerEdit(\'batch\',\''+t.id+'\')" '+(!editable||m.pending?'disabled title="需要用例编辑和测试内容创建权限"':'')+'>重命名批次</button><button class="qa-delete-action" onclick="QA_libraryDeletePreview(\'batch\',\''+t.id+'\')" '+(!QA_libraryCanDelete()||m.pending?'disabled title="需要节点删除和测试内容删除权限"':'')+'>删除批次</button><button onclick="closeModal();QA_libraryOpen(\''+t.id+'\')">打开批次</button></div></div>').join('')+(rows.length?'':'<p class="focus-empty">没有匹配的测试批次；尚未生成用例的批次也会显示在这里。</p>')+'</div><div class="qa-library-pagination"><span>共 '+rows.length+' 个批次 · 每页 10 个</span><div><button '+(m.page===1?'disabled':'')+' onclick="QA_versionManager.page--;QA_libraryRenderManager()">上一页</button><span>'+m.page+' / '+pages+'</span><button '+(m.page>=pages?'disabled':'')+' onclick="QA_versionManager.page++;QA_libraryRenderManager()">下一页</button></div></div>');
}
function QA_libraryManagerFilter(key,value){if(!QA_versionManager||QA_versionManager.pending)return;QA_versionManager[key]=value;if(key==='version'){QA_versionManager.editing=null;QA_versionManager.error=''}QA_versionManager.page=1;QA_libraryRenderManager()}
function QA_libraryManagerEdit(kind,id){
 const m=QA_versionManager;if(!m||m.pending||!QA_libraryCanCreate())return;
 if(kind==='version'&&m.version==='unassigned'){m.editing={kind:'unassigned',value:'',existing:''};m.error='';QA_libraryRenderManager();$('qa-manager-name')?.focus();return}
 const row=kind==='version'?m.versions.find(v=>v.id===m.version):m.batches.find(t=>t.id===id);if(!row)return;
 m.editing={kind,id:row.id,original:kind==='version'?row.name:row.title,value:kind==='version'?row.name:row.title};m.error='';QA_libraryRenderManager();$('qa-manager-name')?.focus();$('qa-manager-name')?.select()
}
async function QA_libraryManagerSave(){
 const m=QA_versionManager;if(!m?.editing||m.pending||m.project!==project?.id)return;
 const edit=m.editing,name=$('qa-manager-name').value;m.editing.value=name;m.pending=true;m.error='';QA_libraryRenderManager();
 try{
  const body=edit.kind==='version'?{name,expected_name:edit.original}:{title:name,expected_title:edit.original};
  let assigned=null;if(edit.kind==='unassigned'){assigned=await api(QA_libraryPath()+'/unassigned-version',edit.existing?{version_id:edit.existing}:{version_name:name})}else{await api(QA_libraryPath()+'/'+(edit.kind==='version'?'versions':'batches')+'/'+edit.id+'/rename',body)}
  if(project?.id!==m.project)return;
  const [versions,batches]=await Promise.all([api(QA_libraryPath()+'/versions'),api(QA_libraryPath()+'/batches')]);
  if(project?.id!==m.project)return;
  QA_CaseLibrary.versions=versions.items;tasks=QA_boundFlow?batches.items.filter(t=>t.id===QA_boundTask):batches.items;
  if(task){const row=batches.items.find(t=>t.id===task.id);if(row){task.title=row.title;task.version=row.version_id?{id:row.version_id,name:row.version_name}:null}}
  m.versions=versions.items;m.batches=batches.items;m.editing=null;m.pending=false;if(assigned){m.version=assigned.version.id;if(QA_CaseLibrary.version==='unassigned')QA_CaseLibrary.version=assigned.version.id;if(QA_CaseLibrary.filterVersion==='unassigned')QA_CaseLibrary.filterVersion=assigned.version.id}render();
  if(QA_CaseLibrary.view==='library')await QA_libraryLoad();
  // A closed modal stays closed, even if the request completes later.
  if(document.getElementById('qa-manager-search')&&QA_versionManager===m)QA_libraryRenderManager();
  notice(edit.kind==='unassigned'?'项目版本已设置，批次名称保持不变':'名称已更新，历史快照保持原样');
 }catch(e){m.pending=false;m.error=e.message;if(document.getElementById('qa-manager-search')&&QA_versionManager===m)QA_libraryRenderManager()}
}

async function QA_libraryDeletePreview(kind,id){
 const m=QA_versionManager;if(!m||m.pending||!QA_libraryCanDelete())return;
 const seq=QA_CaseLibrary.uiSequence;m.pending=true;
 try{
  const preview=await api(QA_libraryPath()+'/'+(kind==='version'?'versions':'batches')+'/'+id+'/delete-preview');
  if(m!==QA_versionManager||m.project!==project?.id||seq!==QA_CaseLibrary.uiSequence)return;
  m.pending=false;m.deleting=preview;m.error='';QA_libraryRenderDelete();
 }catch(e){notice(e.message)}finally{m.pending=false}
}
function QA_libraryRenderDelete(){
 const m=QA_versionManager,d=m?.deleting;if(!d)return;
 const version=d.kind==='version';
 modal(version?'确认删除项目版本':'确认删除测试批次',
  '<div id="qa-delete-confirm"><p>确定删除 <strong>'+escapeHtml(d.name)+'</strong>？</p><p class="small muted">'+
  (version?'该版本下 '+d.batches.filter(b=>m.batches.some(active=>active.id===b.id)).length+' 个批次将保留，并归回「未分配版本」。不会连同批次一起删除。':'该批次将从工作台、批次选择和用例库移除。')+
  '历史证据保留在本机，不删除飞书记录。</p><p class="qa-manager-error" role="alert">'+escapeHtml(m.error||'')+
  '</p><div class="qa-library-form-actions"><button onclick="QA_versionManager.deleting=null;QA_libraryRenderManager()" '+(m.pending?'disabled':'')+'>取消</button><button class="qa-delete-confirm" onclick="QA_libraryDeleteConfirm()" '+(m.pending?'disabled':'')+'>'+(m.pending?'删除中…':'确认删除')+'</button></div></div>');
}
async function QA_libraryDeleteConfirm(){
 const m=QA_versionManager,d=m?.deleting;if(!d||m.pending)return;
 m.pending=true;m.error='';QA_libraryRenderDelete();
 try{
  await api(QA_libraryPath()+'/'+(d.kind==='version'?'versions':'batches')+'/'+d.id+'/delete',{confirmed:true,token:d.token});
  if(project?.id!==m.project)return;
  const [versions,batches]=await Promise.all([api(QA_libraryPath()+'/versions'),api(QA_libraryPath()+'/batches')]);
  if(project?.id!==m.project)return;
  const open=!!$('qa-delete-confirm')&&QA_versionManager===m;
  QA_CaseLibrary.versions=versions.items;tasks=QA_boundFlow?batches.items.filter(t=>t.id===QA_boundTask):batches.items;
  if(d.kind==='version'){
   if(QA_CaseLibrary.version===d.id)QA_CaseLibrary.version='unassigned';
   if(QA_CaseLibrary.filterVersion===d.id)QA_CaseLibrary.filterVersion='unassigned';
   m.version='unassigned';
  }
  if(task){const row=batches.items.find(t=>t.id===task.id);
   if(row){task.version=row.version_id?{id:row.version_id,name:row.version_name}:null}
   else{QA_CaseLibrary.draft=null;task=null;selectedStage=0;QA_CaseLibrary.version='all';
    if(tasks.length)task=await api('/api/projects/'+project.id+'/tasks/'+tasks[0].id);
    if(task)selectedStage=task.stage;
   }
  }
  m.versions=versions.items;m.batches=batches.items;m.deleting=null;m.pending=false;m.error='';render();
  if(QA_CaseLibrary.view==='library')await QA_libraryLoad();
  if(open&&$('qa-delete-confirm'))QA_libraryRenderManager();
  notice(d.kind==='version'?'版本已删除，批次已归回未分配版本':'批次已删除');
 }catch(e){m.pending=false;m.error=e.message;if($('qa-delete-confirm')&&QA_versionManager===m)QA_libraryRenderDelete()}
}
