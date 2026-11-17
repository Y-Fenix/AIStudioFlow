// Real HTTP/SQLite/Chrome navigation and sequential gates. No AI or external sends.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require('/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-flows-'));
 const server=spawn('python3',['-u','-c','import sys;from server.app import create_server;s=create_server("127.0.0.1",0,sys.argv[1],local_development=True);print(s.server_port,flush=True);s.serve_forever()',path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+10000;while(!/^\d+\s*$/m.test(output)){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const base='http://127.0.0.1:'+output.match(/^(\d+)\s*$/m)[1];
  browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1512,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept(d.type()==='prompt'?'重命名验收':undefined));
  async function api(url,body){const r=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(r.ok(),await r.text());return r.json()}
  const studio=(await api('/api/studios')).items[0].id,project=await api(`/api/studios/${studio}/projects`,{name:'工作流导航验收'}),root=`/api/studios/${studio}/projects/${project.id}`;
  const task=(id,text,extra={})=>({id,type:'task',config:{label:id,auto_next:false,blocks:[{id:'report',type:'template',config:{text}}],...extra}});
  for(let i=0;i<100;i++)await api(root+'/custom-flows',{name:'工作流 '+String(i).padStart(3,'0'),revision:0,description:'分页数据',blocks:[task('prepare','资料') ]});
  const flow=await api(root+'/custom-flows',{name:'版本质量验收',revision:0,description:'两个业务节点',blocks:[task('analysis','第一份交付',{label:'分析'}),task('accept','最终 {{previous}}',{label:'验收'})]});
  await api(root+'/enter',{});await api('/api/me/preferences',{active_studio_id:studio,role:'studio_owner'});await page.goto(base);
  await page.locator('[data-action="view:overview"]').click();await page.waitForSelector('.department-cards');assert.equal(await page.locator('.department-card').count(),4);assert.equal(await page.locator('#content [data-action="view:flows"]').count(),0);
  await page.locator('[data-action="view:flows"]').click();await page.waitForSelector('.workflow-list-row');assert.equal(await page.locator('.workflow-list-row').count(),10);assert.equal(await page.locator('.builder-editor').count(),0);
  await page.locator('[data-workflow="page:1"]').click();assert((await page.locator('[data-workflow-pagination]').innerText()).includes('2 / 11'));
  await page.locator('[data-workflow-size]').selectOption('20');assert.equal(await page.locator('.workflow-list-row').count(),20);
  await page.locator('[data-workflow-search]').fill('版本质量验收');assert.equal(await page.locator('.workflow-list-row').count(),1);await page.locator(`[data-workflow="open:${flow.id}"]`).first().click();
  await page.waitForSelector('.workflow-node-card');assert.equal(await page.locator('.workflow-node-card').count(),2);assert.equal(await page.locator('.builder-editor').count(),0);
  await page.locator('[data-workflow="node:analysis"]').click();await page.waitForSelector('[data-workflow-input]');await page.locator('[data-workflow-input]').fill('本节点资料');await page.locator('[data-workflow="save-node"]').click();await page.waitForFunction(()=>!document.querySelector('[data-workflow-input]')?.readOnly);
  // The shell topbar scrolls away: the workflow strip must meet the viewport,
  // with an opaque theme background and the approved caption + compact cards.
  for(const theme of ['paper','forge','arcade']){
   await page.locator('html').evaluate((el,t)=>el.dataset.theme=t,theme);
   await page.waitForTimeout(250); // Let the existing shell theme transitions settle.
   await page.evaluate(()=>{document.querySelector('[data-workflow-input]').style.height='900px';scrollTo(0,350)});
   const sticky=await page.locator('.workflow-sticky-strip').evaluate(el=>({top:el.getBoundingClientRect().top,height:el.getBoundingClientRect().height,bg:getComputedStyle(el).backgroundColor,page:getComputedStyle(document.body).backgroundColor}));
   assert(Math.abs(sticky.top)<2,'workflow sticky strip must meet viewport top, not leave a topbar-sized gap');
   assert(sticky.height<=140,'workspace caption and navigation must remain compact: '+sticky.height);assert.equal(sticky.bg,sticky.page,'sticky backdrop follows the page theme');
   assert.equal(await page.locator('.workflow-node-config .workflow-skill-bar .skill-actions').count(),1,'Skill actions share the approved compact toolbar');
   assert.equal(await page.locator('.workflow-node-config .node-bottom [data-workflow="save-node"]').count(),1,'save belongs in the shared panel footer');
   const selected=await page.locator('.workflow-node-card.selected .workflow-node-enter').evaluate(el=>({bg:getComputedStyle(el).backgroundColor,ink:getComputedStyle(el).color}));
   if(theme==='forge'){assert.equal(selected.bg,'rgb(17, 42, 69)');assert.equal(selected.ink,'rgb(145, 202, 255)')}
   else {assert.equal(selected.bg,'rgb(230, 244, 255)');assert.equal(selected.ink,'rgb(9, 88, 217)')}
   await page.screenshot({path:'/tmp/studioflow-workflow-sticky-'+theme+'.png'});
  }
  await page.locator('html').evaluate(el=>el.dataset.theme='paper');await page.evaluate(()=>{document.querySelector('[data-workflow-input]').style.height='';scrollTo(0,0)});
  await page.locator('[data-workflow="skill-toggle"]').click();assert(await page.locator('[data-workflow-skill]').isVisible());await page.locator('[data-workflow="skill-toggle"]').click();assert(await page.locator('[data-workflow-skill]').isHidden());
  await page.locator('[data-workflow="skill-import"]').click();await page.locator('[data-workflow-skill-file]').setInputFiles({name:'analysis.md',mimeType:'text/plain',buffer:Buffer.from('# 专用 Skill\n输入依据、输出证据与边界')});
  await page.waitForFunction(()=>document.querySelector('.workflow-skill summary')?.textContent.includes('analysis.md'));
  const updated=await api(root+'/custom-flows/'+flow.id);assert(updated.nodes[0].skill.content.includes('专用 Skill'));assert.equal(updated.nodes[1].skill.source,'default');
  await page.locator('[data-workflow="home"]').first().click();await page.locator('[data-workflow="start"]').click();await page.waitForFunction(()=>document.querySelector('.builder-run-status b')?.textContent==='待你操作');assert.equal(await page.locator('[data-builder="continue"]').count(),0,'first node workspace does not expose next boundary action');
  await page.locator('[data-workflow="home"]').first().click();await page.locator('[data-workflow="continue"]').click();await page.waitForSelector('[data-builder="continue"]');await page.locator('[data-builder="continue"]').click();await page.waitForFunction(()=>document.querySelector('.builder-run-status b')?.textContent==='已完成');
  const runs=(await api(root+'/block-runs?flow='+flow.id)).items;assert.equal(runs[0].output,'最终 第一份交付');assert((await page.locator('#builder-run-detail').textContent()).includes('最终 第一份交付'));
  await page.locator('[data-workflow="home"]').first().click();await page.locator('[data-workflow="edit"]').click();await page.waitForSelector('.builder-editor');await page.locator('[data-builder="add:task"]').click();assert.equal(await page.locator('.builder-block').count(),3);await page.locator('[data-builder="edit-task:2"]').click();await page.waitForSelector('[data-builder="add:template"]');await page.locator('[data-builder="add:template"]').click();await page.locator('[data-builder="save"]').click();await page.waitForSelector('[data-builder="edit-task:2"]');await page.locator('[data-builder="save"]').click();await page.waitForSelector('.workflow-node-card');assert.equal(await page.locator('.workflow-node-card').count(),2,'current historical run remains two nodes');
  await page.locator('[data-workflow-run]').selectOption('');assert.equal(await page.locator('.workflow-node-card').count(),3);
  await page.locator('[data-workflow="list"]').click();await page.waitForSelector('[data-workflow-search]');assert.equal(await page.locator('[data-workflow-search]').inputValue(),'版本质量验收');
  await page.locator('[data-workflow-search]').fill('');await page.locator('[data-workflow-size]').selectOption('10');await page.locator('[data-workflow="page:1"]').click();const entered=await page.locator('.workflow-title-button').first().getAttribute('data-workflow');await page.locator('.workflow-title-button').first().click();await page.locator('[data-workflow="list"]').click();assert((await page.locator('[data-workflow-pagination]').innerText()).includes('2 / 11'));
  await page.goto(base+'/?studio='+studio+'&project='+project.id+'&block_run='+runs[0].id);await page.waitForSelector('.workflow-node-card');assert.equal(await page.locator('.workflow-node-card').count(),2);
  const polished=await api(root+'/custom-flows',{name:'游戏版本交付',revision:0,description:'跨部门协作流程',blocks:[{id:'research',type:'node',config:{node:'product:0',label:'市场调研'}},task('plan','方案',{label:'需求评审'}),{id:'design',type:'node',config:{node:'design:0',label:'视觉定调'}},{id:'dev',type:'node',config:{node:'development:0',label:'技术方案'}},task('qa','验收',{label:'质量验收'})]});
  await page.locator('[data-workflow="list"]').click();await page.locator('[data-workflow-search]').fill('游戏版本交付');await page.locator('[data-workflow="open:'+polished.id+'"]').first().click();await page.locator('[data-workflow="node:research"]').click();
  await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no mobile overflow');await page.screenshot({path:'/tmp/studioflow-workflow-mobile.png',fullPage:true});await page.setViewportSize({width:1512,height:1000});await page.evaluate(()=>scrollTo(0,0));await page.waitForTimeout(250);await page.screenshot({path:'/tmp/studioflow-workflow-desktop.png'});assert.deepEqual(errors,[]);
  console.log('PASS: 101 flows, overview exclusion, search/pagination/return, business node homepage, local input/Skill, real manual gate, nested editor, historical snapshot/deep link, compact workspace, Skill toolbar, three-theme sticky/selection colors and mobile. No AI/Feishu.');
 }catch(e){console.error(output.slice(-5000));throw e}finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
