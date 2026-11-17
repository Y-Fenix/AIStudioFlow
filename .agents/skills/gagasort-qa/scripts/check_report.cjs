/* Browser regression for the fixed report. Does not execute the game. */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const {pathToFileURL} = require('url');

async function main() {
  const args = process.argv.slice(2);
  function option(name, required = false) {
    const i = args.indexOf(name);
    if (required && (i < 0 || !args[i + 1])) throw Error('Missing ' + name);
    return i < 0 ? null : args[i + 1];
  }
  const report = path.resolve(option('--report', true));
  const out = path.resolve(option('--output-dir', true));
  fs.mkdirSync(out, {recursive: true});
  const result = {status: 'running', checks: [], errors: [], skipped: [],
    report_sha256: crypto.createHash('sha256').update(fs.readFileSync(report)).digest('hex'),
    scope: 'HTML交互校验，与游戏运行无关'};
  const receipt = path.join(out, 'html-interaction-check.json');
  const save = () => fs.writeFileSync(receipt, JSON.stringify(result, null, 2) + '\n');
  save();
  let browser;
  function ok(value, label) {
    result.checks.push({label, passed: Boolean(value)});
    if (!value) throw Error(label);
  }
  try {
    let chromium;
    try { ({chromium} = require('playwright')); }
    catch (_) { ({chromium} = require('playwright-core')); }
    const candidates = [option('--browser'), process.env.GAGASORT_QA_BROWSER,
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
      '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
      process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, 'Google/Chrome/Application/chrome.exe')];
    const executablePath = candidates.find(p => p && fs.existsSync(p));
    browser = await chromium.launch({headless: true, ...(executablePath ? {executablePath} : {})});
    result.browser = executablePath || 'Playwright bundled Chromium';
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: true});
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    const url = pathToFileURL(report).href;
    async function go(hash) {
      await page.goto(url + '#' + hash);
      await page.waitForSelector('#headline', {state: 'attached'});
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    }
    await go('overview');
    ok(await page.locator('#overview-panel').isVisible(), '默认总览可见');
    ok(!await page.locator('#module-panel').isVisible(), '总览不混入模块明细');
    await page.screenshot({path: path.join(out, 'report-overview.png')});
    const payload = await page.evaluate(() => {const data=JSON.parse(document.getElementById('payload').textContent);data.assets=Object.fromEntries(Object.entries(data.assets).map(([k,v])=>[k,{mime:v.mime,sha256:v.sha256}]));return data;});
    const bugHeaders = JSON.parse(fs.readFileSync(path.join(__dirname, '../assets/bug-columns.json'), 'utf8')).fields.map(f => f.name);
    const bugRows = payload.bug_register.rows;
    ok(bugRows.every(row=>row.fields['版本号']==='Codex'),'Bug列表、CSV及提单共用固定版本号Codex');
    ok(await page.locator('#bug-register').isVisible(), '总览完整Bug列表可见');
    ok(await page.locator('#bug-table th:visible').count() === 23, '默认显示23列，空列不隐藏');
    ok(JSON.stringify(await page.locator('#bug-table th').allTextContents()) === JSON.stringify(bugHeaders), '表头与固化模板名称及顺序一致');
    ok(bugRows.length === new Set(payload.issues.filter(i => i.confirmed).map(i => i.id)).size,
      'Bug列表覆盖全部已确认问题，不混入风险');
    for (const row of bugRows) {
      const tr = page.locator('#bug-table-body tr').nth(bugRows.indexOf(row));
      ok(await tr.getAttribute('data-bug-id') === row.id && await tr.locator('td:visible').count() === 23, row.id + '完整23格，含空值');
      const description = await tr.locator('td').first().innerText();
      ok(description.includes(row.detail.cause) && description.includes(row.detail.actual)
        && row.detail.steps.every(s => description.includes(s)), row.id + '列表直接显示步骤、表现和归因');
    }
    ok(await page.locator('#bug-update-table').count() === 1 && await page.locator('#bug-submit').count() === 1,
      'Bug列表包含更新表格和提单按钮');
    ok(await page.locator('#bug-submit').isDisabled(), '未同步远程表头前提单保持禁用');
    await page.locator('#bug-update-table').click();
    ok(await page.locator('#table-sync').evaluate(e => e.open), '更新表格打开URL输入窗口');
    ok(await page.locator('#table-sync-title').innerText() === '新建 Bug 单', '弹窗使用新建Bug单流程');
    ok(await page.locator('#table-auth-code, #start-feishu-auth, #feishu-qr').count() === 0,
      '弹窗不再混入Bearer、二维码和备用授权');
    if (!payload.feishu_authorized) ok(await page.locator('#read-table').isDisabled(), '本轮未授权时禁止读取飞书');
    await page.locator('#cancel-table-sync').click();
    // Exercise the write UI against deterministic mock endpoints, never the real bridge.
    const ticketTemplate = fs.readFileSync(path.join(__dirname, '../assets/report-template.html'), 'utf8');
    async function ticketPage(authorized, failure = false) {
      const p = await context.newPage();
      p.on('pageerror', error => result.errors.push(String(error)));
      await p.addInitScript(() => {});
      const model = {...payload, assets: {}, feishu_authorized: authorized};
      await p.setContent(ticketTemplate.replace('__PAYLOAD__', JSON.stringify(model).replace(/</g, '\\u003c')));
      await p.evaluate(failure => {
        window.__qaCalls=[];window.__qaFailRead=false;
        const headers=['归因','标题','复现步骤','期望结果','实际结果','负责人','空列','需求模块'];
        window.fetch=async (input,init={})=>{
          const url=String(input);window.__qaCalls.push({url, body:init.body?JSON.parse(init.body):null});
          if(url.endsWith('/auth/status'))return new Response(JSON.stringify({ok:true,status:'authorized'}));
          if(url.endsWith('/base/fields'))return new Response(JSON.stringify(window.__qaFailRead?{ok:false,error:'测试读取失败'}:{ok:true,headers:window.__qaHeaders||headers,fields:(window.__qaHeaders||headers).map(name=>({name,type:name==='负责人'?'user':'text',writable:name!=='负责人'}))}));
          if(url.endsWith('/base/records')){await new Promise(r=>setTimeout(r,100));return new Response(JSON.stringify(failure?{ok:false,error:'模拟提交未确认'}:{ok:true,submitted:JSON.parse(init.body).records.length,total:JSON.parse(init.body).records.length}));}
          throw Error('意外测试请求：'+url);
        };
      },failure);
      await p.locator('#bug-update-table').click();return p;
    }
    const noAuth=await ticketPage(false);
    ok(await noAuth.locator('#read-table').isDisabled() && await noAuth.locator('#confirm-bug-submit').isDisabled(), '未授权报告即使本机已登录也不能读取或写入');
    ok(await noAuth.evaluate(()=>window.__qaCalls.length===0),'打开弹窗不发起飞书请求');
    await noAuth.close();
    if (bugRows.length) {
      const tp=await ticketPage(true);
      const target='https://example.feishu.cn/base/mock?table=tbl_mock&view=vew_mock';
      await tp.locator('#table-url').fill(target);await tp.locator('#read-table').click();
      await tp.waitForFunction(()=>document.querySelector('#table-sync-status').textContent.includes('读取成功'));
      const expectedHeaders=['归因','标题','复现步骤','期望结果','实际结果','负责人','空列','需求模块'];
      ok(JSON.stringify(await tp.locator('#bug-table th').allTextContents())===JSON.stringify(expectedHeaders),'目标列名与顺序完整保留，含未知空列');
      const cells=await tp.locator('#table-preview-body tr').first().locator('td').allTextContents();
      ok(cells[0]===bugRows[0].detail.cause && cells[4]===bugRows[0].detail.actual && cells[3]===bugRows[0].fields['期望描述'], '归因、实际与预期分别映射到对应列');
      ok(cells[1].includes(bugRows[0].detail.title)&&bugRows[0].detail.steps.every(x=>cells[2].includes(x)), '标题与完整复现步骤同步到预览');
      ok(cells[5]==='—'&&cells[6]==='—'&&cells[7]===(bugRows[0].fields['功能模块']||'—'), '未知列和无来源的人员、模块留空');
      ok(await tp.locator('#table-preview-body tr').count()===bugRows.length,'预览包含全部问题，不只显示样例');
      ok(await tp.evaluate(()=>!window.__qaCalls.some(c=>c.url.endsWith('/base/records'))),'读取和预览不创建记录');
      const remoteCsvPending=tp.waitForEvent('download');await tp.locator('#cancel-table-sync').click();await tp.locator('#bug-export').click();
      const remoteCsv=fs.readFileSync(await (await remoteCsvPending).path(),'utf8');
      ok(remoteCsv.startsWith('\ufeff'+expectedHeaders.map(x=>'"'+x+'"').join(',')),'远端列顺序同步到CSV，空列也导出');
      await tp.locator('#bug-submit').click();
      ok(await tp.locator('#table-sync').evaluate(e=>e.open),'列表提单按钮先打开内容预览');
      await tp.locator('#table-url').fill(target+'&changed=1');
      ok(await tp.locator('#confirm-bug-submit').isDisabled(),'修改URL立即清除旧表可提单状态');
      await tp.evaluate(()=>window.__qaFailRead=true);await tp.locator('#read-table').click();
      await tp.waitForFunction(()=>document.querySelector('#table-sync-status').textContent.includes('测试读取失败'));
      ok(await tp.locator('#confirm-bug-submit').isDisabled()&&await tp.locator('#table-preview').isHidden(),'读取失败不保留旧目标或过期预览');
      await tp.evaluate(()=>window.__qaFailRead=false);await tp.locator('#table-url').fill(target);await tp.locator('#read-table').click();
      await tp.waitForFunction(()=>!document.querySelector('#confirm-bug-submit').disabled);
      const fullPreview=await ticketPage(true);
      await fullPreview.evaluate(headers=>window.__qaHeaders=headers,bugHeaders);
      await fullPreview.locator('#table-url').fill(target);await fullPreview.locator('#read-table').click();
      await fullPreview.waitForFunction(()=>!document.querySelector('#confirm-bug-submit').disabled);
      for(const viewport of [{width:1440,height:900},{width:1920,height:900}]){
        await fullPreview.setViewportSize(viewport);
        const geometry=await fullPreview.evaluate(()=>{
          const dialog=document.querySelector('#table-sync'),preview=document.querySelector('.sync-preview');
          const row=document.querySelector('#table-preview-body tr').getBoundingClientRect(),area=preview.getBoundingClientRect();
          const actions=document.querySelector('.sync-actions').getBoundingClientRect();
          return {rowBottom:row.bottom,areaBottom:area.bottom,availableBottom:area.bottom-(preview.offsetHeight-preview.clientHeight),actionsBottom:actions.bottom,outerOverflow:dialog.scrollWidth>dialog.clientWidth,font:parseFloat(getComputedStyle(preview.querySelector('table')).fontSize)};
        });
        await fullPreview.screenshot({path:path.join(out,'report-bug-submit-full-row.png')});
        ok(geometry.rowBottom<=geometry.availableBottom,viewport.width+'px预览完整展示首条Bug，无需纵向滚动 '+JSON.stringify(geometry));
        ok(geometry.actionsBottom<=viewport.height&&!geometry.outerOverflow,viewport.width+'px提单按钮可见，弹窗不向外横溢');
        ok(geometry.font>=11,'预览字号不小于11px');
      }
      await fullPreview.screenshot({path:path.join(out,'report-bug-submit-full-row.png')});
      await fullPreview.setViewportSize({width:390,height:844});
      ok(await fullPreview.evaluate(()=>{const d=document.querySelector('#table-sync');return d.scrollWidth<=d.clientWidth&&document.querySelector('.sync-actions').getBoundingClientRect().bottom<=innerHeight}),'窄屏仅表格内横滚，提单操作保持可见');
      ok(await fullPreview.locator('#table-preview-head th').count()===23,'加宽预览保留全部23列');
      await fullPreview.close();
      await tp.screenshot({path:path.join(out,'report-bug-submit-preview.png')});
      await tp.locator('#confirm-bug-submit').evaluate(b=>{b.click();b.click();});
      await tp.waitForFunction(()=>document.querySelector('#table-sync-status').textContent.includes('已提交'));
      const writes=await tp.evaluate(()=>window.__qaCalls.filter(c=>c.url.endsWith('/base/records')));
      ok(writes.length===1&&writes[0].body.records.length===bugRows.length,'连续点击只提交一次全部已确认问题');
      ok(JSON.stringify(writes[0].body.headers)===JSON.stringify(expectedHeaders)&&!('负责人' in writes[0].body.records[0]),'请求绑定已预览表头并过滤不可写字段');
      ok(await tp.locator('#confirm-bug-submit').isDisabled()&&await tp.locator('#read-table').isDisabled(),'成功后锁定本页，避免重复提单');
      await tp.close();
      const failed=await ticketPage(true,true);await failed.locator('#table-url').fill(target);await failed.locator('#read-table').click();
      await failed.waitForFunction(()=>!document.querySelector('#confirm-bug-submit').disabled);await failed.locator('#confirm-bug-submit').click();
      await failed.waitForFunction(()=>document.querySelector('#table-sync-status').textContent.includes('提交未确认'));
      ok(await failed.locator('#confirm-bug-submit').isDisabled()&&(await failed.locator('#table-sync-status').innerText()).includes('勿重复提交'),'结果不明时不报成功、不自动重试');
      ok(await failed.evaluate(()=>window.__qaCalls.filter(c=>c.url.endsWith('/base/records')).length===1),'失败无自动重发');await failed.close();
    }
    await page.locator('#bug-search').fill('__qa_no_matching_bug__');
    ok(await page.locator('#bug-table th:visible').count() === 23 && await page.locator('#bug-empty-result').isVisible(),
      '空结果仍保留23列表头');
    // Deliberately download while filtered to no matches: export always means all rows.
    const csvPending = page.waitForEvent('download');
    await page.locator('#bug-export').click();
    const csvDownload = await csvPending;
    const csvBytes = fs.readFileSync(await csvDownload.path());
    ok(csvBytes.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf])) && csvBytes.equals(Buffer.from(payload.bug_register.csv, 'utf8')),
      '筛选后导出全部23列，中文BOM及多行内容保持原字节');
    const savedCSV = path.join(path.dirname(report), 'bugs.csv');
    if (fs.existsSync(savedCSV)) ok(csvBytes.equals(fs.readFileSync(savedCSV)), '页面导出与配套bugs.csv完全一致');
    await page.locator('#bug-search').fill('');
    if (bugRows.length) {
      await page.locator('#bug-module').selectOption(bugRows[0].detail.category);
      ok(await page.locator('#bug-table-body tr').count() === bugRows.filter(r => r.detail.category === bugRows[0].detail.category).length,
        'Bug列表按分类筛选且不丢记录');
      await page.locator('#bug-module').selectOption('');
    }
    await page.locator('a.stat[href="#bug-register"]').click();
    ok(!await page.locator('#detail').evaluate(e => e.open) && new URL(page.url()).hash === '#bug-register',
      '总览问题数直接跳列表，不开证据弹窗');
    await page.reload();
    await page.waitForSelector('#bug-register');
    ok(!await page.locator('#overview-panel').getAttribute('hidden') && await page.locator('#bug-register').isVisible(), '刷新保持Bug列表定位');
    for (const [key, category] of Object.entries({play: '玩法', levels: '关卡', systems: '系统', config: '配置', tracking: '埋点'})) {
      await go(key);
      ok(await page.locator('#module-panel').isVisible(), category + '模块可见');
      ok(!await page.locator('#overview-panel').isVisible(), category + '不重复总览');
      ok(!await page.locator('#bug-register').isVisible(), category + '不重复总览Bug列表');
      ok(await page.locator('#module-summary .module-metric').count() === 4, category + '四项可点击指标');
      await page.locator('#search').fill('__qa_no_matching_feature__');
      ok(await page.locator('.feature-row').count() === 0, category + '搜索无匹配显示空结果');
      await page.locator('#search').fill('');
      for (const filter of ['clear', 'incomplete']) {
        await page.locator('a[href="#module-' + key + '-' + filter + '"]').click();
        await page.waitForFunction(hash => location.hash === hash, '#module-' + key + '-' + filter);
        ok(!await page.locator('#overview-panel').isVisible(), category + '筛选保持模块');
      }
      await page.reload();
      await page.waitForSelector('#headline', {state: 'attached'});
      ok(new URL(page.url()).hash === '#module-' + key + '-incomplete', category + '刷新保留筛选');
    }
    await go('systems');
    ok((await page.locator('body').innerText()).includes('多语言'), '系统包含多语言');
    await page.screenshot({path: path.join(out, 'report-systems.png')});
    for (const tone of ['green', 'amber', 'red']) {
      const feature = payload.features.find(f => f.tone === tone);
      if (!feature) { result.skipped.push('本轮无 ' + tone + ' 功能，不造示例'); continue; }
      await go('feature-' + feature.id);
      ok(await page.locator('#detail').evaluate(e => e.open), tone + '功能详情可打开');
      ok(await page.locator('#detail .conclusion.' + tone).count() > 0, tone + '状态遵循证据');
    }
    for (const issue of payload.issues) {
      await go('issue-' + issue.id);
      ok(await page.locator('#detail').evaluate(e => e.open), issue.id + '可打开');
      const text = await page.locator('#detail').innerText();
      ok(/步骤|核查/.test(text) && /归因|原因|为什么会这样/.test(text), issue.id + '可见步骤与归因');
    }
    if (!payload.issues.length) result.skipped.push('本轮没有问题，不造缺陷展示');
    const risks = payload.level_audit.risks || [];
    for (const kind of ['wall', 'water']) {
      const index = risks.findIndex(r => r.risk_types.includes(kind));
      if (index < 0) { result.skipped.push('本轮无 ' + kind + ' 风险图'); continue; }
      await go('level-gallery-' + kind);
      ok(!await page.locator('#detail').evaluate(e => e.open) && !await page.locator('#evidence').evaluate(e => e.open),
        kind + '入口直接到图片，不弹证据');
      ok(await page.locator('#level-visual-risks').evaluate(e => e.open), kind + '图库自动展开');
      const id = 'level-risk-' + risks[index].level_id + '-' + index;
      await go(id);
      const figure = page.locator('[id="' + id + '"]');
      ok(await figure.evaluate(e => e.open), kind + '指定关卡图展开');
      ok(await figure.locator('img').evaluate(e => e.complete && e.naturalWidth > 0), kind + '原图内嵌成功');
      await page.reload();
      await page.waitForSelector('#headline', {state: 'attached'});
      ok(await page.locator('[id="' + id + '"]').evaluate(e => e.open), kind + '刷新仍定位原图');
      await page.screenshot({path: path.join(out, 'report-level-' + kind + '.png')});
    }
    // Check the actual embedded evidence bytes via the user's download control.
    await go('overview');
    const artifact = Object.keys(payload.assets).find(k => !payload.assets[k].mime);
    if (artifact) {
      await page.evaluate(name => showEvidence(name), artifact);
      ok(await page.locator('#evidence').evaluate(e => e.open), '开发证据可打开');
      const download = page.waitForEvent('download');
      await page.locator('#download-evidence').click();
      const file = await download;
      const downloaded = fs.readFileSync(await file.path());
      ok(crypto.createHash('sha256').update(downloaded).digest('hex') === payload.assets[artifact].sha256,
        '下载证据保持原字节');
    }
    await page.setViewportSize({width: 390, height: 844});
    for (const key of ['overview', 'play', 'levels', 'systems', 'config', 'tracking']) {
      await go(key);
      if (key === 'overview') ok(await page.locator('#bug-table th:visible').count() === 23, '390px仍保留全部23列');
      ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), key + '在390px无页面横溢');
      ok(await page.locator('a:visible').evaluateAll(elements => elements.every(e =>
        !getComputedStyle(e).textDecorationLine.includes('underline'))), key + '链接无下划线');
    }
    await page.screenshot({path: path.join(out, 'report-mobile.png')});
    ok(result.errors.length === 0, '页面无JavaScript错误');
    result.status = 'passed';
  } catch (error) {
    result.status = 'failed';
    result.errors.push(String(error));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    save();
    console.log(result.status, result.checks.length, 'HTML assertions');
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
