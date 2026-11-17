const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const modulePath = require.resolve('../web/node-builder.js').replace('node-builder.js', 'workflow-pages.js');
const load = () => {
  assert.ok(fs.existsSync(modulePath), 'workflow pages module must exist');
  return require(modulePath);
};
const flow = {id:'f', name:'验收', revision:3, blocks:[
  {id:'input-a',type:'input',config:{required:true}},
  {id:'review-a',type:'review',config:{}},
  {id:'ref-a',type:'node',config:{node:'testing:1',label:'执行'}},
  {id:'task-a',type:'task',config:{label:'汇总',blocks:[{id:'inner-a',type:'template',config:{text:'{{previous}}'}}]}}
]};

test('legacy consecutive generic blocks form one business node and repeated source nodes keep IDs', () => {
  const {projectNodes} = load();
  const nodes = projectNodes(flow);
  assert.deepEqual(nodes.map(n=>n.id), ['input-a','ref-a','task-a']);
  assert.equal(nodes[0].blocks.length, 2);
  assert.equal(nodes[1].source_node, 'testing:1');
  assert.equal(nodes[2].name, '汇总');
});

test('historical business nodes come from the chosen run snapshot, never current flow', () => {
  const {projectNodes} = load();
  const run = {groups:[{id:'old-node',name:'旧任务',source_node:'product:0'}],steps:[]};
  assert.deepEqual(projectNodes(flow, run).map(n=>n.id), ['old-node']);
  assert.equal(projectNodes(flow, {steps:[{id:'s',instance:'old-reference',node:'design:0',type:'manual',config:{label:'旧设计'}}]})[0].id,'old-reference');
});

test('list pagination searches names, filters latest statuses and clamps empty pages', () => {
  const {filterPage} = load();
  const items = Array.from({length:100},(_,i)=>({id:'f'+i,name:'流程 '+i,updated_at:i}));
  const runs = [{flow_id:'f9',status:'failed',created_at:'2026-10-22T01:00:00Z'}];
  const result = filterPage(items, runs, {query:'流程 9',status:'failed',size:10,page:50});
  assert.equal(result.total,1);assert.equal(result.page,1);assert.equal(result.items[0].id,'f9');
  assert.equal(filterPage(items, runs, {size:20,page:3}).items.length,20);
  assert.equal(filterPage(items, runs, {query:'missing',size:50,page:3}).pages,1);
});

test('business status uses only selected group steps and distinguishes completed from approval', () => {
  const {nodeStatus} = load();
  const run={status:'waiting_user',cursor:2,steps:[{group:'a',done:true},{group:'a',done:true},{group:'b',type:'review'}]};
  assert.equal(nodeStatus('a',run),'completed');
  assert.equal(nodeStatus('b',run),'waiting_user');
  assert.equal(nodeStatus('missing',run),'idle');
  assert.equal(nodeStatus('a',null),'idle');
});

test('saving legacy node configuration keeps original internal IDs and leaves source flow untouched', () => {
  const {patchNode} = load();
  const patched = patchNode(flow,'input-a',{inputs:'资料',skill:'规则',skill_name:'实例规则'});
  assert.equal(patched.blocks[0].type,'task');
  assert.deepEqual(patched.blocks[0].config.blocks.map(b=>b.id),['input-a','review-a']);
  assert.equal(patched.blocks[1].id,'ref-a');
  assert.equal(flow.blocks[0].type,'input');
  const reset=patchNode({...flow,blocks:patched.blocks},'input-a',{skill:null});
  assert.equal('skill' in reset.blocks[0].config,false);
  assert.equal('skill_name' in reset.blocks[0].config,false);
});

test('node logs exclude other groups and represent times in Beijing', () => {
  const {nodeEvents,beijingTime} = load();
  const run={events:[{action:'submit',detail:{group:'a'}},{action:'submit',detail:{group:'b'}}]};
  assert.equal(nodeEvents(run,'a').length,1);
  assert.match(beijingTime('2026-10-22T01:02:03Z'),/09:02/);
});

test('controller opens list first and fetches explicit detail and selected run', async () => {
  load();const pages=globalThis.WorkflowPages;
  const requests=[];
  const host={path:()=>'/p',department:()=> 'product',permissions:()=>({flowCreate:true,flowEdit:true}),dirty(){},show(){},render(){},api:async path=>{requests.push(path);if(path==='/p/custom-flows')return {items:[flow]};if(path==='/p/custom-flows/f')return flow;if(path==='/p/block-runs?flow=f')return {items:[]};if(path==='/p/block-runs')return {items:[]};return {id:'run',flow_id:'f',groups:[],steps:[],status:'completed'};}};
  pages.setup({host,builder:{}});
  await pages.open();assert.equal(pages.view,'list');assert.match(pages.page(),/自定义工作流/);
  await pages.open('f','run');assert.equal(pages.view,'home');assert.equal(pages.currentRun.id,'run');
  assert.ok(requests.includes('/p/custom-flows/f'));assert.ok(requests.includes('/p/block-runs/run'));
  pages.dispose();
});

