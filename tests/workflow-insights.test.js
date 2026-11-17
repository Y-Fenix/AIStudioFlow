const test = require('node:test');
const assert = require('node:assert/strict');
require('../web/workflow-insights.js');
const api = globalThis.WorkflowInsights;

const fixture = () => ({id: 'fixture', requirements: [{id: 'R1', source: '<img onerror=alert(1)>', content: '规则'}],
  artifacts: {'0': {points: [{id: 'P1', title: '奖励', requirement_id: 'R1', quote: '规则'}],
    cases: [{id: 'C1', title: '同名用例', point_ids: ['P1']}, {id: 'C2', title: '同名用例', point_ids: ['P1']}], gaps: []},
    '1': {method: 'static_code_review', results: [{id: 'C1', case_id: 'C1', status: 'failed',
      assertions: [{call_chain: [{file: 'Assets/A.cs', line: 2, quote: '<unsafe>'}]}]}]},
    '2': {groups: [{root_cause_id: 'root', title: '缺少去重', result_ids: ['C1']}]},
    '4': {linked_records: [{root_cause_id: 'root', record_id: 'rec1'}]}},
  regression: {roots: [{root_cause_id: 'root', verdict: 'insufficient_evidence'}]}});

test('trace uses stable IDs across source, point, case, result, root, bug and regression', () => {
  const rows = api.QA_traceRows(fixture());
  assert.equal(rows.length, 2);
  assert.equal(rows[0].sources[0].source, '<img onerror=alert(1)>');
  assert.equal(rows[0].roots[0].root_cause_id, 'root');
  assert.deepEqual(rows[0].bugs.map(x => x.record_id), ['rec1']);
  assert.equal(rows[0].regressions[0].verdict, 'insufficient_evidence');
  assert.equal(rows[0].citations[0].file, 'Assets/A.cs');
  assert.equal(rows[1].status, 'not_run');
  assert.equal(rows[1].roots.length, 0, 'duplicate titles must not imply shared results');
});

test('uncovered points and undecomposed requirements remain visible', () => {
  const task = fixture();
  task.artifacts['0'].points.push({id: 'P2', title: '边界', requirement_id: 'R1'});
  task.requirements.push({id: 'R2', source: '未拆解资料'});
  const rows = api.QA_traceRows(task);
  assert(rows.some(x => x.pointIds.includes('P2') && !x.caseId && x.unresolved));
  assert(rows.some(x => x.sources.some(s => s.id === 'R2') && !x.caseId && x.unresolved));
});

test('a reachable failure does not hide a separate unresolved assertion', () => {
  const task = fixture();
  task.artifacts['1'].results[0].assertions.push({status:'needs_runtime',gap:'需设备观察动画',next_action:'真机核对',call_chain:[]});
  const row = api.QA_traceRows(task)[0];
  assert.equal(row.status, 'failed');
  assert.equal(row.unresolved, true);
  assert.equal(api.QA_page([row], {filter:'unresolved'}).total, 1);
});

test('filter and pagination show exact counts and clamp stale page', () => {
  const rows = Array.from({length: 47}, (_, i) => ({status: i % 2 ? 'failed' : 'passed', unresolved: i % 2 === 1}));
  const page = api.QA_page(rows, {filter: 'failed', page: 99, size: 10});
  assert.equal(page.total, 23);
  assert.equal(page.page, 3);
  assert.equal(page.items.length, 3);
  assert.equal(api.QA_page(rows, {filter: 'unresolved', page: 1, size: 20}).items.length, 20);
});

test('trace markup escapes all source, title and citation content', () => {
  const html = api.QA_renderRows(api.QA_traceRows(fixture()));
  assert(!html.includes('<img onerror'));
  assert(html.includes('&lt;img onerror'));
  assert(html.includes('静态'));
  assert(!html.includes('<unsafe>'));
});

test('restricted or missing data never manufactures associations', () => {
  assert.deepEqual(api.QA_traceRows({artifacts: {}}), []);
  const task = fixture();
  task.requirements = [];
  task.artifacts['2'] = {};
  task.artifacts['4'] = {};
  const rows = api.QA_traceRows(task);
  assert.equal(rows[0].sources.length, 0);
  assert.equal(rows[0].roots.length, 0);
  assert.equal(rows[0].bugs.length, 0);
});

test('skill inspection is a rule checklist, never a model quality score', () => {
  const checked = api.checkSkill({content: '# 输入\n需求\n# 输出\n用例\n# 证据\n来源\n# 边界\n失败时说明缺口', sha256: 'real-fingerprint'});
  assert(checked.checks.every(x => x.found));
  assert.equal(checked.sha256, 'real-fingerprint');
  assert.equal(checked.evaluated, false);
  const empty = api.checkSkill({content: ''});
  assert(empty.issues.some(x => x.includes('为空')));
  const dependent = api.checkSkill({content: '[规则](references/rules.md)'});
  assert(dependent.issues.some(x => x.includes('references/rules.md')));
  const html = api.renderSkillCheck({content: '[<unsafe>](references/rules.md)', name: '<script>'});
  assert(!html.includes('<script>'));
  assert(html.includes('未做样本评测'));
  assert(!html.includes('99%'));
});
