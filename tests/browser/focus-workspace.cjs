// Isolated real HTTP/SQLite fixture, no model or external writes.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-focus-'));
 const bootstrap=`import sys,json
from server.store import Store
from server.app import create_server
s=Store(sys.argv[1]);studio=s.studios()[0]['id'];p=s.create_project('FOCUS验收项目')['id'];t=s.create_task(p,'版本验证');t=s.import_requirement(p,t['id'],'玩法需求','奖励只能领取一次');rid=t['requirements'][0]['id']
s.record_artifact(p,t['id'],0,{'points':[{'id':'P','title':'领取边界','requirement_id':rid,'quote':'奖励只能领取一次'}],'cases':[{'id':'C'+str(i),'title':'领取边界 '+str(i),'point_ids':['P'],'preconditions':['已领取'],'steps':[{'action':'再次领取','expected':'金币不增加'}]} for i in range(933)],'gaps':[],'ambiguities':['待确认边界 '+str(i) for i in range(120)],'coverage':{'identified':1,'covered':1,'gaps':0,'scope':'隔离UI样例'}})
with s.connection() as db:
 db.execute("INSERT INTO jobs(id,project_id,task_id,revision,status,stage) VALUES(?,?,?,?,?,?)",('layout-job',p,t['id'],t['revision'],'completed',0))
 for i in range(45): s._event(db,t['id'],'user_decision','日志滚动样例 '+str(i),0)
server=create_server('127.0.0.1',0,sys.argv[1],local_development=True)
empty=s.create_task(p,'空需求批次')
stop=s.create_task(p,'终止验证')
with s.connection() as db:
 db.execute("INSERT INTO jobs(id,project_id,task_id,revision,status,stage,kind) VALUES(?,?,?,?,?,?,?)",('stop-job',p,stop['id'],stop['revision'],'running',0,'generate'))
print(json.dumps({'port':server.server_port,'studio':studio,'project':p,'task':t['id'],'empty':empty['id'],'stop':stop['id']}),flush=True);server.serve_forever()`;
 const server=spawn('python3',['-u','-c',bootstrap,path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+15000;while(!output.includes('"port"')){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const c=JSON.parse(output.split('\n').find(l=>l.startsWith('{'))),base='http://127.0.0.1:'+c.port;
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:800}}),errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error('PAGE ERROR',e.message)});page.setDefaultTimeout(5000);
  for(const embedded of [false,true]){
   await page.goto(embedded?base+'/?'+new URLSearchParams({studio:c.studio,project:c.project,node:'testing:0',task:c.task}):base+'/testing.html?'+new URLSearchParams({studio:c.studio,project:c.project,task:c.task}));
   const ui=embedded?page.frameLocator('#testing-frame'):page;
   await page.waitForFunction(({embedded,id})=>{try{return embedded?document.querySelector('#testing-frame')?.contentWindow.eval('task?.id')===id:task?.id===id}catch{return false}},{embedded,id:c.task});
   await ui.locator('.qa-workspace-panel').waitFor();
   assert.deepEqual(await ui.locator('.focus-tabs [role=tab]').evaluateAll(x=>x.map(e=>e.dataset.focusTab)),['sources','cases','review']);
   await ui.locator('body').evaluate(()=>{notice('提示一');notice('提示二')});assert.equal(await ui.locator('body > .toast').count(),1,'successive notices do not overlap');assert.equal(await ui.locator('body > .toast').textContent(),'提示二');assert.equal(await ui.locator('.focus-job-indicator').count(),0,'status text is not mixed into toolbar buttons');
   await ui.getByRole('tab',{name:/测试用例/}).click();
   assert(await ui.locator('[data-section=cases] table').isVisible(),'cases visible without opening nested disclosures');
   assert(!(await ui.locator('.requirement-inputs').isVisible()),'sources do not crowd case list');
   const visibleRows=await ui.locator('[data-section=cases] tbody tr').evaluateAll(rows=>{const clip=document.querySelector('.qa-workspace-panel>.panelbody').getBoundingClientRect();return rows.filter(row=>{const r=row.getBoundingClientRect();return r.top>=clip.top&&r.bottom<=clip.bottom}).length});console.log('VISIBLE ROWS',embedded?'embedded':'standalone',visibleRows);assert(visibleRows>=5,'1440×800 with completed job must show at least 5 full case rows, got '+visibleRows);
   await ui.getByRole('button',{name:'运行详情',exact:true}).click();assert(await ui.locator('dialog[open] .operation-status').isVisible());await page.keyboard.press('Escape');
   await ui.locator('body').evaluate(()=>{Object.assign(task.jobs[0],{kind:'generate',status:'running',revision:task.revision,progress:{batch:3,batches:4,completed:2,phase:'design',events_received:2,seconds_since_response:8,progress_updated_at:Date.now()/1000}});render()});
   const progress=ui.locator('#focus-progress-trigger');assert.match(await progress.textContent(),/已完成 2 \/ 4 个需求分段/);const widthBefore=await ui.locator('.qa-workspace-panel').evaluate(el=>el.getBoundingClientRect().width);
   await progress.click();assert.match(await ui.locator('dialog[open]').textContent(),/最近更新：需求分段 3 \/ 4/);assert.match(await ui.locator('dialog[open]').textContent(),/分段生成与审计/);assert.equal(await ui.locator('dialog[open] .focus-progress-stage').count(),3);await ui.locator('body').evaluate(()=>render());assert(await ui.locator('dialog[open] [data-focus-drawer=progress]').isVisible(),'progress drawer survives redraw');
   assert(await ui.getByRole('button',{name:'终止任务',exact:true}).isVisible());
   assert.equal(await ui.locator('.focus-progress-stage.is-current .focus-stage-number').evaluate(el=>getComputedStyle(el,'::after').animationName),'qa-progress-orbit');
   await ui.getByRole('button',{name:/查看运行详情/}).click();
   assert(await ui.locator('dialog[open] [data-focus-drawer=diagnostics]').isVisible());
   await ui.getByRole('button',{name:'返回任务进度',exact:true}).click();
   assert(await ui.locator('dialog[open] [data-focus-drawer=progress]').isVisible(),'back returns to generation progress');
   await page.keyboard.press('Escape');assert(await ui.locator('dialog.is-closing').count(),'drawer animates before closing');await ui.locator('dialog[open]').waitFor({state:'hidden'});assert(await progress.evaluate(el=>el===document.activeElement),'progress trigger regains focus');assert.equal(await ui.locator('.qa-workspace-panel').evaluate(el=>el.getBoundingClientRect().width),widthBefore,'drawer does not compress workspace');
   await ui.locator('body').evaluate(()=>{task.jobs[0].status='completed';task.jobs[0].progress={};render()});
   await ui.locator('body').evaluate(async()=>{const originalApi=api,originalCheck=canImportRequirements;const mock=structuredClone(task);Object.assign(mock.jobs[0],{kind:'generate',status:'queued',progress:{}});api=async url=>url.endsWith('/generation-jobs')?{}:mock;canImportRequirements=()=>true;try{await generateCases()}finally{api=originalApi;canImportRequirements=originalCheck}});
   assert(await ui.locator('dialog[open] [data-focus-drawer=progress]').isVisible(),'generation opens progress drawer automatically');await page.keyboard.press('Escape');await ui.locator('dialog[open]').waitFor({state:'hidden'});await ui.locator('body').evaluate(()=>{task.jobs[0].status='completed';render()});
   await ui.locator('body').evaluate(()=>{task.jobs[0].status='failed';task.jobs[0].error='隔离样例失败原因';render()});assert.match(await ui.getByRole('button',{name:'运行详情',exact:true}).getAttribute('class'),/focus-failure/);await ui.getByRole('button',{name:'运行详情',exact:true}).click();assert.match(await ui.locator('dialog[open] .operation-status').textContent(),/隔离样例失败原因/);await page.keyboard.press('Escape');await ui.locator('body').evaluate(()=>{task.jobs[0].status='completed';task.jobs[0].error=null;render()});
   await ui.getByRole('textbox',{name:'搜索测试用例',exact:true}).fill('C932');assert.equal(await ui.locator('[data-section=cases] tbody tr').count(),1);assert.match(await ui.locator('[data-section=cases] tbody').textContent(),/C932/);await ui.locator('[data-section=cases] tbody').getByRole('button',{name:'详情',exact:true}).click();assert.match(await ui.locator('#overlay .panelhead h2').textContent(),/C932/);await page.keyboard.press('Escape');
   await ui.getByRole('textbox',{name:'搜索测试用例',exact:true}).fill('');
   await ui.locator('[data-section=cases] .pagination select').selectOption('20');assert.equal(await ui.locator('[data-section=cases] tbody tr').count(),20);
   await ui.locator('[data-section=cases] .pagination button').last().click();assert.equal(await ui.locator('[data-section=cases] tbody tr').count(),20);

   await ui.getByRole('tab',{name:/需求来源/}).click();assert(await ui.locator('.requirement-inputs').isVisible());
   await ui.getByRole('tab',{name:/待确认/}).click();
   await ui.locator('[data-review-edit] > summary').click();
   await ui.locator('.review-row').first().locator('summary').click();await ui.locator('#case-risk-reason-0').fill('保留的评审说明');
   await ui.locator('body').evaluate(()=>render());assert.equal(await ui.locator('#case-risk-reason-0').inputValue(),'保留的评审说明');
   assert.equal(await ui.getByRole('tab',{name:/待确认/}).getAttribute('aria-selected'),'true');
   const last=ui.locator('.review-row').last();await last.scrollIntoViewIfNeeded();
   const bar=await ui.locator('.footeraction').boundingBox();const viewport=page.viewportSize().height;assert(bar.y>=0&&bar.y+bar.height<=viewport+1,'actions in viewport '+JSON.stringify(bar));
   await ui.getByRole('button',{name:'操作日志',exact:true}).click();await ui.locator('dialog[open]').waitFor();
   await ui.locator('body').evaluate(()=>{const content=document.querySelector('.focus-drawer-body');content.scrollTop=150;});
   const logScroll=await ui.locator('.focus-drawer-body').evaluate(el=>el.scrollTop);assert(logScroll>=100,'fixture must actually scroll the log');
   await ui.locator('body').evaluate(()=>render());assert(await ui.locator('dialog[open] .operation-log').isVisible(),'open drawer survives polling');
   assert.equal(await ui.locator('.focus-drawer-body').evaluate(el=>el.scrollTop),logScroll,'log scroll survives polling');
   await page.keyboard.press('Escape');await ui.locator('dialog[open]').waitFor({state:'hidden'});assert(await ui.getByRole('button',{name:'操作日志',exact:true}).evaluate(el=>el===document.activeElement),'Escape restores trigger focus');
   await ui.getByRole('button',{name:'节点助手',exact:true}).click();assert(await ui.locator('dialog[open] .node-memory textarea').isVisible());
   await ui.locator('dialog[open] .node-memory textarea').fill('保留助手草稿');await ui.locator('body').evaluate(()=>render());assert.equal(await ui.locator('dialog[open] textarea').inputValue(),'保留助手草稿');
   const drawerRect=await ui.locator('dialog[open]').boundingBox();await page.mouse.click(drawerRect.x-10,drawerRect.y+100);await ui.locator('dialog[open]').waitFor({state:'hidden'});
   await ui.locator('body').evaluate(()=>{casePage=1;render()});
   for(const theme of ['paper','forge','arcade']){
    await ui.locator('body').evaluate((_,t)=>{document.documentElement.dataset.theme=t},theme);
    await ui.getByRole('tab',{name:/测试用例/}).click();
    const dir=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,`focus-${embedded?'embedded':'standalone'}-${theme}.png`)});
   }
   for(const stage of [1,2,4,5]){
    await ui.locator('body').evaluate((_,stage)=>{selectedStage=stage;render()},stage);
    assert(await ui.locator('.footeraction').isVisible(),'actions retained in stage '+stage);
    await ui.getByRole('button',{name:'操作日志',exact:true}).click();assert(await ui.locator('dialog[open]').isVisible());await page.keyboard.press('Escape');
   }
   console.log('PASS',embedded?'embedded':'standalone','tabs, drafts, drawer redraw, ESC, footer, themes');
  }
  await page.goto(base+'/testing.html?'+new URLSearchParams({studio:c.studio,project:c.project,task:c.stop}));
  await page.waitForFunction(id=>task?.id===id,c.stop);
  await page.locator('#focus-progress-trigger').click();
  page.once('dialog',dialog=>dialog.dismiss());
  await page.getByRole('button',{name:'终止任务',exact:true}).click();
  assert.notEqual(await page.evaluate(()=>task.status),'cancelled','dismiss does not cancel task');
  page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'终止任务',exact:true}).click();
  await page.waitForFunction(()=>task.status==='cancelled');
  assert.equal(await page.evaluate(async()=> (await api('/api/projects/'+project.id+'/tasks/'+task.id)).status),'cancelled','server persisted cancellation');
  console.log('PASS isolated task cancellation confirmation and persisted state');
  await page.goto(base+'/testing.html?'+new URLSearchParams({studio:c.studio,project:c.project,task:c.empty}));
  await page.waitForFunction(id=>task?.id===id,c.empty);await page.getByRole('tab',{name:/需求来源/}).waitFor();assert.equal(await page.getByRole('tab',{name:/需求来源/}).getAttribute('aria-selected'),'true','empty task starts with sources');
  await page.locator('.import-choice').filter({hasText:'文件上传 / 粘贴正文'}).locator('summary').click();
  await page.locator('#requirement-source').fill('未保存来源');await page.locator('#requirement-content').fill('未保存需求正文');
  await page.getByRole('tab',{name:/测试用例/}).click();assert(await page.locator('.focus-empty').first().isVisible());
  await page.evaluate(()=>render());await page.getByRole('tab',{name:/需求来源/}).click();assert.equal(await page.locator('#requirement-content').inputValue(),'未保存需求正文');
  console.log('PASS empty task and source drafts across tabs/redraw');
  await page.setViewportSize({width:390,height:844});
  await page.goto(base+'/?'+new URLSearchParams({studio:c.studio,project:c.project,node:'testing:0',task:c.task}));
  const ui=page.frameLocator('#testing-frame');await ui.locator('.qa-workspace-panel').waitFor();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'outer narrow no overflow');
  assert(await ui.locator('body').evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'inner narrow no overflow');
  await page.screenshot({path:path.resolve(__dirname,'../../data/visual-review/focus-mobile.png')});
  assert.deepEqual(errors,[]);console.log('PASS narrow viewport; no real model or production data');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
