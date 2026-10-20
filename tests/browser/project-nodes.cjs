// Isolated user workflow; real local HTTP/SQLite, no external model or account.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-nodes-'));
 const server=spawn('python3',['-u','-c','import sys;from server.app import create_server;s=create_server("127.0.0.1",0,sys.argv[1],local_development=True);print(s.server_port,flush=True);s.serve_forever()',path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+10000;while(!/^\d+\s*$/m.test(output)){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const base='http://127.0.0.1:'+output.match(/^(\d+)\s*$/m)[1];
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  async function api(url,body){const r=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(r.ok(),await r.text());return r.json()}
  const studio=(await api('/api/studios')).items[0].id,project=await api(`/api/studios/${studio}/projects`,{name:'节点真实界面验证'}),root=`/api/studios/${studio}/projects/${project.id}`;
  await api(root+'/enter',{});await api('/api/me/preferences',{active_studio_id:studio,role:'product'});await page.goto(base);
  for(const department of ['product','design','development','testing','growth']){
   console.log('Checking department:',department);
   await page.locator(`[data-action="home:${department}"]`).click();await page.locator('[data-action="manage-nodes"]').click();
   await page.locator('.node-manager-add summary').click();
   for(const [id,text] of Object.entries({'name':'附加'+department+'<评审>','purpose':'核对证据','input':'真实输入','output':'审查报告','check':'人工确认'}))await page.locator('#new-node-'+id).fill(text);
   await page.locator('[data-action="node-manager:add"]').click();
   const count=await page.locator('.node-manager-row').count();
   await page.locator(`[data-action="node-manager:up:${count-1}"]`).click();
   await page.locator('[data-action="node-manager:save"]').click();await page.waitForSelector('.modal',{state:'detached'});
   const config=await api(root+'/nodes?department='+department),custom=config.nodes.at(-2);
   assert(custom.id.startsWith(department+':custom-'));
   const index=config.nodes.findIndex(n=>n.id===custom.id);
   await page.locator(`.home-node[data-action="node:${department}:${index}"]`).click();
   await page.locator('#node-deliverable').fill('保持稳定节点证据');await page.locator('[data-action="save-node"]').click();
   await page.waitForFunction(()=>document.querySelector('#save-status')?.textContent.includes('版本 1'));
   assert.equal((await api(root+'/workspace?node='+custom.id)).deliverable,'保持稳定节点证据');
   assert.equal(await page.locator('#testing-frame').count(),0,'custom testing nodes use manual workspace');
   await page.locator(`[data-action="home:${department}"]`).click();await page.locator('[data-action="manage-nodes"]').click();
   await page.locator(`[data-action="node-manager:remove:${index}"]`).click();await page.locator('[data-action="node-manager:save"]').click();await page.waitForSelector('.modal',{state:'detached'});
   assert.equal((await api(root+'/nodes?department='+department)).archived[0].id,custom.id);
   await page.locator('[data-action="manage-nodes"]').click();await page.locator('details').last().locator('summary').click();
   await page.locator(`[data-action="node-manager:restore:${custom.id}"]`).click();await page.locator('[data-action="node-manager:save"]').click();await page.waitForSelector('.modal',{state:'detached'});
   assert.equal((await api(root+'/nodes?department='+department)).nodes.at(-1).id,custom.id);
   assert.equal((await api(root+'/workspace?node='+custom.id)).deliverable,'保持稳定节点证据');
  }
  await page.reload();await page.locator('[data-action="manage-nodes"]').click();await page.keyboard.press('Escape');assert.equal(await page.locator('.modal').count(),0);
  await page.setViewportSize({width:390,height:844});await page.locator('[data-action="manage-nodes"]').click();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile does not overflow');
  assert.deepEqual(errors,[]);
  console.log('PASS: five departments add/reorder/save/manual-workspace/archive/restore, stable evidence, refresh, ESC, mobile and escaped custom labels. Temporary database; no AI or Feishu calls.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
