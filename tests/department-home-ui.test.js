const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(new URL('../web/studio.js', `file://${__filename}`), 'utf8');
const teamUiSource = fs.readFileSync(new URL('../web/team-ui.js', `file://${__filename}`), 'utf8');
const testingUiSource = fs.readFileSync(new URL('../web/app.js', `file://${__filename}`), 'utf8');
const css = fs.readFileSync(new URL('../web/themes.css', `file://${__filename}`), 'utf8');
const studioCss = fs.readFileSync(new URL('../web/studio.css', `file://${__filename}`), 'utf8');

test('department identity home is a real page with project context and department module slots', () => {
  assert.match(source, /async function openHome\(departmentId\)/);
  assert.match(source, /function departmentHome\(\)/);
  const home = source.match(/function departmentHome\(\)\s*\{([\s\S]*?)\nfunction definition/);
  assert.ok(home, 'department home renderer should be defined');
  assert.match(home[1], /departmentExtension\('renderHome'/);
  assert.match(home[1], /department-hero-grid/);
  assert.match(home[1], /data-action="node:/);
  assert.match(home[1], /state\.project/);
  assert.match(home[1], /department-tool-links/);
  assert.match(home[1], /target="_blank" rel="noopener noreferrer"/);
  assert.match(home[1], /API 适配器/);
});

test('department node overview uses the same compact card sizing as the shared project overview', () => {
  assert.match(css, /--home-module-height:\s*270px/);
  assert.match(css, /--home-module-height:\s*290px/);
  assert.match(css, /\.home-node-grid\{display:grid;grid-template-columns:repeat\(5,minmax\(0,1fr\)\);grid-auto-rows:1fr;gap:12px\}/);
  assert.match(css, /\.home-node\{padding:18px 16px 14px;display:flex;flex-direction:column;[^}]*border-radius:11px/);
  assert.match(css, /\.home-node \.node-title\{margin:15px 0 10px\}/);
  assert.match(css, /\.home-node \.node-title h3\{font-size:13px/);
  assert.match(css, /\.home-node>p\{font-size:10px/);
  assert.match(css, /@media\(max-width:1060px\)\{[^}]*\.home-node-grid\{grid-template-columns:repeat\(3,minmax\(0,1fr\)\)\}/);
  assert.match(css, /@media\(max-width:760px\)\{[^}]*\.home-node-grid\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)\}/);
  assert.doesNotMatch(css, /@media\(min-width:1600px\)\{[^}]*\.department-hero\{min-height:275px\}/);
  assert.match(studioCss, /\.department-cards\{display:grid;grid-template-columns:repeat\(5,minmax\(0,1fr\)\);gap:12px\}/);
});

test('the final department node has no forward arrow affordance', () => {
  assert.match(source, /isLast=i===nodes\.length-1/);
  assert.match(source, /\$\{isLast\?'':icon\('arrow'\)\}/);
  assert.match(source, /\$\{isLast\?'进入节点':'进入节点 →'\}/);
});

test('node Skill toolbar offers local Codex handoff before import and export', () => {
  const toolbar = source.match(/<div class="skill-actions">([\s\S]*?)<\/div>/);
  assert.ok(toolbar, 'Skill actions should be rendered');
  assert.ok(toolbar[1].indexOf('在 Codex 使用') >= 0);
  assert.ok(toolbar[1].indexOf('在 Codex 使用') < toolbar[1].indexOf('导入 Skill'));
  assert.match(source, /async function handoffSkill\(\)/);
  assert.match(source, /workspace\/codex-handoff\?node=/);
  assert.match(source, /openUri:StudioFlowCodexHandoff\.openProtocolUri/);
  assert.match(source, /onUnconfirmed:\(\)=>recoverSkillHandoff\(context\)/);
});

test('testing workflow offers authorized Codex Skill handoff from its six-node task Skill', () => {
  const controls = testingUiSource.match(/function nodeSkillControls\(\)\s*\{([\s\S]*?)\nfunction viewNodeSkill/);
  assert.ok(controls, 'testing Skill controls should be defined');
  assert.match(controls[1], /n\.skill_export\?'<button onclick="handoffNodeSkill\(\)">在 Codex 使用<\/button>'/);
  assert.ok(controls[1].indexOf('在 Codex 使用') < controls[1].indexOf('导入 Skill'));
  assert.match(testingUiSource, /async function handoffNodeSkill\(\)/);
  assert.match(testingUiSource, /\/codex-handoff\?stage=/);
});

test('department home omits the redundant summary metrics row', () => {
  const home = source.match(/function departmentHome\(\)\s*\{([\s\S]*?)\nfunction definition/);
  assert.ok(home, 'department home renderer should be defined');
  assert.doesNotMatch(home[1], /home-metrics|\$\{metrics\}/);
  assert.doesNotMatch(css, /\.home-metrics/);
});

test('department home has one shell-owned renderer instead of a shadow legacy duplicate', () => {
  assert.doesNotMatch(teamUiSource, /function departmentHome\s*\(/);
});
