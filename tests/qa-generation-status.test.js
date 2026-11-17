const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8');
const status=source.split('\n').find(line=>line.startsWith('function operationStatus()'));
function render(job){return vm.runInNewContext(status+';operationStatus()',{
 task:{jobs:[{stage:0,revision:1,kind:'generate',...job}]},selectedStage:0,
 operationDuration:()=>'',beijingTime:value=>value,
 escapeHtml:value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
});}
test('generation shows bounded validation correction and escapes its error',()=>{
 const html=render({status:'running',progress:{requested_model:'m',state:'validation_repair',
  validation_attempt:1,validation_max_attempts:3,validation_error:'引用不匹配 <script>'}});
 assert.match(html,/正在校正/);
 assert.match(html,/校正 1 \/ 2/);
 assert.match(html,/&lt;script&gt;/);
});
test('failed generation does not describe a stale concurrent request as waiting',()=>{
 const html=render({status:'failed',error:'引用校验失败',progress:{requested_model:'m',state:'started'}});
 assert.doesNotMatch(html,/等待响应/);
 assert.match(html,/已停止/);
});
