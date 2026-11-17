// Real HTTP, UI, queue, validators and source reads. Model/Git are explicit isolated fixtures.
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawn}=require('node:child_process');const {chromium}=require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'studioflow-qa-auto-'));
 const bootstrap=`import sys,json
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from server.store import Store
from server.app import create_server
from server.codex_model import CodexModel
from server.requirements import validate_cases
root=Path(sys.argv[1]);source=root/'GagaSort/Assets/Reward.cs';source.parent.mkdir(parents=True);source.write_text('class Reward { void Claim() { coins += 10; } }\\n')
store=Store(root/'db.sqlite');studio=store.studios()[0]['id'];project=store.create_project('隔离全自动')['id'];task=store.create_task(project,'浏览器自动静态链路');task=store.import_requirement(project,task['id'],'req','奖励只能领取一次');req=task['requirements'][0]
output={'points':[{'id':'P','title':'重复领取','requirement_id':req['id'],'quote':req['content']}],'cases':[{'id':'C','title':'重复领取','point_ids':['P'],'preconditions':['已领取'],'steps':[{'action':'再次领取','expected':'金币不增加'}]}],'gaps':[],'ambiguities':['待确认远端规则 '+str(i) for i in range(350)]}
task=store.record_artifact(project,task['id'],0,validate_cases(output,task['requirements']))
binding={'repository':str(root),'project_root':str(root/'GagaSort'),'branch':'master','commit':'sha-new','code_fingerprint':'hash-new','execution_suite':'static'}
task=store.bind_execution(project,task['id'],{**binding,'commit':'sha-old','code_fingerprint':'hash-old'},task['revision'])
def transport(self,prompt):
 if '"failures":' in prompt:return {'suggestions':[{'id':'R','title':'缺少领取幂等守卫','reasoning':'已领取后同一入口仍加金币','result_ids':['C'],'evidence':[{'file':'Assets/Reward.cs','line':1,'quote':source.read_text()}]}]}
 if '"sources": {}' in prompt:return {'read':['Assets/Reward.cs']}
 return {'assertions':[{'step_index':0,'status':'failed','reasoning':'再次进入Claim仍增加金币','precondition_analysis':'已领取仍可重复调用入口','counterexample_search':'检查重复调用守卫','call_chain':[{'file':'Assets/Reward.cs','line':1,'quote':source.read_text()}],'counterexample':{'preconditions':['已领取'],'steps':['再次调用Claim'],'expected':'金币不增加','actual':'金币增加10','reachability':'缺少重复领取守卫'}}]}
with ExitStack() as stack:
 stack.enter_context(patch('server.gagasort.inspect_project',return_value=binding));stack.enter_context(patch('server.attribution.inspect_project',return_value=binding));stack.enter_context(patch.object(CodexModel,'request_json',transport))
 server=create_server('127.0.0.1',0,str(root/'db.sqlite'),local_development=True)
 print(json.dumps({'port':server.server_port,'studio':studio,'project':project,'task':task['id']}),flush=True)
 server.serve_forever()
`;
 const server=spawn('python3',['-u','-c',bootstrap,folder],{cwd:path.resolve(__dirname,'../..'),stdio:['ignore','pipe','pipe']});let output='',browser;
 server.stdout.on('data',d=>output+=d);server.stderr.on('data',d=>output+=d);
 try{
  const deadline=Date.now()+15000;while(!output.split('\n').some(x=>x.startsWith('{'))){if(Date.now()>deadline||server.exitCode!==null)throw Error(output);await new Promise(r=>setTimeout(r,50));}
  const c=JSON.parse(output.split('\n').find(x=>x.startsWith('{'))),base='http://127.0.0.1:'+c.port;
  browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/testing.html?'+new URLSearchParams({studio:c.studio,project:c.project,task:c.task}));
  await page.locator('[data-qa-automation]').waitFor({timeout:15000});
  const review=page.locator('details[data-section="review"]');await review.locator(':scope>summary').click();
  await review.locator('input[onchange*="review-select"]').check();await page.locator('#review-batch-action').selectOption('accept_scope_gap');await page.locator('#review-batch-reason').fill('保留风险，先静态检测');
  await page.getByRole('button',{name:'应用到所选',exact:true}).click();await page.locator('#case-decomposition-top').check();
  assert.equal(await page.locator('#case-decomposition').isChecked(),true);
  const top=page.locator('[data-case-review-save]').first();const riskTop=await review.locator('.review-row').first().boundingBox();assert((await top.boundingBox()).y<riskTop.y);
  await top.click();await page.waitForFunction(()=>task.artifacts['0'].user_review?.ready_for_execution);
  assert.equal(await page.evaluate(()=>task.stage),0);
  await page.getByRole('button',{name:'开启全自动',exact:true}).click();
  // Reload during execution: backend continues even without a persistent browser loop.
  await page.reload();try{await page.waitForFunction(()=>task?.automation?.state==='completed',{},{timeout:30000})}catch(e){console.error('CHAIN',await page.evaluate(()=>({stage:task?.stage,automation:task?.automation,jobs:task?.jobs.map(j=>({kind:j.kind,status:j.status,error:j.error})),attribution:task?.attribution})),errors,output);throw e;}
  const result=await page.evaluate(()=>({stage:task.stage,status:task.status,state:task.automation.state,cases:task.artifacts['0'].cases.length,risks:task.artifacts['0'].user_review.decisions.length,drafts:task.artifacts['4'].drafts.length,origin:task.artifacts['4'].drafts[0].reproduction_provenance,jobCount:task.jobs.length,commit:task.binding.commit,publication:task.artifacts['4'].publication_complete}));
  assert.equal(result.stage,4);assert.equal(result.status,'waiting_user');assert.equal(result.risks,350);assert.equal(result.drafts,1);assert.equal(result.origin,'static_inference');assert.equal(result.commit,'sha-new');assert.equal(result.jobCount,2);assert.equal(result.publication,false);assert.deepEqual(errors,[]);
  const shots=path.resolve(__dirname,'../../data/visual-review');fs.mkdirSync(shots,{recursive:true});await page.screenshot({path:path.join(shots,'qa-automation-completed.png')});
  console.log('PASS: 350-risk top save, synchronized confirmation, backend automatic static execution and attribution, stale baseline refresh, one internal draft, reload, no external writes. '+JSON.stringify(result));
 }finally{if(browser)await browser.close();server.kill('SIGTERM');await new Promise(r=>server.exitCode!==null?r():server.once('exit',r));fs.rmSync(folder,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
