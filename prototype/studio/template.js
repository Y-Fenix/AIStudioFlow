/* Interface exploration only. All studio, profile and node changes remain in memory. */
'use strict';

state.studio = 'main';
state.studios = [{id:'main',name:'我的游戏工作室'}, {id:'indie',name:'独立游戏实验室 · 示例'}];
state.projects[0].studio = 'main';
state.projects[1].studio = 'indie';
state.role = 'owner';
const studioRoles = [
  {id:'owner',name:'工作室负责人',home:'overview'},
  ...departments.map(d=>({id:d.id,name:d.title,home:d.id}))
];
const currentStudio = ()=>state.studios.find(s=>s.id===state.studio);
const currentRole = ()=>studioRoles.find(r=>r.id===state.role);
const studioProjects = ()=>state.projects.filter(p=>p.studio===state.studio);

const baseSidebar = sidebar;
sidebar = function(){
  baseSidebar();
  const label = $('.workspace-label');
  const picker = document.createElement('button');
  picker.className = 'workspace-label';
  picker.dataset.action = 'studios';
  picker.title = '切换工作室';
  picker.innerHTML = `<span class="avatar">S</span><span>${esc(currentStudio().name)}</span>${icon('down','small-icon')}`;
  label.replaceWith(picker);
  $('.user .small').textContent = currentRole().name;
  $('.user small').textContent = '身份决定默认首页';
};

const baseTopbar = topbar;
topbar = function(){
  if(project()) baseTopbar();
  else $('#topbar').innerHTML=`<div class="breadcrumb">${button('','toggle-sidebar','ghost icon-button','menu')}<span>工作室</span><span class="separator">/</span>${button('选择项目','projects','project-trigger','folder')}</div><div class="top-actions">${button('AI 待连接','view:settings','ai-status','spark')}${tag('交互原型')}<span class="avatar">YF</span></div>`;
  const avatar = $('.top-actions > .avatar');
  avatar.outerHTML = `<button class="profile-trigger" data-action="profile" title="身份与默认首页" aria-label="身份与默认首页"><span class="avatar">YF</span><span class="profile-role">${esc(currentRole().name)}</span>${icon('down','small-icon')}</button>`;
  $('.breadcrumb > span').outerHTML = `<button class="studio-crumb ghost" data-action="studios">${esc(currentStudio().name)}</button>`;
};

let entityPage = 1, pickerKind = 'project';
function renderEntities(query='',page=1){
  const list = (pickerKind==='studio'?state.studios:studioProjects()).filter(p=>p.name.toLowerCase().includes(query.toLowerCase()));
  const pages = Math.max(1,Math.ceil(list.length/5));
  entityPage = Math.max(1,Math.min(page,pages));
  const active = pickerKind==='studio'?state.studio:state.project;
  $('#project-results').innerHTML = `<div class="project-results">${list.slice((entityPage-1)*5,entityPage*5).map(p=>`<button class="project-result ${p.id===active?'active':''}" data-action="${pickerKind}:${esc(p.id)}"><span class="project-info"><span class="project-logo">${esc(p.logo||p.name[0])}</span><span><h3>${esc(p.name)}</h3><p>${esc(p.type||(state.projects.filter(x=>x.studio===p.id).length+' 个项目'))}</p></span></span>${p.id===active?tag('当前','green'):icon('chevron','small-icon')}</button>`).join('')||'<p class="small muted">没有匹配结果</p>'}</div><div class="pagination"><span>共 ${list.length} 个${pickerKind==='studio'?'工作室':'项目'}</span><div class="row"><button data-action="entity-page:-1" ${entityPage===1?'disabled':''} aria-label="上一页">‹</button><span>${entityPage} / ${pages}</span><button data-action="entity-page:1" ${entityPage===pages?'disabled':''} aria-label="下一页">›</button></div></div>`;
}
function pickEntity(kind){
  pickerKind = kind;
  modal(kind==='studio'?'选择工作室':'选择项目',`<p>${kind==='studio'?'工作室管理多个项目；项目资料、Skill 与交付物分别归属。':'当前工作室：'+esc(currentStudio().name)+'。各项目的输入与节点互不混用。'}</p><input id="project-search" type="search" placeholder="搜索${kind==='studio'?'工作室':'项目'}" style="width:100%"><div id="project-results"></div>`,`<span>每页 5 个 · 当前为内存演示</span>${button(kind==='studio'?'新增工作室':'新增项目',kind==='studio'?'new-studio':'new-project','','plus')}`);
  renderEntities();
}
projectPicker = ()=>pickEntity('project');
renderProjects = (query='',page=1)=>renderEntities(query,page);

