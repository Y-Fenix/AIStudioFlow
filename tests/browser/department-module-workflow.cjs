// Isolated browser acceptance. Requires Playwright; no live account or model calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {chromium} = require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE || 'playwright');

function contrast(foreground, background) {
  const luminance = color => color.match(/[\d.]+/g).slice(0, 3).map(Number)
    .map(value => color.startsWith('color(srgb ') ? value : value / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
  return (values[0] + .05) / (values[1] + .05);
}

const fixture = `export default {
  renderHome() {return '<button data-product-action="summary">项目摘要</button><output></output>';},
  mountHome(root, context, tools) {
    root.querySelector('button').addEventListener('click', () => {
      root.querySelector('output').textContent = context.project.name;
    }, {signal: tools.signal});
  },
  renderWorkspace() {return '<button data-product-action="draft">整理输入草稿</button>';},
  mountWorkspace(root, context, tools) {
    globalThis.__fixturePreviousTools = tools;
    root.querySelector('button').addEventListener('click', () => {
      tools.updateDraft({inputs: 'fixture: source-backed product inputs'});
    }, {signal: tools.signal});
    return () => {globalThis.__fixtureCleanupCount = (globalThis.__fixtureCleanupCount || 0) + 1;};
  }
};`;

(async () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'studioflow-module-ui-'));
  let browser;
  let base;
  const server = spawn(process.env.PYTHON || 'python3', ['-u', '-c',
    'import sys; from server.app import create_server; s=create_server("127.0.0.1",0,sys.argv[1],local_development=True); print(s.server_port,flush=True); s.serve_forever()',
    path.join(temp, 'test.sqlite')], {cwd: path.resolve(__dirname, '../..'), stdio: ['ignore', 'pipe', 'pipe']});
  let serverOutput = '';
  server.stdout.on('data', data => {serverOutput += data;});
  server.stderr.on('data', data => {serverOutput += data;});
  try {
    const deadline = Date.now() + 10000;
    while (true) {
      if (server.exitCode !== null) throw Error('isolated server exited: ' + serverOutput);
      const port = serverOutput.match(/^(\d+)\s*$/m)?.[1];
      if (port) {base = 'http://127.0.0.1:' + port;break;}
      if (Date.now() > deadline) throw Error('isolated server did not become ready');
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    const executablePath = process.env.STUDIOFLOW_CHROME ||
      (fs.existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome') ?
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined);
    browser = await chromium.launch({headless: true, executablePath});
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/departments/product/ui.js', route => route.fulfill({contentType: 'text/javascript', body: fixture}));
    const request = async (url, body) => {
      const response = await page.request[body === undefined ? 'get' : 'post'](base + url, body === undefined ? {} : {data: body});
      assert(response.ok(), url + ': ' + await response.text());
      return response.json();
    };
    const studio = (await request('/api/studios')).items[0].id;
    const project = await request('/api/studios/' + studio + '/projects', {name: 'Module UI fixture'});
    await request('/api/me/preferences', {active_studio_id: studio, role: 'product'});
    await request(`/api/studios/${studio}/projects/${project.id}/enter`, {});
    const root = `/api/studios/${studio}/projects/${project.id}`;
    await page.goto(base);
    await page.locator('[data-product-action="summary"]').click();
    await page.waitForFunction(() => document.querySelector('.department-owned-slot output')?.textContent === 'Module UI fixture', null, {timeout: 3000});
    assert.equal(await page.locator('.department-owned-slot .department-owned-slot').count(), 0, 'one extension wrapper per module');
    await page.locator('.home-node[data-action="node:product:0"]').click();
    await page.locator('[data-product-action="draft"]').click();
    assert.equal(await page.inputValue('#node-inputs'), 'fixture: source-backed product inputs');
    assert.equal((await request(root + '/workspace?node=product:0')).inputs, '', 'module edits remain unsaved until shell save');
    const originalSkill = (await request(root + '/workspace?node=product:0')).skill.sha256;
    await page.locator('[data-action="save-node"]').click();
    await page.waitForFunction(() => document.querySelector('#save-status')?.textContent.includes('版本 1'));
    const saved = await request(root + '/workspace?node=product:0');
    assert.equal(saved.inputs, 'fixture: source-backed product inputs');
    assert.equal(saved.skill.sha256, originalSkill);
    await page.evaluate(() => recoverSkillHandoff(nodeContext()));
    const preview = await request(root + '/workspace/codex-handoff?node=product:0', {origin: base, preview: true});
    assert.equal(await page.inputValue('#codex-handoff-recovery'), preview.prompt,
      'manual recovery uses the server prompt, including Codex install normalization');
    await page.keyboard.press('Escape');
    const stale = await page.evaluate(() => {
      globalThis.__fixtureSavedTools = globalThis.__fixturePreviousTools;
      return globalThis.__fixtureCleanupCount;
    });
    const recoveryPattern = /\/workspace\/codex-handoff\?/;
    let resolveRecovery;
    const interceptedRecovery = new Promise(resolve => {resolveRecovery = resolve;});
    await page.route(recoveryPattern, route => resolveRecovery(route));
    const recovering = page.evaluate(() => recoverSkillHandoff(nodeContext()));
    const heldRecovery = await interceptedRecovery;
    await page.locator('[data-action="home:design"]').click();
    await page.waitForFunction(() => document.querySelector('.page-crumb')?.textContent === '设计部门 · 首页');
    await heldRecovery.continue();
    await recovering;
    await page.unroute(recoveryPattern);
    assert.equal(await page.locator('.modal').count(), 0, 'late recovery must not open a modal in another department');
    const result = await page.evaluate(() => {
      try {globalThis.__fixtureSavedTools.updateDraft({inputs: 'stale'});return {blocked: false};}
      catch (error) {return {blocked: /失效/.test(error.message), cleaned: globalThis.__fixtureCleanupCount};}
    });
    assert(result.blocked);
    assert(result.cleaned > stale);
    assert.equal((await request(root + '/workspace?node=product:0')).inputs, saved.inputs);
    assert.deepEqual(errors, []);
    console.log('PASS: isolated department home/workspace interactions, shell save, unchanged Skill, server-owned manual handoff prompt, cleanup and stale callback/recovery rejection (explicit UI fixture).');

    // The remaining checks use the actual repository modules, without the UI fixture.
    await page.unroute('**/departments/product/ui.js');
    const roles = [['studio_owner', '项目总览'], ['product', '产品部门 · 首页'],
      ['design', '设计部门 · 首页'], ['development', '开发部门 · 首页'],
      ['qa', '测试部门 · 首页'], ['growth', '发行与增长 · 首页']];
    const cards = [];
    let overviewCard;
    for (const [role, label] of roles) {
      await request('/api/me/preferences', {active_studio_id: studio, role});
      await page.reload();
      await page.waitForFunction(expected => document.querySelector('.page-crumb')?.textContent === expected, label);
      const selector = role === 'studio_owner' ? '.hero-grid' : '.department-hero-grid';
      const dimensions = await page.locator(selector + '>section').evaluateAll(elements =>
        elements.map(element => Math.round(element.getBoundingClientRect().height)));
      assert.deepEqual(dimensions, [270, 270], role + ' desktop module height');
      if (role === 'studio_owner') {
        overviewCard = await page.locator('.department-card').first().evaluate(element => ({
          width: Math.round(element.getBoundingClientRect().width), height: Math.round(element.getBoundingClientRect().height)
        }));
      }
      if (role !== 'studio_owner') {
        const sizes = await page.locator('.home-node').evaluateAll(elements => elements.map(element => ({
          width: Math.round(element.getBoundingClientRect().width), height: Math.round(element.getBoundingClientRect().height)
        })));
        assert(sizes.every(size => size.width === sizes[0].width && size.height === sizes[0].height));
        assert.deepEqual(sizes[0], overviewCard, role + ' nodes match overview card size');
        assert.equal(await page.locator('.home-node:last-child .node-title .icon').count(), 1, 'last node has department icon only');
        assert(!/→/.test(await page.locator('.home-node:last-child').innerText()));
        assert.equal(await page.locator('.department-owned-slot .department-owned-slot').count(), 0);
        cards.push({role, ...sizes[0]});
      }
    }
    await page.setViewportSize({width: 1000, height: 900});
    assert.deepEqual(await page.locator('.department-hero-grid>section').evaluateAll(elements =>
      elements.map(element => Math.round(element.getBoundingClientRect().height))), [290, 290]);
    await page.setViewportSize({width: 390, height: 844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile page must not overflow');
    await page.setViewportSize({width: 1440, height: 1000});
    for (const theme of ['forge', 'paper', 'arcade']) {
      await page.locator('[data-action="view:themes"]').first().click();
      const apply = page.locator('[data-action="theme:' + theme + '"]');
      if (await apply.count()) await apply.click();
      for (const department of ['product', 'design', 'development', 'testing', 'growth']) {
        await page.locator(`[data-action="home:${department}"]`).click();
        await page.waitForSelector(`#sidebar [data-action="home:${department}"].active`);
        await page.waitForSelector('.department-hero .department-mark svg');
        assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
        const colors = await page.evaluate(department => {
          const hero = document.querySelector('.department-hero');
          const background = getComputedStyle(hero).backgroundColor;
          const button = hero.querySelector('button.lime');
          return {
            background,
            gradient: getComputedStyle(hero).backgroundImage,
            sidebar: getComputedStyle(document.querySelector(`#sidebar [data-action="home:${department}"] .dept-dot`)).backgroundColor,
            text: ['h2', ':scope>p', '.hero-kicker', '.hero-cta>span', '.hero-bottom'].map(selector => getComputedStyle(hero.querySelector(selector)).color),
            button: {color: getComputedStyle(button).color, background: getComputedStyle(button).backgroundColor},
            decoration: getComputedStyle(hero.querySelector('.department-mark')).color,
            markFillToken: getComputedStyle(hero).getPropertyValue('--hero-mark-fill').trim(),
            markFill: hero.querySelector('.mark-card') ? getComputedStyle(hero.querySelector('.mark-card')).fill : null,
            footerFits: hero.querySelector('.hero-bottom').getBoundingClientRect().bottom <= hero.getBoundingClientRect().bottom
          };
        }, department);
        const label = theme + '/' + department;
        assert.equal(colors.background, colors.sidebar, label + ' hero follows sidebar department color');
        assert(new Set(colors.text).size >= 3, label + ' title, copy and supporting labels have distinct color levels');
        assert.notEqual(colors.decoration, colors.text[0], label + ' artwork has its own accent color');
        const backgrounds = colors.gradient === 'none' ? [colors.background] : colors.gradient.match(/rgb\([^)]*\)|color\(srgb [^)]*\)/g);
        assert(backgrounds?.length, label + ' measurable hero background colors');
        for (const background of backgrounds) for (const [index, color] of colors.text.entries()) {
          assert(contrast(color, background) >= (index === 0 ? 3 : 4.5), label + ' readable hero text');
        }
        assert(contrast(colors.button.color, colors.button.background) >= 4.5, label + ' readable CTA');
        if (colors.markFill) assert(colors.markFillToken, label + ' SVG overlap fill belongs to hero palette');
        assert(colors.footerFits, label + ' footer stays inside hero');
        if (theme === 'paper' && ['product', 'design', 'growth'].includes(department)) {
          const shots = path.resolve(__dirname, '../../data/visual-review');
          fs.mkdirSync(shots, {recursive: true});
          await page.locator('.department-hero').screenshot({path: path.join(shots, 'department-color-' + department + '.png')});
        }
      }
      assert.equal((await request(root + '/workspace?node=product:0')).inputs, saved.inputs);
    }
    for (let index = 0; index < 6; index++) {
      await request('/api/studios/' + studio + '/projects', {name: 'Picker fixture ' + index});
    }
    await page.locator('.sidebar-project-actions [data-action="projects"]').click();
    await page.waitForSelector('.project-result');
    assert.equal(await page.locator('.project-result').count(), 5);
    await page.locator('[data-action="picker-page:1"]').click();
    await page.waitForFunction(() => document.querySelectorAll('.project-result').length === 2);
    await page.fill('#picker-search', 'Module UI fixture');
    await page.waitForFunction(() => document.querySelectorAll('.project-result').length === 1);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.modal').count(), 0);
    assert.deepEqual(errors, []);
    console.log('PASS: real modules across six identity homepages; 270/290px heights; node sizing; final-node arrows; mobile; all themes; project search/pagination/ESC. Sizes: ' + JSON.stringify(cards));
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null) {server.kill('SIGTERM');await once(server, 'exit');}
    fs.rmSync(temp, {recursive: true, force: true});
  }
})().catch(error => {console.error(error);process.exitCode = 1;});
