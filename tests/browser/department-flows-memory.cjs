// Temporary database and a deterministic model fixture; no external AI or live user data.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-flow-memory-'));
 const code=`import sys,json
from server.codex_model import CodexModel
def fixture(self,prompt):
 data=json.loads(prompt.split('\\n',1)[1]); sources=data['sources']
 return {'answer':'FIXTURE: '+(sources[0]['text'] if sources else 'No sources'), 'citations':[sources[0]['id']] if sources else []}
CodexModel.request_json=fixture
from server.app import create_server
s=create_server('127.0.0.1',0,sys.argv[1],local_development=True)
print(s.server_port,flush=True)
s.serve_forever()`;
 const server=spawn('python3',['-u','-c',code,path.join(temp,'fixture.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let logs='',browser;server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 try{
  const deadline=Date.now()+15000;while(!logs.match(/^(\d+)\s*$/m)){if(Date.now()>deadline||server.exitCode!==null)throw Error(logs||'start timeout');await pause(50)}
  const base='http://127.0.0.1:'+logs.match(/^(\d+)\s*$/m)[1];
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1512,height:980}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const req=async(url,data)=>{const r=await page.request[data===undefined?'get':'post'](base+url,data===undefined?{}:{data});assert(r.ok(),url+': '+await r.text());return r.json()};
  const studio=(await req('/api/studios')).items[0].id,p=await req('/api/studios/'+studio+'/projects',{name:'Flow memory fixture'}),root=`/api/studios/${studio}/projects/${p.id}`;
  await req('/api/me/preferences',{active_studio_id:studio,role:'product'});await req(root+'/enter',{});
  await req(root+'/workspace?node=product:0',{revision:0,inputs:'DEFAULT ONLY',deliverable:'Default saved'});
  await page.goto(base);await page.locator('#department-flow-select').waitFor();
  await page.locator('[data-action="new-department-flow"]').click();await page.locator('#department-flow-name').fill('Parallel A');await page.locator('[data-action="create-department-flow"]').click();
  await page.waitForFunction(()=>state.activeFlow?.name==='Parallel A');const a=await page.evaluate(()=>currentFlow());
  assert.match(await page.locator('.wb-home-signals').textContent(),/0 份已保存交付/,'new flow readiness must not use default results');
  await page.locator('[data-action="node:product:0"]').first().click();await page.locator('#node-inputs').waitFor();
  assert.equal(await page.inputValue('#node-inputs'),'');await page.locator('#node-inputs').fill('A ONLY: coins 12');await page.locator('[data-action="save-node"]').click();await page.waitForFunction(()=>!state.saving&&!state.dirty);
  await page.locator('.node-memory>summary').click();await page.locator('.node-memory textarea').fill('How many coins?');await page.locator('.node-memory button[type="submit"]').click();await page.locator('.memory-answer').filter({hasText:'A ONLY: coins 12'}).waitFor();
  await page.reload();await page.locator('.memory-answer').filter({hasText:'A ONLY: coins 12'}).waitFor({state:'attached'});
  await page.evaluate(()=>{state.dirty=false;return openHome('product')});
  await page.locator('[data-action="new-department-flow"]').click();await page.locator('#department-flow-name').fill('Parallel B');await page.locator('[data-action="create-department-flow"]').click();await page.waitForFunction(()=>state.activeFlow?.name==='Parallel B');const b=await page.evaluate(()=>currentFlow());
  await page.locator('[data-action="node:product:0"]').first().click();await page.locator('#node-inputs').waitFor();assert.equal(await page.inputValue('#node-inputs'),'');assert.equal(await page.locator('.memory-message').count(),0);
  await page.locator('#node-inputs').fill('unsaved B');await page.locator('#department-flow-select').selectOption(a);await page.locator('.modal').waitFor();await page.keyboard.press('Escape');assert.equal(await page.inputValue('#node-inputs'),'unsaved B');assert.equal(await page.locator('#department-flow-select').inputValue(),b);
  await page.locator('#department-flow-select').selectOption(a);await page.locator('[data-action="discard"]').click();await page.waitForFunction(id=>currentFlow()===id&&document.querySelector('#node-inputs')?.value==='A ONLY: coins 12',a);
  assert.equal((await req(root+'/workspace?node=product:0')).inputs,'DEFAULT ONLY');
  // An explicitly linked approved PRD appears in the source picker, and remains removable after editing.
  let source=await req(root+'/workspace?node=design:0',{revision:0,deliverable:'Confirmed design fixture'});source=await req(root+'/workspace/decision?node=design:0',{revision:source.revision,action:'approve',reason:'Fixture'});
  if(!await page.locator('.node-memory').evaluate(e=>e.open))await page.locator('.node-memory>summary').click();
  await page.locator('[data-memory="sources"]').click();const sourceLabel=page.locator('.memory-source-picker label').filter({hasText:'视觉定调'}).first();await sourceLabel.locator('input').check();await page.locator('[data-memory="source-status"]').filter({hasText:'已保存'}).waitFor();
  await req(root+'/workspace?node=design:0',{revision:source.revision,deliverable:'Edited unapproved design'});await page.locator('[data-memory="sources"]').click();await page.locator('[data-memory="sources"]').click();await page.locator('.memory-source-picker label').filter({hasText:'未确认'}).locator('input').uncheck();
  await page.locator('[data-memory="source-status"]').filter({hasText:'已保存'}).waitFor();assert.equal((await req(root+'/node-memory/links?node=product:0&flow='+a)).items.length,0);
  // Theme tokens match the surrounding workbench and fit a narrow viewport.
  for(const theme of ['paper','forge','arcade'])for(const width of [375,1512]){
   await page.setViewportSize({width,height:900});await page.evaluate(t=>StudioThemes.select(t),theme);
   const colors=await page.locator('.node-memory').evaluate(el=>{const c=getComputedStyle(el);return {bg:c.backgroundColor,expected:c.getPropertyValue('--surface').trim(),color:c.color,ink:c.getPropertyValue('--ink').trim()}});
   assert.equal(colors.bg,await page.evaluate(()=>{const el=document.createElement('div');el.style.background='var(--surface)';document.body.append(el);const c=getComputedStyle(el).backgroundColor;el.remove();return c}),'theme '+theme);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),theme+' width '+width);
  }
  // A default-workspace link must override the remembered independent flow.
  await page.goto(base+'/?studio='+studio+'&project='+p.id+'&node=product:0');await page.locator('#node-inputs').waitFor();assert.equal(await page.inputValue('#node-inputs'),'DEFAULT ONLY');
  await page.evaluate(()=>{state.view='overview';render()});assert.equal(new URL(page.url()).searchParams.has('node'),false);await page.reload();await page.locator('.department-cards').waitFor();assert.equal(await page.evaluate(()=>state.view),'overview');
  // QA flows bind distinct real batches. The embedded view cannot switch to another batch.
  await page.evaluate(()=>{state.dirty=false;return openHome('testing')});await page.locator('[data-action="new-department-flow"]').click();await page.locator('#department-flow-name').fill('QA A');await page.locator('[data-action="create-department-flow"]').click();await page.waitForFunction(()=>state.activeFlow?.name==='QA A');
  const qa=await page.evaluate(()=>state.activeFlow);assert(qa.task_id);await page.locator('[data-action="node:testing:0"]').first().click();const frame=page.frameLocator('#testing-frame');await frame.locator('.node-memory').waitFor({state:'attached'});assert.equal(await frame.locator('.node-memory').count(),1);
  assert.equal(await page.locator('#testing-frame').evaluate(el=>new URL(el.src).searchParams.get('task')),qa.task_id);
  assert.equal(await page.locator('#testing-frame').evaluate(el=>new URL(el.src).searchParams.get('flow')),qa.id);
  assert.equal(await frame.locator('.task-selector option').count(),1);assert.equal(await frame.locator('.task-selector select').inputValue(),qa.task_id);
  assert.deepEqual(errors,[]);console.log('PASS flow create/switch/save isolation, unsaved guard, persistent Q&A fixture, explicit source/unlink, 3 themes, QA batch binding. No live AI.');
 }catch(e){console.error(logs.slice(-5000));throw e}finally{await browser?.close();server.kill('SIGTERM');await pause(150);fs.rmSync(temp,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
