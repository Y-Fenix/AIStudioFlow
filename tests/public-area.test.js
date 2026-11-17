'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const ctx=vm.createContext({module:{exports:{}}});vm.runInContext(fs.readFileSync('web/public-area.js','utf8'),ctx);const ui=ctx.module.exports;
test('runtime discovery tolerates only a missing endpoint on an older team service',async()=>{
 assert.equal(await ui.readRuntime(async path=>{assert.equal(path,'/api/runtime');return {mode:'personal'}}),'personal');
 assert.equal(await ui.readRuntime(async()=>{throw Object.assign(Error('missing'),{status:404})}),'team');
 for(const status of [401,403,500])await assert.rejects(ui.readRuntime(async()=>{throw Object.assign(Error('request failed'),{status})}),{status});
 await assert.rejects(ui.readRuntime(async()=>{throw Error('network unavailable')}),/network unavailable/);
});
test('preview escapes untrusted content and requires fresh explicit confirmation',()=>{
 const html=ui.previewMarkup({id:'draft',status:'draft',package:{title:'<img onerror=evil()>',content:'<script>evil()</script>',includes:[],attachments:[]}});
 assert(!html.includes('<script>'));assert(html.includes('&lt;script&gt;'));assert(!/checked/.test(html));assert(html.includes('data-public="publish"'));assert(html.includes('disabled'));
});
test('source options are optional and never selected by default',()=>{
 const html=ui.sourceMarkup({nodes:[{node:'product:0',title:'<Research>',department:'product'}],tasks:[],flows:[]});
 assert(!html.includes('<Research>'));assert(!html.includes('checked'));assert(html.includes('include_skill'));assert(html.includes('include_requirements'));
});
test('list maintains pager filters and does not claim disconnected state is empty success',()=>{
 assert(ui.listMarkup({items:[],total:470,page:3,pages:47,size:10}).includes('3 / 47'));
 assert(ui.offlineMarkup('offline').includes('offline'));assert(!ui.offlineMarkup('offline').includes('暂无共享内容'));
});
test('project paging derives pages from Store total and source context selects only current node',()=>{
 assert.equal(ui.pageCount({total:26,size:5}),6);
 const html=ui.sourceMarkup({nodes:[{node:'product:0',title:'Research',department:'product'},{node:'testing:1',title:'Execute',department:'testing'}],tasks:[{id:'batch',title:'Current batch'}],flows:[]},{type:'testing',node:'testing:1',task_id:'batch'});
 assert.match(html,/<option value="[^"]*batch[^"]*" selected>/);
 assert.equal((html.match(/ selected/g)||[]).length,1);
});
