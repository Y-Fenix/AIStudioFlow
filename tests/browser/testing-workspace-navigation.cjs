// Real HTTP/SQLite regression for the embedded legacy testing workspace.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-testing-navigation-'));
 const server=spawn('python3',['-u','-c','import sys;from server.app import create_server;s=create_server("127.0.0.1",0,sys.argv[1],local_development=True);print(s.server_port,flush=True);s.serve_forever()',path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+10000;while(!/^\d+\s*$/m.test(output)){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const base='http://127.0.0.1:'+output.match(/^(\d+)\s*$/m)[1];
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],failures=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  async function api(url,body){const r=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(r.ok(),await r.text());return r.json()}
  async function check(label,run){try{await run();console.log('PASS:',label)}catch(e){failures.push(label+': '+e.message);console.error('FAIL:',label,e.message)}}
  const studio=(await api('/api/studios')).items[0].id;
  const project=await api(`/api/studios/${studio}/projects`,{name:'测试节点同步'}),root=`/api/studios/${studio}/projects/${project.id}`;
  const batch=await api(root+'/tasks',{title:'历史批次证据保留'});
  for(let i=0;i<12;i++)await api(root+'/tasks/'+batch.id+'/requirements',{source:'需求来源 '+i,content:'第 '+i+' 条真实界面测试资料：奖励数量必须大于零。'});
  let config=await api(root+'/nodes?department=testing');
  config.nodes=[4,0,1,2,5].map(stage=>config.nodes.find(n=>n.id==='testing:'+stage));
  await api(root+'/nodes?department=testing',config);
  await api(root+'/enter',{});await api('/api/me/preferences',{active_studio_id:studio,role:'qa'});
  await page.goto(base);await page.locator('[data-action="home:testing"]').click();
  await page.locator('.home-node[data-action="node:testing:1"]').click();
  const frame=page.frameLocator('#testing-frame');await frame.locator('.steps').waitFor();
  await check('deleted/reordered nodes match project navigation',async()=>{
   assert.deepEqual(await frame.locator('.step b').allTextContents(),['提单','用例','执行','归因','回归']);
   await frame.locator('.step').first().click();assert.equal(await frame.locator('.workspace-head h2').innerText(),'提单工作区');
   await frame.locator('.step').nth(1).click();assert.equal(await frame.locator('.workspace-head h2').innerText(),'用例工作区');
   assert.deepEqual((await api(root+'/tasks/'+batch.id)).workflow_nodes,batch.workflow_nodes,'historical snapshot is immutable');
  });
  await check('reordered buttons use stable stage permissions',async()=>{
   // Simulate a refreshed capability response; server authorization is covered separately.
   await frame.locator('body').evaluate(()=>{testingCapabilities.nodes['testing:0'].view=false;render()});
   assert(await frame.locator('.step').nth(1).isDisabled(),'use-case permission stays on stage 0');
   assert(await frame.locator('.step').first().isEnabled(),'draft permission stays on stage 4');
   assert.equal(await frame.locator('.step.selected b').innerText(),'提单');
   await frame.locator('body').evaluate(()=>{testingCapabilities.nodes['testing:0'].view=true;render()});
  });
  for(const theme of ['paper','forge','arcade'])await check(theme+' sticky background matches shell while scrolling',async()=>{
   await page.locator('[data-action="view:themes"]').first().click();const choice=page.locator('[data-action="theme:'+theme+'"]');if(await choice.count())await choice.click();
   await page.locator('[data-action="home:testing"]').click();await page.locator('.home-node[data-action="node:testing:1"]').click();
   const inner=page.frameLocator('#testing-frame');await inner.locator('.steps').waitFor();
   const outerColor=await page.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor);
   const bodyColor=await inner.locator('body').evaluate(e=>getComputedStyle(e).backgroundColor);
   const stickyColor=await inner.locator('.flow-sticky').evaluate(e=>getComputedStyle(e).backgroundColor);
   assert.equal(bodyColor,outerColor,'iframe canvas uses active theme');assert.equal(stickyColor,bodyColor,'sticky reserve uses same canvas');
   await inner.locator('body').evaluate(()=>window.scrollTo(0,200));
   const pinned=await inner.locator('.flow-sticky').evaluate(e=>({top:e.getBoundingClientRect().top,cover:document.elementFromPoint(e.getBoundingClientRect().left+20,4)===e}));
   assert.equal(pinned.top,0);assert(pinned.cover,'sticky top padding covers scrolling content');
   const shots=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(shots,{recursive:true});
   await page.screenshot({path:path.join(shots,'testing-sticky-'+theme+'.png')});
  });
  await check('deleted selected stage falls back safely without bypassing evidence gates',async()=>{
   config=await api(root+'/nodes?department=testing');config.nodes=config.nodes.filter(n=>n.id!=='testing:0');await api(root+'/nodes?department=testing',config);
   const legacy=await browser.newPage();
   await legacy.goto(base+'/testing.html?'+new URLSearchParams({studio,project:project.id,task:batch.id,stage:'0'}));await legacy.locator('.steps').waitFor();
   assert.deepEqual(await legacy.locator('.step b').allTextContents(),['提单','执行','归因','回归']);
   assert.equal(await legacy.locator('.workspace-head h2').innerText(),'提单工作区');
   assert.match(await legacy.locator('.workflow-config-notice').innerText(),/恢复/);
   assert.equal((await api(root+'/tasks/'+batch.id)).stage,0);
   config=await api(root+'/nodes?department=testing');config.nodes.unshift({...config.archived.find(n=>n.id==='testing:0'),restore:true});await api(root+'/nodes?department=testing',config);
   await legacy.reload();await legacy.locator('.steps').waitFor();assert.equal(await legacy.locator('.step.selected b').innerText(),'用例');
   const restored=await api(root+'/nodes?department=testing');
   const other=await api(`/api/studios/${studio}/projects`,{name:'独立默认配置'});
   assert.equal((await api(`/api/studios/${studio}/projects/${other.id}/nodes?department=testing`)).nodes.length,6,'other project keeps its own navigation');
   await api(root+'/nodes?department=testing',{revision:restored.revision,nodes:[]});
   await legacy.reload();await legacy.getByText('当前项目没有可查看的活动测试节点', {exact:false}).waitFor();
   assert.equal(await legacy.locator('.step').count(),0);assert.equal(await legacy.locator('.workspace-head').count(),0,'archived workspace is not displayed');
   await legacy.close();
  });
  assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
  console.log('PASS: testing navigation and three-theme sticky regressions. Temporary data only; no model/Unity/Feishu calls.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
