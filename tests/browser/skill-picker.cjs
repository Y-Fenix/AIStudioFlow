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
  const project=await api(`/api/studios/${studio}/projects`,{name:'Skill 快速选择'}),root=`/api/studios/${studio}/projects/${project.id}`;
  const batch=await api(root+'/tasks',{title:'选择目标批次'}),other=await api(root+'/tasks',{title:'隔离批次'});
  async function upload(node,name,content){const current=await api(root+'/skills?node='+encodeURIComponent(node));return api(root+'/skills?node='+encodeURIComponent(node),{id:current.id,revision:current.revision,name,content,note:'浏览器回归用规则'})}
  const content='---\nname: team-case\ndescription: 团队用例规则\n---\n# 来源核查\n必须保留需求引用与边界条件。';
  await upload('testing:0','团队用例规则',content);
  await upload('product:0','团队产品规则','---\nname: product-review\ndescription: 产品核查\n---\n只使用已确认的产品资料。');
  await api(root+'/enter',{});await api('/api/me/preferences',{active_studio_id:studio,role:'qa'});await page.goto(base);
  await page.locator('[data-action="home:testing"]').click();await page.locator('.home-node[data-action="node:testing:0"]').click();
  const frame=page.frameLocator('#testing-frame');await frame.locator('.workspace-head').waitFor();
  await frame.locator('.task-selector select').selectOption(batch.id);
  await check('task status is Chinese and explains the required human action',async()=>{
   assert.equal(await frame.locator('.workspace-head>.pill').innerText(),'待你操作');
   assert.match(await frame.locator('.workspace-head>.pill').getAttribute('title'),/审核|操作/);
  });
  assert.equal(await frame.getByRole('button',{name:'选择 Skill',exact:true}).count(),1,'node toolbar exposes Skill selector');
  for(let stage=0;stage<6;stage++){
   await frame.locator(`.step[data-stage="${stage}"]`).click();assert(await frame.getByRole('button',{name:'选择 Skill',exact:true}).isEnabled());
  }
  await frame.locator('.step[data-stage="1"]').click();
  assert(await frame.locator('.workspace-head').evaluate(e=>e.scrollWidth<=e.clientWidth),'testing toolbar fits with the new selector');
  await frame.getByRole('button',{name:'选择 Skill',exact:true}).click();
  await frame.locator('[data-skill-search]').fill('用例');
  await frame.locator('[data-skill-source="testing:0"]').click();await frame.locator('.skill-picker-preview pre').waitFor();assert.match(await frame.locator('.skill-picker-preview pre').innerText(),/必须保留需求引用与边界条件/);
  assert(await frame.getByRole('button',{name:'使用并保存',exact:true}).isEnabled());
  const shots=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(shots,{recursive:true});await page.screenshot({path:path.join(shots,'skill-picker-testing.png')});
  await frame.getByRole('button',{name:'使用并保存',exact:true}).click();await frame.locator('.modalwrap').waitFor({state:'detached'});
  let saved=await api(root+'/tasks/'+batch.id);assert.equal(saved.node_skills['1'].content,content);assert.equal(saved.node_skills['1'].name,'团队用例规则');
  assert.deepEqual(saved.node_skills['0'],batch.node_skills['0']);assert.deepEqual((await api(root+'/tasks/'+other.id)).node_skills,other.node_skills);
  assert.match(await frame.locator('.skill-label').innerText(),/当前 Skill.*团队用例规则/);
  assert.notEqual((await api(root+'/skills?node=testing:1')).skill.content,content,'batch choice does not rewrite project default');
  await frame.getByRole('button',{name:'选择 Skill',exact:true}).click();await frame.locator('[data-skill-search]').waitFor();await page.keyboard.press('Escape');await frame.locator('.modalwrap').waitFor({state:'detached'});
  await frame.getByRole('button',{name:'选择 Skill',exact:true}).click();await frame.locator('.modalwrap').click({position:{x:4,y:4}});await frame.locator('.modalwrap').waitFor({state:'detached'});
  await frame.getByRole('button',{name:'选择 Skill',exact:true}).click();await frame.locator('[data-skill-source="testing:0"]').click();await frame.locator('.skill-picker-preview pre').waitFor();
  await upload('testing:0','新版团队规则',content+'\n补充历史版本检查。');
  await frame.getByRole('button',{name:'使用并保存',exact:true}).click();await frame.locator('[data-skill-error]').getByText(/所选 Skill 已变化/).waitFor();
  assert.equal((await api(root+'/tasks/'+batch.id)).revision,saved.revision,'source conflict does not write the target');await page.keyboard.press('Escape');
  // A late preview response must not reopen a dialog that has been closed.
  let release,arrived;const held=new Promise(r=>release=r),seen=new Promise(r=>arrived=r);
  const pattern='**/skills?node=testing%3A0';
  await page.route(pattern,async route=>{const response=await route.fetch();arrived();await held;await route.fulfill({response})});
  await frame.getByRole('button',{name:'选择 Skill',exact:true}).click();await frame.locator('[data-skill-source="testing:0"]').click();await seen;
  await page.keyboard.press('Escape');release();await page.unrouteAll({behavior:'wait'});assert.equal(await frame.locator('.modalwrap').count(),0);
  // Default rules without a library row must also support selection/export.
  await frame.locator('.step[data-stage="2"]').click();await frame.getByRole('button',{name:'选择 Skill',exact:true}).click();await frame.locator('[data-skill-source="testing:2"]').click();await frame.locator('.skill-picker-preview pre').waitFor();
  await frame.getByRole('button',{name:'使用并保存',exact:true}).click();await frame.locator('.modalwrap').waitFor({state:'detached'});saved=await api(root+'/tasks/'+batch.id);
  assert.equal(saved.node_skills['2'].content,batch.node_skills['2'].content);await frame.locator('.step[data-stage="1"]').click();
  await frame.getByRole('button',{name:'选择 Skill',exact:true}).click();await frame.locator('[data-skill-source="testing:0"]').click();await frame.getByRole('button',{name:'使用并保存',exact:true}).waitFor({state:'visible'});
  await frame.locator('.skill-picker-preview pre').waitFor();
  await api(root+'/tasks/'+batch.id+'/node-skill?stage=1',{revision:saved.revision,content:'并发新版本',name:'并发规则'});
  await frame.getByRole('button',{name:'使用并保存',exact:true}).click();await frame.locator('[data-skill-error]').getByText(/任务已变化|重新打开/).waitFor();
  assert.equal((await api(root+'/tasks/'+batch.id)).node_skills['1'].content,'并发新版本');await page.keyboard.press('Escape');
  await page.locator('[data-action="home:product"]').click();await page.locator('.home-node[data-action="node:product:1"]').click();
  assert(await page.locator('.node-head').evaluate(e=>e.scrollWidth<=e.clientWidth),'shared toolbar fits with the new selector');
  await page.locator('[data-action="select-skill"]').click();await page.locator('[data-skill-source="product:0"]').click();await page.locator('.skill-picker-preview pre').waitFor();
  await page.getByRole('button',{name:'使用并保存',exact:true}).click();await page.locator('.modal').waitFor({state:'detached'});
  assert.equal((await api(root+'/workspace?node=product:1')).skill.name,'团队产品规则');
  await page.reload();await page.locator('[data-action="home:product"]').click();await page.locator('.home-node[data-action="node:product:1"]').click();await page.locator('#node-deliverable').waitFor();assert.match(await page.locator('.node-skill-inline>.skill-label').innerText(),/团队产品规则/);
  await page.locator('[data-action="select-skill"]').click();await page.locator('[data-skill-search]').fill('没有这个规则');assert.match(await page.locator('.skill-picker-list').innerText(),/没有/);assert(await page.getByRole('button',{name:'使用并保存',exact:true}).isDisabled());
  await page.keyboard.press('Escape');await page.setViewportSize({width:390,height:844});await page.locator('[data-action="select-skill"]').click();await page.locator('[data-skill-source="product:0"]').click();await page.locator('.skill-picker-preview pre').waitFor();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'picker does not overflow narrow viewport');await page.screenshot({path:path.join(shots,'skill-picker-mobile.png')});
  assert.deepEqual(errors,[]);assert.deepEqual(failures,[]);
  console.log('PASS: six testing nodes and shared department picker, Chinese status, preview/save/persistence, default rules, target isolation, ESC/backdrop, late preview, source/target conflicts, empty search and mobile. No model calls.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