function profileDialog(){
  modal('身份与默认首页',`<p>同一个项目可跨部门查看，身份决定从哪个工作区开始。</p><div class="field"><label for="profile-role">我的身份</label><select id="profile-role">${studioRoles.map(r=>`<option value="${r.id}" ${r.id===state.role?'selected':''}>${esc(r.name)}</option>`).join('')}</select></div><div class="info-strip" id="profile-home">默认首页：${currentRole().home==='overview'?'项目总览':currentRole().name}</div>`,`<span>仅本次预览有效，刷新恢复</span>${button('使用此身份并进入','save-profile','primary','arrow')}`);
}

const baseAction = action;
action = function(code){
  const [key,value] = code.split(':');
  if(key==='studios') return pickEntity('studio');
  if(key==='studio'){
    state.studio=value;
    const first=studioProjects()[0];
    closeModal();
    if(first){activateProject(first.id);navigate('overview');}else{state.project=null;state.decisions=[];navigate('overview');}
    return;
  }
  if(key==='entity-page') return renderEntities($('#project-search').value,entityPage+Number(value));
  if(key==='new-studio'||key==='new-project') return createEntityDialog(key==='new-studio'?'studio':'project');
  if(key==='create-studio'||key==='create-project'){
    const kind=key==='create-studio'?'studio':'project',name=$('#entity-name').value.trim();
    if(!name) return toast('请填写名称');
    const items=kind==='studio'?state.studios:studioProjects();
    if(items.some(p=>p.name===name)) return toast('已有同名'+(kind==='studio'?'工作室':'项目'));
    const id=kind+'-'+Date.now();
    if(kind==='studio'){
      state.studios.push({id,name});state.studio=id;state.project=null;state.decisions=[];closeModal();navigate('overview');createEntityDialog('project');
    }else{
      state.projects.push({id,studio:state.studio,name,type:$('#entity-type').value.trim()||'新项目',logo:name[0].toUpperCase()});
      activateProject(id);closeModal();navigate('overview');
    }
    return;
  }
  if(key==='profile') return profileDialog();
  if(key==='save-profile'){
    state.role=$('#profile-role').value;closeModal();
    const home=currentRole().home;
    home==='overview'||!project()?navigate('overview'):openNode(home,0);
    return;
  }
  if(!project()&&(key==='dept'||key==='node'||key==='variant'||key==='cycle'||key==='view'&&!['settings','overview'].includes(value))) return toast('请先在当前工作室创建或选择项目');
  return baseAction(code);
};
function createEntityDialog(kind){
  const label=kind==='studio'?'工作室':'项目';
  modal('新增'+label,`<p>${kind==='studio'?'先创建工作室，再在其中创建项目。':'归属工作室：'+esc(currentStudio().name)}</p><div class="field"><label for="entity-name">${label}名称</label><input id="entity-name" maxlength="80" placeholder="填写${label}名称"></div>${kind==='project'?'<div class="field"><label for="entity-type">项目方向</label><input id="entity-type" placeholder="例如：休闲解谜 / Unity / Android"></div>':''}`,`<span>演示数据，刷新后恢复</span>${button('创建'+label,'create-'+kind,'primary','plus')}`);
}
document.addEventListener('change',event=>{
  if(event.target.id==='profile-role'){
    const role=studioRoles.find(r=>r.id===event.target.value);
    $('#profile-home').textContent='默认首页：'+(role.home==='overview'?'项目总览':role.name);
  }
});

