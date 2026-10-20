const test=require('node:test');
const assert=require('node:assert/strict');
const nodes=require('../web/project-nodes.js');

test('stable keys follow reordered catalog and custom nodes never become testing stages',()=>{
 const d={id:'testing',nodes:[['回归'],['用例'],['新增']],node_keys:['testing:5','testing:0','testing:custom-a']};
 assert.equal(nodes.key(d,0),'testing:5');
 assert.equal(nodes.key(d,2),'testing:custom-a');
 assert.equal(nodes.testingStage(nodes.key(d,0)),5);
 assert.equal(nodes.testingStage(nodes.key(d,2)),null);
 assert.equal(nodes.key({id:'product',nodes:[['默认']]},0),'product:0');
});

test('moving nodes keeps identities and refuses out of range moves',()=>{
 const original=[{id:'a'},{id:'b'},{id:'c'}];
 assert.deepEqual(nodes.move(original,2,-1).map(n=>n.id),['a','c','b']);
 assert.deepEqual(original.map(n=>n.id),['a','b','c']);
 assert.deepEqual(nodes.move(original,0,-1),original);
});
