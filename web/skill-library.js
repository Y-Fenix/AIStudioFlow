/* Actual project node rules, version history and administrator recycle bin. */
'use strict';
const SkillWorkbench={
 listing:null,detail:null,context:null,binContext:null,history:[],busy:false,
 current(context){return !!state.project&&root()===context.path&&$('.modal')===context.dialog},
 async load(){const path=root(),value=await api(path+'/skills');if(state.project&&root()===path)this.listing=value},
 page(){
  const items=(this.listing?.items||[]).filter(n=>state.skillFilter==='all'||n.node.startsWith(state.skillFilter+':'));
  return heading('团队经验，持续积累。','查看节点实际使用的规则、版本与来源。项目默认规则只影响后续新测试批次。',this.listing?.can_recycle?button('回收站','library:bin','','folder'):'','SKILL WORKBENCH')+
   `<div class="library-filters">${button('全部部门','skill-filter:all',state.skillFilter==='all'?'active':'')}${departments().map(d=>button(d.name,'skill-filter:'+d.id,state.skillFilter===d.id?'active':'')).join('')}</div><div class="skill-grid">${items.map(n=>{
    const d=departments().find(d=>d.id===n.node.split(':')[0]);
    return `<section class="panel skill-card" style="${tone(d)}"><div class="between"><span class="dept-symbol">${icon(d.icon)}</span>${tag(n.status==='active'?'当前规则':'未配置',n.status==='active'?'green':'amber')}</div><button class="skill-detail-title" data-action="library:detail:${n.node}"><h3>${esc(n.node_name)}</h3></button><p>${esc(n.description)}</p><div class="skill-card-meta"><span>上传者 · ${esc(n.uploader)}</span><span>更新 · ${this.time(n.updated_at)}</span></div><div class="between"><span class="small muted">${d.title} · v${n.revision}</span>${button('查看详情','library:detail:'+n.node)}</div></section>`
   }).join('')||'<section class="panel empty-state"><p>当前范围没有可查看的 Skill。</p></section>'}</div>`;
 },
 time(value){return value==null?'未记录':beijing(new Date(value*1000).toISOString())},
 async open(node){
  const path=root();modal('Skill 详情','<p>正在读取规则…</p>');const placeholder=$('.modal');
  const value=await api(path+'/skills?node='+encodeURIComponent(node));
  if(!state.project||root()!==path||$('.modal')!==placeholder)return;
  this.context={path,node};this.detail=value;this.history=value.history;this.draw();
 },
 draw(){
  const n=this.detail,p=n.permissions;
  modal('Skill 详情 · '+definition(n.node).n[0],`<div class="skill-detail-meta"><span>上传者<b>${esc(n.uploader)}</b></span><span>更新时间<b>${this.time(n.updated_at)}</b></span><span>当前版本<b>v${n.revision}</b></span></div><h3>描述</h3><p>${esc(n.description)}</p><h3>当前正文</h3><pre class="history-text skill-current-text">${esc(n.skill.content||'当前规则已删除，请导入或由管理员恢复。')}</pre><div class="between"><h3>更新历史 · ${n.history_total}</h3>${n.next_before!=null?button('查看更早版本','library:older'):''}</div><div class="skill-history">${[...this.history].reverse().map(v=>`<div class="skill-history-row"><div><b>v${v.version}</b><span>${esc(v.uploader)} · ${this.time(v.updated_at)}</span><p>${esc(v.note)}</p></div>${p.export?button('查看 / 导出','library:version:'+v.version):''}</div>`).join('')||'<p class="muted">默认或旧规则暂无已记录的变更历史。</p>'}</div>${p.import?'<div class="field"><label for="skill-update-note">更新说明（导入前填写）</label><textarea id="skill-update-note" maxlength="2000" placeholder="本次修改了什么、为什么修改"></textarea></div>':''}`,
   `<div class="row">${p.delete&&n.status==='active'?button('移入回收站','library:trash'):''}</div><div class="row">${p.export&&n.status==='active'?button('在 Codex 使用','library:handoff','','spark'):''}${p.import?button('导入 Skill','library:import','','upload'):''}${p.export&&n.status==='active'?button('导出 Skill','library:export','','download'):''}</div>`);
  this.context.dialog=$('.modal');
 },
 async action(operation,arg,extra){
  if(operation==='detail'){await this.open(arg+':'+extra);return}
  if(operation==='bin'){await this.bin();return}
  if(this.busy)return;
  if(operation==='restore'||operation==='purge'||operation==='bin-export'){
   const context=this.binContext;if(!context||!this.current(context))return;
   const row=this.binItems.find(n=>n.id===arg);if(!row)return;
   if(operation==='bin-export'){const s=await api(context.path+'/skills/'+row.id+'/export');download(s.content,s.name+'.md');return}
   if(operation==='purge'&&!confirm('永久删除此 Skill 及其版本正文？此操作无法恢复。'))return;
   await api(context.path+'/skills/'+row.id+'/'+operation,{revision:row.revision,confirmed:true});if(!this.current(context))return;await this.load();if(!this.current(context))return;render({keepScroll:true});await this.bin();return;
  }
  const context=this.context,n=this.detail;if(!context||!this.current(context))throw Error('项目已变化，请重新打开');
  if(operation==='handoff'){await this.handoff(context,n);return}
  if(operation==='copy-handoff'){await navigator.clipboard.writeText($('#library-codex-recovery').value);toast('交接文本已复制');return}
  if(operation==='older'){
   const next=await api(context.path+'/skills?node='+encodeURIComponent(context.node)+'&before='+n.next_before);
   if(!this.current(context))return;
   this.history=[...next.history,...this.history];n.next_before=next.next_before;this.draw();
  }else if(operation==='export'){
   const s=n.id?await api(context.path+'/skills/'+n.id+'/export'):n.skill;download(s.content,s.name+'.md');
  }else if(operation==='version'){
   const s=await api(context.path+'/skills/'+n.id+'/export?version='+Number(arg));this.versionSkill=s;
   if(!this.current(context))return;
   modal('历史版本 · v'+arg,`<pre class="history-text">${esc(s.content)}</pre>`,`${button('返回详情','library:detail:'+context.node)}${button('导出此版本','library:version-export')}`);context.dialog=$('.modal');
  }else if(operation==='version-export')download(this.versionSkill.content,this.versionSkill.name+'.md');
  else if(operation==='import'){
   const note=$('#skill-update-note').value.trim();if(!note)throw Error('请先填写更新说明');
   const input=document.createElement('input');input.type='file';input.accept='.md,.markdown,text/plain';
   input.onchange=async()=>{try{
    const file=input.files?.[0];if(!file)return;if(file.size>100000)throw Error('Skill 最大100KB');
    const content=await file.text();if(!this.current(context)||this.context!==context)return;
    await api(context.path+'/skills?node='+encodeURIComponent(context.node),{id:n.id,revision:n.revision,content,name:file.name.replace(/\.(md|markdown)$/i,''),note});
    if(!this.current(context))return;await this.load();if(!this.current(context))return;render({keepScroll:true});await this.open(context.node);toast('Skill 已导入，版本已记录');
   }catch(e){toast(e.message)}};input.click();
  }else if(operation==='trash'){
   if(!confirm('移入回收站？此节点将未配置 Skill，30 天后自动永久清除回收站正文。'))return;
   await api(context.path+'/skills/trash?node='+encodeURIComponent(context.node),{revision:n.revision,confirmed:true});
   if(!this.current(context))return;await this.load();if(!this.current(context))return;closeModal();render({keepScroll:true});toast('Skill 已移入回收站');
  }
 },
 async handoff(context,n){
  const result=await api(context.path+'/workspace/codex-handoff?node='+encodeURIComponent(context.node),{origin:location.origin,expected_sha256:n.skill.sha256});
  if(!this.current(context))return;
  this.cancelHandoff?.();
  this.cancelHandoff=StudioFlowCodexHandoff.beginCodexHandoff({uri:result.uri,openUri:StudioFlowCodexHandoff.openProtocolUri,
   onWaiting:()=>toast('正在请求本机 Codex 桥接工具…请在 Codex 检查内容后按回车'),
   onUnconfirmed:()=>this.recoverHandoff(context,n)});
 },
 async recoverHandoff(context,n){
  if(!this.current(context))return;
  try{
   const result=await api(context.path+'/workspace/codex-handoff?node='+encodeURIComponent(context.node),{origin:location.origin,preview:true,expected_sha256:n.skill.sha256});
   if(!this.current(context))return;
   modal('尚未确认 Codex 接收',`<p>请先检查 Codex 发送框。浏览器不能确认本机是否已经粘贴；未收到时，可复制下面的同一份交接内容。</p><textarea id="library-codex-recovery" style="min-height:260px">${esc(result.prompt)}</textarea><p>每台 Mac 需安装 StudioFlow Codex Bridge。桥接只粘贴，最终由你按回车提交。</p>`,`${button('返回详情','library:detail:'+context.node)}${button('复制交接文本','library:copy-handoff','primary')}`);
   context.dialog=$('.modal');
  }catch(error){if(this.current(context))toast(error.message)}
 },
 async bin(){
  const path=root();modal('Skill 回收站','<p>正在读取…</p>');const placeholder=$('.modal');
  const data=await api(path+'/skills/recycle-bin');if(root()!==path||$('.modal')!==placeholder)return;
  this.binItems=data.items;
  modal('Skill 回收站',`<p>删除满 30 天自动清除正文与版本。服务停机期间的到期记录会在下次启动时补清理。</p><div class="skill-history">${data.items.map(n=>`<div class="skill-history-row"><div><b>${esc(n.name)}</b><p>${esc(n.node)}${n.task_id?' / 测试批次 '+esc(n.task_id):''}</p><span>${esc(n.deleted_by)} · ${this.time(n.deleted_at)} 删除</span><p>到期 ${this.time(n.expires_at)}</p></div><div class="row">${button('导出','library:bin-export:'+n.id)}${n.can_delete?button('恢复','library:restore:'+n.id)+button('永久删除','library:purge:'+n.id):''}</div></div>`).join('')||'<p>回收站为空。</p>'}</div>`);
  this.binContext={path,dialog:$('.modal')};
 }
};