// Node-specific starter methods, kept separate from the user's exact test Skill snapshots.
const starterMethods = {
  product:[
    ['明确地区、平台、品类、目标玩家和调研时间窗。','按来源日期整理市场规模、玩家评论、渠道与付费动机；无数据时写出验证计划。','对机会列出支持证据、反证、成本约束与停止条件。','每条市场结论有来源；机会建议可以通过下一轮实验被证伪。'],
    ['拆解首局路径、核心循环、关卡节奏、经济系统、广告与内购触点。','区分实机观察、公开资料和包体静态证据；记录版本与分析工具。','只分析用户有权提供的包体；混淆、加密和不可读取部分列为缺口，不声称取得完整源码。','交付玩法、变现和实现对照表；每条借鉴建议说明差异化、成本与依据。'],
    ['定义玩家动机、操作反馈、胜负条件、成长循环与可调参数。','为广告与内购标明触发条件、奖励、防重复与失败恢复规则。','提出可衡量的首版实验，明确预算、时间窗、成功阈值和停止条件。','不虚构收益预测；每个商业假设有明确数据需求和验收方法。'],
    ['划定 MVP 必做、暂缓和排除范围，为需求分配稳定编号。','每条规则描述入口、前置状态、操作、状态迁移、结果与异常边界。','输出页面流程与低保真线框；逐条关联验收条件和待确认问题。','设计与开发能据此实施；测试能直接追溯到需求编号与可观察断言。']
  ],
  design:[
    ['从题材、用户、玩法与目标设备提取视觉约束。','给出两到三个可比较方向，标明配色、字体、形状、层级与参考来源。','选定方向后定义可复用 token，并记录商用授权与资源来源缺口。','视觉方案适配真实游戏场景，方向差异清楚，不用占位图冒充成品。'],
    ['按任务路径整理首屏、玩法、结算、广告与内购页面。','逐页设计正常、加载、空、异常、禁用与重试状态。','注明触控区域、安全区、多分辨率、文字溢出与无障碍要求。','交付页面流程、关键设计图和交互状态表；未知规则回到产品确认。'],
    ['按必需程度和复用率列出 UI、图标、角色、场景、动效与音频清单。','逐项明确尺寸、格式、透明通道、命名、图集与性能预算。','根据接通工具生成或整理素材；保留来源、版本与许可信息。','只有实际生成并可读取的文件才记为已交付；未生成的资产列为缺口。'],
    ['对照 PRD 和 UX 状态表核对全部必需页面与资源。','检查切图、锚点、九宫格、字体、动效参数和适配说明。','整理可追溯交付版本、缺失资产与开发可验收条件。','开发可按清单定位资源并实施；所有阻塞问题都有责任节点。']
  ],
  development:[
    ['只读梳理现有工程、模块边界、依赖、配置、存档和目标平台。','按需求编号拆分实现任务，明确接口契约、数据迁移和失败恢复。','评估性能、兼容性、可观测性、测试入口和回退策略。','方案与实际工程吻合；每个任务都有输入、输出、依赖和验收条件。'],
    ['核对已确认需求、设计交付与代码基线，仅修改当前授权范围。','实现核心路径及错误恢复，记录配置、资源和存档变更。','整理可审阅差异与逐需求实现映射，实际执行过的检查才写为完成。','改动可复核、可回退；不擅自拉取、提交或推送 Git，不修改 Figma。'],
    ['检查模块接口、依赖版本、资源引用、配置和初始化顺序。','围绕边界、重入、异步回调、生命周期和存档兼容检查错误路径。','把静态证据和实际运行结果分别记录；未执行的构建与运行检查明确标记。','交测阻塞、已知问题与未验证范围可定位；不把静态通过当成运行通过。'],
    ['记录本地分支与提交指纹、需求版本、资源版本和交测范围。','汇总变更、配置迁移、已知问题、测试建议和回退方式。','已有包体记录其平台和校验信息；没有包体时清楚注明未构建。','交测资料可复现基线；不自动构建、不自动提交，也不虚构交测包。']
  ],
  testing:[
    [],[],
    ['从失败断言和可达反例追踪共同调用链、状态与配置。','比较根因、触发条件和修复位置；同现象但不同根因必须拆分。','为每个根因保留证据位置、受影响用例与尚未证实的推断。','每个合并组有共同根因证据；无法确认时保留独立候选。'],
    ['区分确认缺陷、需求歧义、证据不足与重复问题。','按影响范围、触发条件、严重程度和证据完整度形成可批量审核的分组。','保留用户选择、暂缓原因与排除依据，不静默删除问题。','每条候选可追溯到原用例和根因；只有确认范围进入提单。'],
    ['读取目标 Bug 模板字段与枚举，缺失权限或字段时报告缺口。','按已确认根因生成标题、环境、前置条件、复现步骤、预期与实际结果。','一个根因保留关联用例和影响范围；静态推导的步骤注明未实机复现。','导出可审阅草稿，发布由用户决定；不编造截图、复现率或运行结果。'],
    ['对齐原 Bug、失败反例、需求与用例版本，读取指定修复代码基线。','重查原路径与相邻影响范围，比较修复前后证据并列出剩余缺口。','区分已证实的修复、仅可能修复和必须运行验证的项目。','不伪造修复概率；用户决定是否改为验证通过，状态变更不自动执行。']
  ],
  growth:[
    ['按目标商店整理包体、元数据、截图、分级、隐私和平台资料清单。','核对版本基线、已知阻塞与商店描述是否和实际能力一致。','列出上线所需人工审批、缺失资料及回退准备。','形成可追溯放行建议；未经确认不提交商店或对外发布。'],
    ['从真实卖点与目标受众提出素材钩子、脚本、规格和实验分组。','逐项定义渠道、预算上限、样本目标、归因窗口与停止条件。','区分已产出素材、待生产脚本与未经验证的转化假设。','不声称已投放或取得 ROI；实验预算与外部动作必须由人确认。'],
    ['核对数据来源、时间窗、时区、去重、币种与事件口径。','计算有真实数据支持的漏斗、留存、付费、广告收入与获客成本。','区分相关性和因果，用分群、版本与实验对照定位问题。','所有指标可追溯；数据不足不补造数值，结论附限制与下一步验证。'],
    ['对照事前确定的商业门槛与实际实验结果。','评估继续投入、调整方向、停止三种选择的证据与成本。','形成下一轮范围、负责人、预算、验证周期与停止条件。','建议基于真实结果且可追溯；最终投入由人决定，并回流产品节点。']
  ]
};
const baseDefaultSkill = defaultSkill;
defaultSkill = function(d,n){
  const sk=baseDefaultSkill(d,n),method=starterMethods[d]?.[n];
  if(!method?.length||sk.snapshot) return sk;
  const steps=method.slice(0,3).map((s,i)=>`${i+1}. ${s}`).join('\n');
  return {...sk,text:sk.text.replace(/## 工作步骤\n[\s\S]*?\n## 交付物/,`## 工作步骤\n${steps}\n\n## 验收门槛\n${method[3]}\n\n## 交付物`)};
};
const baseRender = render;
render = function(options={}){
  if(!project()&&state.view!=='settings'){
    sidebar();topbar();
    $('#content').innerHTML=heading('从第一个项目开始。','工作室中的每款游戏都有独立的流程、Skill 与交付记录。','','YOUR GAME STUDIO')+`<section class="panel empty-state">${icon('folder')}<h3>${esc(currentStudio().name)}暂无项目</h3><p>先创建项目，再进入产品、设计、开发与测试。</p><div class="row" style="justify-content:center;margin-top:22px">${button('新增项目','new-project','primary','plus')}${button('选择项目','projects')}</div></section>`;
    $('#prototype-switcher').hidden=true;
    return;
  }
  $('#prototype-switcher').hidden=false;
  baseRender(options);
};
render({keepScroll:true});
