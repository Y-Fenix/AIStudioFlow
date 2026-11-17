// Three isolated SQLite/HTTP installations and two real public accounts. No AI or Webhooks.
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-public-')),servers=[];let browser;
 async function start(name,mode){
  const child=spawn('python3',['-u','-c','import sys;from server.app import create_server;s=create_server("127.0.0.1",0,sys.argv[1],runtime_mode=sys.argv[2],local_development=sys.argv[2]=="personal");print(s.server_port,flush=True);s.serve_forever()',path.join(folder,name,'db.sqlite'),mode],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
  const record={child,output:''};servers.push(record);child.stdout.on('data',d=>record.output+=d);child.stderr.on('data',d=>record.output+=d);
  const deadline=Date.now()+15000;while(!/^\d+\s*$/m.test(record.output)){if(Date.now()>deadline||child.exitCode!==null)throw Error(record.output);await new Promise(r=>setTimeout(r,50))}
  return 'http://127.0.0.1:'+record.output.match(/^(\d+)\s*$/m)[1];
 }
 try{
  const central=await start('central','public'),a=await start('a','personal'),b=await start('b','personal');
  browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const contexts=await Promise.all([browser.newContext({viewport:{width:1512,height:1000}}),browser.newContext({viewport:{width:1512,height:1000}}),browser.newContext({viewport:{width:1512,height:1000}})]);
  const [pc,pa,pb]=await Promise.all(contexts.map(c=>c.newPage())),errors=[];
  for(const p of [pc,pa,pb])p.on('pageerror',e=>errors.push(e.message));
  async function api(page,base,url,body){const r=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(r.ok(),r.status()+' '+url+' '+await r.text());return r.json()}
  await api(pc,central,'/api/auth/setup',{username:'owner',name:'Owner',password:'Owner-test-1234'});
  const studio=(await api(pc,central,'/api/studios')).items[0].id;
  for(let i=0;i<7;i++)await api(pc,central,`/api/studios/${studio}/projects`,{name:'Other '+i});
  const project=await api(pc,central,`/api/studios/${studio}/projects`,{name:'Central project'}),root=`/api/studios/${studio}/projects/${project.id}`;
  const version=await api(pc,central,root+'/public/versions',{name:'v1.0'});
  const reader=(await api(pc,central,'/api/auth/register',{username:'reader',name:'Reader',password:'Reader-test-1234'})).user;
  await api(pc,central,'/api/admin/members',{studio_id:studio,project_id:project.id,department:'product',user_id:reader.id,role:'member'});
  for(const action of ['view','export','create'])await api(pc,central,'/api/admin/rules',{studio_id:studio,project_id:project.id,department:'product',node:'',subject_type:'user',subject_id:reader.id,resource:'publication',action,effect:'allow'});
  async function local(page,base,name){const s=(await api(page,base,'/api/studios')).items[0].id,p=await api(page,base,`/api/studios/${s}/projects`,{name}),r=`/api/studios/${s}/projects/${p.id}`;
   await api(page,base,r+'/workspace?node=product:0',{revision:0,deliverable:'Reviewed '+name,inputs:'PRIVATE INPUT '+name});await api(page,base,r+'/enter',{});return {s,p,r}}
  const la=await local(pa,a,'A'),lb=await local(pb,b,'B');
  await pa.route('**/api/runtime',route=>route.fulfill({status:404,contentType:'application/json',body:JSON.stringify({error:'unknown route'})}));
  await pa.goto(a);await pa.waitForSelector('[data-action="view:public"]');
  await pa.unroute('**/api/runtime');
  async function connect(page,base,user){await page.goto(base);await page.locator('[data-action="view:public"]').click();await page.locator('[data-public="connect"]').click();await page.locator('#public-server').fill(central);await page.locator('#public-lan').check();await page.locator('#public-user').fill(user);await page.locator('#public-password').fill(user==='owner'?'Owner-test-1234':'Reader-test-1234');await page.locator('#public-connect-form [type="submit"]').click();await page.waitForSelector('#public-project-page');
   if(user==='owner'){assert.equal(await page.locator('#public-project option').count(),6);assert.equal(await page.locator('#public-project-page').textContent(),'1 / 2');await page.locator('[data-public="project-next"]').click();await page.waitForFunction(()=>document.querySelector('#public-project-page')?.textContent==='2 / 2')}
   await page.locator('#public-project-q').fill('Central project');await page.locator('#public-project-search button').click();await page.waitForFunction(id=>[...document.querySelector('#public-project').options].some(o=>o.value===id),project.id);await page.locator('#public-project').selectOption(project.id);await page.waitForFunction(()=>document.querySelector('#public-version option')?.nextElementSibling);await page.locator('#public-version').selectOption(version.id);await page.locator('[data-public="bind"]').click();try{await page.waitForSelector('.public-pagination')}catch(e){console.error('CONNECT STATE',user,await page.locator('body').innerText());throw e}}
  await connect(pa,a,'owner');await connect(pb,b,'reader');
  await pa.locator('[data-public="source"]').click();await pa.locator('#public-title').fill('Reviewed game plan');await pa.locator('#public-source-form [type="submit"]').click();await pa.waitForSelector('#public-confirm');
  assert(await pa.locator('[data-public="publish"]').isDisabled());assert(!(await pa.locator('.public-preview').textContent()).includes('PRIVATE INPUT'));
  assert.equal((await api(pc,central,root+'/public/items')).total,0);
  await pa.locator('#public-confirm').check();await pa.locator('[data-public="publish"]').click();await pa.waitForFunction(()=>document.querySelector('.public-preview')?.textContent.includes('发布成功'));
  const item=(await api(pc,central,root+'/public/items')).items[0];assert.equal(item.author_name,'Owner');await pa.keyboard.press('Escape');await pa.waitForSelector('.modal',{state:'detached'});
  await pb.locator('#public-filter [data-public="refresh"]').click();await pb.waitForSelector('.public-item h3');assert.equal(await pb.locator('.public-item h3').first().innerText(),'Reviewed game plan');
  await pb.locator('[data-public="detail:'+item.id+'"]').click();await Promise.all([pb.waitForResponse(r=>r.url().endsWith('/public-local/copy')),pb.locator('[data-public="copy"]').click()]);await pb.keyboard.press('Escape');
  const copied=await api(pb,b,lb.r+'/public-local/copies');assert.equal(copied.items[0].package.content,'Reviewed A');assert(copied.items[0].inert);
  assert.equal((await api(pb,b,lb.r+'/workspace?node=product:0')).deliverable,'Reviewed B');
  await api(pa,a,la.r+'/workspace?node=product:0',{revision:1,deliverable:'Updated A',inputs:'PRIVATE INPUT A'});
  assert.equal((await api(pc,central,root+'/public/items/'+item.id)).package.content,'Reviewed A');
  await pa.locator('[data-public="detail:'+item.id+'"]').click();await pa.locator('[data-public="update"]').click();await pa.locator('#public-source-form [type="submit"]').click();await pa.locator('#public-confirm').check();await pa.locator('[data-public="publish"]').click();await pa.waitForFunction(()=>document.querySelector('.public-preview')?.textContent.includes('发布成功'));await pa.keyboard.press('Escape');
  assert.equal((await api(pc,central,root+'/public/items/'+item.id)).revision,2);
  await pc.goto(central+'/?studio='+studio+'&project='+project.id+'&publication='+item.id);await pc.waitForSelector('#public-revision');assert.equal(await pc.locator('.public-body').innerText(),'Updated A');await pc.locator('#public-revision').selectOption('1');await pc.waitForFunction(()=>document.querySelector('.public-body')?.textContent==='Reviewed A');
  await pc.mouse.click(2,2);await pc.waitForSelector('.modal',{state:'detached'});
  const requests=[];pc.on('request',r=>{if(r.url().includes('/api/'))requests.push(r.url())});
  await pc.locator('[data-action="view:admin"]').click();await pc.waitForSelector('.admin-context');assert.equal(await pc.locator('[data-action="admin-tab:connections"]').count(),0);
  await pc.locator('[data-action="view:settings"]').click();await pc.waitForSelector('#notification-config');await pc.locator('#notification-config summary').click();await pc.waitForSelector('#notify-scope');
  assert(!requests.some(r=>/ai-models|project-connection|\/summary/.test(r)));
  await pc.locator('[data-action="view:public"]').click();await pc.waitForSelector('.public-pagination');
  for(const theme of ['paper','forge','arcade']){await pc.locator('html').evaluate((el,t)=>el.dataset.theme=t,theme);await pc.screenshot({path:'/tmp/studioflow-public-'+theme+'.png'})}
  await pc.setViewportSize({width:390,height:844});assert(await pc.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'public mobile overflow');
  assert(await pc.locator('[data-public="version"]').evaluate(el=>parseFloat(getComputedStyle(el).fontSize)>0),'new version button has no visible label');
  const projectBox=await pc.locator('#topbar [data-action="projects"]').boundingBox(),accountBox=await pc.locator('#topbar [data-action="user-settings"]').boundingBox();
  assert(projectBox.x+projectBox.width<=accountBox.x,'project selector overlaps account settings');
  await pc.screenshot({path:'/tmp/studioflow-public-mobile.png',fullPage:true});
  await pa.locator('[data-public="detail:'+item.id+'"]').click();await pa.locator('[data-public="withdraw"]').click();await pa.locator('[data-public="withdraw-confirm"]').click();await pa.waitForSelector('.modal',{state:'detached'});
  assert.equal((await api(pc,central,root+'/public/items')).total,0);assert.equal((await api(pb,b,lb.r+'/public-local/copies')).items[0].revision,1);
  assert.deepEqual(errors,[]);
  console.log('PASS: three isolated installs; two public identities; 5/project paging; explicit selected upload; frozen snapshots; inert copy; revisions/deep link; withdrawal; Escape/backdrop; central admin/notifications; three themes/mobile. No AI/Webhooks.');
 }catch(e){for(const s of servers)console.error(s.output.slice(-1500));throw e}finally{if(browser)await browser.close();for(const s of servers){s.child.kill('SIGTERM');await new Promise(r=>s.child.exitCode!==null?r():s.child.once('exit',r))}fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
