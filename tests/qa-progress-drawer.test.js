const test=require('node:test');
const assert=require('node:assert/strict');
const {QA_progressModel}=require('../web/QA_progress.js');

test('completed job shows actual edge continuation outcome',()=>{
 for(const kind of ['generate','execute']){
  const pending=QA_progressModel({kind,status:'completed',progress:{continuation_state:'pending',continuation_detail:'自动保存范围风险'}});
  assert.match(pending.action,/自动保存范围风险/);
  const stopped=QA_progressModel({kind,status:'completed',progress:{continuation_state:'stopped',continuation_detail:'节点开关已关闭'}});
  assert.match(stopped.action,/节点开关已关闭/);
 }
});

test('running generation uses observed batches and response age, not fake overall percent',()=>{
 const m=QA_progressModel({kind:'generate',status:'running',progress:{batch:3,batches:4,completed:2,phase:'design',state:'running',events_received:2,seconds_since_response:8,progress_updated_at:100}}, {now:105});
 assert.equal(m.summary,'已完成 2 / 4 个需求分段');
 assert.match(m.phase,/最近更新：需求分段 3 \/ 4.*用例设计/);
 assert.match(m.response,/13 秒/);
 assert.doesNotMatch(JSON.stringify(m),/%/);
});
test('heartbeat without observed event does not claim a model response',()=>{
 const m=QA_progressModel({kind:'generate',status:'running',progress:{state:'running',events_received:0,seconds_since_response:70,progress_updated_at:100}}, {now:105});
 assert.match(m.response,/尚未观察到模型响应/);
 assert.doesNotMatch(m.response,/最近收到/);
});
test('unknown totals, failures, queued jobs and auto completion provide accurate decisions',()=>{
 assert.match(QA_progressModel({kind:'generate',status:'queued',progress:{}},{}).phase,/排队/);
 assert.equal(QA_progressModel({kind:'generate',status:'running',progress:{}},{}).summary,'正在准备进度信息');
 assert.match(QA_progressModel({kind:'generate',status:'failed',error:'鉴权失败',progress:{}},{}).action,/鉴权失败/);
 assert.match(QA_progressModel({kind:'generate',status:'completed',progress:{}},{automation:true}).action,/全自动/);
 assert.match(QA_progressModel({kind:'generate',status:'completed',progress:{}},{automation:false}).action,/用例/);
});
test('stage details use observed progress and distinguish completed from pending',()=>{
 const m=QA_progressModel({kind:'generate',status:'running',progress:{batch:3,batches:4,completed:2,phase:'design'}},{sources:4});
 assert.equal(m.title,'正在生成测试用例');
 assert.match(m.stages[0].detail,/4/);
 assert.match(m.stages[1].detail,/2 \/ 4/);
 assert.equal(m.stages[1].state,'current');
 assert.equal(m.stages[2].state,'pending');
 const unknown=QA_progressModel({kind:'generate',status:'running',progress:{}},{});
 assert.doesNotMatch(JSON.stringify(unknown.stages),/0 \/ 0/);
});

test('static execution and other jobs use actual status and counts without generation stages',()=>{
 const m=QA_progressModel({kind:'execute',status:'running',progress:{completed:3,total:10}},{duration:'12 秒'});
 assert.match(m.title,/静态检测/);assert.match(m.summary,/3 \/ 10/);assert.doesNotMatch(JSON.stringify(m),/需求准备|分段生成/);
 const failed=QA_progressModel({kind:'attribution',status:'failed',error:'连接失败'},{});assert.match(failed.action,/连接失败/);
});

test('static drawer displays observed activity and request phase without claiming job completion',()=>{
 const m=QA_progressModel({kind:'execute',status:'running',progress:{state:'completed',events_received:192,seconds_since_response:0,progress_updated_at:100,workers:3}}, {now:105});
 assert.match(m.response,/最近更新的请求.*5 秒/);
 assert.match(m.phase,/本次模型调用已完成/);
 assert.equal(m.status,'running');
 const missing=QA_progressModel({kind:'execute',status:'running',progress:{events_received:0}},{});
 assert.match(missing.response,/尚未观察到模型响应/);
 assert.match(QA_progressModel({kind:'execute',status:'completed',progress:{state:'running'}},{}).response,/任务已完成/);
});

test('project Agent shows shared investigation packages and independently validated case count',()=>{
 const m=QA_progressModel({kind:'execute',status:'running',progress:{execution_engine:'project_agent',batch:2,batch_total:7,completed:0,total:30,state:'running',tool_calls:8,commands_completed:3,last_tool:'command_execution',events_received:25,seconds_since_response:2,progress_updated_at:100,workers:3}},{now:104});
 assert.match(m.phase,/项目Agent共享调查.*工作包 2 \/ 7/);
 assert.equal(m.summary,'已校验 0 / 30 条');
 assert.match(m.response,/已调用工具 8 次/);assert.match(m.response,/已结束命令 3 次/);assert.match(m.response,/最近工具.*命令执行/);assert.match(m.response,/最近更新的请求.*6 秒/);
 assert.doesNotMatch(JSON.stringify(m),/%|命令成功|已查.*文件/);
});
test('project Agent activity never turns tool completions into validated cases',()=>{
 const m=QA_progressModel({kind:'regression',status:'running',progress:JSON.stringify({execution_engine:'project_agent',batch:1,batch_total:2,completed:4,total:12,tool_calls:9,commands_completed:8,last_tool:'mcp_tool_call'})});
 assert.equal(m.summary,'已校验 4 / 12 条');assert.match(m.response,/已调用工具 9 次.*已结束命令 8 次/);assert.doesNotMatch(m.response,/尚未观察到模型响应/);
 const unknown=QA_progressModel({kind:'execute',status:'running',progress:{execution_engine:'project_agent',batch:1,tool_calls:-1,commands_completed:'8'}});
 assert.doesNotMatch(JSON.stringify(unknown),/工作包 1 \/|已校验 0|工具 -1|命令 8/);
});
