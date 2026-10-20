const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = fs.readFileSync(new URL('../web/studio.js', `file://${__filename}`), 'utf8');

test('project picker keeps search and authorized project creation together above the results', () => {
  const picker = source.match(/async function pickerOpen\(kind\)\s*\{([\s\S]*?)\nasync function loadPicker/);
  assert.ok(picker, 'pickerOpen should exist');
  const body = picker[1];
  assert.match(body, /const create=canCreate\?button\([\s\S]*new-project[\s\S]*:\'\';/);
  assert.match(body, /const toolbar=`<div class=\"project-picker-toolbar\"><input id=\"picker-search\"[\s\S]*\$\{create\}<\/div>`/);
  assert.match(body, /canCreateEntity\(kind,state\.capabilities\)/);
  assert.match(body, /const footer=`<span>每页 5 个<\/span>`/);
  assert.doesNotMatch(body, /const footer=`[^`]*new-project/);
});
