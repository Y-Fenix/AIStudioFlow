const test=require('node:test'),assert=require('node:assert/strict');
const b=require('../web/node-builder.js');
test('run timeline shows returned node quality without inventing checks for independent AI',()=>{
 const render=step=>globalThis.NodeBuilder.runMarkup.call({currentRun:{id:'fixture',status:'completed',cursor:1,steps:[{type:'adapter',config:{label:'引用节点'},...step}]}});
 const html=render({quality:{contract:'product_fixture',sections_checked:6,source_quotes_checked:2,fact_checked:false}});
 assert.match(html,/本次交付检查/);
 assert.match(html,/product_fixture/);
 assert.match(html,/结构检查项[\s\S]*6/);
 assert.match(html,/来源引用检查项[\s\S]*2/);
 assert.match(html,/未进行事实核验/);
 assert.match(html,/结构与来源检查不等于事实核验/);
 assert.doesNotMatch(render({type:'ai'}),/本次交付检查|结构检查项/);
 assert.match(render({quality:{contract:'<script>',fact_checked:true}}),/&lt;script&gt;/);
 assert.match(render({quality:{}}),/未返回/);
});
test('failed builder runs explain what to check before retry',()=>{
 const html=globalThis.NodeBuilder.runMarkup.call({currentRun:{status:'failed',cursor:0,steps:[{type:'ai',config:{label:'生成'}}],error:'provider failure'}});
 assert.match(html,/核对.*错误.*输入.*Skill.*连接/);
 assert.match(html,/重试当前步骤/);
});
test('drag insertion is immutable and preserves IDs when sorting',()=>{
 const list=[{id:'a'},{id:'b'},{id:'c'}];
 assert.deepEqual(b.reorder(list,0,3).map(x=>x.id),['b','c','a']);
 assert.deepEqual(list.map(x=>x.id),['a','b','c']);
 assert.deepEqual(b.reorder(list,-1,1),list);
});
test('defaults describe executable types and escape hostile content',()=>{
 assert.equal(b.make('checklist','x').config.items.length,1);
 assert(b.make('template','t').config.text.includes('{{previous}}'));
 assert.equal(b.escape('<script>'), '&lt;script&gt;');
});
test('JSON drafts reject duplicate IDs, unknown types and malformed props before preview',()=>{
 const types={input:{fields:{label:'text',required:'bool'}},checklist:{fields:{label:'text',items:'list'}},tool:{fields:{url:'url'}},node:{fields:{node:'text'}}};
 for(const blocks of [[b.make('input','same'),b.make('input','same')],[{id:'x',type:'script',config:{}}],[{id:'x',type:'checklist',config:{items:'bad'}}],[{id:'x',type:'tool',config:{url:'javascript:alert(1)'}}],[{id:'x',type:'node',config:{node:'product:0'}}]])assert.throws(()=>b.validateDraft({schema_version:1,blocks},types,false));
 assert.equal(b.validateDraft({schema_version:1,blocks:[b.make('input','x')]},types,false).length,1);
});
test('business task import validates children and never accepts nested workflow references',()=>{
 const types={input:{fields:{label:'text',required:'bool'}},task:{fields:{label:'text',blocks:'blocks'}},node:{fields:{node:'text'}}};
 const task={id:'t',type:'task',config:{label:'分析节点',blocks:[{id:'i',type:'input',config:{required:true}}]}};
 assert.equal(b.validateDraft({schema_version:1,blocks:[task]},types,true)[0].config.blocks.length,1);
 for(const child of [{id:'t2',type:'task',config:{blocks:[]}}, {id:'n',type:'node',config:{node:'product:0'}}]){
  assert.throws(()=>b.validateDraft({schema_version:1,blocks:[{...task,config:{...task.config,blocks:[child]}}]},types,true));
 }
 assert.throws(()=>b.validateDraft({schema_version:1,blocks:[task]},types,false));
});
