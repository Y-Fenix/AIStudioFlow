const test=require('node:test');
const assert=require('node:assert/strict');
const continuation=require('../web/node-continuation.js');
test('switch states have explicit text, accessible labels, stable edge IDs and escaped names',()=>{
 const edge={source:'product:0',target:'product:1',source_name:'<来源>',target_name:'竞品',enabled:false,editable:true,available:true};
 const off=continuation.markup(edge);
 assert.match(off,/role="switch"/);assert.match(off,/aria-checked="false"/);assert.match(off,/手动继续/);
 assert(!off.includes('<来源>'));assert.match(off,/&lt;来源&gt;/);
 const on=continuation.markup({...edge,enabled:true});assert.match(on,/aria-checked="true"/);assert.match(on,/自动继续/);
 assert.match(continuation.markup({...edge,editable:false}),/disabled/);
 assert.match(continuation.markup({...edge,available:false,reason:'依赖不满足'}),/依赖不满足/);
});
test('no edge produces no accidental switch',()=>assert.equal(continuation.markup(null),''));
