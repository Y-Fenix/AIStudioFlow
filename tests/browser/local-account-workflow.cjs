// Real browser + local password HTTP/SQLite. No live accounts or external services.
const assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {spawn} = require('node:child_process');
const {chromium} = require(process.env.STUDIOFLOW_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'studioflow-local-login-'));
  const server = spawn('python3', ['-u', '-c',
    'import sys;from server.app import create_server;s=create_server("127.0.0.1",0,sys.argv[1]);print(s.server_port,flush=True);s.serve_forever()',
    path.join(folder, 'platform.sqlite')], {cwd: path.resolve(__dirname, '../..'), stdio: ['ignore', 'pipe', 'pipe']});
  let output = '', browser;
  server.stdout.on('data', data => output += data);server.stderr.on('data', data => output += data);
  try {
    const deadline = Date.now() + 10000;
    while (!/^\d+\s*$/m.test(output)) {
      if (Date.now() > deadline || server.exitCode !== null) throw Error(output);
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    const base = 'http://127.0.0.1:' + output.match(/^(\d+)\s*$/m)[1];
    browser = await chromium.launch({headless: true, executablePath: process.env.STUDIOFLOW_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
    const ownerContext = await browser.newContext(), memberContext = await browser.newContext();
    const owner = await ownerContext.newPage(), member = await memberContext.newPage(), errors = [];
    for (const page of [owner, member]) page.on('pageerror', error => errors.push(error.message));
    const api = async (context, url, body) => {
      const response = await context.request[body === undefined ? 'get' : 'post'](base + url, body === undefined ? {} : {data: body});
      assert(response.ok(), await response.text());return response.json();
    };
    await owner.goto(base);
    await owner.waitForSelector('[data-auth-view="setup"]');
    assert.equal(await owner.locator('a[href*="feishu"]').count(), 0);
    await owner.locator('#auth-username').fill('studio-owner');
    await owner.locator('#auth-name').fill('隔离验证负责人');
    await owner.locator('#auth-password').fill('Owner-browser-2026');
    await owner.locator('#auth-confirm-password').fill('Mismatch-browser-2026');
    await owner.locator('.auth-submit').click();
    await owner.waitForSelector('#auth-error:not([hidden])');
    assert.match(await owner.locator('#auth-error').innerText(), /不一致/);
    await owner.locator('#auth-confirm-password').fill('Owner-browser-2026');
    await owner.locator('.auth-submit').click();
    await owner.waitForSelector('#sidebar .brand');
    const studio = (await api(ownerContext, '/api/studios')).items[0].id;
    const project = await api(ownerContext, `/api/studios/${studio}/projects`, {name: '本地登录验证项目'});
    await api(ownerContext, `/api/studios/${studio}/projects/${project.id}/enter`, {});
    await owner.reload();await owner.waitForSelector('#sidebar .brand');

    await member.goto(base);await member.waitForSelector('[data-auth-view="login"]');
    const shots = path.resolve(__dirname, '../../data/visual-review');fs.mkdirSync(shots, {recursive: true});
    await member.screenshot({path: path.join(shots, 'local-account-login.png'), fullPage: true});
    await member.locator('[data-action="auth-view:register"]').click();
    await member.waitForSelector('[data-auth-view="register"]');
    await member.locator('#auth-username').fill('qa-tester');
    await member.locator('#auth-name').fill('隔离验证测试员');
    await member.locator('#auth-password').fill('Tester-browser-2026');
    await member.locator('#auth-confirm-password').fill('Tester-browser-2026');
    await member.locator('.auth-submit').click();
    await member.waitForSelector('[data-action="login-refresh"]');
    assert.match(await member.locator('.auth-card').innerText(), /待审批/);
    const actor = (await api(memberContext, '/api/auth/session')).user.id;
    assert.equal((await memberContext.request.get(base + '/api/studios')).status(), 403);

    await owner.locator('[data-action="view:admin"]').click();
    await owner.waitForSelector('#member-user');
    await owner.locator('#member-user').selectOption(actor);
    await owner.locator('#member-project').selectOption(project.id);
    await owner.locator('#member-department').selectOption('testing');
    await owner.locator('[data-action="admin-member-save"]').click();
    await owner.waitForFunction(() => document.querySelector('.admin-members')?.textContent.includes('已启用'));
    await member.locator('[data-action="login-refresh"]').click();
    await member.waitForFunction(() => document.querySelector('.page-crumb')?.textContent === '测试部门 · 首页');
    await member.locator('[data-action="user-settings"]').first().click();
    await member.locator('[data-action="change-password"]').click();
    await member.locator('#current-password').fill('Tester-browser-2026');
    await member.locator('#new-password').fill('Changed-browser-2026');
    await member.locator('#confirm-new-password').fill('Changed-browser-2026');
    await member.locator('#local-password-form [type="submit"]').click();
    await member.waitForSelector('[data-auth-view="login"]');
    await member.locator('#auth-username').fill('qa-tester');
    await member.locator('#auth-password').fill('Tester-browser-2026');
    await member.locator('.auth-submit').click();
    await member.waitForSelector('#auth-error:not([hidden])');
    await member.locator('#auth-password').fill('Changed-browser-2026');
    await member.locator('.auth-submit').click();
    await member.waitForSelector('#sidebar .brand');

    await owner.locator(`[data-action="admin-password:${actor}"]`).click();
    await owner.locator('#new-password').fill('Reset-browser-2026');
    await owner.locator('#confirm-new-password').fill('Reset-browser-2026');
    await owner.locator('#local-password-form [type="submit"]').click();
    await owner.waitForSelector('#local-password-form', {state: 'detached'});
    await member.reload();await member.waitForSelector('[data-auth-view="login"]');
    await member.locator('#auth-username').fill('qa-tester');
    await member.locator('#auth-password').fill('Reset-browser-2026');
    await member.locator('.auth-submit').click();await member.waitForSelector('#sidebar .brand');
    await member.locator('[data-action="user-settings"]').first().click();
    await member.locator('.modal [data-action="logout"]').click();
    await member.waitForSelector('[data-auth-view="login"]');
    for (const width of [980, 390]) {
      await member.setViewportSize({width, height: 900});
      assert(await member.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'login does not overflow at ' + width);
    }
    await member.screenshot({path: path.join(shots, 'local-account-login-mobile.png'), fullPage: true});
    assert.deepEqual(errors, []);
    console.log('PASS: local owner setup, password confirmation, register/pending/approval, department homepage, password change, admin reset, old-session revocation, login/logout and responsive login. Temporary database, no live accounts.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit', resolve));
    fs.rmSync(folder, {recursive: true, force: true});
  }
})().catch(error => {console.error(error);process.exitCode = 1;});
