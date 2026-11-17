const test=require('node:test'),assert=require('node:assert/strict');
const UI=require('../web/production-console.js');
test('production progress only counts server completed steps',()=>{
 assert.deepEqual(UI.progress({steps:[{status:'completed'},{status:'running'},{status:'failed'}]}),{completed:1,total:3});
 assert.deepEqual(UI.progress({progress:{completed:99,total:100}}),{completed:0,total:0});
});
test('unknown status stays explicit and times do not fabricate elapsed',()=>{
 assert.equal(UI.status('strange'),'未知状态（strange）');assert.equal(UI.elapsed({}),'—');assert.equal(UI.elapsed({started_at:'bad'}),'—');
});
test('download URLs only use authenticated scoped route',()=>{
 assert.equal(UI.artifactURL('/api/studios/s/projects/p','r/1',{id:'a/2',url:'https://evil.test'}),'/api/studios/s/projects/p/production-runs/r%2F1/artifacts/a%2F2');
});
test('server text cannot inject markup and default controls fail closed',()=>{
 assert.equal(UI.escape('<img onerror="x">'),'&lt;img onerror=&quot;x&quot;&gt;');
 assert.deepEqual(UI.actions({status:'running'}),[]);
 assert.deepEqual(UI.actions({allowed_actions:['pause','javascript','cancel']}),['pause','cancel']);
});
test('terminal duration uses last recorded timestamp rather than continuing to tick',()=>{
 assert.equal(UI.elapsed({status:'failed',created_at:'2026-11-10 01:00:00',updated_at:'2026-11-10 01:01:30'}),'1 分 30 秒');
});
