const test=require('node:test');
const assert=require('node:assert/strict');
const continuation=require('../web/node-continuation.js');
test('switch states have explicit text, accessible labels, stable edge IDs and escaped names',()=>{
 const edge={source:'product:0',target:'product:1',source_name:'<来源>',target_name:'竞品',enabled:false,editable:true,available:true};
 const off=continuation.markup(edge);
 assert.match(off,/role="switch"/);assert.match(off,/aria-checked="false"/);assert.match(off,/手动继续/);
 assert(!off.includes('<来源>'));assert.match(off,/&lt;来源&gt;/);
 const on=continuation.markup({...edge,enabled:true});assert.match(on,/aria-checked="true"/);assert.match(on,/自动执行/);
 assert.match(continuation.markup({...edge,editable:false}),/aria-disabled=/);
 assert.match(continuation.markup({...edge,available:false,reason:'依赖不满足'}),/依赖不满足/);
});
test('no edge produces no accidental switch',()=>assert.equal(continuation.markup(null),''));
test('node indicators distinguish approval, activity, waiting and failures independently of selection',()=>{
 for(const status of ['approved','completed'])assert.deepEqual(continuation.nodeState(status),{value:'confirmed',label:'已确认',indicator:'confirmed'});
 assert.deepEqual(continuation.nodeState('waiting_user'),{value:'current',label:'待人工确认',indicator:'waiting'});
 assert.deepEqual(continuation.nodeState('running'),{value:'current',label:'进行中',indicator:'running'});
 assert.deepEqual(continuation.nodeState('queued'),{value:'current',label:'排队中',indicator:'running'});
 assert.deepEqual(continuation.nodeState('failed'),{value:'current',label:'执行失败',indicator:'failed'});
 assert.deepEqual(continuation.nodeState('interrupted'),{value:'current',label:'执行中断',indicator:'failed'});
 assert.deepEqual(continuation.nodeState('not_started'),{value:'pending',label:'未开始',indicator:'pending'});
 assert.equal(continuation.nodeState('cancelled').indicator,'pending');
 assert.equal(continuation.nodeState('draft').indicator,'pending');
});
test('job activity does not turn completed execution into human approval',()=>{
 assert.equal(continuation.nodeState('waiting_user','running').indicator,'running');
 assert.equal(continuation.nodeState('waiting_user','failed').indicator,'failed');
 assert.equal(continuation.nodeState('waiting_user','completed').indicator,'waiting');
 assert.equal(continuation.nodeState('approved','failed').indicator,'confirmed');
 assert.equal(continuation.nodeState('cancelled','running').label,'已取消');
});

test('unavailable connectors explain the reason on click and keyboard instead of swallowing input',()=>{
 const html=continuation.markup({source:'testing:0',target:'testing:2',source_name:'用例',target_name:'归因',available:false,editable:false,enabled:false,reason:'缺少执行证据，请恢复执行节点'});
 assert.match(html,/aria-disabled="true"/);assert.match(html,/查看原因/);assert.doesNotMatch(html,/<button[^>]*\sdisabled(?:[ >])/);
 assert.match(html,/role="status"/);
});
