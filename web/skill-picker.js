/* Shared, project-scoped selection of existing workbench rules. Saves a text snapshot. */
(function(root){
 'use strict';
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={product:'产品',design:'设计',development:'开发',testing:'测试',growth:'发行与增长'};
 root.StudioSkillPicker={
  async open(options){
   options.modal('Skill 工作台 · 选择 Skill','<div class="skill-picker"><p>正在读取当前项目的 Skill…</p></div>');
   const host=document.querySelector('.skill-picker');
   const current=()=>host.isConnected&&options.isCurrent();
   const endpoint=options.path+'/skills';
   let items=[],filter=options.department,query='',page=1,selected=null,sequence=0,busy=false;
   const size=5;
   const error=message=>{if(current())host.querySelector('[data-skill-error]').textContent=message};
   function draw(){
    host.innerHTML=`<p class="skill-picker-hint">从当前项目的 Skill 工作台选择规则，保存到「${escape(options.target)}」。后续操作使用此次保存的版本。</p><div class="skill-picker-filters"><label>部门<select data-skill-filter><option value="all">全部部门</option>${Object.entries(labels).map(([id,label])=>`<option value="${id}" ${id===filter?'selected':''}>${label}</option>`).join('')}</select></label><label>搜索<input data-skill-search type="search" placeholder="搜索节点、描述或上传者"></label></div><div class="skill-picker-grid"><section><div class="skill-picker-list"></div><div class="skill-picker-pages"></div></section><section class="skill-picker-preview"><p class="muted">选择左侧 Skill 查看正文与版本。</p></section></div><p data-skill-error role="alert"></p><div class="skill-picker-footer"><span class="small muted">仅修改当前节点</span><div><button type="button" data-skill-cancel>取消</button><button type="button" class="primary" data-skill-save disabled>使用并保存</button></div></div>`;
    drawList();
   }
   function drawList(){
    const matches=items.filter(n=>(filter==='all'||n.node.startsWith(filter+':'))&&[n.node_name,n.description,n.uploader,n.node].join(' ').toLowerCase().includes(query.toLowerCase()));
    const pages=Math.max(1,Math.ceil(matches.length/size));page=Math.max(1,Math.min(page,pages));
    host.querySelector('.skill-picker-list').innerHTML=matches.slice((page-1)*size,page*size).map(n=>`<button type="button" data-skill-source="${escape(n.node)}" class="skill-picker-item ${selected?.node===n.node?'selected':''}" aria-pressed="${selected?.node===n.node}"><strong>${escape(n.node_name)}</strong><span>${escape(labels[n.node.split(':')[0]]||n.node)} · v${n.revision} · ${escape(n.uploader)}</span><small>${escape(n.description)}</small></button>`).join('')||'<p class="muted">没有可选择的 Skill。仅显示已配置且有查看、导出权限的规则。</p>';
    host.querySelector('.skill-picker-pages').innerHTML=`<span>共 ${matches.length} 项 · 每页 ${size} 项</span><div><button type="button" data-skill-page="-1" ${page===1?'disabled':''}>上一页</button><span>${page} / ${pages}</span><button type="button" data-skill-page="1" ${page===pages?'disabled':''}>下一页</button></div>`;
   }
   async function preview(node){
    const ticket=++sequence;selected=null;error('');
    host.querySelector('[data-skill-save]').disabled=true;
    host.querySelector('.skill-picker-preview').innerHTML='<p class="muted">正在读取正文…</p>';drawList();
    try{
     const detail=await options.api(endpoint+'?node='+encodeURIComponent(node));
     if(!current()||ticket!==sequence)return;
     if(detail.status!=='active'||!detail.skill.content||!detail.permissions.export)throw Error('此 Skill 已不可用，或没有导出权限，请重新选择');
     selected=detail;
     host.querySelector('.skill-picker-preview').innerHTML=`<h3>${escape(detail.skill.name)}</h3><p class="small muted">v${detail.revision} · 上传者：${escape(detail.uploader)}</p><pre>${escape(detail.skill.content)}</pre>`;
     host.querySelector('[data-skill-save]').disabled=false;drawList();
    }catch(e){if(current()&&ticket===sequence){host.querySelector('.skill-picker-preview').innerHTML='<p class="muted">读取失败，请重新选择。</p>';error(e.message)}}
   }
   async function save(){
    if(busy||!selected||!current())return;
    busy=true;error('');host.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);
    try{
     const chosen=selected;
     const latest=await options.api(endpoint+'?node='+encodeURIComponent(chosen.node));
     if(!current())throw Error('当前节点或任务版本已变化，请关闭后重新打开');
     if(latest.status!=='active'||latest.id!==chosen.id||latest.revision!==chosen.revision||latest.skill.sha256!==chosen.skill.sha256||!latest.permissions.export)throw Error('所选 Skill 已变化或不可用，请重新选择');
     const source=chosen.id?endpoint+'/'+encodeURIComponent(chosen.id)+'/export':options.path+'/workspace/skill-export?node='+encodeURIComponent(chosen.node);
     const skill=await options.api(source);
     if(!current())throw Error('当前节点或任务版本已变化，请关闭后重新打开');
     if(skill.sha256!==chosen.skill.sha256)throw Error('所选 Skill 已变化，请重新选择');
     await options.save({name:skill.name,content:skill.content},chosen.node,()=>host.isConnected);
    }catch(e){if(host.isConnected)host.querySelector('[data-skill-error]').textContent=e.message}
    finally{
     busy=false;
     if(host.isConnected){host.querySelectorAll('button,input,select').forEach(el=>el.disabled=false);host.querySelector('[data-skill-save]').disabled=!selected;drawList()}
    }
   }
   try{
    const result=await options.api(endpoint);if(!current())return;
    items=result.items.filter(n=>n.status==='active'&&n.permissions.export);draw();
    host.addEventListener('input',e=>{if(e.target.matches('[data-skill-search]')&&!busy){query=e.target.value;page=1;drawList()}});
    host.addEventListener('change',e=>{if(e.target.matches('[data-skill-filter]')&&!busy){filter=e.target.value;page=1;drawList()}});
    host.addEventListener('click',e=>{
     const button=e.target.closest('button');if(!button||button.disabled)return;
     if(button.hasAttribute('data-skill-cancel')){options.close();return}
     if(busy)return;
     if(!current()){host.querySelector('[data-skill-error]').textContent='当前节点或任务版本已变化，请关闭后重新打开';return}
     if(button.hasAttribute('data-skill-source'))preview(button.dataset.skillSource);
     else if(button.hasAttribute('data-skill-page')){page+=Number(button.dataset.skillPage);drawList()}
     else if(button.hasAttribute('data-skill-save'))save();
    });
   }catch(e){if(current())host.innerHTML=`<p role="alert" data-skill-error>${escape(e.message)}</p>`}
  }
 };
})(globalThis);