test('markup escapes user data and does not expose node Skill without permission', () => {
  load();const pages=globalThis.WorkflowPages;
  pages.view='node';pages.flow={...flow,nodes:[{id:'n',name:'<img>',permissions:{view:true,skill_view:false},skill:{content:'SECRET'}}]};
  pages.selectedNode='n';pages.currentRun=null;
  assert.ok(!pages.page().includes('SECRET'));assert.ok(pages.page().includes('&lt;img&gt;'));
});

test('start input does not cross workflow or project boundaries', async () => {
  load();const pages=globalThis.WorkflowPages;
  const host={path:()=>'/new-project',permissions:()=>({}),dirty(){},show(){},api:async path=>path.endsWith('/custom-flows')?{items:[]}:{items:[]}};
  pages.setup({host,builder:{}});pages.startInput='上个项目的私有输入';
  await pages.open();
  assert.equal(pages.startInput,'');
});

test('polling unchanged runtime keeps the actual textarea DOM and its scroll', () => {
  load();const pages=globalThis.WorkflowPages;
  let replaced=0;
  const runtime={querySelector:()=>null,querySelectorAll:()=>[],contains:()=>false,scrollTop:95,set innerHTML(value){replaced++;}};
  const container={querySelector:selector=>selector==='#builder-run-detail'?runtime:null,querySelectorAll:()=>[]};
  globalThis.document={querySelector:()=>container};
  pages.host={path:()=>'/p'};pages.path='/p';pages.flow={id:'f'};pages.builder={runMarkup:()=>'<textarea>draft</textarea>'};
  pages.currentRun={id:'r',flow_id:'f',status:'waiting_user',cursor:0,steps:[{id:'s',group:'n',type:'manual'}]};
  pages.updateRun(structuredClone(pages.currentRun));
  assert.equal(replaced,0);assert.equal(runtime.scrollTop,95);
  delete globalThis.document;
});

test('saving input alone never creates an empty override for unreadable Skill', async () => {
  load();const pages=globalThis.WorkflowPages;
  const node={id:'ref-a',name:'执行',inputs:'old',permissions:{edit:true,skill_view:false,skill_edit:false}};
  pages.flow={...flow,nodes:[node]};pages.currentRun=null;pages.selectedNode=node.id;pages.path='/p';pages.busy=false;
  pages.host={path:()=>'/p',permissions:()=>({flowEdit:true}),dirty(){}};pages.drafts.clear();
  pages.draft(node).inputs='updated';
  let saved;
  const original=pages.savePatch;pages.savePatch=async(id,patch)=>saved=patch;
  try { await pages.action('save-node');assert.deepEqual(saved,{inputs:'updated'}); }
  finally { pages.savePatch=original; }
});

test('saving input with unchanged default Skill preserves inheritance', async () => {
  load();const pages=globalThis.WorkflowPages;
  const node={id:'ref-a',name:'执行',inputs:'old',skill:{name:'默认规则',content:'inherited',source:'default'},permissions:{edit:true,skill_view:true,skill_edit:true}};
  pages.flow={...flow,nodes:[node]};pages.currentRun=null;pages.selectedNode=node.id;pages.path='/p';pages.busy=false;
  pages.host={path:()=>'/p',permissions:()=>({flowEdit:true}),dirty(){}};pages.drafts.clear();pages.draft(node).inputs='updated';
  let saved;const original=pages.savePatch;pages.savePatch=async(id,patch)=>saved=patch;
  try {await pages.action('save-node');assert.deepEqual(saved,{inputs:'updated'});} finally {pages.savePatch=original;}
});

test('old runs with empty groups still render frozen instance steps', () => {
  const {projectNodes} = load();
  assert.equal(projectNodes(flow,{groups:[],steps:[{id:'s',instance:'legacy',type:'manual',config:{label:'历史'}}]})[0].id,'legacy');
});

test('a historical node never offers Skill selection based on current flow permissions', () => {
  load();const pages=globalThis.WorkflowPages;
  pages.flow={...flow,nodes:[{id:'historic',permissions:{skill_view:true}}]};pages.currentRun={groups:[{id:'historic',name:'历史',inputs:'frozen',skill_name:'冻结规则'}],steps:[],status:'completed'};
  pages.selectedNode='historic';pages.view='node';pages.runs=[];pages.builder={};pages.path='/p';
  pages.host={path:()=>'/p',permissions:()=>({flowEdit:true})};
  assert.match(pages.page(),/冻结规则/);
  assert.ok(!pages.page().includes('运行 Skill 快照'));
});

