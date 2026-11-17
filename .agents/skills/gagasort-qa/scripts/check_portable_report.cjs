#!/usr/bin/env node
// Usage: NODE_PATH=<modules> node check_portable_report.cjs <viewer.html> <batch-dir> [chrome] [receipt.json]
// Reads a real batch; malformed test copies and downloads live only in a temporary directory.
'use strict';
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const crypto=require('node:crypto');
async function snapshot(viewer,bundle){
 const files={viewer:crypto.createHash('sha256').update(await fs.readFile(viewer)).digest('hex')};
 async function walk(dir,prefix){for(const entry of (await fs.readdir(dir,{withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name))){
  if(entry.isSymbolicLink())throw Error('报告内不允许软链接');const file=path.join(dir,entry.name),key=prefix+'/'+entry.name;
  if(entry.isDirectory())await walk(file,key);else files[key]=crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
 }}
 await walk(bundle,'bundle');return files;
}
let chromium;try{({chromium}=require('playwright'))}catch{({chromium}=require('playwright-core'))}
async function main(){
 const [viewer,bundle,chrome,receipt]=process.argv.slice(2);if(!viewer||!bundle)throw Error('需要查看器 HTML 和报告目录');
 if(receipt)await fs.rm(receipt,{force:true});
 const before=await snapshot(viewer,bundle);
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'portable-report-check-'));
 const md=await fs.readFile(path.join(bundle,'report.md'),'utf8'),p=JSON.parse(md.match(/^```gagasort-report-v1\n([\s\S]*?)\n```/m)[1]);
 const browser=await chromium.launch({headless:true,...(chrome?{executablePath:chrome}:{})});
 const checks=[],errors=[],network=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},acceptDownloads:true});
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
  page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url())});
  await page.goto(pathToFileURL(path.resolve(viewer)).href);
  const f=page.frameLocator('#report');
  async function select(dir){await page.locator('#folder').setInputFiles(dir);await page.waitForFunction(()=>document.getElementById('message').className!=='pending')}
  async function tab(name){await f.locator(`a[href="#${name}"]`).first().click()}
  assert(await page.locator('#home').isVisible());checks.push('初始空态');
  assert.equal(await page.locator('#viewer-directory').inputValue(),path.dirname(path.resolve(viewer))+'/');
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.copiedDirectory=text}}}));
  await page.locator('#copy-directory').click();
  assert.equal(await page.evaluate(()=>window.copiedDirectory),path.dirname(path.resolve(viewer))+'/');
  assert((await page.locator('#path-status').innerText()).includes('已复制'));
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('denied')}}}));
  await page.locator('#copy-directory').click();
  assert((await page.locator('#path-status').innerText()).includes('路径已选中'));
  assert.equal(await page.locator('#viewer-directory').evaluate(e=>e.selectionEnd-e.selectionStart),(await page.locator('#viewer-directory').inputValue()).length);
  assert.equal(await page.evaluate(()=>viewerDirectory('file:///C:/Reports/view.html')),'C:/Reports/');
  assert.equal(await page.evaluate(()=>viewerDirectory('https://example.com/view.html')),'');
  checks.push('所在目录与移动后路径解析、复制成功/失败回退（剪贴板模拟，不代表系统选择器定位）');
  await select(bundle);await f.locator('#bug-table-head th').first().waitFor();
  assert.equal(await page.locator('#message').getAttribute('class'),'');
  assert.equal(await f.locator('#bug-table-head th').count(),p.csv.headers.length);
  assert.deepEqual(await f.locator('#bug-table-head th').allTextContents(),p.csv.headers);
  assert.equal(await f.locator('#bug-table-body tr').count(),p.csv.ids.length);
  checks.push('CSV 全列表头、空列及 Bug 行数');
  assert(await f.locator('#bug-update-table').isEnabled());assert(await f.locator('#bug-submit').isDisabled());
  checks.push('更新表格可点击，读取前禁止提单；加载不发网络请求');
  for(const [route,label]of Object.entries({play:'玩法',levels:'关卡',systems:'系统',config:'配置',tracking:'埋点'})){
   await tab(route);assert((await f.locator('#category-heading').innerText()).includes(label));
  }checks.push('五模块页签');
  await tab('play');
  const feature=f.locator('a[href^="#feature-"]').first();await feature.click();
  assert(await f.locator('#detail').isVisible());assert((await f.locator('#detail-body').innerText()).length>100);
  await f.locator('#close-detail').click();checks.push('功能明细');
  await tab('overview');
  for(const row of p.view.bug_register.rows){
   const first=row.id,routes={玩法:'play',关卡:'levels',系统:'systems',配置:'config',埋点:'tracking'};
   await tab(routes[row.detail.category]||'play');
   await f.locator(`a[href="#issue-${first}"]:visible`).first().click();
   const content=await f.locator('#detail-body').innerText();
   assert(content.includes(row.detail.cause),'问题详情遗漏归因：'+first);
   for(const step of row.detail.steps)assert(content.includes(step),'问题详情遗漏步骤：'+first);
   const evidence=f.locator('#detail-body a[data-file]').first();
   if(await evidence.count()){
    await evidence.click();assert((await f.locator('#evidence-body').innerText()).length>0);
    assert((await f.locator('#evidence-hash').innerText()).includes('SHA256'));
    assert(await f.locator('#download-evidence').isHidden());await f.locator('#close-evidence').click();
   }
   await f.locator('#close-detail').click();
  }
  checks.push(p.csv.ids.length?'全部 Bug 完整步骤、归因及适用关键摘录':'零 Bug 真实空状态');
  await tab('levels');
  const gallery=f.locator('a[href="#level-gallery-wall"]');
  if(await gallery.count()){
   await gallery.first().click();
   const img=f.locator('#level-visual-risks details[open] img').first();await img.scrollIntoViewIfNeeded();
   await img.evaluate(i=>i.decode());assert(await img.evaluate(i=>i.naturalWidth>0));
   assert(!await f.locator('#evidence').isVisible());checks.push('风险入口直接跳图，图片实际解码');
  }
  await tab('overview');await f.locator('#bug-search').fill('不存在的搜索词-qa');
  assert.equal(await f.locator('#bug-table-body tr').count(),0);
  const downloaded=page.waitForEvent('download');await f.locator('#bug-export').click();const download=await downloaded;
  const out=path.join(temp,'download.csv');await download.saveAs(out);
  const downloadedRaw=await fs.readFile(out,'utf8'),original=await fs.readFile(path.join(bundle,'bugs.csv'),'utf8');
  // Browser exports may normalize CRLF to LF. Compare parsed cells including embedded line breaks.
  // parseCsv lives in the outer viewer and is the strict reader used when loading.
  const cells=await page.evaluate(raw=>parseCsv(raw),downloadedRaw),expected=await page.evaluate(raw=>parseCsv(raw),original);
  assert.deepEqual(cells,expected);checks.push('筛选后 CSV 导出仍保留全量字段和内容');
  for(const [name,mutate,pattern]of [
   ['missing-csv',async dir=>fs.unlink(path.join(dir,'bugs.csv')),'必须同时包含'],
   ['changed-csv',async dir=>fs.appendFile(path.join(dir,'bugs.csv'),'changed'),'不属于同一份报告'],
   ['missing-image',async dir=>{if(p.images.length)await fs.unlink(path.join(dir,p.images[0].path))},'缺少关卡图片'],
   ['broken-md',async dir=>fs.writeFile(path.join(dir,'report.md'),'# broken'),'数据区块']
  ]){
   if(name==='missing-image'&&!p.images.length)continue;
   const dir=path.join(temp,name);await fs.cp(bundle,dir,{recursive:true});await mutate(dir);await select(dir);
   assert((await page.locator('#message').innerText()).includes(pattern));
   assert(await page.locator('#report').isVisible());assert.equal(await f.locator('#bug-table-head th').count(),p.csv.headers.length);
  }checks.push('缺 CSV、混入改写 CSV、缺图片、坏 MD 均阻断且保留上一报告');
  const second=path.join(temp,'second-batch');await fs.cp(bundle,second,{recursive:true});await select(second);
  await page.waitForFunction(()=>document.getElementById('batch').textContent.includes('second-batch'));
  await f.locator('#bug-table-head th').first().waitFor();assert.equal(await f.locator('#bug-table-body tr').count(),p.csv.ids.length);
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  assert(await page.frames().find(x=>x.parentFrame()).evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.locator('#clear').click();assert(await page.locator('#home').isVisible());assert(await page.locator('#report').isHidden());
  await select(bundle);await f.locator('#bug-table-head th').first().waitFor();checks.push('切换、关闭、重新加载与窄屏');
  assert.deepEqual(errors,[]);assert.deepEqual(network,[]);checks.push('无 JS/控制台错误，无网络请求');
  // Simulated local bridge: validates the actual UI without touching a Feishu table.
  let mode='unauthorized',writes=0,fieldReads=0;
  const remoteHeaders=['标题','复现步骤','期望描述','实际结果','归因','版本号','未知空列'];
  const fulfill=(route,value)=>route.fulfill({status:200,headers:{'Access-Control-Allow-Origin':'*'},contentType:'application/json',body:JSON.stringify(value)});
  await page.route('http://127.0.0.1:17321/**',async route=>{
   const req=route.request(),endpoint=new URL(req.url()).pathname;
   if(req.method()==='OPTIONS')return route.fulfill({status:204,headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'Content-Type','Access-Control-Allow-Methods':'GET,POST,OPTIONS'}});
   if(mode==='offline')return route.abort();
   if(endpoint==='/auth/status')return fulfill(route,{ok:true,status:mode==='unauthorized'?'unauthorized':'authorized'});
   if(endpoint==='/base/fields'){fieldReads++;return fulfill(route,mode==='invalid'?{ok:true,headers:['重复','重复'],fields:[]}:{ok:true,headers:remoteHeaders,fields:remoteHeaders.map(name=>({name,writable:name!=='未知空列'}))})}
   if(endpoint==='/base/records'){writes++;const body=req.postDataJSON();assert.equal(body.records.length,p.csv.ids.length);assert.deepEqual(body.headers,remoteHeaders);for(const record of body.records){assert(record['标题']);assert(record['复现步骤']);assert(record['归因']);assert.equal(record['版本号'],'Codex');assert(!('未知空列'in record))}return fulfill(route,{ok:true,submitted:p.csv.ids.length,total:p.csv.ids.length})}
   throw Error('意外桥接请求：'+endpoint);
  });
  await tab('overview');await f.locator('#bug-update-table').click();assert(await f.locator('#table-sync').isVisible());
  const url='https://example.feishu.cn/base/test?table=tbl_test';
  await f.locator('#table-url').fill(url);await f.locator('#read-table').click();
  await f.locator('#table-sync-status.error').waitFor();assert.equal(fieldReads,0);assert.equal(writes,0);
  const errorCount=errors.length;mode='offline';await f.locator('#read-table').click();await f.locator('#table-sync-status.error').waitFor();assert((await f.locator('#table-sync-status').innerText()).includes('连接不可用'));assert(await f.locator('#read-table').isEnabled());for(const error of errors.splice(errorCount))assert(error.includes('net::ERR_FAILED'),error);
  mode='invalid';await f.locator('#read-table').click();await f.locator('#table-sync-status.error').waitFor();assert(await f.locator('#confirm-bug-submit').isDisabled());
  mode='authorized';await f.locator('#read-table').click();await f.locator('#table-sync-status.success').waitFor();
  assert.deepEqual(await f.locator('#bug-table-head th').allTextContents(),remoteHeaders);assert.equal(writes,0);
  assert.equal(await f.locator('#table-preview-body tr').count(),p.csv.ids.length);
  const first=p.view.bug_register.rows[0];
  if(first){const cells=await f.locator('#table-preview-body tr').first().locator('td').allTextContents();assert(cells[1].includes(first.detail.steps[0]));assert.equal(cells[4],first.detail.cause);assert.equal(cells[6],'—')}
  await f.locator('#table-url').fill(url+'&view=changed');assert(await f.locator('#confirm-bug-submit').isDisabled());assert.deepEqual(await f.locator('#bug-table-head th').allTextContents(),p.csv.headers);
  await f.locator('#read-table').click();await f.locator('#table-sync-status.success').waitFor();await f.locator('#cancel-table-sync').click();
  const remoteDownload=page.waitForEvent('download');await f.locator('#bug-export').click();const remoteFile=await remoteDownload;await remoteFile.saveAs(path.join(temp,'remote.csv'));
  const remoteCells=await page.evaluate(raw=>parseCsv(raw),await fs.readFile(path.join(temp,'remote.csv'),'utf8'));assert.deepEqual(remoteCells[0],remoteHeaders);assert.equal(remoteCells.length,p.csv.ids.length+1);
  checks.push('模拟桥接：未登录、断连及错误表头明确提示；读取映射、空列、URL失效和远程列CSV导出');
  if(first){await f.locator('#bug-submit').click();await f.locator('#confirm-bug-submit').click();await f.locator('#table-sync-status.success').waitFor();assert.equal(writes,1);assert(await f.locator('#confirm-bug-submit').isDisabled());checks.push('模拟桥接：手动确认才提交全部Bug，成功锁定防重复（未真实提单）')}
  assert.deepEqual(errors,[]);
  const after=await snapshot(viewer,bundle);assert.deepEqual(after,before,'交互期间报告文件变化');
  const result={status:'passed',passed:true,format:'gagasort-report-v1',files:before,bugs:p.csv.ids.length,columns:p.csv.headers.length,features:p.view.features.length,images:p.images.length,checks};
  if(receipt)await fs.writeFile(receipt,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify(result,null,2));
 }finally{await browser.close();await fs.rm(temp,{recursive:true,force:true})}
}
main().catch(error=>{console.error(error);process.exitCode=1});
