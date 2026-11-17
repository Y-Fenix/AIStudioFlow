// Isolated HTTP/SQLite fixture. No model, Unity, Git or Feishu operations.
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-merged-triage-'));
 const bootstrap=`import sys,json
from server.store import Store
from server.core.project_nodes import ProjectNodes
from server.triage import triage_report
from server.app import create_server
store=Store(sys.argv[1]);studio=store.studios()[0]['id'];project=store.create_project('隔离五步流程')['id']
manager=ProjectNodes(store);config=manager.get(studio,project,'testing');config['nodes']=[n for n in config['nodes'] if n['id']!='testing:3'];manager.save(studio,project,'testing',config)
results=[{'id':key,'test_name':'样例 '+key,'status':'failed','detail':'静态样例','evidence':'fixture-'+key,'preconditions':['样例前置'],'steps':['样例调用'],'expected':'1','actual':'0'} for key in ('f1','f2')]
triage=triage_report(results,[{'result_id':r['id'],'root_cause_id':r['id']} for r in results],[{'id':r['id'],'title':'样例根因 '+r['id'],'confirmed':True,'evidence':[r['evidence']]} for r in results],[])
ids=[]
for stage in (2,3):
 task=store.create_task(project,'归因样例' if stage==2 else '旧筛选批次');ids.append(task['id'])
 artifacts={'0':{'points':[],'cases':[],'gaps':[],'ambiguities':[],'coverage':{'identified':0,'covered':0,'gaps':0,'scope':'隔离界面样例'}},'1':{'results':results,'method':'static_code_review','code_fingerprint':'fixture-only'},'2':triage}
 with store.connection() as db:db.execute('UPDATE tasks SET stage=?,artifacts=? WHERE id=?',(stage,json.dumps(artifacts),task['id']))
server=create_server('127.0.0.1',0,sys.argv[1],local_development=True)
print(json.dumps({'port':server.server_port,'studio':studio,'project':project,'tasks':ids}),flush=True)
server.serve_forever()`;
 const server=spawn('python3',['-u','-c',bootstrap,path.join(folder,'db.sqlite')],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});
 let output='',browser;server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+10000;while(!output.includes('"port"')){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,40))}
  const config=JSON.parse(output.split('\n').find(l=>l.startsWith('{'))),base='http://127.0.0.1:'+config.port;
  browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1600,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function api(route,body){const r=await page.request[body===undefined?'get':'post'](base+route,body===undefined?{}:{data:body});assert(r.ok(),await r.text());return r.json()}
  const root='/api/studios/'+config.studio+'/projects/'+config.project;
  const url=id=>base+'/testing.html?'+new URLSearchParams({studio:config.studio,project:config.project,task:id,stage:'2'});
  await page.goto(url(config.tasks[0]));await page.locator('.steps').waitFor();
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  assert.deepEqual(await page.locator('.step b').allTextContents(),['用例','执行','归因','提单','回归']);
  assert.equal(await page.locator('.step[data-node-state=confirmed]').count(),2);
  assert.equal(await page.locator('.step[data-node-state=current]').count(),1);
  assert.equal(await page.locator('.step[data-node-state=pending]').count(),2);
  assert.doesNotMatch(await page.locator('.steps').innerText(),/已确认|当前节点|未开始/);
  const shots=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(shots,{recursive:true});
  async function backgroundRGB(stage){
   return page.locator('.step[data-stage="'+stage+'"]').evaluate(el=>{
    const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
    const ctx=canvas.getContext('2d');ctx.fillStyle=getComputedStyle(el).backgroundColor;ctx.fillRect(0,0,1,1);
    return Array.from(ctx.getImageData(0,0,1,1).data).slice(0,3);
   });
  }
  function contrast(a,b){
   const luminance=rgb=>rgb.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
   const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
  }
  for(const theme of ['paper','forge','arcade']){
   await page.locator('html').evaluate((el,t)=>el.dataset.theme=t,theme);
   await page.mouse.move(0,0);
   const neutral=await backgroundRGB(0),selectedFill=await backgroundRGB(2);
   assert.deepEqual(await backgroundRGB(4),neutral,theme+': unselected states share neutral fill');
   assert.notDeepEqual(selectedFill,neutral,theme+': selection has a separate fill');
   assert.equal(await page.locator('.step[data-stage="2"]').getAttribute('title'),'待人工确认');
   const dots=await page.locator('.step .node-status-dot').evaluateAll(els=>els.map(el=>getComputedStyle(el).backgroundColor));
   assert.deepEqual(dots,['rgb(82, 196, 26)','rgb(82, 196, 26)','rgb(250, 173, 20)','rgb(191, 191, 191)','rgb(191, 191, 191)']);
   for(const stage of [0,4,2]){
    await page.locator('.step[data-stage="'+stage+'"]').click();await page.mouse.move(0,0);
    assert.deepEqual(await backgroundRGB(stage),selectedFill,theme+': every state uses the same selected fill');
    const selected=await page.locator('.step[data-stage="'+stage+'"]').evaluate(el=>({
     color:getComputedStyle(el).color,
     number:getComputedStyle(el.querySelector('.stepnum')).color,
     title:getComputedStyle(el.querySelector('b')).color,
     outline:getComputedStyle(el).outlineStyle,
     shadow:getComputedStyle(el).boxShadow,
     border:getComputedStyle(el).borderColor,
     pressed:el.getAttribute('aria-pressed'),
    }));
    assert.equal(selected.number,selected.color,theme+': number remains readable');
    assert.equal(selected.title,selected.color,theme+': title inherits selected text color');
    assert(contrast(selected.color.match(/\d+/g).map(Number),selectedFill)>=4.5,theme+': text contrast >= 4.5');
    assert.equal(selected.outline,'none');assert.equal(selected.shadow,'none');
    assert.equal(selected.pressed,'true');
    assert.equal(selected.border,await page.locator('.step:not(.selected)').first().evaluate(el=>getComputedStyle(el).borderColor),'selection adds no border');
    assert.deepEqual(await page.locator('.step .node-status-dot').evaluateAll(els=>els.map(el=>getComputedStyle(el).backgroundColor)),dots,'selection never changes status dots');
   }
   await page.locator('.step[data-stage="4"]').hover();
   assert.notDeepEqual(await backgroundRGB(4),neutral,'unselected hover is visible');
   await page.locator('.step[data-stage="2"]').hover();
   assert.deepEqual(await backgroundRGB(2),selectedFill,'selected hover keeps blue fill');
   await page.mouse.move(0,0);
   await page.screenshot({path:path.join(shots,'node-state-selection-'+theme+'.png')});
  }
  // UI-only fixtures exercise real rendering without starting model jobs.
  for(const [status,label,color] of [['queued','排队中','rgb(22, 119, 255)'],['running','进行中','rgb(22, 119, 255)'],['failed','执行失败','rgb(255, 77, 79)'],['completed','待人工确认','rgb(250, 173, 20)']]){
   await page.evaluate(status=>{task.jobs=[{stage:2,status,revision:task.revision}];render()},status);
   assert.equal(await page.locator('.step[data-stage="2"]').getAttribute('title'),label);
   assert.equal(await page.locator('.step[data-stage="2"] .node-status-dot').evaluate(el=>getComputedStyle(el).backgroundColor),color);
  }
  await page.evaluate(()=>{task.jobs=[{stage:2,status:'failed',revision:task.revision-1}];render()});
  assert.equal(await page.locator('.step[data-stage="2"]').getAttribute('title'),'待人工确认','obsolete failure is ignored after reset');
  await page.evaluate(()=>{task.jobs=[];render()});
  const bridge=page.locator('[data-continuation-source="testing:2"] [role=switch]');assert.equal(await bridge.getAttribute('aria-disabled'),'false');
  await bridge.click();await page.locator('[data-continuation-source="testing:2"] [role=switch][aria-checked=true]').waitFor();
  await page.locator('#filing-select-1').uncheck();await page.locator('#filing-reason-1').fill('本次范围外，保留原因');
  await page.getByRole('button',{name:'保存提单范围',exact:true}).click();
  await page.waitForFunction(()=>task.artifacts['2'].filing_scope?.excluded?.f2==='本次范围外，保留原因');
  assert.equal((await api(root+'/tasks/'+config.tasks[0])).stage,2,'saving scope does not approve');
  await page.getByRole('button',{name:'确认当前节点',exact:true}).click();
  await page.getByText('提单工作区',{exact:true}).waitFor();
  await page.waitForFunction(()=>task.artifacts['4']?.drafts?.length===1,{},{timeout:12000});
  const task=await api(root+'/tasks/'+config.tasks[0]);assert.equal(task.stage,4);assert.equal(task.artifacts['4'].drafts[0].root_cause_id,'f1');assert.equal(task.artifacts['4'].publication_complete,false);
  assert.equal((await api(root+'/tasks/'+config.tasks[0]+'/publication-ledger')).records.length,0,'no remote publication prepared or sent');
  await page.goto(url(config.tasks[1]));await page.locator('.workflow-config-notice').waitFor();
  assert.match(await page.locator('.workflow-config-notice').innerText(),/筛选已并入归因/);
  assert.equal(await page.locator('.step[data-node-state=current]').getAttribute('data-stage'),'2');
  await page.getByRole('button',{name:'保存提单范围',exact:true}).click();
  await page.waitForFunction(()=>task.stage===2&&!!task.artifacts['2'].filing_scope);
  await page.getByRole('button',{name:'确认当前节点',exact:true}).click();await page.getByText('提单工作区',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS: blue selection, independent status dots, readable text in three themes, actionable 2→4 bridge, explicit exclusions, automatic internal draft only, old stage-3 recovery. Isolated fixtures; no external writes.');
 }catch(error){console.error(output.slice(-2000));throw error}
 finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true})}
})().catch(e=>{console.error(e);process.exitCode=1});