test('SQLite audit timestamps are interpreted as UTC, then displayed in Beijing', () => {
  const {beijingTime} = load();
  assert.equal(beijingTime('2026-10-22 01:02:03'),beijingTime('2026-10-22T01:02:03Z'));
});

test('frozen groups use only current matching permissions and keep frozen values', () => {
  const {projectNodes} = load();
  const current={nodes:[{id:'x',inputs:'live',skill:{content:'LIVE'},permissions:{edit:false,skill_view:false}}]};
  const nodes=projectNodes(current,{groups:[{id:'x',inputs:'frozen'},{id:'deleted',inputs:'history'}]});
  assert.equal(nodes[0].inputs,'frozen');assert.equal(nodes[0].permissions.skill_view,false);
  assert.equal(nodes[1].permissions.edit,false);assert.ok(!JSON.stringify(nodes).includes('LIVE'));
});

test('saving a different node keeps the existing unsaved draft and its dirty state', async () => {
  load();const pages=globalThis.WorkflowPages;
  const updated={...flow,revision:4,nodes:[{id:'input-a',inputs:''},{id:'ref-a',inputs:''}]};
  let dirty=false,rendered=0;
  pages.path='/p';pages.flow={...flow,nodes:updated.nodes};pages.currentRun=null;pages.drafts.clear();pages.builder={};
  pages.host={path:()=>'/p',dirty:value=>dirty=value,toast(){},api:async(path,body)=>body?updated:updated};
  const draft=pages.draft(updated.nodes[1]);draft.inputs='unsaved';draft.dirty=true;
  await pages.savePatch('input-a',{auto_next:true},{redraw:false});
  assert.equal(pages.draft(updated.nodes[1]).inputs,'unsaved');assert.equal(dirty,true);
});

test('collection latest-run summary survives global run history limit', () => {
  const {filterPage} = load();
  const result=filterPage([{id:'older',name:'旧流',last_run:{id:'r-old',status:'failed'}}],[],{status:'failed'});
  assert.equal(result.total,1);assert.equal(result.latest.get('older').status,'failed');
});

test('disabled workflow controls explain the relevant permission or frozen state', () => {
  load();const pages=globalThis.WorkflowPages;
  pages.path='/no-permission';pages.items=[];pages.runs=[];pages.host={path:()=>'/no-permission',permissions:()=>({})};pages.view='list';
  assert.match(pages.page(),/title="需要工作流创建权限"/);
});

test('late copy response cannot mutate another selected project', async () => {
  load();const pages=globalThis.WorkflowPages;
  let path='/old',finish,posts=0;
  const pending=new Promise(resolve=>finish=resolve);
  pages.path='/old';pages.host={path:()=>path,permissions:()=>({flowCreate:true}),api:async(url,body)=>{if(body){posts++;return flow;}return pending;}};
  const originalPrompt=globalThis.prompt;globalThis.prompt=()=> 'copy';
  try {
    const task=pages.collectionAction('copy','f');path='/new';finish(flow);await task;
    assert.equal(posts,0);
  } finally {globalThis.prompt=originalPrompt;}
});

test('discarding current workflow drafts leaves other workflow drafts intact', () => {
  load();const pages=globalThis.WorkflowPages;
  pages.path='/p';pages.flow={...flow,nodes:[{id:'x'}]};pages.drafts.clear();let dirty=true;
  pages.host={dirty:value=>dirty=value};pages.draft({id:'x'}).dirty=true;
  pages.drafts.set('/p/other/x',{inputs:'other',dirty:true});
  pages.discardDrafts();assert.equal(pages.drafts.has('/p/f/x'),false);assert.equal(pages.drafts.has('/p/other/x'),true);assert.equal(dirty,false);
});

test('operation logs use localized action names while preserving real recorded detail', () => {
  load();const pages=globalThis.WorkflowPages;
  pages.selectedNode='n';pages.currentRun={events:[{action:'block_run_submit',created_at:'2026-10-22 01:02:03',detail:{group:'n',reason:'真实依据'}}]};
  assert.match(pages.logsMarkup(),/提交本步骤/);assert.match(pages.logsMarkup(),/真实依据/);
  assert.ok(!pages.logsMarkup().includes('block_run_submit'));
});

test('archived workflow configuration stays readonly', () => {
  load();const pages=globalThis.WorkflowPages;
  pages.host={permissions:()=>({flowEdit:true})};pages.currentRun=null;pages.flow={...flow,archived:true};
  assert.equal(pages.canEdit({permissions:{edit:true}}),false);
});

