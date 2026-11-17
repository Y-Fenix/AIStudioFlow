// Isolated real HTTP / SQLite API + Chrome. Production worker disabled: no models, tools, notifications or APK claims.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawn,execFileSync}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-production-ui-'));
 const server=spawn('python3',['-u','-c','import sys;from server.core.production_runs import ProductionWorker;ProductionWorker.run=lambda self:None;from server.app import create_server;s=create_server("127.0.0.1",0,sys.argv[1],local_development=True);print(s.server_port,flush=True);s.serve_forever()',path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+20000;while(!/^\d+\s*$/m.test(output)){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50))}
  const base='http://127.0.0.1:'+output.match(/^(\d+)\s*$/m)[1];browser=await chromium.launch({headless:true,executablePath:process.env.STUDIOFLOW_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1512,height:1100}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function api(url,body){const r=await page.request[body===undefined?'get':'post'](base+url,body===undefined?{}:{data:body});assert(r.ok(),await r.text());return r.json()}
  const studio=(await api('/api/studios')).items[0].id,project=await api(`/api/studios/${studio}/projects`,{name:'生产控制台隔离验收'}),root=`/api/studios/${studio}/projects/${project.id}`;
  await api(root+'/enter',{});await api('/api/me/preferences',{active_studio_id:studio,role:'studio_owner'});await page.goto(base+'/?view=production&studio='+studio+'&project='+project.id);await page.locator('#production-idea').waitFor();
  const idea='隔离验收：一款竖屏单词游戏，验证生产控制台交互；本脚本禁用生产执行器，不生成游戏。';await page.locator('#production-idea').fill(idea);await page.locator('#production-delegation').check();
  await page.route('**/production-runs',route=>route.request().method()==='POST'?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'验收模拟网络失败'})}):route.continue());await page.locator('[data-production-start]').click();await page.getByText('验收模拟网络失败',{exact:true}).waitFor();assert.equal(await page.locator('#production-idea').inputValue(),idea);assert(await page.locator('[data-production-start]').isEnabled());await page.unroute('**/production-runs');
  let release,arrived,posts=0;const held=new Promise(r=>release=r),seen=new Promise(r=>arrived=r);await page.route('**/production-runs',async route=>{if(route.request().method()!=='POST')return route.continue();posts++;arrived();await held;await route.continue()});
  await page.locator('[data-production-start]').click();await seen;assert.equal(await page.locator('[data-production-start]').getAttribute('aria-busy'),'true');await page.locator('[data-production-start]').evaluate(el=>el.click());release();await page.locator('.production-run').waitFor();await page.waitForFunction(()=>!document.querySelector('[data-production-start]').disabled);assert.equal(posts,1);await page.unroute('**/production-runs');
  const runs=(await api(root+'/production-runs')).items;assert.equal(runs.length,1);const id=runs[0].id;assert.equal(runs[0].status,'queued');assert.equal(await page.locator('.production-stages details').count(),runs[0].steps.length);assert.equal(await page.locator('progress').getAttribute('value'),'0');assert.equal(await page.locator('.production-artifact').count(),0);
  const savedURL=page.url();assert(savedURL.includes('production_run='+id));await page.reload();await page.locator('.production-run').waitFor();assert.equal(await page.locator('.production-stages details').count(),runs[0].steps.length);
  await page.locator('[data-production=pause]').click();await page.locator('[data-production=resume]').waitFor();assert.equal((await api(root+'/production-runs/'+id)).status,'paused');await page.locator('[data-production=resume]').click();await page.locator('[data-production=pause]').waitFor();assert.equal((await api(root+'/production-runs/'+id)).status,'queued');
  await page.locator('.production-stages summary').first().click();assert(await page.locator('.production-stages details').first().getAttribute('open')!==null);await page.locator('[data-production=refresh]').first().click();await page.waitForTimeout(150);assert(await page.locator('.production-stages details').first().getAttribute('open')!==null);
  // Real isolated SQLite updates drive HTTP polling; no response substitute or model execution.
  const fixtureUpdate=(summary,longOutput)=>execFileSync('python3',['-c',
   'import sqlite3,json,sys;db=sqlite3.connect(sys.argv[1]);row=db.execute("SELECT steps FROM production_runs WHERE id=?",(sys.argv[2],)).fetchone();steps=json.loads(row[0]);[step.update(output=("\\n".join(str(i)+" "+"Fixture evidence "+"x"*600 for i in range(160)) if sys.argv[4]=="long" else "")) for step in steps[:2]];db.execute("UPDATE production_runs SET steps=?,summary=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(json.dumps(steps),sys.argv[3],sys.argv[2]));db.commit()',
   path.join(folder,'db.sqlite'),id,summary,longOutput?'long':'short']);
  fixtureUpdate('Scroll fixture before real polling update',true);
  await page.locator('[data-production=refresh]').first().click();await page.getByText('Scroll fixture before real polling update',{exact:true}).waitFor();
  const probeStyle=await page.addStyleTag({content:'.production-stage pre{white-space:pre}'}); // Exercise both native scroll axes.
  await page.locator('.production-stages details').nth(1).evaluate(el=>el.open=true);
  const beforeScroll=await page.locator('.production-stages details').evaluateAll(nodes=>nodes.slice(0,2).map((el,i)=>{const pre=el.querySelector('pre');pre.scrollTop=240+i*155;pre.scrollLeft=65+i*40;return {id:el.dataset.step,top:pre.scrollTop,left:pre.scrollLeft}}));
  assert(beforeScroll.every(s=>s.top>0&&s.left>0),'long real fixture must scroll on both axes');
  await page.locator('.production-stages summary').first().focus();
  fixtureUpdate('Scroll fixture changed by server while reading',true);
  await page.getByText('Scroll fixture changed by server while reading',{exact:true}).waitFor(); // Four-second real polling.
  const afterScroll=await page.locator('.production-stages details').evaluateAll(nodes=>nodes.slice(0,2).map(el=>{const pre=el.querySelector('pre');return {id:el.dataset.step,top:pre.scrollTop,left:pre.scrollLeft}}));
  assert.deepEqual(afterScroll,beforeScroll,'polling server summary changes must retain each evidence pane scroll position');
  assert.equal(await page.locator('.production-stages summary').first().evaluate(el=>document.activeElement===el),true,'polling preserves summary focus');
  assert(await page.locator('.production-stages details').nth(1).evaluate(el=>el.open));
  const readingPane=page.locator('.production-stages details pre').nth(1);await readingPane.hover();await page.mouse.wheel(0,120);
  await page.waitForFunction(()=>document.querySelectorAll('.production-stages details pre')[1].scrollTop>395);
  const userScroll=await readingPane.evaluate(el=>({top:el.scrollTop,left:el.scrollLeft}));fixtureUpdate('Scroll fixture after user wheel',true);await page.getByText('Scroll fixture after user wheel',{exact:true}).waitFor();
  assert.deepEqual(await readingPane.evaluate(el=>({top:el.scrollTop,left:el.scrollLeft})),userScroll,'new user scroll remains authoritative at the next update');
  assert.notEqual(await page.locator('body').evaluate(el=>getComputedStyle(el).position),'fixed','page must not be scroll-locked');
  await probeStyle.evaluate(el=>el.remove());fixtureUpdate('Scroll fixture cleaned up',false);await page.locator('[data-production=refresh]').first().click();await page.getByText('Scroll fixture cleaned up',{exact:true}).waitFor();await page.locator('.production-stages details').nth(1).evaluate(el=>el.open=false);
  await page.screenshot({path:'/tmp/studioflow-production-console-desktop.png',fullPage:true});
  await page.emulateMedia({reducedMotion:'reduce'});for(const width of [375,768,1024,1512]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'horizontal overflow at '+width+' '+JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().right>innerWidth+2).map(el=>[el.tagName,el.className,Math.round(el.getBoundingClientRect().right)]).slice(0,20))))}await page.setViewportSize({width:375,height:900});await page.screenshot({path:'/tmp/studioflow-production-console-mobile.png',fullPage:true});
  for(const theme of ['paper','forge','arcade']){await page.locator('html').evaluate((el,t)=>el.dataset.theme=t,theme);assert(await page.locator('[data-production=cancel]').isVisible())}await page.locator('html').evaluate(el=>el.dataset.theme='paper');
  await page.locator('[data-production=cancel]').focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('.production-run-head [data-state=cancelled]'));assert.equal((await api(root+'/production-runs/'+id)).status,'cancelled');assert.equal(await page.locator('[data-production-control]').count(),0);
  // Permission loss hides previously returned sensitive detail.
  await page.route('**/production-runs/'+id,route=>route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({error:'验收模拟撤权'})}));await page.locator('[data-production=refresh]').first().click();await page.getByText('权限变化后已隐藏运行详情。请登录或联系负责人后刷新。',{exact:true}).waitFor();assert.equal(await page.locator('.production-run').count(),0);await page.unroute('**/production-runs/'+id);
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,realAPI:true,workerDisabled:true,checks:['failure retention','pending duplicate guard','durable run reload','real pause resume cancel','all actual server nodes','zero fabricated progress','keyboard','375/768/1024/1512 responsive','reduced motion','three theme rendering','independent evidence scroll through real polling'],screenshots:['/tmp/studioflow-production-console-desktop.png','/tmp/studioflow-production-console-mobile.png']}));
 }finally{await browser?.close();server.kill('SIGTERM');fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
