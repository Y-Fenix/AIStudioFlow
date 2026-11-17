const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8');
function context(){
 const elements={'case-decomposition-top':{checked:true},'case-decomposition':{checked:false},'case-risk-0':{value:'accept_scope_gap'},'case-risk-reason-0':{value:'本次保留范围风险'}};
 let saves=0,resolve;
 const pending=new Promise(r=>resolve=r),buttons=[{},{}];
 const c={taskEnded:()=>false,activeJob:()=>null,testingCapabilities:{nodes:{'testing:0':{approve:true}}},selectedStage:0,task:{artifacts:{'0':{}},case_review_items:[{id:'risk',detail:'缺少接口资料',source:'req'}]},reviewExpanded:true,caseReviewSaving:false,escapeHtml:String,$:id=>elements[id],notice:()=>{},document:{querySelectorAll:selector=>selector==='[data-case-review-save]'?buttons:[elements['case-decomposition-top'],elements['case-decomposition']]},saveStage:async(route,data)=>{saves++;assert.equal(route,'case-review');assert.equal(data.decomposition_confirmed,true);await pending;}};
 vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function caseReviewView()'),source.indexOf('async function importReferences(')),c);
 return {c,elements,buttons,resolve,saves:()=>saves};
}
test('review has confirmation and save in bulk toolbar before first risk row',()=>{
 const {c}=context(),html=c.caseReviewView(),top=html.slice(0,html.indexOf('class="review-row"'));
 assert.match(top,/data-case-review-save/);assert.match(top,/case-decomposition-top/);assert.match(top,/保存范围评审/);
});
test('top confirmation syncs bottom; duplicate saves submit only once and disable both buttons',async()=>{
 const {c,elements,buttons,resolve,saves}=context();
 assert.equal(typeof c.QA_syncReviewConfirmation,'function');c.QA_syncReviewConfirmation(true);
 assert.equal(elements['case-decomposition'].checked,true);
 const first=c.saveCaseReview();await c.saveCaseReview();assert.equal(saves(),1);assert(buttons.every(b=>b.disabled));
 resolve();await first;assert(buttons.every(b=>!b.disabled));
});

test('failed save preserves revoked permission on every save button',async()=>{
 const {c,buttons,resolve}=context();const pending=c.saveCaseReview();
 c.testingCapabilities.nodes['testing:0'].approve=false;resolve();await pending;
 assert(buttons.every(b=>b.disabled),'completion cannot re-enable revoked actions');
});

test('risk list defaults to display and makes classification basis explicit',()=>{
 const {c}=context();const html=c.caseReviewView();
 assert.match(html,/按问题类型初步分级/);assert.match(html,/查看或处理/);
 assert.doesNotMatch(html,/data-review-status="0">待处理/);
});

test('risk items use distinct origin styles and wrap content separately from metadata',()=>{
 const {c}=context(); c.task.case_review_items=[{id:'a',kind:'source_gap',detail:'来源问题',source:'req'},{id:'b',kind:'coverage_gap',detail:'覆盖问题',source:'req'},{id:'c',kind:'ambiguity',detail:'需求问题',source:'req'}];
 const html=c.caseReviewView();
 assert.match(html,/class="qa-review-content"/);assert.match(html,/class="qa-review-meta"/);
 for(const name of ['source','coverage','ambiguity'])assert.match(html,new RegExp('qa-risk-origin is-'+name));
});

test('paused automation displays its reason outside the compact control',()=>{
 const start=source.indexOf('function QA_automationNotice()');assert.notEqual(start,-1);
 const end=source.indexOf('function QA_automationControls()',start);const c={task:{automation:{enabled:false,state:'paused',detail:'请先绑定仓库'}},escapeHtml:String};vm.createContext(c);vm.runInContext(source.slice(start,end),c);
 assert.match(c.QA_automationNotice(),/请先绑定仓库/);c.task.automation.state='running';assert.equal(c.QA_automationNotice(),'');
});

test('paused notice can be dismissed without changing automation and returns for a new reason',()=>{
 const start=source.indexOf('function QA_automationNotice()'),end=source.indexOf('function QA_automationControls()',start);
 const c={task:{id:'one',automation:{state:'paused',detail:'原因一'}},escapeHtml:String,render:()=>{}};vm.createContext(c);vm.runInContext(source.slice(start,end),c);
 assert.match(c.QA_automationNotice(),/关闭/);c.QA_dismissAutomationNotice();assert.equal(c.QA_automationNotice(),'');assert.equal(c.task.automation.state,'paused');c.task.automation.detail='原因二';assert.match(c.QA_automationNotice(),/原因二/);
});

test('old pause reason is not shown as current after task content changes',()=>{
 const start=source.indexOf('function QA_automationNotice()'),end=source.indexOf('function QA_automationControls()',start);
 const c={task:{id:'one',revision:20,automation:{state:'paused',last_task_revision:8,detail:'请先绑定仓库'}},escapeHtml:String,render:()=>{}};vm.createContext(c);vm.runInContext(source.slice(start,end),c);
 assert.equal(c.QA_automationNotice(),'');
 c.task.automation.last_task_revision=20;assert.match(c.QA_automationNotice(),/请先绑定仓库/);
});
