// Isolated HTTP/SQLite/UI fixtures. No real model, source repository or external writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-qa-actions-'));
 const bootstrap=`import sys,json
from server.store import Store
from server.app import create_server
store=Store(sys.argv[1]);studio=store.studios()[0]['id'];project=store.create_project('操作栏隔离样例')['id'];task=store.create_task(project,'1200 项评审布局样例')
task=store.import_requirement(project,task['id'],'隔离需求','奖励只能领取一次');rid=task['requirements'][0]['id']
store.record_artifact(project,task['id'],0,{'points':[{'id':'P','title':'领取边界','requirement_id':rid,'quote':'奖励只能领取一次'}],'cases':[{'id':'C','title':'重复领取','point_ids':['P'],'preconditions':['已领取'],'steps':[{'action':'再次领取','expected':'金币不增加'}]}],'gaps':[],'ambiguities':['待确认边界 '+str(i) for i in range(1200)],'coverage':{'identified':1,'covered':1,'gaps':0,'scope':'隔离 UI 样例'}})
server=create_server('127.0.0.1',0,sys.argv[1],local_development=True)
print(json.dumps({'port':server.server_port,'studio':studio,'project':project,'task':task['id']}),flush=True)
server.serve_forever()`;
 const server=spawn('python3',['-u','-c',bootstrap,path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+15000;while(!output.includes('"port"')){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50));}
  const c=JSON.parse(output.split('\n').find(l=>l.startsWith('{'))),base='http://127.0.0.1:'+c.port;
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(6000);
  async function visibleActions(ui,label){
   const rect=await ui.locator('.footeraction').boundingBox();
   assert(rect&&rect.y>=0&&rect.y+rect.height<=1001,label+': actions must fit visible browser viewport; '+JSON.stringify(rect));
   assert(await ui.locator('.footeraction').getByRole('button',{name:'确认当前节点',exact:true}).isVisible());
  }
  for(const embedded of [false,true]){
   const url=embedded?base+'/?'+new URLSearchParams({studio:c.studio,project:c.project,node:'testing:0'}):base+'/testing.html?'+new URLSearchParams({studio:c.studio,project:c.project,task:c.task});
   await page.goto(url);const ui=embedded?page.frameLocator('#testing-frame'):page;
   await ui.locator('.workspace-head').waitFor();
   await ui.locator('body').evaluate(()=>{task.node_skills['0'].name='test-scenarios + requirements-coverage + game-static-evidence / very-long-default-skill-name';reviewExpanded=true;render();document.querySelector('.workspace-head').scrollIntoView();});
   await ui.getByRole('tab',{name:/待确认/}).click();
   assert.equal(await ui.locator('.review-row').count(),1200);
   await visibleActions(ui,(embedded?'embedded':'standalone')+' list start');
   const middle=ui.locator('.review-row').nth(600);await middle.scrollIntoViewIfNeeded();
   await visibleActions(ui,'list middle');
   const last=ui.locator('.review-row').last();await last.scrollIntoViewIfNeeded();await ui.locator('body').evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));
   await visibleActions(ui,'list end');
   const end=await last.boundingBox(),bar=await ui.locator('.footeraction').boundingBox();assert(end.y+end.height<=bar.y+1,'last review item must not be hidden by actions '+JSON.stringify({end,bar}));
   await ui.locator('.workspace-head').scrollIntoViewIfNeeded();
   const header=await ui.locator('.workspace-head').boundingBox(),tools=ui.getByRole('button',{name:'Skill 工具',exact:true}),choose=ui.getByRole('button',{name:'选择 Skill',exact:true});
   const a=await tools.boundingBox(),b=await choose.boundingBox();assert(Math.abs(a.y-b.y)<2,'Skill controls stay on the same row');assert(header.height<100,'desktop toolbar must stay compact');
   await ui.locator('body').evaluate(()=>{casePageSize=50;render();});
   assert.equal(await ui.locator('[data-section=cases] .pagination select').inputValue(),'50','redraw preserves requested case page size');
   const visualDir=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(visualDir,{recursive:true});await page.screenshot({path:path.join(visualDir,'qa-actions-'+(embedded?'embedded-':'')+'header.png')});
   await tools.click();const menu=ui.locator('#qa-skill-menu');assert(await menu.isVisible());
   await page.keyboard.press('Escape');assert(!(await menu.isVisible()));assert(await tools.evaluate(el=>el===document.activeElement),'Escape returns focus to trigger');
   await tools.click();await ui.locator('.workspace-head').click({position:{x:3,y:3}});assert(!(await menu.isVisible()),'outside click dismisses tools');
   await tools.click();await page.keyboard.press('ArrowDown');assert.equal(await ui.locator(':focus').innerText(),'在 Codex 使用');
   await page.keyboard.press('End');assert.equal(await ui.locator(':focus').innerText(),'导出 Skill');
   await ui.locator('body').evaluate(()=>render());assert(await menu.isVisible(),'poll redraw keeps active menu open');assert.equal(await ui.locator(':focus').innerText(),'导出 Skill','redraw preserves keyboard focus inside menu');
   await menu.getByRole('button',{name:'检查 Skill',exact:true}).click();await ui.locator('.workflow-skill-check').waitFor();assert(!(await menu.isVisible()),'choosing tool closes menu');await page.keyboard.press('Escape');
   await ui.locator('.review-row').first().locator('summary').click();
   await ui.locator('#case-risk-0').selectOption('needs_revision');await ui.locator('#case-risk-reason-0').fill('尚未保存的边界说明');
   await ui.locator('body').evaluate(()=>render());assert.equal(await ui.locator('#case-risk-reason-0').inputValue(),'尚未保存的边界说明','poll does not erase review edits');
   let releaseSave,saveRequests=0;
   await page.route('**/case-review',async route=>{saveRequests++;await new Promise(r=>releaseSave=r);await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'隔离样例：模拟保存冲突'})});});
   await ui.locator('.footeraction [data-case-review-save]').click();
   await ui.locator('body').evaluate(()=>{saveCaseReview();testingCapabilities.nodes['testing:0'].approve=false;testingCapabilities.nodes['testing:0'].skill_import=false;render();});
   assert.equal(saveRequests,1,'pending save cannot submit twice');
   releaseSave();await ui.locator('body').evaluate(async()=>{while(caseReviewSaving)await new Promise(r=>setTimeout(r,10));});
   assert.equal(await ui.locator('#case-risk-reason-0').inputValue(),'尚未保存的边界说明','failed save keeps edits');
   await page.unroute('**/case-review');
   assert(await choose.isDisabled());assert(await ui.locator('.footeraction').getByRole('button',{name:'确认当前节点',exact:true}).isDisabled());assert(await ui.locator('.footeraction [data-case-review-save]').isDisabled());
   await tools.click();assert(await menu.getByRole('button',{name:'导入 Skill',exact:true}).isDisabled());await page.keyboard.press('Escape');
   await ui.locator('body').evaluate(()=>{testingCapabilities.nodes['testing:0'].approve=true;testingCapabilities.nodes['testing:0'].skill_import=true;render();});
   let releaseDecision,decisionRequests=0;
   await page.route('**/decisions',async route=>{decisionRequests++;await new Promise(r=>releaseDecision=r);await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'隔离样例：模拟确认冲突'})});});
   const confirm=ui.locator('.footeraction [data-qa-confirm]');await confirm.click();
   await ui.locator('body').evaluate(()=>decide('confirm'));
   assert.equal(decisionRequests,1,'pending confirmation cannot submit twice');assert(await confirm.isDisabled());
   releaseDecision();await ui.locator('body').evaluate(async()=>{while(QA_decisionPending)await new Promise(r=>setTimeout(r,10));});
   assert(await confirm.isEnabled(),'failed confirmation restores the permitted action');assert.equal(await ui.locator('#case-risk-reason-0').inputValue(),'尚未保存的边界说明','failed confirmation keeps edits');
   await page.unroute('**/decisions');
   await ui.locator('body').evaluate(()=>document.querySelectorAll('.toast').forEach(el=>el.remove()));
   for(const theme of ['paper','forge','arcade']){
    await ui.locator('body').evaluate((_,theme)=>{document.documentElement.dataset.theme=theme;document.querySelector('.review-row:nth-of-type(600)')?.scrollIntoView();},theme);
    await visibleActions(ui,theme);
    const colors=await ui.locator('.footeraction').evaluate(el=>({bar:getComputedStyle(el).backgroundColor,panel:getComputedStyle(el.closest('.panel')).backgroundColor}));assert.equal(colors.bar,colors.panel,'bar uses opaque theme surface');
    const shots=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(shots,{recursive:true});await page.screenshot({path:path.join(shots,'qa-actions-'+(embedded?'embedded-':'')+theme+'.png')});
   }
   console.log('PASS:',embedded?'embedded':'standalone','1200 rows, compact tools, focus, menus, redraw, permissions, three themes');
  }
  await page.setViewportSize({width:390,height:850});
  await page.goto(base+'/testing.html?'+new URLSearchParams({studio:c.studio,project:c.project,task:c.task}));await page.locator('.workspace-head').waitFor();
  await page.locator('.drawer-close').click();
  await page.locator('aside').evaluate(async el=>{await Promise.all(el.getAnimations().map(animation=>animation.finished));});
  await page.locator('body').evaluate(()=>{reviewExpanded=true;render();});
  await page.getByRole('tab',{name:/待确认/}).click();
  const mobile=await page.locator('.footeraction').boundingBox();assert(mobile.x>=0&&mobile.x+mobile.width<=391&&mobile.y+mobile.height<=851,'mobile actions fit viewport');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile has no horizontal page overflow');
  assert(await page.locator('.footeraction [data-qa-confirm]').evaluate(el=>{const r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===el;}),'mobile confirm is not covered by navigation');
  await page.getByRole('button',{name:'更多操作',exact:true}).click();await page.keyboard.press('Escape');
  await page.screenshot({path:path.resolve(__dirname,'../../data/visual-review/qa-actions-mobile.png')});
  assert.deepEqual(errors,[]);
  console.log('PASS: narrow viewport; no model, Unity, webhook or real data calls.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
