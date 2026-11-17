// Real local HTTP/SQLite + Chrome. Fixture text only; no models or Feishu.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-interaction-'));
 const server=spawn('python3',['-u','-c','import sys;from server.app import create_server;s=create_server("127.0.0.1",0,sys.argv[1],local_development=True);print(s.server_port,flush=True);s.serve_forever()',path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+15000;while(!/^\d+\s*$/m.test(output)){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const base='http://127.0.0.1:'+output.match(/^(\d+)\s*$/m)[1];
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1512,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',d=>{throw Error('Unexpected discard dialog: '+d.message())});
  async function api(url,body){const r=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(r.ok(),await r.text());return r.json()}
  const studio=(await api('/api/studios')).items[0].id,project=await api(`/api/studios/${studio}/projects`,{name:'交互验收隔离项目'}),root=`/api/studios/${studio}/projects/${project.id}`;
  const currentSkill=await api(root+'/skills?node=product%3A0');await api(root+'/skills?node=product%3A0',{id:currentSkill.id,revision:currentSkill.revision,name:'验收用规则',note:'隔离验收规则',content:'# 输入\n依据真实资料\n# 输出\n交付正文\n# 证据\n保留引用\n# 边界\n不得虚构'});
  const task=(id,label)=>({id,type:'task',config:{label,auto_next:false,blocks:[{id:'text',type:'template',config:{text:'隔离测试交付'}},{id:'review',type:'review',config:{label:'人工审核'}}]}});
  const flow=await api(root+'/custom-flows',{name:'版本质量验收',description:'需求、代码和交付的完整协作',revision:0,blocks:[task('prepare','资料整理'),task('check','质量核查'),task('deliver','交付确认')]});
  await api(root+'/enter',{});await api('/api/me/preferences',{active_studio_id:studio,role:'studio_owner'});await page.goto(base);
  await page.locator('[data-action="view:flows"]').click();await page.locator('[data-workflow="open:'+flow.id+'"]').first().click();await page.locator('[data-workflow="node:prepare"]').click();
  assert.equal(await page.getByRole('tab',{name:'节点配置'}).getAttribute('aria-selected'),'true');
  await page.locator('[data-workflow-input]').fill('节点一未保存资料');
  await page.locator('[data-workflow="source:links"]').click();await page.locator('[data-workflow="source:file"]').click();assert(await page.locator('#workflow-links-source').isVisible());assert(await page.locator('#workflow-file-source').isVisible());
  await page.locator('[data-workflow-links]').fill('https://example.test/requirements');
  await page.locator('[data-workflow="node:check"]').click();await page.locator('[data-workflow-input]').fill('节点二草稿');await page.locator('[data-workflow="node:prepare"]').click();assert.equal(await page.locator('[data-workflow-input]').inputValue(),'节点一未保存资料');assert(await page.locator('#workflow-links-source').isVisible());assert.equal(await page.locator('[data-workflow-links]').inputValue(),'https://example.test/requirements');
  await page.locator('[data-workflow="start"]').click();await page.getByText('请先保存所有已修改节点的配置，再开始工作流',{exact:true}).waitFor();assert.equal((await api(root+'/block-runs?flow='+flow.id)).items.length,0);
  await page.locator('[data-workflow="append-links"]').click();assert((await page.locator('[data-workflow-input]').inputValue()).includes('未读取正文'));
  await page.locator('[data-workflow-source-file]').setInputFiles({name:'需求.md',mimeType:'text/markdown',buffer:Buffer.from('文件需求正文')});await page.waitForFunction(()=>document.querySelector('[data-workflow-input]').value.includes('文件需求正文'));
  // Failed save retains actual DOM, focus, value and retry capability.
  const configEndpoint='**/custom-flows';
  await page.route(configEndpoint,route=>route.request().method()==='POST'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'验收模拟保存失败'})}):route.continue());
  await page.locator('[data-workflow="save-node"]').click();await page.getByText(/验收模拟保存失败/).waitFor();assert((await page.locator('[data-workflow-input]').inputValue()).includes('文件需求正文'));assert(await page.locator('[data-workflow="save-node"]').isEnabled());await page.unroute(configEndpoint);
  // Delay exactly one real write: pending feedback and duplicate clicks.
  let release,arrived,posts=0;const held=new Promise(r=>release=r),seen=new Promise(r=>arrived=r);
  await page.route(configEndpoint,async route=>{if(route.request().method()!=='POST')return route.continue();posts++;arrived();await held;await route.continue()});
  await page.locator('[data-workflow-input]').evaluate(el=>el.dataset.identity='retained');await page.locator('[data-workflow="save-node"]').click();await seen;assert.equal(await page.locator('[data-workflow="save-node"]').getAttribute('aria-busy'),'true');await page.locator('[data-workflow="save-node"]').evaluate(el=>el.click());release();await page.waitForFunction(()=>!document.querySelector('[data-workflow="save-node"]').hasAttribute('aria-busy'));await page.unroute(configEndpoint);assert.equal(posts,1);assert.equal(await page.locator('[data-workflow-input]').getAttribute('data-identity'),'retained');
  assert((await api(root+'/custom-flows/'+flow.id)).nodes[0].inputs.includes('文件需求正文'));
  // Real shared Skill selection, drawer geometry and modal scroll lock.
  await page.locator('[data-workflow="skill-select"]').click();await page.locator('[data-skill-search]').waitFor();
  const drawer=await page.locator('.modal').boundingBox();assert(Math.abs(drawer.x+drawer.width-1512)<25,'Skill picker should dock to the right');
  await page.locator('[data-skill-search]').fill('product:0');await page.locator('[data-skill-source="product:0"]').click();await page.locator('.skill-picker-preview pre').waitFor();
  await page.getByRole('button',{name:'使用并保存',exact:true}).click();await page.locator('.modal').waitFor({state:'detached'});assert.match((await api(root+'/custom-flows/'+flow.id)).nodes[0].skill.content,/不得虚构/);
  await page.locator('[data-workflow="skill-select"]').click();await page.locator('[data-skill-search]').waitFor();await page.keyboard.press('Escape');await page.locator('.modal').waitFor({state:'detached'});assert.equal(await page.locator('[data-workflow="skill-select"]').evaluate(el=>el===document.activeElement),true);
  await page.locator('[data-workflow="skill-select"]').click();await page.locator('[data-skill-search]').waitFor();await page.locator('.modal-backdrop').click({position:{x:4,y:4}});await page.locator('.modal').waitFor({state:'detached'});
  // Tabs are keyboard operable without rebuilding the input.
  await page.getByRole('tab',{name:'节点配置'}).focus();await page.keyboard.press('ArrowRight');assert(await page.locator('#workflow-result-panel').isVisible());await page.keyboard.press('Home');assert(await page.locator('#workflow-config-panel').isVisible());
  for(const theme of ['paper','forge','arcade']){
   await page.locator('html').evaluate((el,t)=>el.dataset.theme=t,theme);await page.locator('[data-workflow-input]').evaluate(el=>el.style.height='1000px');await page.evaluate(()=>scrollTo(0,380));
   const bar=await page.locator('.workflow-sticky-strip').evaluate(el=>({top:el.getBoundingClientRect().top,bg:getComputedStyle(el).backgroundColor,page:getComputedStyle(document.body).backgroundColor}));assert(Math.abs(bar.top)<2);assert.equal(bar.bg,bar.page);
  }
  await page.locator('html').evaluate(el=>el.dataset.theme='paper');await page.locator('[data-workflow-input]').evaluate(el=>el.style.height='');await page.evaluate(()=>scrollTo(0,0));
  await page.screenshot({path:'/tmp/studioflow-interaction-production-desktop.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});for(const width of [375,768,1024,1512]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow at '+width+' '+JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().right>innerWidth+2).map(el=>[el.tagName,el.className,Math.round(el.getBoundingClientRect().right)]).slice(0,15))))}
  await page.setViewportSize({width:375,height:900});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'/tmp/studioflow-interaction-production-mobile.png',fullPage:true});await page.setViewportSize({width:1512,height:1100});
  await page.locator('[data-workflow="node:check"]').click();assert.equal(await page.locator('[data-workflow-input]').inputValue(),'节点二草稿');await page.locator('[data-workflow="save-node"]').click();await page.waitForFunction(()=>document.querySelector('[data-workflow="save-node"]').disabled&&!document.querySelector('[data-workflow="save-node"]').hasAttribute('aria-busy'));
  await page.locator('[data-workflow="start"]').click();await page.waitForFunction(()=>document.querySelector('.builder-run-status b')?.textContent==='待你操作');assert(await page.locator('#workflow-result-panel').isVisible());assert.match(await page.locator('[data-workflow-state-banner]').innerText(),/等待人工审核/);
  await page.locator('#builder-step-value').fill('验收依据：已核对隔离交付');
  const runEndpoint='**/block-runs/*';
  await page.route(runEndpoint,route=>route.request().method()==='POST'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'验收模拟审核保存失败'})}):route.continue());
  await page.locator('[data-builder="submit"]').click();await page.getByText('验收模拟审核保存失败',{exact:true}).waitFor();assert.equal(await page.locator('#builder-step-value').inputValue(),'验收依据：已核对隔离交付');assert(await page.locator('[data-builder="submit"]').isEnabled());await page.unroute(runEndpoint);
  let releaseReview,reviewArrived,reviewPosts=0;const reviewHeld=new Promise(r=>releaseReview=r),reviewSeen=new Promise(r=>reviewArrived=r);
  await page.route(runEndpoint,async route=>{if(route.request().method()!=='POST')return route.continue();reviewPosts++;reviewArrived();await reviewHeld;await route.continue()});
  await page.locator('[data-builder="submit"]').click();await reviewSeen;assert.equal(await page.locator('[data-builder="submit"]').getAttribute('aria-busy'),'true');assert.match(await page.locator('[data-builder="submit"]').innerText(),/处理中/);assert(await page.locator('[data-builder="save-draft"]').isDisabled());await page.locator('[data-builder="submit"]').evaluate(el=>el.click());releaseReview();
  await page.waitForFunction(()=>document.querySelector('.builder-run-status b')?.textContent==='待你操作'&&document.querySelector('[data-workflow-primary]')?.textContent.includes('步骤已完成'));await page.unroute(runEndpoint);assert.equal(reviewPosts,1);
  await page.locator('[data-workflow="current"]').click();await page.waitForSelector('[data-builder="continue"]');await page.locator('[data-builder="continue"]').click();await page.waitForFunction(()=>document.querySelector('[data-workflow-state-banner]')?.textContent.includes('等待人工审核'));
  await page.getByRole('tab',{name:'节点配置'}).click();assert(await page.locator('[data-workflow-input]').getAttribute('readonly')!==null);assert(await page.locator('[data-workflow="skill-select"]').isDisabled());
  await page.screenshot({path:'/tmp/studioflow-interaction-production-review.png',fullPage:true});assert.deepEqual(errors,[]);
  console.log('PASS: real persistence, independent drafts/sources, file input, failed/pending configuration and review saves, duplicate prevention, Skill drawer/save/ESC/backdrop/focus, keyboard tabs, frozen snapshot, real review/manual gates, three-theme sticky, four widths. No AI/Feishu.');
 }catch(e){console.error(output.slice(-1800));throw e}finally{await browser?.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
