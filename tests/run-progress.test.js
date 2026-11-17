const test=require('node:test'),assert=require('node:assert/strict');
const {model}=require('../web/run-progress.js');
test('generic drawer reports real status and observed counts only',()=>{
 assert.equal(model({status:'running'}).summary,'正在执行');
 assert.match(model({status:'running',progress:{completed:2,total:5}}).summary,/2 \/ 5/);
 assert.match(model({status:'failed',error:'网络错误'}).detail,/网络错误/);
 assert.equal(model({status:'waiting_user'}).summary,'等待处理');
});
test('generic running drawer exposes actual model diagnostics without fabricating completion',()=>{
 const m=model({status:'running',progress:{state:'running',events_received:38,assistant_chars:420,seconds_since_response:2,progress_updated_at:100}},{now:105});
 assert.match(m.detail,/38 个.*事件/);assert.match(m.detail,/420.*字符/);assert.match(m.detail,/7 秒/);assert.doesNotMatch(m.detail,/详细进度暂不可用|执行完成/);
});
test('generic drawer distinguishes model request completion and terminal errors',()=>{
 assert.match(model({status:'running',progress:JSON.stringify({state:'completed',events_received:3})}).detail,/本次模型调用已完成.*节点/);
 assert.match(model({status:'running',progress:{state:'retrying',attempt:2,max_attempts:3}}).detail,/重试.*2 \/ 3/);
 assert.equal(model({status:'failed',error:'真实错误',progress:{events_received:5}}).detail,'真实错误');
 assert.doesNotMatch(model({status:'running',progress:{events_received:0}}).detail,/已观察到 0/);
});