test('choosing a Skill preserves unsaved input in the same node', async () => {
  load();const pages=globalThis.WorkflowPages;
  const node={id:'ref-a',inputs:'saved',skill:{name:'old',content:'old'}};
  const updated={...flow,revision:4,nodes:[{...node,skill:{name:'new',content:'new'}}]};
  pages.path='/p';pages.flow={...flow,nodes:[node]};pages.currentRun=null;pages.drafts.clear();pages.builder={};
  let dirty=false;
  pages.host={path:()=>'/p',dirty:value=>dirty=value,toast(){},api:async()=>updated};
  const draft=pages.draft(node);draft.inputs='unsaved input';draft.dirty=true;
  await pages.savePatch(node.id,{skill:'new',skill_name:'new'},{redraw:false});
  assert.equal(pages.draft(updated.nodes[0]).inputs,'unsaved input');assert.equal(pages.draft(updated.nodes[0]).skill,'new');assert.equal(dirty,true);
});

test('switching business nodes retains drafts without a discard prompt', async () => {
  load();const pages=globalThis.WorkflowPages;
  pages.path='/p';pages.flow={...flow,nodes:[{id:'a',inputs:''},{id:'b',inputs:''}]};pages.currentRun=null;pages.busy=false;pages.view='node';pages.selectedNode='a';pages.drafts.clear();
  pages.host={path:()=>'/p',permissions:()=>({flowEdit:true}),dirty(){},render(){}};
  pages.draft(pages.flow.nodes[0]).inputs='未保存的资料';pages.draft(pages.flow.nodes[0]).dirty=true;
  const previous=globalThis.confirm;globalThis.confirm=()=>{throw Error('node navigation must not discard drafts')};
  try {await pages.action('node:b');assert.equal(pages.selectedNode,'b');await pages.action('node:a');assert.equal(pages.draft(pages.flow.nodes[0]).inputs,'未保存的资料');}
  finally {globalThis.confirm=previous;}
});

test('workspace has semantic config/result tabs and truthful run-level start action', () => {
  load();const pages=globalThis.WorkflowPages;
  pages.path='/p';pages.flow={...flow,nodes:[{id:'a',name:'需求整理',inputs:'资料',skill:{name:'规则',content:'规则'},permissions:{edit:true}}]};pages.currentRun=null;pages.view='node';pages.selectedNode='a';pages.builder={};pages.drafts.clear();
  pages.host={path:()=>'/p',permissions:()=>({flowEdit:true,flowExecute:true})};
  const markup=pages.page();assert.match(markup,/role="tablist"/);assert.match(markup,/role="tabpanel"/);assert.match(markup,/本节点准备/);assert.match(markup,/开始工作流/);
  assert.ok(!markup.includes('预览运行'));assert.ok(!markup.includes('演示'));
});

test('starting a flow refuses unsaved drafts without discarding them', async () => {
  load();const pages=globalThis.WorkflowPages;
  pages.path='/p';pages.flow={...flow,nodes:[{id:'a',inputs:''}]};pages.currentRun=null;pages.selectedNode='a';pages.busy=false;pages.drafts.clear();
  let starts=0;pages.builder={startWorkflow(){starts++;throw Error('started without saving')}};pages.host={path:()=>'/p',permissions:()=>({flowExecute:true}),dirty(){}};
  const draft=pages.draft(pages.flow.nodes[0]);draft.inputs='未保存';draft.dirty=true;
  const previous=globalThis.confirm;globalThis.confirm=()=>true;
  try {await assert.rejects(()=>pages.action('start'),/先保存/);assert.equal(starts,0);assert.equal(draft.dirty,true);assert.equal(draft.inputs,'未保存');}
  finally {globalThis.confirm=previous;}
});

test('node presentation never confuses another node running or completed steps with approval', () => {
  const {nodePresentation}=load();
  assert.equal(typeof nodePresentation,'function');
  const run={status:'running',cursor:1,steps:[{group:'a',done:true,type:'template'},{group:'b',type:'ai'}]};
  assert.equal(nodePresentation('a',run).title,'本节点步骤已完成');
  assert.equal(nodePresentation('c',run).action,'current');
  const waiting={status:'waiting_user',cursor:0,steps:[{group:'a',type:'review'}]};
  assert.equal(nodePresentation('a',waiting).title,'交付就绪，等待人工审核');
  assert.equal(nodePresentation('a',{...waiting,status:'failed'}).status,'failed');
  assert.equal(nodePresentation('a',waiting,true).action,'');
});

test('flow home exposes current run diagnostics without requiring node entry', () => {
  load();require('../web/workbench.js');
  const html=globalThis.WorkflowPages.homeMarkup.call({currentRun:{status:'running',cursor:0,steps:[{}],progress:{state:'retrying',attempt:2,max_attempts:3}},runSelector:()=>'',access:()=>({flowExecute:true}),stripMarkup:()=>'',summaryMarkup:()=>'',startInput:''});
  assert.match(html,/data-workflow-progress/);assert.match(html,/重试.*2\/3/);
});
