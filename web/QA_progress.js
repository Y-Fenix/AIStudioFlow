'use strict';
function QA_progressModel(job, options={}) {
 let p=job?.progress||{};if(typeof p==='string'){try{p=JSON.parse(p)}catch{p={}}}if(!p||typeof p!=='object')p={};
 const edgeAction=typeof p.continuation_detail==='string'&&p.continuation_state?('节点自动继续：'+p.continuation_detail):'';
 const status=job?.status||'',number=v=>Number.isFinite(v)&&v>=0?v:null;
 const batch=number(p.batch),batches=number(p.batches),completed=number(p.completed),total=number(p.total);
 if(job?.kind && job.kind!=='generate'){
  const name=({execute:'静态检测',static_review:'静态检测',attribution:'问题归因',regression:'回归检查'})[job.kind]||'节点任务';
  let phase=({queued:'排队等待执行',running:'正在处理',completed:'处理完成',failed:'执行失败',interrupted:'执行中断',cancelled:'运行已终止',waiting_user:'等待处理'})[status]||'状态待更新';
  if(status==='running')phase=({preparing:'准备审查',started:'等待模型响应',running:'模型请求进行中',completed:'本次模型调用已完成，继续审查',retrying:'连接暂时异常，正在重试',validation_repair:'结果校验未通过，正在校正'})[p.state]||phase;
  const age=number(p.seconds_since_response),updated=number(p.progress_updated_at),now=number(options.now);
  const seconds=age===null?null:Math.floor(age+(updated!==null&&now!==null?Math.max(0,now-updated):0));
  let response=number(p.events_received)>0?(seconds!==null?`距最近可观察事件 ${seconds} 秒`:`已观察到 ${p.events_received} 个模型事件`):'尚未观察到模型响应';
  if(p.workers>1)response=`最近更新的请求：${response}`;
  if(status!=='running')response=({queued:'尚未开始执行',completed:'任务已完成',failed:'任务已失败',interrupted:'任务已中断',cancelled:'任务已终止',waiting_user:'等待处理'})[status]||'活动状态待更新';
  const agent=p.execution_engine==='project_agent';
  if(agent){
   const packageTotal=number(p.batch_total),calls=number(p.tool_calls),commands=number(p.commands_completed),activity=[];
   if(status==='running')phase='项目Agent共享调查'+(batch>0&&packageTotal>0?` · 工作包 ${batch} / ${packageTotal}`:' · 工作包信息待返回');
   if(calls!==null)activity.push(`已调用工具 ${calls} 次`);
   if(commands!==null)activity.push(`已结束命令 ${commands} 次`);
   if(typeof p.last_tool==='string'&&p.last_tool.trim())activity.push('最近工具：'+(({command_execution:'命令执行',mcp_tool_call:'MCP工具调用',web_search:'网络搜索',file_change:'文件变更'})[p.last_tool]||p.last_tool));
   if(activity.length){
    // Command completion is an observed event, never a success or case-validation count.
    const observed=calls>0||commands>0||typeof p.last_tool==='string'&&!!p.last_tool.trim();
    let base=response.replace(/^最近更新的请求：/,'');
    if(status==='running'&&observed&&!(number(p.events_received)>0))base='';
    response=(p.workers>1?'最近更新的请求：':'')+[...activity,...(base?[base]:[])].join(' · ');
   }
  }
  const summary=total>0&&completed!==null?`${agent?'已校验':'已处理'} ${completed} / ${total} 条`:agent?'已校验数量待返回':phase;
  return {status,title:name,summary,phase,response,action:edgeAction|| (job.error?`任务停止：${job.error}`:status==='completed'?'请查看节点结果。':'任务状态会自动更新。'+(agent&&p.workers>1?' 允许多个工作包并发；活动显示最近更新的请求，不代表唯一在途请求。':'')),stages:[{label:name,detail:summary,state:status==='completed'?'done':status==='running'?'current':'pending'}],source:'',duration:options.duration||''};
 }

 const labels={design:'用例设计',audit:'反向审计',merged:'汇总与校验'};
 let summary='正在准备进度信息',phase='正在准备任务';
 if(batches>0&&completed!==null)summary=`已完成 ${completed} / ${batches} 个需求分段`;
 else if(total>0&&completed!==null)summary=`已处理 ${completed} / ${total} 条`;
 if(p.phase==='merged')phase='汇总与校验';
 else if(batch!==null&&batches>0)phase=`最近更新：需求分段 ${batch} / ${batches} · ${labels[p.phase]||'处理中'}`;
 else if(p.state==='validation_repair')phase='结果校验未通过，正在校正';
 else if(p.state==='retrying')phase='连接暂时异常，正在重试';
 else if(status==='running')phase='正在处理';
 if(status==='queued'){summary='任务已排队';phase='排队等待执行';}
 if(status==='completed'){summary='任务已完成';phase='处理完成';}
 if(status==='failed'||status==='interrupted'){summary='任务未完成';phase=status==='failed'?'执行失败':'执行中断';}
 const age=number(p.seconds_since_response),updated=number(p.progress_updated_at),now=number(options.now);
 const seconds=age===null?null:Math.floor(age+(updated!==null&&now!==null?Math.max(0,now-updated):0));
 const response=number(p.events_received)>0&&seconds!==null?`距最近可观察事件 ${seconds} 秒`:'尚未观察到模型响应';
 let action='当前无需操作，完成后可查看结果；请保持本机服务运行。';
 if(status==='queued')action='当前无需操作，任务将在队列中等待执行。';
 if(status==='completed')action=options.automation?'全自动模式已开启，请查看后续节点状态。':'请查看生成的用例和待确认问题，再决定是否继续。';
 if(status==='completed'&&edgeAction)action=edgeAction;
 if(status==='failed'||status==='interrupted')action=job.error?`任务停止：${job.error}`:'任务已停止，请查看运行详情。';
 const title=({queued:'测试用例等待生成',running:'正在生成测试用例',completed:'测试用例生成完成',failed:'测试用例生成失败',interrupted:'测试用例生成已中断',cancelled:'测试用例生成已终止'})[status]||'测试用例生成';
 const finished=status==='completed',merging=p.phase==='merged',working=status==='running';
 const stages=[{label:'需求准备',detail:Number.isFinite(options.sources)?`已导入 ${options.sources} 份来源`:'来源信息暂无',state:'done'},
  {label:'分段生成与审计',detail:batches>0&&completed!==null?`已完成 ${completed} / ${batches} 个需求分段`:(working?'正在处理，分段信息暂无':'等待执行'),state:finished||merging?'done':working?'current':'pending'},
  {label:'汇总与校验',detail:finished?'已完成':merging?'正在汇总与校验':'等待前序步骤完成',state:finished?'done':merging?'current':'pending'}];
 return {status,title,summary,phase,response,action,stages,source:typeof p.source==='string'?p.source:'',duration:options.duration||''};
}
if(typeof module!=='undefined')module.exports={QA_progressModel};
