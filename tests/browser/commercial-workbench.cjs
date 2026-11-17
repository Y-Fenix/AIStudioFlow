// Isolated temporary database; execution responses below are explicit UI fixtures.
// This suite does not call a real model, modify live accounts, or prove tool integration.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-commercial-ui-'));
 const server=spawn('python3',['-u','-c','import sys; from server.app import create_server; s=create_server("127.0.0.1",0,sys.argv[1],local_development=True); print(s.server_port,flush=True); s.serve_forever()',path.join(temp,'fixture.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let logs='',browser;server.stdout.on('data',x=>logs+=x);server.stderr.on('data',x=>logs+=x);
 try{
  const deadline=Date.now()+15000;while(!logs.match(/^(\d+)\s*$/m)){if(Date.now()>deadline||server.exitCode!==null)throw Error(logs||'server timeout');await pause(50)}
  const base='http://127.0.0.1:'+logs.match(/^(\d+)\s*$/m)[1];
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1512,height:980}}),errors=[];page.on('pageerror',x=>errors.push(x.message));
  const request=async(url,body)=>{const response=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(response.ok(),url+': '+await response.text());return response.json()};
  const studio=(await request('/api/studios')).items[0].id,project=await request('/api/studios/'+studio+'/projects',{name:'Commercial workbench UI fixture'}),root=`/api/studios/${studio}/projects/${project.id}`;
  await request('/api/me/preferences',{active_studio_id:studio,role:'product'});await request(root+'/enter',{});
  let job=null,failPoll=false,posts=0,releasePost;
  await page.route('**/workspace/job?*',async route=>{const node=new URL(route.request().url()).searchParams.get('node');if(failPoll){failPoll=false;return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'fixture temporary failure'})})}return route.fulfill({json:node==='product:0'?job:null})});
  await page.route('**/workspace/execute?*',async route=>{posts++;await new Promise(resolve=>releasePost=resolve);await route.fulfill({json:job})});
  await page.goto(base);await page.locator('.home-node[data-action="node:product:0"]').click();await page.locator('#wb-preview').waitFor({state:'attached'});
  assert.equal(await page.locator('.skill-actions>button').count(),1,'only choose Skill remains primary');
  await page.locator('.wb-tools summary').click();await page.locator('[data-action="export-skill"]').focus();await page.keyboard.press('Escape');assert.equal(await page.locator('.wb-tools').getAttribute('open'),null);assert(await page.locator('.wb-tools summary').evaluate(el=>el===document.activeElement));
  await page.locator('#node-inputs').fill('fixture source: verified product request');await page.locator('[data-wb-view="edit"]').click();
  const malicious='# Report\n\n**Readable**\n\n<script>globalThis.pwned=1</script>\n![track](https://example.com/tracker.png)\n[bad](javascript:alert(1))\n\n'+Array.from({length:80},(_,i)=>'Paragraph '+i+' — source-backed draft content.').join('\n\n');
  await page.locator('#node-deliverable').fill(malicious);const handle=await page.locator('#node-deliverable').elementHandle();await page.locator('[data-wb-view="preview"]').click();assert(await handle.evaluate(el=>el.isConnected),'textarea remains mounted');assert.equal(await page.locator('#wb-preview img,#wb-preview script').count(),0);assert.equal(await page.evaluate(()=>globalThis.pwned),undefined);
  await page.locator('[data-action="save-node"]').click();await page.waitForFunction(()=>!state.saving&&!state.dirty);
  const saved=await request(root+'/workspace?node=product:0');
  job={id:'fixture-delayed',node:'product:0',revision:saved.revision,status:'queued'};
  await page.locator('[data-action="run-node"]').click();await page.waitForFunction(()=>!!state.runPending);
  await page.evaluate(()=>{const b=document.querySelector('[data-action="run-node"]');b.dispatchEvent(new MouseEvent('click',{bubbles:true}))});
  await page.locator('#node-inputs').fill('draft typed while execute POST is pending');releasePost();await page.waitForFunction(()=>!state.runPending);
  assert.equal(posts,1,'double click submits one execution');assert.equal(await page.inputValue('#node-inputs'),'draft typed while execute POST is pending');
  job={...job,status:'running',progress:{state:'retrying',requested_model:'gpt-6.1-sol',effort:'high',attempt:2,max_attempts:3,assistant_chars:234,seconds_since_response:81,progress_updated_at:Date.now()/1000}};
  await page.waitForFunction(()=>document.querySelector('#wb-progress')?.textContent.includes('2/3'));
  assert.match(await page.locator('#wb-progress').textContent(),/gpt-6.1-sol.*234.*81 秒/);
  assert.equal(await page.inputValue('#node-inputs'),'draft typed while execute POST is pending');
  failPoll=true;
  const result=await request(root+'/workspace?node=product:0',{revision:saved.revision,inputs:saved.inputs,deliverable:'# Generated fixture\n\nResult with sources.'});
  job={...job,status:'completed',result:{workspace:result,evidence:[{quote:'fixture source'}],gaps:['No external research performed'],quality:{contract:'fixture',sections_checked:3,source_quotes_checked:1,fact_checked:false}}};
  await page.waitForFunction(()=>state.departmentJob?.status==='completed'&&state.workspace?.revision===state.departmentJob.result.workspace.revision,null,{timeout:10000});
  assert.equal(await page.inputValue('#node-inputs'),'draft typed while execute POST is pending');assert.equal(await page.inputValue('#node-deliverable'),result.deliverable);assert(await page.locator('#wb-report').isHidden(),'dirty inputs invalidate report');
  await page.locator('[data-action="save-node"]').click();await page.waitForFunction(()=>!state.saving&&!state.dirty);assert(await page.locator('#wb-report').isHidden(),'manual save invalidates old report');
  // Exact revision result is visible, then immediately disappears on editing.
  const current=await request(root+'/workspace?node=product:0');job={...job,revision:current.revision,result:{...job.result,workspace:current}};await page.evaluate(()=>openDepartment('product',0));await page.locator('#wb-report').waitFor();
  // Status refresh must preserve reading selection and expanded evidence.
  await page.locator('#wb-report details>summary').click();
  const reading=await page.locator('#wb-preview h1').elementHandle();
  await reading.evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);const selection=getSelection();selection.removeAllRanges();selection.addRange(range)});
  const selected=await page.evaluate(()=>getSelection().toString());assert(selected.length>0);
  await page.evaluate(()=>{for(let i=0;i<3;i++)refreshDepartmentChrome()});
  assert(await reading.evaluate(el=>el.isConnected),'progress refresh retains preview content DOM');
  assert.equal(await page.evaluate(()=>getSelection().toString()),selected,'progress refresh preserves reading selection');
  assert(await page.locator('#wb-report details').evaluate(el=>el.open),'progress refresh retains expanded evidence');
  const visualDir=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(visualDir,{recursive:true});
  await page.evaluate(()=>{getSelection().removeAllRanges();scrollTo(0,0)});await page.screenshot({path:path.join(visualDir,'commercial-workbench-desktop.png')});
  await page.locator('#node-inputs').fill('new unsaved input');assert(await page.locator('#wb-report').isHidden());
  // A theme redraw must preserve the draft too.
  await page.evaluate(()=>StudioThemes.select('forge'));assert.equal(await page.inputValue('#node-inputs'),'new unsaved input');
  // Upstream copies require preview, append to existing draft, and remain unsaved.
  let source=await request(root+'/workspace?node=product:1');source=await request(root+'/workspace?node=product:1',{revision:source.revision,inputs:'source fixture',deliverable:'# Confirmed upstream\n\nApproved source content'});source=await request(root+'/workspace/decision?node=product:1',{revision:source.revision,action:'approve',reason:'fixture approval'});await page.evaluate(()=>reloadSummary());
  if(await page.locator('[data-action="upstream"]').isHidden())await page.locator('.wb-document-tools>summary').click();await page.locator('[data-action="upstream"]').click();await page.locator('[data-action="take-upstream:product:1"]').click();await page.locator('[data-action="append-upstream"]').waitFor();await page.keyboard.press('Escape');assert.equal(await page.inputValue('#node-inputs'),'new unsaved input');
  if(await page.locator('[data-action="upstream"]').isHidden())await page.locator('.wb-document-tools>summary').click();await page.locator('[data-action="upstream"]').click();await page.locator('[data-action="take-upstream:product:1"]').click();await page.locator('[data-action="append-upstream"]').click();await page.waitForFunction(()=>!state.modal);assert.match(await page.inputValue('#node-inputs'),/^new unsaved input\n\n## 上游：/);assert.equal((await request(root+'/workspace?node=product:0')).inputs,current.inputs,'append does not save');
  if(await page.locator('[data-action="upstream"]').isHidden())await page.locator('.wb-document-tools>summary').click();await page.locator('[data-action="upstream"]').click();await page.locator('[data-action="take-upstream:product:1"]').click();await page.locator('[data-action="append-upstream"]').waitFor();const before=await page.inputValue('#node-inputs');await request(root+'/workspace?node=product:1',{revision:source.revision,deliverable:'changed upstream'});await page.locator('[data-action="append-upstream"]').click();await page.locator('.toast').filter({hasText:'上游版本已变化'}).waitFor();assert.equal(await page.inputValue('#node-inputs'),before);await page.keyboard.press('Escape');
  // Save failures restore permission-disabled controls; active execution stays disabled.
  await page.evaluate(()=>{state.capabilities.nodes[nodeKey()].execute=false;state.capabilities.nodes[nodeKey()].approve=false;refreshDepartmentChrome()});
  await page.route('**/workspace?node=product%3A0',route=>route.request().method()==='POST'?route.fulfill({status:409,json:{error:'fixture save conflict'}}):route.continue());
  await page.locator('[data-action="save-node"]').click();await page.waitForFunction(()=>!state.saving);assert(await page.locator('[data-action="run-node"]').isDisabled());assert(await page.locator('[data-action="review-node"]').isDisabled());assert.equal(await page.inputValue('#node-inputs'),before);
  await page.unroute('**/workspace?node=product%3A0');
  // A late job response after navigation must not populate another node.
  let releaseJob;await page.route('**/workspace/job?node=product%3A2',async route=>{await new Promise(resolve=>releaseJob=resolve);await route.fulfill({json:{...job,node:'product:2'}})});
  const late=page.evaluate(()=>openDepartment('product',2));while(!releaseJob)await pause(20);await page.evaluate(()=>openDepartment('product',3));releaseJob();await late;assert.equal(await page.evaluate(()=>nodeKey()),'product:3');assert.equal(await page.evaluate(()=>state.departmentJob),null);
  // Long documents, all three existing themes, and phone/tablet/desktop widths.
  await page.evaluate(()=>{state.dirty=false;return openDepartment('product',0)});
  await page.locator('[data-wb-view="edit"]').click();await page.locator('#node-deliverable').fill(malicious);await page.locator('[data-wb-view="preview"]').click();
  for(const theme of ['paper','forge','arcade'])for(const width of [375,768,1512]){
   await page.setViewportSize({width,height:900});await page.evaluate(t=>StudioThemes.select(t),theme);await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));await pause(40);
   const bounds=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.right>innerWidth+1&&r.width>0}).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width})).slice(0,20),footer:(()=>{const r=document.querySelector('.node-bottom').getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom}})()}));
   assert(bounds.scroll<=bounds.width+1,theme+' '+width+' no horizontal overflow '+JSON.stringify(bounds));assert(bounds.footer.y>=0&&bounds.footer.bottom<=901&&bounds.footer.right<=width+1,'visible persistent actions');
   if(theme==='paper'&&width===375)await page.screenshot({path:path.join(visualDir,'commercial-workbench-mobile.png')});
  }
  // Homepage uses saved project records and current per-node permissions.
  await page.setViewportSize({width:1512,height:980});await page.evaluate(()=>{state.dirty=false;return openHome('product')});
  await page.locator('.wb-home-signals').waitFor();const home=await page.locator('.wb-home-signals').textContent();assert.match(home,/已保存交付/);assert.match(home,/输入、Skill 与版本须进入节点核对/);assert.match(home,/实际运行结果为准/);
  await page.evaluate(()=>{for(const c of Object.values(state.capabilities.nodes))c.execute=false;render()});assert.match(await page.locator('.wb-home-signals').textContent(),/0 个节点具备执行器及编辑\/执行权限/);
  await page.setViewportSize({width:375,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'home signals fit phone');
  // Failed and interrupted executions retain an actionable manual recovery instruction.
  await page.evaluate(()=>{state.dirty=false;return openDepartment('product',0)});
  for(const status of ['failed','interrupted']){
   await page.evaluate(status=>{state.departmentJob={node:'product:0',status,error:'fixture provider failure'};refreshDepartmentChrome()},status);
   assert.match(await page.locator('#wb-recovery').textContent(),status==='failed'?/核对错误、输入、Skill 与模型连接/:/中断.*手动重新运行/);
  }
  // Ordinary node builder refresh preserves the textarea itself, focus and selection.
  await request(root+'/node-blueprint?node=product:0',{revision:0,blocks:[{id:'fixture-input',type:'input',config:{label:'资料',required:true}},{id:'fixture-review',type:'review',config:{label:'人工审核'}}],sources:[]});
  await page.evaluate(async()=>{await reloadSummary();return openDepartment('product',0)});await page.locator('.builder-workspace-title').waitFor();await page.locator('[data-builder="start"]').click();await page.locator('#builder-step-value').waitFor();
  await page.locator('#builder-step-value').fill('Builder draft retained through refresh');const builderHandle=await page.locator('#builder-step-value').elementHandle();await page.locator('#builder-step-value').evaluate(el=>{el.focus();el.setSelectionRange(3,9)});
  await page.evaluate(async()=>{const b=NodeBuilder;b.currentRun=await api(b.path+'/block-runs/'+b.currentRun.id);b.updateRun()});
  assert(await builderHandle.evaluate(el=>el.isConnected&&el===document.activeElement),'same ordinary builder textarea remains focused');assert.equal(await page.inputValue('#builder-step-value'),'Builder draft retained through refresh');assert.deepEqual(await builderHandle.evaluate(el=>[el.selectionStart,el.selectionEnd]),[3,9]);
  // A referenced node exposes only checks actually returned by its executor.
  await page.evaluate(()=>{NodeBuilder.currentRun.steps[0].quality={contract:'fixture-product',sections_checked:6,source_quotes_checked:2,fact_checked:false};NodeBuilder.currentRun.status='completed';NodeBuilder.updateRun()});
  await page.locator('.builder-quality>summary').click();assert.match(await page.locator('.builder-quality').textContent(),/fixture-product.*结构检查项6.*来源引用检查项2.*未进行事实核验/);
  await page.evaluate(()=>{delete NodeBuilder.currentRun.steps[0].quality;NodeBuilder.updateRun()});assert.equal(await page.locator('.builder-quality').count(),0);
  await page.evaluate(()=>{NodeBuilder.currentRun.status='running';NodeBuilder.currentRun.progress={state:'running',assistant_chars:100,seconds_since_response:8,progress_updated_at:Date.now()/1000};NodeBuilder.updateRun()});
  assert.match(await page.locator('[data-builder-progress]').textContent(),/100.*8 秒/);
  await page.evaluate(()=>{NodeBuilder.currentRun.progress.assistant_chars=200;NodeBuilder.updateRun()});
  assert.match(await page.locator('[data-builder-progress]').textContent(),/200/);
  assert.deepEqual(errors,[]);console.log('PASS commercial workbench: draft/race/retry/permissions/Markdown/upstream/report/home signals/builder DOM; 3 themes × 3 widths. Execution is a UI fixture.');
 }finally{await browser?.close();server.kill('SIGTERM');await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));fs.rmSync(temp,{recursive:true,force:true})}
})().catch(error=>{console.error(error);process.exitCode=1});
