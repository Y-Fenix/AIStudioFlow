// Real HTTP/SQLite, production permissions and snapshot lifecycle; no model calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-library-'));
 const bootstrap=`import sys,json
from server.store import Store
from server.app import create_server
from server.requirements import validate_cases,review_cases
from server.core.testing_library import TestingLibrary
s=Store(sys.argv[1]);studio=s.studios()[0]['id'];p=s.create_project('GagaSort 样例')['id'];lib=TestingLibrary(s)
v=lib.create_version(studio,p,'1.0.0');old=None
for i in range(13):
 t=lib.create_batch(studio,p,{'title':'连胜排行' if i==0 else '历史用例 '+str(i),'version_id':v['id']})
 t=s.import_requirement(p,t['id'],'奖励需求','奖励只能领取一次');rid=t['requirements'][0]['id']
 a=validate_cases({'points':[{'id':'P','title':'领取边界','requirement_id':rid,'quote':'奖励只能领取一次'}],'cases':[{'id':'C'+str(n),'title':'领取边界 '+str(n),'point_ids':['P'],'preconditions':['已领取'],'steps':[{'action':'再次领取 '+str(n),'expected':'金币不增加'}]} for n in range(30)],'gaps':[],'ambiguities':[]},t['requirements'])
 a['user_review']=review_cases(a,t['requirements'],[],True);t=s.record_artifact(p,t['id'],0,a);t=s.decide(p,t['id'],'confirm',t['revision'])
 if i==0:old=t['id']
legacy=s.create_task(p,'历史批次（没有项目版本）')['id']
empty=s.create_project('删除最后批次样例')['id'];single=lib.create_batch(studio,empty,{'title':'唯一批次','version_name':'0.1'})['id']
server=create_server('127.0.0.1',0,sys.argv[1],local_development=True)
print(json.dumps({'port':server.server_port,'studio':studio,'project':p,'task':old,'legacy':legacy,'emptyproject':empty,'single':single}),flush=True);server.serve_forever()`;
 const server=spawn('python3',['-u','-c',bootstrap,path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+15000;while(!output.includes('"port"')){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const c=JSON.parse(output.split('\n').find(l=>l.startsWith('{'))),base='http://127.0.0.1:'+c.port;
  browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:800}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(5000);
  for(const embedded of [false,true]){
   const version=embedded?'1.2.0':'1.1.0';
   await page.goto(embedded?base+'/?'+new URLSearchParams({studio:c.studio,project:c.project,node:'testing:0',task:c.task}):base+'/testing.html?'+new URLSearchParams({studio:c.studio,project:c.project,task:c.task,stage:'0'}));
   const ui=embedded?page.frameLocator('#testing-frame'):page;
   await page.waitForFunction(({embedded,id})=>{try{return embedded?document.querySelector('#testing-frame')?.contentWindow.eval('task?.id')===id:task?.id===id}catch{return false}},{embedded,id:c.task});
   await ui.locator('body').evaluate(()=>{selectedStage=0;render()});
   await ui.getByRole('tab',{name:/需求来源/}).click();
   assert(await ui.locator('[data-qa-generation-blocked]').isVisible(),'later stage has actionable inline reason');
   assert(await ui.locator('[data-qa-generate]').isDisabled(),'cannot trigger a known rejected action');
   await ui.getByRole('button',{name:'新建测试批次',exact:true}).first().click();
   await ui.locator('#qa-batch-version').selectOption('__new__');await ui.locator('#qa-batch-version-name').fill(version);await ui.locator('#qa-batch-title').fill('新版本奖励测试');
   await ui.getByRole('button',{name:'创建并进入',exact:true}).click();await ui.locator('#qa-batch-create').waitFor({state:'detached'});
   await ui.getByRole('tab',{name:/需求来源/}).waitFor();
   await ui.locator('body').evaluate(()=>{if(task.version?.name===undefined)throw Error('version absent')});
   assert.equal(await ui.locator('body').evaluate(()=>task.version.name),version);
   assert.equal(await ui.locator('body').evaluate(()=>task.stage),0);assert.equal(await ui.locator('body').evaluate(()=>task.requirements.length),0);
   await ui.getByRole('button',{name:'版本管理',exact:true}).click();await ui.getByRole('combobox',{name:'管理版本'}).waitFor();
   assert.match(await ui.locator('.qa-manager-list').textContent(),/新版本奖励测试/,'empty batches belong in manager');
   await ui.getByRole('button',{name:'重命名版本',exact:true}).click();await ui.locator('#qa-manager-name').fill('1.0.0');await ui.getByRole('button',{name:'保存名称',exact:true}).click();await ui.locator('.qa-manager-error').filter({hasText:'已存在'}).waitFor();
   await ui.locator('#qa-manager-name').fill(version+'-renamed');await ui.getByRole('button',{name:'保存名称',exact:true}).click();await ui.locator('#qa-manager-name').waitFor({state:'detached'});
   assert.equal(await ui.locator('body').evaluate(()=>task.version.name),version+'-renamed');
   await ui.getByRole('button',{name:'重命名批次',exact:true}).click();await ui.locator('#qa-manager-name').fill('空批次已改名');await ui.getByRole('button',{name:'保存名称',exact:true}).click();await ui.locator('#qa-manager-name').waitFor({state:'detached'});
   assert.equal(await ui.locator('body').evaluate(()=>task.title),'空批次已改名');assert.equal(await ui.locator('body').evaluate(()=>task.revision),1,'renaming must not change workflow revision');
   await page.screenshot({path:path.resolve(__dirname,'../../data/visual-review/qa-version-manager-'+(embedded?'embedded':'standalone')+'.png')});
   await page.keyboard.press('Escape');assert.equal(await ui.locator('#qa-manager-search').count(),0);
   await page.reload();await ui.getByRole('button',{name:'版本管理',exact:true}).waitFor();assert.equal(await ui.locator('body').evaluate(()=>task.title),'空批次已改名');

   await ui.getByRole('button',{name:'用例库',exact:true}).click();
   await ui.locator('[data-qa-library-table]').waitFor();
   await ui.getByRole('combobox',{name:'用例库版本'}).selectOption('');await ui.getByRole('combobox',{name:'每页用例集'}).selectOption('10');
   await ui.getByRole('button',{name:'下一页',exact:true}).click();await ui.locator('[data-qa-library-table] tbody tr').last().waitFor();
   await ui.getByRole('textbox',{name:'搜索用例集'}).fill('连胜排行');await ui.getByRole('button',{name:'搜索',exact:true}).click();
   await ui.locator('.qa-library-pagination>span').filter({hasText:'共 1 个用例集'}).waitFor();
   await ui.getByRole('button',{name:'归属版本',exact:true}).click();await ui.locator('#qa-batch-create').waitFor();assert.equal(await ui.locator('#qa-batch-version option:checked').textContent(),'1.0.0','assignment must default to target batch version');await page.keyboard.press('Escape');
   await ui.getByRole('button',{name:'查看快照',exact:true}).click();await ui.locator('#qa-snapshot-history').waitFor();
   assert.match(await ui.locator('#overlay').textContent(),/只读快照/);await page.keyboard.press('Escape');
   await ui.getByRole('button',{name:'复制',exact:true}).click();await ui.locator('#qa-batch-version').selectOption('__new__');await ui.locator('#qa-batch-version-name').fill(version+'-copy');await ui.locator('#qa-batch-title').fill('历史复制草稿');await ui.getByRole('button',{name:'创建并进入',exact:true}).click();await ui.locator('#qa-batch-create').waitFor({state:'detached'});
   await ui.getByRole('tab',{name:/测试用例/}).waitFor();
   assert.equal(await ui.locator('body').evaluate(()=>task.stage),0);assert.equal(await ui.locator('body').evaluate(()=>Object.keys(task.artifacts).join(',')),'0');assert.equal(await ui.locator('body').evaluate(()=>!!task.artifacts['0'].user_review),false);
   assert.equal(await ui.locator('body').evaluate(()=>task.artifacts['0'].cases.length),30);
   const copiedId=await ui.locator('body').evaluate(()=>task.id);await page.reload();await page.waitForFunction(({embedded,id})=>{try{return embedded?document.querySelector('#testing-frame')?.contentWindow.eval('task?.id')===id:task?.id===id}catch{return false}},{embedded,id:copiedId});
   await ui.getByRole('tab',{name:/测试用例/}).waitFor();
   const fullRows=await ui.locator('[data-section=cases] tbody tr').evaluateAll(rows=>{const clip=document.querySelector('.qa-workspace-panel>.panelbody').getBoundingClientRect();return rows.filter(row=>{const r=row.getBoundingClientRect();return r.top>=clip.top&&r.bottom<=clip.bottom}).length});assert(fullRows>=5,'must retain five full rows, got '+fullRows);
   await page.screenshot({path:path.resolve(__dirname,'../../data/visual-review/qa-case-library-workspace-'+(embedded?'embedded':'standalone')+'.png')});
   await ui.getByRole('button',{name:'用例库',exact:true}).click();await ui.locator('[data-qa-library-table]').waitFor();
   await ui.getByRole('textbox',{name:'搜索用例集'}).fill('');await ui.getByRole('button',{name:'搜索',exact:true}).click();await ui.locator('[data-qa-library-table] tbody tr').nth(5).waitFor();await ui.locator('.toast').last().waitFor({state:'detached'});
   const dir=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:path.join(dir,'qa-case-library-'+(embedded?'embedded':'standalone')+'.png')});
   await ui.getByRole('button',{name:'当前工作台',exact:true}).click();await ui.getByRole('tab',{name:/需求来源/}).click();await ui.locator('.import-choice').filter({hasText:'文件上传 / 粘贴正文'}).locator('summary').click();await ui.locator('#requirement-content').fill('保留的需求草稿');await ui.getByRole('button',{name:'用例库',exact:true}).click();await ui.getByRole('button',{name:'当前工作台',exact:true}).click();assert.equal(await ui.locator('#requirement-content').inputValue(),'保留的需求草稿');
   console.log('PASS',embedded?'embedded':'standalone','new version, non-destructive creation, library paging/search, immutable detail, independent copy, drafts, five rows');
  }
  // Legacy version setup is independent of the batch title; deletion always asks twice.
  {
   const ui=page.frameLocator('#testing-frame');
   await ui.getByRole('button',{name:'版本管理',exact:true}).click();
   await ui.getByRole('combobox',{name:'管理版本'}).selectOption('unassigned');
   await ui.getByRole('button',{name:'设置项目版本',exact:true}).click();
   await ui.locator('#qa-manager-name').fill('旧版本 1.7.0');
   await ui.getByRole('button',{name:'保存名称',exact:true}).click();
   await ui.locator('#qa-manager-name').waitFor({state:'detached'});
   await ui.getByRole('combobox',{name:'管理版本'}).selectOption({label:'旧版本 1.7.0'});
   assert.match(await ui.locator('.qa-manager-list').textContent(),/历史批次（没有项目版本）/);
   await ui.getByRole('button',{name:'删除版本',exact:true}).click();
   await ui.locator('#qa-delete-confirm').waitFor();
   assert.match(await ui.locator('#qa-delete-confirm').textContent(),/不会连同批次一起删除/);
   await page.keyboard.press('Escape');await ui.locator('#qa-delete-confirm').waitFor({state:'detached'});
   // Cancelling must not delete anything.
   await ui.getByRole('button',{name:'版本管理',exact:true}).click();
   await ui.getByRole('combobox',{name:'管理版本'}).selectOption({label:'旧版本 1.7.0'});
   await ui.getByRole('button',{name:'删除版本',exact:true}).click();
   await ui.getByRole('button',{name:'确认删除',exact:true}).click();
   await ui.locator('#qa-manager-search').waitFor();
   assert.equal(await ui.getByRole('combobox',{name:'管理版本'}).inputValue(),'unassigned');
   const legacy=ui.locator('.qa-manager-batch').filter({hasText:'历史批次（没有项目版本）'});
   assert.equal(await legacy.count(),1);
   await legacy.getByRole('button',{name:'删除批次',exact:true}).click();
   await ui.getByRole('button',{name:'取消',exact:true}).click();
   assert.equal(await legacy.count(),1);
   await legacy.getByRole('button',{name:'删除批次',exact:true}).click();
   await ui.getByRole('button',{name:'确认删除',exact:true}).click();
   await ui.locator('#qa-manager-search').waitFor();assert.equal(await legacy.count(),0);
   // Deleting the active batch updates the workspace and refresh URL as well.
   await ui.getByRole('combobox',{name:'管理版本'}).selectOption('');
   const active=await ui.locator('body').evaluate(()=>task.id);
   await ui.locator('.qa-manager-batch').filter({has:ui.locator('button[onclick*="'+active+'"]')}).getByRole('button',{name:'删除批次',exact:true}).click();
   await ui.getByRole('button',{name:'确认删除',exact:true}).click();
   await ui.locator('#qa-manager-search').waitFor();
   assert.notEqual(await ui.locator('body').evaluate(()=>task?.id),active);
   await page.keyboard.press('Escape');
   await page.reload();await ui.getByRole('button',{name:'版本管理',exact:true}).waitFor();
   assert.notEqual(await ui.locator('body').evaluate(()=>task?.id),active);
   console.log('PASS legacy version setup, confirmation cancel/ESC, version deletion preserves batches, active batch deletion and refresh');
  }
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));const ui=page.frameLocator('#testing-frame');assert(await ui.locator('body').evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await ui.getByRole('button',{name:'用例库',exact:true}).click();await ui.locator('[data-qa-library-table]').waitFor();assert(await ui.locator('body').evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'library uses internal horizontal scroll on narrow screens');await page.screenshot({path:path.resolve(__dirname,'../../data/visual-review/qa-case-library-mobile.png')});
  await page.setViewportSize({width:1440,height:800});
  await page.goto(base+'/?'+new URLSearchParams({studio:c.studio,project:c.emptyproject,node:'testing:0',task:c.single}));
  {
   const ui=page.frameLocator('#testing-frame');
   await ui.getByRole('button',{name:'版本管理',exact:true}).click();
   await ui.getByRole('button',{name:'删除批次',exact:true}).click();
   await ui.getByRole('button',{name:'确认删除',exact:true}).click();
   await ui.locator('#qa-manager-search').waitFor();await page.keyboard.press('Escape');
   await page.waitForFunction(()=>!new URL(location.href).searchParams.has('task'));
   assert.equal(await ui.locator('body').evaluate(()=>task),null);
   await page.reload();await ui.getByRole('button',{name:'版本管理',exact:true}).waitFor();
   assert.equal(await ui.locator('body').evaluate(()=>task),null);
   await ui.getByRole('combobox',{name:'工作台版本'}).selectOption({label:'0.1'});
   await ui.getByRole('button',{name:'删除当前版本',exact:true}).click();
   assert.match(await ui.locator('#qa-delete-confirm').textContent(),/该版本下 0 个批次将保留/);
   const confirmDelete=ui.getByRole('button',{name:'确认删除',exact:true});
   await confirmDelete.hover();
   assert.equal(await confirmDelete.evaluate(el=>getComputedStyle(el).color),'rgb(255, 255, 255)','destructive hover keeps readable white text');
   assert.equal(await confirmDelete.evaluate(el=>getComputedStyle(el).borderColor),await confirmDelete.evaluate(el=>getComputedStyle(el).backgroundColor),'destructive hover uses a matching border');
   await ui.getByRole('button',{name:'确认删除',exact:true}).click();
   await ui.locator('#qa-manager-search').waitFor();
   assert.equal(await ui.getByRole('combobox',{name:'管理版本'}).locator('option').filter({hasText:'0.1'}).count(),0);
   await page.keyboard.press('Escape');await page.reload();
   assert.equal(await ui.getByRole('combobox',{name:'工作台版本'}).locator('option').filter({hasText:'0.1'}).count(),0);
   console.log('PASS deleting final batch clears embedded and parent URL; reload keeps empty workspace');
  }
  assert.deepEqual(errors,[]);console.log('PASS narrow layout; no live AI or external calls');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
