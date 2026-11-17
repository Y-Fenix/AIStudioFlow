// Real HTTP/SQLite/browser, isolated database. Explicitly empty adapter registry
// exercises the manual fallback; registered AI adapters have separate coverage.
// No model or Feishu calls.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-builder-'));
 const server=spawn('python3',['-u','-c','import sys;from server.app import create_server;from server.core.integrations import AdapterRegistry;s=create_server("127.0.0.1",0,sys.argv[1],registry=AdapterRegistry(),local_development=True);print(s.server_port,flush=True);s.serve_forever()',path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+10000;while(!/^\d+\s*$/m.test(output)){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const base='http://127.0.0.1:'+output.match(/^(\d+)\s*$/m)[1];
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1512,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',d=>d.accept(d.type()==='prompt'?'团队常用节点':undefined));
  async function api(url,body){const r=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(r.ok(),await r.text());return r.json()}
  const studio=(await api('/api/studios')).items[0].id,project=await api(`/api/studios/${studio}/projects`,{name:'搭建器验收'}),root=`/api/studios/${studio}/projects/${project.id}`;
  await api(root+'/enter',{});await api('/api/me/preferences',{active_studio_id:studio,role:'product'});await page.goto(base);
  await page.locator('[data-action="node:product:0"]').first().click();await page.locator('[data-action="build-node"]').click();
  await page.locator('[data-builder="add:input"]').click();
  // Browser drag event through real HTML5 dataTransfer, not an API mutation.
  const transfer=await page.evaluateHandle(()=>new DataTransfer());
  await page.locator('[data-block-type="template"]').dispatchEvent('dragstart',{dataTransfer:transfer});
  await page.locator('[data-drop-index="1"]').dispatchEvent('drop',{dataTransfer:transfer});
  await page.locator('[data-builder="add:checklist"]').click();await page.locator('[data-builder="add:review"]').click();
  await page.locator('[data-block-prop="label"]').fill('负责人验收');
  await page.locator('[data-builder="up:3"]').click();await page.locator('[data-builder="down:2"]').click();
  assert.equal(await page.locator('.builder-block h3').last().textContent(),'负责人验收');
  assert.equal(await page.locator('.builder-block').count(),4);
  await page.locator('[data-builder="save"]').click();await page.waitForFunction(()=>document.querySelector('.page-heading p').textContent.includes('配置版本 1'));
  await page.locator('[data-builder="publish"]').click();await page.waitForSelector('.builder-template');
  const downloadEvent=page.waitForEvent('download');await page.locator('[data-builder="export"]').click();const download=await downloadEvent;await download.saveAs(path.join(folder,'template.json'));
  const exported=JSON.parse(fs.readFileSync(path.join(folder,'template.json')));assert.equal(exported.blocks.length,4);assert.equal(exported.schema_version,1);
  await page.locator('#builder-json-file').setInputFiles({name:'hostile.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({schema_version:1,blocks:[{id:'bad',type:'script',config:{}}]}))});
  assert.equal(await page.locator('.builder-block').count(),4);
  await page.locator('[data-builder="preview"]').click();await page.keyboard.press('Escape');assert.equal(await page.locator('.modal').count(),0);
  await page.locator('#builder-run-input').fill('测试输入');await page.locator('[data-builder="start"]').click();
  await page.waitForSelector('#builder-step-value');assert.equal(await page.locator('.builder-run-tabs button').count(),1);await page.locator('#builder-step-value').fill('真实资料 A');await page.locator('[data-builder="submit"]').click();
  await page.waitForSelector('#builder-run-checks');await page.locator('#builder-run-checks input').check();const savedDraft=page.waitForResponse(r=>r.url().includes('/block-runs/')&&r.request().method()==='POST'&&r.request().postDataJSON()?.action==='save-draft');await page.locator('[data-builder="save-draft"]').click();assert((await savedDraft).ok());
  const draftRun=(await api(root+'/block-runs')).items[0];assert.deepEqual(draftRun.draft,[true]);await page.locator('[data-builder="submit"]').click();
  await page.waitForSelector('#builder-step-value');await page.locator('#builder-step-value').fill('已核对证据');await page.locator('[data-builder="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('.builder-run-status b')?.textContent==='已完成');
  assert((await api(root+'/block-runs')).items[0].output.includes('真实资料 A'));
  await page.locator('[data-action="home:product"]').click();await page.locator('[data-action="node:product:0"]').first().click();await page.waitForSelector('.builder-workspace-title');
  assert(await page.locator('.builder-editor').isHidden());
  await page.locator('[data-builder="publish-result"]').click();await page.waitForSelector('.modal');
  const workspace=await api(root+'/workspace?node=product:0');assert.equal(workspace.status,'waiting_user');assert(workspace.deliverable.includes('真实资料 A'));
  await page.keyboard.press('Escape');
  await page.locator('[data-action="view:flows"]').click();
  await page.locator('[data-workflow="create"]').first().click();
  await page.locator('[data-builder="node:product:0"]').click();await page.locator('[data-builder="node:design:0"]').click();
  await page.locator('[data-block-prop="auto_next"]').check();await page.locator('[data-block-index="0"]').click();await page.locator('[data-block-prop="auto_next"]').check();
  await page.locator('[data-builder="save"]').click();await page.waitForSelector('.workflow-node-card');await page.locator('[data-workflow="edit"]').click();
  const flow=(await api(root+'/custom-flows')).items[0];assert.equal(flow.blocks.length,2);
  await page.locator('[data-builder="publish"]').click();await page.getByText('模板已共享给本部门',{exact:true}).waitFor();
  const templates=await api('/api/studios/'+studio+'/block-templates?department=product');assert(templates.items.some(t=>t.kind==='flow'));
  await page.locator('#builder-template-department').selectOption('design');await page.locator('#builder-template-department').selectOption('product');
  await page.locator('[data-builder="start"]').click();await page.waitForSelector('#builder-step-value');
  await page.locator('#builder-step-value').fill('跨部门资料');await page.locator('[data-builder="submit"]').click();
  await page.waitForSelector('#builder-run-checks');await page.locator('#builder-run-checks input').check();await page.locator('[data-builder="submit"]').click();
  await page.waitForSelector('#builder-step-value');await page.locator('#builder-step-value').fill('产品审核通过');await page.locator('[data-builder="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('.builder-step-action label')?.textContent.includes('人工交付内容'));
  await page.locator('#builder-step-value').fill('设计人工交付');await page.locator('[data-builder="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('.builder-run-status b')?.textContent==='已完成');
  const runs=(await api(root+'/block-runs')).items;assert.equal(runs.find(r=>r.flow_id===flow.id).output,'设计人工交付');
  const finishedFlow=runs.find(r=>r.flow_id===flow.id);await page.goto(base+'/?studio='+studio+'&project='+project.id+'&block_run='+finishedFlow.id);await page.waitForSelector('.workflow-node-card');await page.locator('[data-workflow="node:'+flow.blocks[1].id+'"]').click();await page.waitForFunction(()=>document.querySelector('.builder-run-status b')?.textContent==='已完成');assert((await page.locator('#builder-run-detail').textContent()).includes('设计人工交付'));
  assert.equal(await page.locator('#sidebar [data-action="home:growth"]').count(),0);
  await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'/tmp/studioflow-builder-desktop.png'});
  const second=await api(`/api/studios/${studio}/projects`,{name:'共享模板第二项目'}),r2=`/api/studios/${studio}/projects/${second.id}`;
  const template=templates.items.find(t=>t.kind==='node'),full=await api(`/api/studios/${studio}/block-templates?department=product&id=${template.id}`);
  const applied=await api(r2+'/node-blueprint?node=product:0',{revision:0,blocks:full.blocks,sources:[{id:full.id,department:'product',revision:full.revision}]});assert.equal(applied.sources[0].revision,1);assert.equal(applied.blocks.length,4);
  await page.reload();await page.locator('[data-action="view:flows"]').click();await page.locator(`[data-workflow="open:${flow.id}"]`).first().click();await page.waitForFunction(()=>document.querySelectorAll('.workflow-node-card').length===2);
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/studioflow-builder-mobile.png',fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'narrow viewport does not overflow');
  assert.deepEqual(errors,[]);console.log('PASS: drag/reorder/property edits, save/apply, JSON export + invalid import, studio/department templates reused in second project, ESC, durable checklist draft, formal node rendering, publish for review, cross-department flow, flow templates, exact run deep link, reload and mobile. Isolated DB; no AI/Feishu calls.');
 }catch(e){console.error('SERVER:',output);throw e}finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
