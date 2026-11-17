const test = require('node:test');
const assert = require('node:assert/strict');
const {markdown, currentReport, mergeDraft, homeSummary, recoveryHint} = require('../web/workbench.js');

test('failed and interrupted runs give an explicit manual recovery step', () => {
  assert.match(recoveryHint({status:'failed'}), /错误.*输入.*Skill.*连接.*重新运行/);
  assert.match(recoveryHint({status:'interrupted'}), /中断.*手动.*重新运行/);
  assert.equal(recoveryHint({status:'completed'}), '');
  assert.equal(recoveryHint(null), '');
});

test('Markdown renders useful structure without executing HTML or loading images', () => {
  const html = markdown('# Heading\n\n**bold** and `code`\n\n| A | B |\n| --- | --- |\n| one | two |\n\n<script>alert(1)</script>\n![remote](https://example.com/track.png)\n[bad](javascript:alert(1))\n[good](https://example.com)\n\n```html\n<img src=x onerror=alert(1)>\n```');
  assert.match(html, /<h1>Heading<\/h1>/);
  assert.match(html, /<strong>bold<\/strong>/);
  assert.match(html, /<table>/);
  assert.doesNotMatch(html, /<script|<img|href="javascript:/i);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /rel="noopener noreferrer"/);
});

test('result reports require exact current completed workspace, and disappear on edits', () => {
  const workspace = {revision: 8};
  const job = {node: 'product:0', status: 'completed', result: {workspace: {revision: 8}, quality: {fact_checked: false}}};
  assert.equal(currentReport({job, workspace, node: 'product:0', dirty: false}), job.result);
  for (const change of [{dirty: true}, {node: 'product:1'}, {workspace: {revision: 9}}, {job: {...job, status: 'failed'}}, {job: {...job, result: {...job.result, workspace: {revision: 7}}}}]) {
    assert.equal(currentReport({job, workspace, node: 'product:0', dirty: false, ...change}), null);
  }
});

test('new saved results update only untouched fields and preserve concurrent edits', () => {
  const old = {inputs: 'saved input', deliverable: 'old result'};
  assert.deepEqual(mergeDraft(old, {inputs: 'typed during request', deliverable: 'old result'}, {inputs: 'saved input', deliverable: 'new result'}), {inputs: 'typed during request', deliverable: 'new result'});
  assert.deepEqual(mergeDraft(old, {inputs: 'typed input', deliverable: 'typed result'}, {inputs: 'saved input', deliverable: 'new result'}), {inputs: 'typed input', deliverable: 'typed result'});
});

test('home signals use accessible saved records and distinguish permission from readiness', () => {
  const nodes = [
    {key:'product:0',status:'draft',hasDeliverable:true,adapter:true,capabilities:{view:true,edit:true,execute:true}},
    {key:'product:1',status:'waiting_user',hasDeliverable:true,adapter:true,capabilities:{view:true,approve:true}},
    {key:'design:0',status:'approved',hasDeliverable:true,adapter:true,capabilities:{view:false,edit:true,execute:true}},
    {key:'product:custom-a',status:'draft',hasDeliverable:false,adapter:false,capabilities:{view:true,edit:true,execute:true}},
  ];
  const signals = homeSummary({project:true,nodes});
  assert.deepEqual([signals.total,signals.saved,signals.approved,signals.pending,signals.runnable],[3,2,0,1,1]);
  assert.equal(signals.next.key,'product:1');
  assert.equal(signals.next.kind,'review');
  assert.equal(homeSummary({project:false,nodes}).next.kind,'project');
  assert.equal(homeSummary({project:true,nodes:nodes.filter(n=>!n.capabilities.view)}).next.kind,'access');
  assert.equal(homeSummary({project:true,nodes:[{...nodes[0],status:'approved'}]}).next.kind,'complete');
  assert.equal(homeSummary({project:true,nodes:[nodes[3]]}).runnable,0);
});

test('run progress distinguishes live output, stale telemetry and transport retries', () => {
  const {progressSummary}=require('../web/workbench.js');
  const now=1800000000000;
  assert.equal(progressSummary(null,now),'');
  const live=progressSummary({state:'running',requested_model:'gpt-6.1-sol',effort:'high',assistant_chars:234,seconds_since_response:12,progress_updated_at:now/1000},now);
  assert.match(live,/gpt-6.1-sol.*high/);assert.match(live,/234/);assert.match(live,/12 秒/);
  const retry=progressSummary({state:'retrying',attempt:2,max_attempts:3,progress_updated_at:now/1000},now);
  assert.match(retry,/重试.*2\/3/);assert.doesNotMatch(retry,/成功|失败/);
  const stale=progressSummary({state:'running',assistant_chars:234,seconds_since_response:12,progress_updated_at:now/1000-90},now);
  assert.match(stale,/102 秒/);assert.match(stale,/进度更新已中断/);assert.doesNotMatch(stale,/执行失败/);
});
