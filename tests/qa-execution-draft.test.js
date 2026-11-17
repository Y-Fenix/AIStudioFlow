const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
function context(){
 const store=new Map(),fields={'execution-path':{value:'/repo/game'},'execution-branch':{value:'main'}},messages=[];
 const c={studioId:'studio',project:{id:'project'},task:{id:'task',binding:null},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)},$:id=>fields[id],notice:m=>messages.push(m)};
 vm.createContext(c);const begin=source.indexOf('function QA_executionDraftKey()'),end=source.indexOf('async function bindExecution()',begin);assert(begin>=0);vm.runInContext(source.slice(begin,end),c);return {c,fields,store,messages};
}
test('save and restore path and branch per task without binding',()=>{const {c,fields}=context();c.QA_saveExecutionDraft();fields['execution-path'].value='';assert.equal(c.QA_readExecutionDraft().path,'/repo/game');assert.equal(c.QA_readExecutionDraft().branch,'main');c.task.id='other';assert.equal(c.QA_readExecutionDraft(),null)});
test('storage failure is reported instead of claiming success',()=>{const {c,messages}=context();c.localStorage.setItem=()=>{throw Error('denied')};c.QA_saveExecutionDraft();assert.match(messages.at(-1),/无法保存/)});
test('cancelled execution directs users to restore the batch and disables execution',()=>{
 const start=source.indexOf('function executionView()'),end=source.indexOf('\nlet analysingAttribution',start);
 const c={task:{status:'cancelled',stage:1,binding:{repository:'/repo',execution_suite:'static'}},QA_readExecutionDraft:()=>null,escapeHtml:String,executingLogic:false,activeJob:()=>null,taskEnded:()=>true,caseMappingView:()=>'',executionResults:()=>''};
 vm.createContext(c);vm.runInContext(source.slice(start,end),c);const html=c.executionView();
 assert.match(html,/批次已取消/);assert.match(html,/恢复批次/);assert.doesNotMatch(html,/重置执行节点/);
 assert.match(html,/onclick="bindExecution\(\)"[^>]*disabled/);assert.match(html,/onclick="executeLogic\(\)"[^>]*disabled/);
});
test('cancelled tasks cannot be reset through the workspace',()=>{
 assert.match(source,/function openNodeReset\(\)\{if\(!task\|\|task\.status==='cancelled'/);
});
test('run details emphasize field labels',()=>{
 for(const label of ['最近操作','任务累计','请求模型','模型来源','进度更新'])
  assert.ok(source.includes('<strong>'+label+'：</strong>'),label);
});
