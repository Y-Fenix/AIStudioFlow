const test = require('node:test');
const assert = require('node:assert/strict');
require('../web/department-ui-contract.js');

test('department UI context exposes only current workspace fields and safe escaping', () => {
  const department = {
    id: 'product', name: '产品', title: '产品部门', desc: '研究',
    nodes: [['调研', '研究输入', 'brief.md', '目标', '决定方向', '资料', '简报']]
  };
  const context = globalThis.DepartmentUIContract.createContext({
    department,
    studio: {id: 'studio-1', name: '工作室', secret: 'not exposed'},
    project: {id: 'project-1', name: '<project>', unrelated: 'not exposed'},
    nodeIndex: 0,
    workspace: {revision: 4, status: 'draft', inputs: 'input', deliverable: 'output', skill: {
      name: 'Default', source_kind: 'bundled', sha256: 'abc', content: 'not exposed'
    }, unrelated: 'not exposed'}
  });
  assert.deepEqual(Object.keys(context.studio).sort(), ['id', 'name']);
  assert.deepEqual(Object.keys(context.project).sort(), ['id', 'name']);
  assert.deepEqual(Object.keys(context.workspace).sort(), ['deliverable', 'inputs', 'revision', 'skill', 'status']);
  assert.deepEqual(Object.keys(context.workspace.skill).sort(), ['name', 'sha256', 'source_kind']);
  assert.equal(context.escape('<tag>&"\''), '&lt;tag&gt;&amp;&quot;&#39;');
  assert.equal(context.node.outputContract, '简报');
});

test('department UI slots reject non-string and oversized markup and preserve public fallback', () => {
  const contract = globalThis.DepartmentUIContract;
  assert.equal(contract.render({}, 'renderHome', {}), '');
  assert.equal(contract.render({renderHome: () => ({html: 'unsafe'})}, 'renderHome', {}), '');
  assert.equal(contract.render({renderHome: () => 'x'.repeat(100001)}, 'renderHome', {}), '');
  assert.equal(contract.render({renderHome: () => '<h3>owned</h3>'}, 'renderHome', {}), '<h3>owned</h3>');
});

test('workspace creation controls follow scoped server capabilities', () => {
  const contract = globalThis.DepartmentUIContract;
  assert.equal(contract.canCreateEntity('studios', {studio_create: true}), true);
  assert.equal(contract.canCreateEntity('studios', {studio_create: false, project_create: true}), false);
  assert.equal(contract.canCreateEntity('projects', {project_create: true}), true);
  assert.equal(contract.canCreateEntity('projects', {project_create: false, studio_create: true}), false);
  assert.equal(contract.canCreateEntity('unknown', {studio_create: true, project_create: true}), false);
});

test('skill controls reflect node-level skill permissions', () => {
  const contract = globalThis.DepartmentUIContract;
  assert.deepEqual(contract.skillControls({nodes: {'product:0': {
    skill_view: true, skill_import: false, skill_export: true
  }}}, 'product:0'), {view: true, import: false, export: true});
  assert.deepEqual(contract.skillControls({nodes: {'product:0': {
    view: true, skill_view: false, skill_import: true, skill_export: true
  }}}, 'product:0'), {view: false, import: false, export: false});
  assert.deepEqual(contract.skillControls({}, 'product:0'), {view: false, import: false, export: false});
});

test('department mount receives scoped draft tools and disposes listeners on navigation', async () => {
  const root = new EventTarget();
  let services, handled = 0, cleaned = 0, draft = {inputs: 'source', deliverable: ''};
  const dispose = DepartmentUIContract.mount({mountWorkspace(element, context, tools) {
    assert.equal(context.department.id, 'product');
    services = tools;
    element.addEventListener('test-action', () => handled++, {signal: tools.signal});
    return () => cleaned++;
  }}, 'mountWorkspace', {
    element: root, context: {department: {id: 'product'}},
    readDraft: () => draft, updateDraft: patch => { draft = {...draft, ...patch}; },
  });
  root.dispatchEvent(new Event('test-action'));
  services.updateDraft({inputs: 'new input'});
  const snapshot = services.readDraft(); snapshot.inputs = 'mutated copy';
  assert.equal(draft.inputs, 'new input');
  dispose(); dispose();
  await Promise.resolve();
  root.dispatchEvent(new Event('test-action'));
  assert.equal(handled, 1);
  assert.equal(cleaned, 1);
  assert.equal(services.signal.aborted, true);
  assert.throws(() => services.updateDraft({inputs: 'stale'}), /失效/);
  assert.equal(draft.inputs, 'new input');
});

test('department draft tools cannot alter Skill, versions or permissions', () => {
  let services, calls = 0;
  const dispose = DepartmentUIContract.mount({mountWorkspace(_root, _context, tools) {services = tools;}},
    'mountWorkspace', {element: {}, context: {}, updateDraft: () => calls++});
  for (const patch of [{skill: 'override'}, {revision: 100}, {permissions: {}}, null, [], {inputs: 3}]) {
    assert.throws(() => services.updateDraft(patch), /草稿/);
  }
  assert.equal(calls, 0);
  dispose();
});

test('late asynchronous mount cleanup runs after disposal without affecting the next view', async () => {
  let resolve, cleaned = 0;
  const dispose = DepartmentUIContract.mount({mountHome: () => new Promise(r => {resolve = r;})},
    'mountHome', {element: {}, context: {}});
  dispose();
  resolve(() => cleaned++);
  await Promise.resolve();
  assert.equal(cleaned, 1);
});

test('department hook failures are isolated and reported without breaking the shell', () => {
  const errors = [];
  const dispose = DepartmentUIContract.mount({mountHome() {throw Error('module failed');}},
    'mountHome', {element: {}, context: {}, onError: e => errors.push(e.message)});
  assert.doesNotThrow(dispose);
  assert.deepEqual(errors, ['module failed']);
});

test('department draft tools refuse use as soon as navigation begins, before the next render', () => {
  let services, current = true, writes = 0;
  const dispose = DepartmentUIContract.mount({mountWorkspace(_element, _context, tools) {services = tools;}},
    'mountWorkspace', {element: {}, context: {}, isCurrent: () => current,
      readDraft: () => ({inputs: 'private draft'}), updateDraft: () => writes++});
  current = false;
  assert.throws(() => services.readDraft(), /失效/);
  assert.throws(() => services.updateDraft({inputs: 'stale'}), /失效/);
  assert.equal(writes, 0);
  dispose();
});

test('module node ID survives project display reordering', () => {
 const department={id:'product',nodes:[['自定义']],node_keys:['product:custom-stable']};
 const ctx=DepartmentUIContract.createContext({department,nodeIndex:0});
 assert.equal(ctx.node.id,'product:custom-stable');
});
