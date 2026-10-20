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
  await page.locator('[data-action="view:skills"]').first().click();
  await page.locator('[data-action="library:detail:product:0"]').first().click();
  await page.waitForSelector('#skill-update-note');
  assert.match(await page.locator('.skill-detail-meta').innerText(),/系统默认|未记录/);
  await page.locator('#skill-update-note').fill('浏览器真实上传版本');
  const chooser=page.waitForEvent('filechooser');await page.locator('[data-action="library:import"]').click();
  await (await chooser).setFiles({name:'验证规则.md',mimeType:'text/markdown',buffer:Buffer.from('---\nname: browser-rule\ndescription: 浏览器规则说明\n---\n# 检查\n核对真实来源。')});
  await page.waitForFunction(()=>document.querySelector('.skill-current-text')?.textContent.includes('核对真实来源。'));
  assert.match(await page.locator('.skill-detail-meta').innerText(),/本机负责人/);
  assert.match(await page.locator('.skill-history').innerText(),/浏览器真实上传版本/);
  const handoff=page.locator('[data-action="library:handoff"]');
  assert(await handoff.isVisible(),'Skill details expose Codex handoff before import/export');
  const labels=await page.locator('.modal-foot .row').last().locator('button').allTextContents();assert.deepEqual(labels,['在 Codex 使用','导入 Skill','导出 Skill']);
  await page.evaluate(()=>{window.libraryHandoff=null;StudioFlowCodexHandoff.beginCodexHandoff=options=>{window.libraryHandoff=options;options.onWaiting();return ()=>{}}});
  await handoff.click();await page.waitForFunction(()=>window.libraryHandoff?.uri);
  const uri=await page.evaluate(()=>window.libraryHandoff.uri),ticket=new URL(uri).searchParams.get('ticket');
  const received=await api('/api/codex-handoff/redeem',{ticket,origin:base});
  assert(received.prompt.includes('核对真实来源。'));assert.equal(received.node,'product:0');
  await page.evaluate(()=>window.libraryHandoff.onUnconfirmed());await page.waitForSelector('#library-codex-recovery');
  assert((await page.locator('#library-codex-recovery').inputValue()).includes('核对真实来源。'));
  await page.locator('.modal [data-action="library:detail:product:0"]').click();await page.waitForSelector('#skill-update-note');
  await page.evaluate(()=>window.libraryHandoff.onUnconfirmed());assert.equal(await page.locator('#library-codex-recovery').count(),0,'old handoff cannot replace a new detail dialog');
  const downloadEvent=page.waitForEvent('download');await page.locator('[data-action="library:export"]').click();
  const download=await downloadEvent;const exported=fs.readFileSync(await download.path(),'utf8');assert(exported.includes('核对真实来源。'));
  await page.locator('[data-action="library:trash"]').click();await page.waitForSelector('.modal',{state:'detached'});
  assert.equal((await api(root+'/skills?node=product:0')).skill.content,'');
  await page.locator('[data-action="library:bin"]').click();await page.waitForSelector('[data-action^="library:restore:"]');
  await page.locator('[data-action^="library:restore:"]').click();await page.waitForFunction(()=>document.querySelector('.modal-body')?.textContent.includes('回收站为空')||document.querySelector('.modal')?.textContent.includes('回收站为空'));
  assert((await api(root+'/skills?node=product:0')).skill.content.includes('核对真实来源。'));
  await page.keyboard.press('Escape');
  await page.locator('[data-action="library:detail:product:0"]').first().click();await page.waitForSelector('[data-action="library:trash"]');await page.locator('[data-action="library:trash"]').click();await page.waitForSelector('.modal',{state:'detached'});
  await page.locator('[data-action="library:bin"]').click();await page.waitForSelector('[data-action^="library:purge:"]');
  await page.locator('[data-action^="library:purge:"]').click();await page.waitForFunction(()=>document.querySelector('.modal')?.textContent.includes('回收站为空'));await page.keyboard.press('Escape');
  await page.locator('[data-action="view:content"]').click();await page.waitForSelector('[data-action="content:add:product"]');
  await page.locator('[data-action="content:add:product"]').click();await page.locator('#content-title').fill('来源<归档>');await page.locator('#content-kind').selectOption('source');await page.locator('#content-body').fill('来源版本 V1');
  await page.locator('[data-action="content:create"]').click();await page.waitForSelector('.modal',{state:'detached'});await page.waitForFunction(()=>document.querySelector('.content-items')?.textContent.includes('来源<归档>'));
  let config=await api(root+'/content'),item=config.items.find(n=>n.title==='来源<归档>');
  await page.locator(`[data-action="content:delete:${item.id}"]`).click();await page.waitForFunction(()=>Array.from(document.querySelectorAll('.content-department details')).some(n=>n.textContent.includes('来源<归档>')));
  const productPanel=page.locator('.content-department').first();await productPanel.locator('details summary').click();await page.locator(`[data-action="content:restore:${item.id}"]`).click();await page.waitForFunction(()=>document.querySelector('.content-items')?.textContent.includes('来源<归档>'));
  await page.locator('[data-action="content:hide:product:focus:0"]').click();await page.waitForSelector('[data-action="content:hide:product:focus:0"]',{state:'detached'});
  config=await api(root+'/content');const hidden=config.items.find(n=>n.kind==='hidden'&&!n.archived);
  await productPanel.locator('details summary').click();await page.locator(`[data-action="content:unhide:${hidden.id}"]`).click();await page.waitForSelector('[data-action="content:hide:product:focus:0"]');
  await page.locator('[data-action="content:disable:product"]').click();await page.waitForSelector('[data-action="content:enable:product"]');assert.equal(await page.locator('#sidebar [data-action="home:product"]').count(),0);
  await page.locator('[data-action="content:enable:product"]').click();await page.waitForSelector('#sidebar [data-action="home:product"]');
  const batch=await api(root+'/tasks',{title:'来源归档界面'});
  await api(root+'/tasks/'+batch.id+'/requirements',{source:'browser-source.md',content:'来源版本与测试点'});
  const legacy=await browser.newPage();legacy.on('pageerror',e=>errors.push(e.message));legacy.on('dialog',d=>d.accept());
  await legacy.goto(base+'/testing.html?'+new URLSearchParams({studio,project:project.id,task:batch.id,embed:'1'}));
  await legacy.getByRole('button',{name:'归档来源'}).click();
  await legacy.waitForFunction(()=>document.querySelector('.panelbody')?.textContent.includes('已归档来源 · 1'));
  await legacy.locator('details').filter({hasText:'已归档来源 · 1'}).locator('summary').click();
  await legacy.getByRole('button',{name:'恢复',exact:true}).click();await legacy.waitForSelector('.import-success');
  assert.equal((await api(root+'/tasks/'+batch.id)).requirements.length,1);await legacy.close();
  const shots=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(shots,{recursive:true});
  for(const theme of ['forge','paper','arcade']){
   await page.locator('[data-action="view:themes"]').first().click();await page.locator('[data-action="theme:'+theme+'"]').click();
   await page.locator('[data-action="home:product"]').click();await page.waitForSelector('.department-hero .department-mark svg');
   assert.equal(await page.locator('.department-hero-grid>section').first().evaluate(e=>Math.round(e.getBoundingClientRect().height)),270);
   await page.locator('.toast').waitFor({state:'detached'});
   assert(await page.locator('.department-hero').evaluate(e=>e.querySelector('.hero-bottom').getBoundingClientRect().bottom<=e.getBoundingClientRect().bottom),'hero footer must fit fixed height');
   await page.screenshot({path:path.join(shots,theme+'-product-desktop.png'),fullPage:true});
   for(const department of ['design','development','testing','growth']){
    await page.locator(`[data-action="home:${department}"]`).click();await page.waitForSelector('.department-hero .department-mark svg');
    assert.equal(await page.locator('.department-hero .department-mark svg').count(),1);
   }
   await page.locator('[data-action="home:product"]').click();
   for(const width of [980,390]){await page.setViewportSize({width,height:900});await page.screenshot({path:path.join(shots,theme+'-product-'+width+'.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'theme does not overflow at '+width)}
   await page.setViewportSize({width:1440,height:1000});
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: Skill actual file import/export/version/actor/trash/restore/purge; workbench Codex ticket/recovery/stale-dialog guard (protocol opening stubbed); content create/archive/restore/default hide/restore/department disable; three themes and five SVG marks; desktop/tablet/mobile. Temporary database, no AI or Feishu calls.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
