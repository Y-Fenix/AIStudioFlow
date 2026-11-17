const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync(require.resolve('../web/app.js'),'utf8');
function setup(selected=0){
 const ctx={project:{id:'p'},task:{id:'t',stage:0,jobs:[{id:'g',status:'running'}],automation:{enabled:false}},selectedStage:selected,continuationWatchUntil:0,Date,notice:()=>{},render:()=>{},QA_CaseLibrary:{view:'workspace'},FocusWorkspace:{requestProgress:key=>ctx.opened=key},setInterval:fn=>ctx.tick=fn};
 ctx.activeJob=()=>ctx.task.jobs.find(j=>['queued','running'].includes(j.status));vm.createContext(ctx);
 vm.runInContext(source.slice(source.indexOf('let polling=false;'),source.indexOf('async function queueOperation')),ctx);return ctx;
}
test('completed source continues polling and follows next node without full autopilot',async()=>{
 const c=setup();c.api=async()=>({id:'t',stage:0,jobs:[{id:'g',status:'completed'}],automation:{enabled:false}});
 await c.tick();assert(c.continuationWatchUntil>Date.now());
 c.api=async()=>({id:'t',stage:1,jobs:[{id:'e',stage:1,status:'running'}],automation:{enabled:false}});
 await c.tick();assert.equal(c.selectedStage,1);assert.equal(c.opened,JSON.stringify(['p','t',1]));
});
test('automatic progression does not steal the page while reading a different node',async()=>{
 const c=setup(2);c.api=async()=>({id:'t',stage:1,jobs:[{id:'e',stage:1,status:'running'}],automation:{enabled:false}});
 await c.tick();assert.equal(c.selectedStage,2);assert.equal(c.opened,undefined);
});
