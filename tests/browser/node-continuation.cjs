// Real local HTTP + SQLite. No model or external writes.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-continuation-'));
 const server=spawn('python3',['-u','-c','import sys;from server.app import create_server;s=create_server("127.0.0.1",0,sys.argv[1],local_development=True);print(s.server_port,flush=True);s.serve_forever()',path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+10000;while(!/^\d+\s*$/m.test(output)){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const base='http://127.0.0.1:'+output.match(/^(\d+)\s*$/m)[1];
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1680,height:1060}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  async function api(url,body){const r=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(r.ok(),await r.text());return r.json()}
  const studio=(await api('/api/studios')).items[0].id,project=await api(`/api/studios/${studio}/projects`,{name:'节点续接验证'}),root=`/api/studios/${studio}/projects/${project.id}`;
  await api(root+'/tasks',{title:'手动审核批次'});await api(root+'/enter',{});await api('/api/me/preferences',{active_studio_id:studio,role:'qa'});await page.goto(base);
  for(const department of ['product','design','development','testing','growth']){
   await page.locator(`[data-action="home:${department}"]`).click();
   console.log('Checking',department);const switches=page.getByRole('switch');await switches.first().waitFor();
   const cfg=await api(root+'/node-continuation?department='+department);assert.equal(await switches.count(),cfg.edges.length);
   assert.equal(await switches.first().getAttribute('aria-checked'),'false');await switches.first().click();
   await page.waitForFunction(()=>document.querySelector('[role=switch]')?.getAttribute('aria-checked')==='true');
   assert.equal(await page.locator('#testing-frame').count(),0,'switch must not enter a node');
   assert.equal((await api(root+'/node-continuation?department='+department)).edges[0].enabled,true);
   assert.equal((await api(root+'/summary')).nodes.length,0,'enabling must not execute or fake evidence');
   await page.locator(`.home-node[data-action="node:${department}:0"]`).click();
   const workspace=department==='testing'?page.frameLocator('#testing-frame'):page;
   await workspace.locator(department==='testing'?'.steps':'.workflow-strip').waitFor();
   await workspace.getByRole('switch').first().waitFor();assert.equal(await workspace.getByRole('switch').first().getAttribute('aria-checked'),'true');
   await workspace.getByRole('switch').first().waitFor({state:'visible'});await workspace.getByRole('switch').first().evaluate(el=>{if(el.disabled)throw Error('switch still busy')});await workspace.getByRole('switch').first().press('Space');
   await workspace.locator('[data-continuation-source="'+department+':0"] [role=switch][aria-checked=false]').waitFor();
   assert.equal((await api(root+'/node-continuation?department='+department)).edges[0].enabled,false);
   // Refresh must not discard unfinished workspace edits.
   if(department!=='testing'){
    await page.locator('#node-inputs').fill('未保存草稿');
    const other=await api(root+'/node-continuation?department='+department);
    await api(root+'/node-continuation?department='+department,{revision:other.revision,source:other.edges[0].source,target:other.edges[0].target,enabled:true});
    await page.waitForFunction(()=>document.querySelector('[role=switch]')?.getAttribute('aria-checked')==='true');assert.equal(await page.locator('#node-inputs').inputValue(),'未保存草稿');
    await page.reload();
   }
  }
  // A worker stop reason must appear without discarding unsaved workspace input.
  await page.locator('[data-action="home:product"]').click();
  await api(root+'/workspace?node=product:1',{revision:0,inputs:'准备资料'});
  await api(root+'/workspace?node=product:0',{revision:0,deliverable:'已核实的交付物'});
  await page.locator('.home-node[data-action="node:product:0"]').click();await page.locator('#node-inputs').waitFor();
  await page.locator('#node-inputs').fill('保留未保存草稿');
  await api(root+'/workspace/decision?node=product:0',{revision:1,action:'approve',reason:'人工核查'});
  await page.locator('.log-body').getByText(/尚未接通执行器/).waitFor({timeout:12000});
  assert.equal(await page.locator('#node-inputs').inputValue(),'保留未保存草稿');
  await page.reload();
  await page.locator('[data-action="home:testing"]').click();await page.getByRole('switch').first().click();
  await page.waitForFunction(()=>document.querySelector('[role=switch]')?.getAttribute('aria-checked')==='true');
  await page.locator('.home-node[data-action="node:testing:0"]').click();
  const frame=page.frameLocator('#testing-frame');await frame.getByRole('switch').first().waitFor();
  assert.equal(await frame.getByRole('switch').first().getAttribute('aria-checked'),'true');
  const shots=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(shots,{recursive:true});
  for(const theme of ['paper','forge','arcade']){
   await page.evaluate(t=>{localStorage.setItem('studioflow-theme',t);document.documentElement.dataset.theme=t},theme);
   await frame.locator('html').evaluate((el,t)=>el.dataset.theme=t,theme);
   assert(await frame.locator('.steps').evaluate(el=>el.scrollWidth>=el.clientWidth));
   await page.screenshot({path:path.join(shots,'node-continuation-'+theme+'.png')});
  }
  await page.setViewportSize({width:390,height:844});await page.locator('[data-action="home:testing"]').click();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile document must not overflow');
  await page.screenshot({path:path.join(shots,'node-continuation-mobile.png'),fullPage:true});
  await page.reload();await page.locator('[data-action="home:testing"]').click();await page.getByRole('switch').first().waitFor();assert.equal(await page.getByRole('switch').first().getAttribute('aria-checked'),'true');
  assert.deepEqual(errors,[]);console.log('PASS: five departments, home/workspace shared settings, keyboard, no accidental navigation or execution, refresh, draft preservation, three themes and mobile. Temporary SQLite; no AI or Feishu calls.');
 }catch(error){console.error(output.slice(-2500));throw error}
 finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
