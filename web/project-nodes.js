/* Shell-owned node management; display positions never identify persisted resources. */
(function(root){
 'use strict';
 const key=(department,index)=>department.node_keys?.[index]||`${department.id}:${index}`;
 const testingStage=value=>/^testing:[0-5]$/.test(value)?Number(value.split(':')[1]):null;
 function move(items,index,offset){const copy=items.slice(),target=index+offset;if(index<0||index>=copy.length||target<0||target>=copy.length)return copy;[copy[index],copy[target]]=[copy[target],copy[index]];return copy}
 root.ProjectNodeKeys={key,testingStage,move};
 if(typeof module!=='undefined')module.exports=root.ProjectNodeKeys;
 root.ProjectNodeManager={
  draft:null,context:null,busy:false,
  async open(){
   if(!state.project)throw Error('请先选择项目');
   const path=rootPath(),department=state.dept;
   modal('管理节点','<p>正在读取节点配置…</p>');
   const placeholder=$('.modal');
   const value=await api(path+'/nodes?department='+department);
   if(rootPath()!==path||state.dept!==department||$('.modal')!==placeholder)return;
   this.context={path,department};this.draft=value;this.draw();
  },
  allowed(action,id=''){return id?!!state.capabilities?.nodes[id]?.[action]:!!state.capabilities?.node_management?.[this.context.department]?.[action]},
  draw(){
   const d=this.draft;
   const rows=d.nodes.map((n,i)=>`<div class="node-manager-row"><span class="node-ordinal">${i+1}</span><div><b>${esc(n.definition[0])}</b><p class="small muted">${esc(n.definition[2])}</p></div><div class="row">${this.allowed('reorder')?`${button('↑','node-manager:up:'+i)}${button('↓','node-manager:down:'+i)}`:''}${(!n.id||this.allowed('delete',n.id))?button('删除','node-manager:remove:'+i):''}</div></div>`).join('');
   modal('管理'+workspaceLabel(this.context.department)+'节点',`<p class="small muted">仅影响当前项目。删除保留历史；排序不改变已有产物和 Skill。测试业务仍检查原有证据依赖。</p><div class="node-manager-list">${rows||'<p>暂无活动节点，可新增节点。</p>'}</div>${this.allowed('create')?`<details class="node-manager-add"><summary>新增节点</summary><div class="field-row"><div class="field"><label>节点名称</label><input id="new-node-name" maxlength="60"></div><div class="field"><label>用途</label><input id="new-node-purpose" maxlength="2000"></div></div><div class="field"><label>输入资料</label><input id="new-node-input" maxlength="2000"></div><div class="field"><label>交付物</label><input id="new-node-output" maxlength="2000"></div><div class="field"><label>人工验收条件</label><input id="new-node-check" maxlength="2000"></div>${button('加入列表','node-manager:add','','plus')}</details>`:''}${d.archived.length?`<details><summary>已删除节点 · ${d.archived.length}</summary>${d.archived.map(n=>`<div class="node-manager-row"><b>${esc(n.definition[0])}</b><div class="row">${button('历史记录','node-history:'+n.id)}${this.allowed('create')?button('恢复','node-manager:restore:'+n.id):''}</div></div>`).join('')}</details>`:''}`,`${button('取消','close')}${button(this.busy?'正在保存…':'保存配置','node-manager:save','primary')}`);
  },
  async action(operation,arg,extra){
   if(this.busy)return;
   if(!this.context||rootPath()!==this.context.path||state.dept!==this.context.department)throw Error('当前项目或部门已变化，请重新打开');
   const d=this.draft,index=Number(arg);
   if(operation==='up'||operation==='down'){d.nodes=move(d.nodes,index,operation==='up'?-1:1);this.draw()}
   else if(operation==='remove'){if(!confirm('删除此节点？历史记录会保留，保存配置后生效。'))return;d.nodes.splice(index,1);this.draw()}
   else if(operation==='restore'){const id=arg+':'+extra,n=d.archived.find(n=>n.id===id);if(n){d.nodes.push({...n,archived:false,restore:true});d.archived=d.archived.filter(n=>n.id!==id);this.draw()}}
   else if(operation==='add'){
    const name=$('#new-node-name').value.trim(),purpose=$('#new-node-purpose').value.trim(),input=$('#new-node-input').value.trim(),output=$('#new-node-output').value.trim(),check=$('#new-node-check').value.trim();
    if(![name,purpose,input,output,check].every(Boolean))throw Error('请完整填写新增节点信息');
    d.nodes.push({definition:[name,purpose,output,purpose,check,input,output]});this.draw();
   }else if(operation==='save'){
    this.busy=true;const context={...this.context};
    try{await api(context.path+'/nodes?department='+context.department,d);if(rootPath()!==context.path)return;await reloadSummary();if(rootPath()!==context.path)return;state.workspace=null;state.view='home';state.node=0;state.dirty=false;render();closeModal();toast('节点配置已保存')}
    finally{this.busy=false}
   }
  }
 };
 function rootPath(){return state.project&&state.studio?'/api/studios/'+state.studio.id+'/projects/'+state.project.id:''}
})(globalThis);
