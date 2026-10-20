/* Project-managed structure and records; no arbitrary HTML or executable plugins. */
'use strict';
const ProjectContentUI={
 value:null,
 async load(){const path=root(),data=await api(path+'/content');if(state.project&&root()===path)this.value=data},
 page(){
  const value=this.value;if(!value)return heading('工作台内容','请先选择项目。');
  return heading('让工作台适合你的团队。','按项目管理部门、工具、信息块、资料与手工交付。增删权限由管理员独立下发。','','WORKSPACE CONTENT')+
   `<div class="content-departments">${departments().filter(d=>value.permissions[d.id]).map(d=>{
    const p=value.permissions[d.id],disabled=value.disabled_departments.includes(d.id),rows=value.items.filter(n=>n.department===d.id),base=state.catalog.departments.find(n=>n.id===d.id);
    return `<section class="panel content-department"><div class="between"><div class="row"><span class="dept-symbol" style="${tone(d)}">${icon(d.icon)}</span><h2>${esc(d.title)}</h2>${tag(disabled?'已停用':'已启用',disabled?'':'green')}</div><div class="row">${p.create?button('新增内容','content:add:'+d.id,'','plus'):''}${(disabled?p.create:p.delete)?button(disabled?'启用部门':'停用部门','content:'+(disabled?'enable:':'disable:')+d.id):''}</div></div><div class="content-items">${rows.filter(n=>!n.archived&&n.kind!=='hidden').map(n=>this.row(n,p)).join('')}${base.tools?.map(t=>{const target='tool:'+t.id,hidden=rows.some(n=>n.kind==='hidden'&&n.target===target&&!n.archived);return hidden?'':`<div class="content-item"><div><b>${esc(t.label)}</b><span>默认工具 · ${esc(t.url)}</span></div>${p.delete?button('删除','content:hide:'+d.id+':'+target):''}</div>`}).join('')||''}${base.homepage.focus.map((t,i)=>{const target='focus:'+i,hidden=rows.some(n=>n.kind==='hidden'&&n.target===target&&!n.archived);return hidden?'':`<div class="content-item"><div><b>${esc(t)}</b><span>默认首页信息</span></div>${p.delete?button('删除','content:hide:'+d.id+':'+target):''}</div>`}).join('')}</div>${rows.some(n=>n.kind==='hidden'?!n.archived:n.archived)?`<details><summary>删除与隐藏记录</summary>${rows.filter(n=>n.kind==='hidden'?!n.archived:n.archived).map(n=>`<div class="content-item"><div><b>${esc(n.title)}</b><span>${n.archived?'已归档':'默认条目已隐藏'}</span></div>${p.create?button('恢复','content:'+(n.kind==='hidden'?'unhide:':'restore:')+n.id):''}</div>`).join('')}</details>`:''}</section>`
   }).join('')}</div>`;
 },
 row(n,p){return `<div class="content-item"><div><b>${esc(n.title)}</b><span>${({note:'首页信息块',tool:'工具入口',source:'需求资料',deliverable:'手工交付',hidden:'隐藏记录'})[n.kind]}</span><p>${esc(n.kind==='tool'?n.url:n.body.slice(0,300))}</p></div><div class="row">${n.kind!=='hidden'?button('查看','content:detail:'+n.id):''}${p.delete?button('删除','content:delete:'+n.id):''}</div></div>`},
 async action(operation,arg,extra,last){
  if(operation==='add'){
   this.department=arg;
   modal('新增'+workspaceLabel(arg)+'内容',`<div class="field"><label>类型</label><select id="content-kind"><option value="note">首页信息块</option><option value="tool">工具入口</option><option value="source">需求资料</option><option value="deliverable">手工交付</option></select></div><div class="field"><label>标题</label><input id="content-title" maxlength="120"></div><div class="field"><label>HTTPS 工具地址（工具入口必填）</label><input id="content-url" placeholder="https://"></div><div class="field"><label>正文 / 来源与版本</label><textarea id="content-body" maxlength="100000"></textarea></div>`,button('新增并保存','content:create','primary'));return;
  }
  if(operation==='detail'){
   const n=this.value.items.find(n=>n.id===arg);if(!n)return;
   modal(n.title,`<pre class="history-text">${esc(n.kind==='tool'?n.url:n.body)}</pre>`);return;
  }
  let data={action:operation,revision:this.value.revision};
  if(operation==='create')data={...data,department:this.department,kind:$('#content-kind').value,title:$('#content-title').value,body:$('#content-body').value,url:$('#content-url').value};
  else if(operation==='disable'||operation==='enable'){data.department=arg;if(operation==='disable'&&!confirm('停用当前项目的此部门？历史内容保留，运行中的任务会阻止停用。'))return}
  else if(operation==='hide'){data.department=arg;data.target=extra+':'+last;if(!confirm('从当前项目移除此默认条目？可以在删除记录恢复。'))return}
  else{data.id=arg;if(operation==='delete'&&!confirm('删除此条目？内容会归档保留。'))return}
  const path=root();await api(path+'/content',data);if(root()!==path)return;
  closeModal();await this.load();await reloadSummary();render({keepScroll:true});toast('工作台内容已更新');
 }
};
