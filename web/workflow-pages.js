/* Project workflows: collection → business-node overview → isolated node workspace. */
(function (root) {
  'use strict';
  const statuses = {idle:'尚未运行', queued:'排队中', running:'运行中', waiting_user:'待人工操作', completed:'已完成', failed:'失败', interrupted:'已中断', cancelled:'已取消'};
  const actions = {block_run_started:'开始运行',block_run_submit:'提交本步骤',block_run_continue:'继续下一节点',block_run_retry:'重试当前步骤',block_run_cancel:'取消运行',block_run_save_draft:'保存填写进度','block_run_save-draft':'保存填写进度',block_run_running:'开始执行',block_run_waiting_user:'等待人工操作',block_run_completed:'执行完成',block_run_failed:'执行失败',block_run_interrupted:'运行中断',block_run_queued:'已加入队列',block_run_published:'保存待审核交付'};
  const departments = {product:'产品', design:'设计', development:'开发', testing:'测试', growth:'发行增长'};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy = value => structuredClone(value);
  const groupId = step => step.group || step.instance || step.id;
  const button = (label, action, disabled = false, primary = false) => {
    const reasons = {create:'需要工作流创建权限',template:'需要工作流创建权限',edit:'需要流程及全部节点查看和编辑权限',start:'需要工作流执行权限',continue:'需要工作流执行权限','save-node':'准备下次运行后，可由有节点编辑权限的成员保存','skill-select':'需节点 Skill 导入权限，且处于下次运行配置视图','skill-import':'需节点 Skill 导入权限，且处于下次运行配置视图','skill-export':'需 Skill 查看及导出权限，运行快照不返回正文','skill-default':'需 Skill 编辑权限，且处于下次运行配置视图',page:'已到分页边界'};
    return `<button type="button" data-workflow="${escape(action)}" ${disabled ? `disabled title="${escape(reasons[action.split(':')[0]] || '当前权限不允许此操作')}"` : ''} class="${primary ? 'primary' : ''}">${escape(label)}</button>`;
  };
  const activeRun = run => run && !['completed','cancelled'].includes(run.status);
  const glyphs = {file:'M14 2H5v20h14V7l-5-5ZM14 2v6h5M8 12h8M8 16h6',spark:'m12 3 2 6 7 3-7 3-2 6-2-6-7-3 7-3 2-6Z',arrow:'M4 12h16m-6-6 6 6-6 6',check:'m5 12 4 4L19 6',link:'m9 15 6-6M8 16l-2 2a4 4 0 0 1-5-6l4-4a4 4 0 0 1 6 1M16 8l2-2a4 4 0 0 1 5 6l-4 4a4 4 0 0 1-6-1',upload:'M12 16V3m-4 4 4-4 4 4M4 15v5h16v-5',chevron:'m7 10 5 5 5-5',sliders:'M3 6h5m4 0h9M3 12h11m4 0h3M8 3v6M14 9v6',circle:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',play:'m8 5 11 7-11 7V5Z'};
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${glyphs[name] || glyphs.circle}"/></svg>`;

  function nodePresentation(id, run, readOnly = false) {
    const status = nodeStatus(id,run), step = run?.steps?.[run.cursor];
    let result;
    if (!run) result = {status:'idle',title:'准备好资料，开始工作流',hint:'运行将从流程首节点开始，使用各节点已保存的配置。人工操作与审核仍需完成。',action:'start',label:'开始工作流'};
    else if (status === 'completed') result = {status,title:'本节点步骤已完成',hint:'查看本节点交付与证据；步骤完成不等于原部门交付已通过审核。',action:step ? 'current' : '',label:'查看当前执行节点'};
    else if (step && groupId(step) !== id) result = {status,title:'此节点尚未执行',hint:'流程按保存的顺序推进，可前往当前执行节点处理。',action:'current',label:'查看当前执行节点'};
    else if (['queued','running'].includes(status)) result = {status,title:status === 'queued' ? '任务已排队' : '正在执行本节点',hint:'进度自动更新。可切换节点查看，任务不会因此重启。',action:'',label:''};
    else if (status === 'waiting_user') result = {status,title:step?.type === 'review' ? '交付就绪，等待人工审核' : step?.type === 'boundary' ? '等待你继续下一节点' : '等待你补充本步骤资料',hint:'在运行结果中处理当前步骤，平台不会替你确认或跳过证据门禁。',action:'result',label:'处理当前步骤'};
    else if (['failed','interrupted'].includes(status)) result = {status,title:status === 'failed' ? '执行失败，资料已保留' : '运行已中断，等待处理',hint:'查看真实错误与已完成步骤，核对后手动重试。',action:'result',label:'查看失败详情'};
    else result = {status,title:statuses[status] || '查看本次记录',hint:'本次运行使用冻结配置。修改配置请切换到“准备下次运行”。',action:'',label:''};
    return readOnly ? {...result,action:'',label:'',hint:'历史运行只读。'+result.hint} : result;
  }

  function projectNodes(flow, run = null) {
    if (run) {
      if (Array.isArray(run.groups) && run.groups.length) return run.groups.map(group => ({...group, kind:group.source_node ? 'reference' : 'task', frozen:true, permissions:flow?.nodes?.find(node => node.id === group.id)?.permissions || {view:false,edit:false,execute:false,skill_view:false,skill_edit:false,skill_import:false,skill_export:false}}));
      const groups = new Map();
      for (const step of run.steps || []) {
        if (step.type === 'boundary') continue;
        const id = groupId(step);
        if (!groups.has(id)) groups.set(id, {id, name:step.config?.label || step.node || '历史任务', source_node:step.node || '', kind:step.node ? 'reference' : 'task', frozen:true});
      }
      return [...groups.values()].map(group => ({...group,permissions:flow?.nodes?.find(node => node.id === group.id)?.permissions || {view:false,edit:false,execute:false,skill_view:false,skill_edit:false,skill_import:false,skill_export:false}}));
    }
    if (Array.isArray(flow?.nodes)) return flow.nodes;
    const nodes = [];
    for (const block of flow?.blocks || []) {
      const config = block.config || {};
      if (['node','task'].includes(block.type)) {
        nodes.push({id:block.id, name:config.label || config.node || '自定义任务', description:config.description || '', kind:block.type === 'node' ? 'reference' : 'task', source_node:config.node || '', inputs:config.inputs || '', skill:{name:config.skill_name || '节点 Skill', content:config.skill || '', source:config.skill === undefined ? 'default' : 'override'}, auto_next:!!config.auto_next, blocks:block.type === 'task' ? config.blocks || [] : [block]});
      } else {
        const last = nodes.at(-1);
        if (last?.legacy) last.blocks.push(block);
        else nodes.push({id:block.id, name:'自定义任务', description:'由原有连续积木组成', kind:'task', legacy:true, blocks:[block], inputs:'', auto_next:false});
      }
    }
    return nodes;
  }

  function latestRuns(runs) {
    const latest = new Map();
    for (const run of [...runs].sort((a,b) => String(b.created_at || b.updated_at || '').localeCompare(String(a.created_at || a.updated_at || '')))) {
      if (run.flow_id && !latest.has(run.flow_id)) latest.set(run.flow_id, run);
    }
    return latest;
  }

  function filterPage(items, runs, query = {}) {
    const latest = latestRuns(runs);
    for (const item of items) if (!latest.has(item.id) && item.last_run) latest.set(item.id,item.last_run);
    const matches = items.filter(item => item.name.toLocaleLowerCase().includes((query.query || '').trim().toLocaleLowerCase()) && (!query.status || (latest.get(item.id)?.status || 'idle') === query.status))
      .sort((a,b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    const size = [10,20,50].includes(Number(query.size)) ? Number(query.size) : 10;
    const pages = Math.max(1, Math.ceil(matches.length / size));
    const page = Math.max(1, Math.min(Number(query.page) || 1, pages));
    return {items:matches.slice((page - 1) * size, page * size), total:matches.length, pages, page, size, latest};
  }

  function nodeStatus(id, run) {
    if (!run) return 'idle';
    const steps = run.steps || [];
    const indices = steps.flatMap((step,index) => groupId(step) === id && step.type !== 'boundary' ? [index] : []);
    if (!indices.length) return 'idle';
    if (indices.every(index => steps[index].done || index < run.cursor)) return 'completed';
    if (indices.includes(run.cursor)) return run.status;
    return 'idle';
  }

  function patchNode(flow, id, patch) {
    const blocks = copy(flow.blocks || []);
    const index = blocks.findIndex(block => block.id === id);
    if (index < 0) throw Error('节点配置已变化，请重新进入流程');
    let block = blocks[index];
    if (!['task','node'].includes(block.type)) {
      let end = index + 1;
      while (end < blocks.length && !['task','node'].includes(blocks[end].type)) end++;
      const inner = blocks.splice(index, end - index);
      block = {id, type:'task', config:{label:'自定义任务', blocks:inner}};
      blocks.splice(index, 0, block);
    }
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) delete block.config[key];
      else block.config[key] = value;
    }
    if (patch.skill === null) delete block.config.skill_name;
    return {id:flow.id, name:flow.name, description:flow.description || '', revision:flow.revision, sources:copy(flow.sources || []), blocks};
  }

  function nodeEvents(run, id) {
    return (run?.events || []).filter(event => {
      const detail = event.detail || {};
      const step = run.steps?.[Number(detail.step ?? detail.cursor)];
      return (event.group || detail.group || detail.instance || (step && groupId(step))) === id;
    });
  }

  function beijingTime(value) {
    if (!value) return '未记录';
    const timestamp = typeof value === 'string' && /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(value) ? value.replace(' ','T') + 'Z' : value;
    const date = new Date(typeof timestamp === 'number' && timestamp < 1e12 ? timestamp * 1000 : timestamp);
    if (Number.isNaN(date.getTime())) return '未记录';
    return date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false});
  }

  root.WorkflowPages = {
    builder:null, host:null, view:'list', flow:null, currentRun:null, selectedNode:null,
    items:[], runs:[], memories:new Map(), drafts:new Map(), panels:new Map(), sequence:0,
    setup({builder, host}) { this.builder = builder; this.host = host; },
    current() { return this.path === this.host.path() && (!this.host.isShown || this.host.isShown()); },
    access() { return this.host.permissions(this.host.department?.() || 'product') || {}; },
    memory() {
      if (!this.memories.has(this.path)) this.memories.set(this.path, {query:'',status:'',size:10,page:1,scroll:0});
      return this.memories.get(this.path);
    },
    rememberScroll() { if (this.view === 'list' && this.path) this.memory().scroll = root.scrollY || 0; },
    async open(identity = '', run = null) {
      this.rememberScroll(); this.dispose();
      const ticket = ++this.sequence;
      const path = this.host.path();
      if (!path) throw Error('请先选择项目');
      this.path = path; this.startInput = '';
      const collection = await this.host.api(path + '/custom-flows');
      if (ticket !== this.sequence || path !== this.host.path()) return;
      this.items = collection.items || []; this.types = collection.types || {};
      const flow = identity ? await this.host.api(path + '/custom-flows/' + encodeURIComponent(identity)) : null;
      if (ticket !== this.sequence || path !== this.host.path()) return;
      const history = await this.host.api(path + '/block-runs' + (identity ? '?flow=' + encodeURIComponent(identity) : ''));
      if (ticket !== this.sequence || path !== this.host.path()) return;
      this.runs = history.items || [];
      let selected = run && typeof run === 'object' ? run : null;
      const runId = typeof run === 'string' ? run : !run && identity ? this.runs.find(item => item.flow_id === identity)?.id : null;
      if (runId) selected = await this.host.api(path + '/block-runs/' + encodeURIComponent(runId));
      if (ticket !== this.sequence || path !== this.host.path()) return;
      if (selected && selected.flow_id !== identity) throw Error('运行记录不属于当前工作流');
      this.flow = flow; this.currentRun = selected; this.selectedNode = null;
      this.view = identity ? 'home' : 'list';
      this.host.dirty(false); this.syncBuilder(); this.host.show(); this.mount();
      if (this.view === 'list') root.requestAnimationFrame?.(() => { if (this.current()) root.scrollTo?.(0, this.memory().scroll); });
    },
    dispose() { root.RunProgress?.reset(); this.abort?.abort(); this.abort = null; this.resizeObserver?.disconnect(); ++this.sequence; },
    syncBuilder() {
      if (!this.builder) return;
      this.builder.data = this.flow; this.builder.currentRun = this.currentRun;
      this.builder.runs = this.runs; this.builder.path = this.path;
      this.builder.readOnly = !!this.currentRun && this.runs.filter(run => run.flow_id === this.flow?.id)[0]?.id !== this.currentRun.id;
    },
    nodes() { return projectNodes(this.flow, this.currentRun); },
    source(node) { return node.source_node ? (departments[node.source_node.split(':')[0]] || node.source_node) + ' · ' + node.source_node : '自定义节点'; },
    draft(node) {
      const key = [this.path, this.flow.id, node.id].join('/');
      if (!this.drafts.has(key) || this.drafts.get(key).revision !== this.flow.revision) this.drafts.set(key, {inputs:node.inputs || '',skill:node.skill?.content || '',skill_name:node.skill?.name || '节点 Skill',dirty:false,skillDirty:false,revision:this.flow.revision});
      return this.drafts.get(key);
    },
    canEdit(node) { return !this.currentRun && !this.flow?.archived && !!this.access().flowEdit && node?.permissions?.edit !== false; },
    panel() {
      const key = [this.path,this.flow.id,this.selectedNode,this.currentRun?.id || 'draft'].join('/');
      if (!this.panels.has(key)) this.panels.set(key,{tab:this.currentRun ? 'result' : 'config',links:false,file:false,skill:false,linkText:'',feedback:''});
      return this.panels.get(key);
    },
    hasDrafts() { return this.flow && projectNodes(this.flow).some(node => this.draft(node).dirty); },
    page() {
      if (this.view === 'list') return this.listMarkup();
      if (!this.flow) return '<section class="panel workflow-empty">工作流读取中…</section>';
      return `<div class="workflow-pages">${this.heading()}${this.view === 'node' ? this.workspaceMarkup() : this.homeMarkup()}</div>`;
    },
    listMarkup() {
      const memory = this.memory(), result = filterPage(this.items, this.runs, memory);
      memory.page = result.page;
      const p = this.access();
      return `<div class="workflow-pages"><header class="workflow-heading"><div><h1>自定义工作流</h1><p>组合业务节点，按保存的配置逐次运行。</p></div><div class="row">${button('从团队模板创建','template',!p.flowCreate)}${button('新建工作流','create',!p.flowCreate,true)}</div></header>
        <section class="panel workflow-list-panel"><div class="workflow-filters"><label>名称搜索<input type="search" data-workflow-search value="${escape(memory.query)}" placeholder="搜索工作流名称"></label><label>最近运行状态<select data-workflow-status><option value="">全部状态</option>${Object.entries(statuses).map(([id,label]) => `<option value="${id}" ${memory.status === id ? 'selected' : ''}>${label}</option>`).join('')}</select></label></div>
        <div data-workflow-list>${this.rowsMarkup(result)}</div><div class="workflow-pagination" data-workflow-pagination>${this.paginationMarkup(result)}</div></section></div>`;
    },
    rowsMarkup(result) {
      const p = this.access();
      return result.items.map(flow => {
        const latest = result.latest.get(flow.id), status = latest?.status || 'idle';
        return `<article class="workflow-list-row"><div class="workflow-row-main"><button class="workflow-title-button" data-workflow="open:${escape(flow.id)}">${escape(flow.name)}</button><p>${escape(flow.description || '暂无说明')}</p><div class="workflow-meta"><span>${projectNodes(flow).length} 个节点</span><span class="workflow-status" data-status="${escape(status)}">${escape(statuses[status] || status)}</span><time>${escape(beijingTime(flow.updated_at))}</time></div></div><div class="row">${button('进入','open:' + flow.id)}<details class="workflow-more"><summary aria-label="${escape(flow.name)} 更多操作">•••</summary><div>${p.flowCreate ? button('复制配置','copy:' + flow.id) : ''}${p.flowEdit ? button('重命名','rename:' + flow.id) : ''}${p.flowDelete ? button('归档','archive:' + flow.id) : ''}${!p.flowCreate && !p.flowEdit && !p.flowDelete ? '<span class="small muted">仅可查看</span>' : ''}</div></details></div></article>`;
      }).join('') || `<div class="workflow-empty"><h2>${this.items.length ? '没有符合条件的工作流' : '还没有工作流'}</h2><p>${p.flowCreate ? '创建空白流程，或从有权使用的团队模板开始。' : '当前账号没有创建工作流权限。'}</p>${p.flowCreate ? button('创建工作流','create',false,true) : ''}</div>`;
    },
    paginationMarkup(result) {
      return `<span>共 ${result.total} 项</span><label>每页 <select data-workflow-size>${[10,20,50].map(size => `<option ${result.size === size ? 'selected' : ''}>${size}</option>`).join('')}</select></label><div class="row">${button('上一页','page:-1',result.page === 1)}<span>${result.page} / ${result.pages}</span>${button('下一页','page:1',result.page === result.pages)}</div>`;
    },
    heading() {
      const node = this.nodes().find(item => item.id === this.selectedNode);
      return `<nav class="workflow-breadcrumb" aria-label="面包屑">${button('自定义工作流','list')}<span>/</span>${this.view === 'node' ? button(this.flow.name,'home') : `<span>${escape(this.flow.name)}</span>`}${node ? `<span>/</span><span>${escape(node.name)}</span>` : ''}</nav><header class="workflow-heading"><div><div class="eyebrow">WORKFLOW / ${this.view === 'node' ? 'WORKSPACE' : 'OVERVIEW'}</div><h1>${escape(this.flow.name)}</h1><p>${escape(this.flow.description || '让资料、执行与交付在同一条流程里交接。')}</p></div><div class="row">${this.view === 'node' ? button('返回流程','home') : ''}<button data-workflow="edit" ${!this.access().flowEdit || this.flow.archived || this.flow.nodes?.some(item => item.permissions?.view === false || item.permissions?.edit === false) ? 'disabled title="需要流程及全部节点查看和编辑权限，归档流程只读"' : ''}>${icon('sliders')}编辑流程</button></div></header>`;
    },
    runSelector() {
      const runs = this.runs.filter(run => run.flow_id === this.flow.id);
      return `<label class="workflow-run-select">查看运行<select data-workflow-run><option value="">准备下次运行</option>${runs.map(run => `<option value="${escape(run.id)}" ${this.currentRun?.id === run.id ? 'selected' : ''}>${escape(beijingTime(run.created_at))} · ${escape(statuses[run.status] || run.status)} · ${escape(run.id.slice(0,8))}</option>`).join('')}</select></label>`;
    },
    stripMarkup(compact = false) {
      const nodes = this.nodes();
      return `<div class="workflow-node-strip ${compact ? 'compact has-continuation' : ''}" aria-label="工作流节点">${nodes.map((node,index) => {
        const status = nodeStatus(node.id,this.currentRun);
        const selected = this.selectedNode === node.id;
        return `<article class="workflow-node-card ${selected ? 'selected' : ''}"><button class="workflow-node-enter" data-workflow="node:${escape(node.id)}" aria-current="${selected ? 'step' : 'false'}"><span class="workflow-node-status" data-status="${escape(status)}" title="${escape(statuses[status] || status)}" aria-label="${escape(statuses[status] || status)}"></span><span class="workflow-node-title"><span class="workflow-node-number">${String(index + 1).padStart(2,'0')}</span><strong>${escape(node.name)}</strong></span><small>${escape(this.source(node))}</small>${compact ? '' : `<p>${escape(node.delivery || node.description || '查看节点输入、交付与证据')}</p><span class="workflow-enter-label">进入节点 →</span>`}</button></article>${index < nodes.length - 1 ? `<div class="workflow-connector"><span aria-hidden="true">→</span>${compact ? '' : `<label><input type="checkbox" data-workflow-auto="${escape(node.id)}" ${node.auto_next ? 'checked' : ''} ${this.currentRun || !this.access().flowEdit || node.permissions?.edit === false ? 'disabled' : ''}><span>${node.auto_next ? '自动执行' : '手动继续'}</span></label>`}</div>` : ''}`;
      }).join('') || '<p class="workflow-empty">流程尚无业务节点，请编辑流程添加。</p>'}</div>`;
    },
    homeMarkup() {
      const run = this.currentRun, step = run?.steps?.[run.cursor];
      return `<section class="panel workflow-run-toolbar">${this.runSelector()}<div class="row">${run ? button('查看运行详情','progress') : ''}<span data-workflow-run-status class="workflow-status" data-status="${escape(run?.status || 'idle')}">${escape(statuses[run?.status || 'idle'] || run?.status)}</span>${button(activeRun(run) ? '继续本次运行' : '开始新运行','start',!this.access().flowExecute,false)}</div></section><p class="workflow-notice">${run ? '当前展示所选运行快照。配置修改作用于下一次运行；完成不等于已获人工批准。' : '点击节点准备输入与 Skill；进入节点不会自动执行。'}</p>${this.stripMarkup()}<div class="workflow-continue" data-workflow-continue>${step?.type === 'boundary' && run.status === 'waiting_user' ? button('继续下一节点','continue',!this.access().flowExecute,true) : ''}</div><section class="panel workflow-start-input"><label>本次运行输入 / 来源与版本<textarea data-workflow-start-input placeholder="填写真实资料，或先进入节点准备输入。">${escape(this.startInput || '')}</textarea></label><p class="small muted">执行使用已保存配置和当前权限；人工输入、审核与测试证据门禁仍需完成。</p></section><section class="panel workflow-run-summary"><h2>本次运行</h2><p class="wb-progress" data-workflow-progress ${run?.status==='running'&&run.progress?'':'hidden'}>${escape(root.StudioWorkbench?.progressSummary(run?.progress)||'')}</p><div data-workflow-run-summary>${this.summaryMarkup()}</div></section>`;
    },
    summaryMarkup() {
      const run = this.currentRun;
      if (!run) return '<p class="muted">尚未选择运行记录。</p>';
      return `<p>运行编号：${escape(run.id)}</p><p>${escape(statuses[run.status] || run.status)} · 步骤 ${Math.min((run.cursor || 0) + 1,run.steps?.length || 0)} / ${run.steps?.length || 0}</p>${run.error ? `<p role="alert">${escape(run.error)}</p>` : ''}`;
    },
    workspaceMarkup() {
      const node = this.nodes().find(item => item.id === this.selectedNode);
      if (!node) return '<section class="panel workflow-empty">此运行中没有该节点，请返回流程重新选择。</section>';
      const p = node.permissions || {}, editable = this.canEdit(node), draft = this.currentRun ? node : this.draft(node), ui = this.panel();
      const skillVisible = p.skill_view !== false;
      this.syncBuilder();
      const skillName = this.currentRun ? node.skill_name || '已冻结规则' : draft.skill_name;
      const skillLabel = this.currentRun ? '运行快照' : node.skill?.source === 'override' ? '实例 Skill' : '默认 Skill';
      const presentation = nodePresentation(node.id,this.currentRun,this.builder.readOnly);
      const next = this.nodes()[this.nodes().findIndex(item => item.id === node.id)+1];
      return `<div class="workflow-sticky-strip"><div class="workflow-flow-caption">${icon('arrow')}<span>工作流节点</span><small>选择节点查看配置，切换不会执行任务</small></div>${this.stripMarkup(true)}</div>
        <div class="workflow-workspace-heading"><div class="workflow-workspace-title"><span class="workflow-node-emblem">${icon('file')}</span><div><span class="eyebrow">NODE ${String(this.nodes().findIndex(item => item.id === node.id)+1).padStart(2,'0')} / ${String(this.nodes().length).padStart(2,'0')}</span><h2>${escape(node.name)}</h2></div><span class="workflow-state-tag" data-workflow-node-state data-status="${presentation.status}">${escape(statuses[presentation.status])}</span></div>
        <div class="workflow-view-tabs" role="tablist" aria-label="节点视图"><button id="workflow-config-tab" type="button" role="tab" data-workflow="tab:config" aria-controls="workflow-config-panel" aria-selected="${ui.tab === 'config'}" tabindex="${ui.tab === 'config' ? '0' : '-1'}">节点配置</button><button id="workflow-result-tab" type="button" role="tab" data-workflow="tab:result" aria-controls="workflow-result-panel" aria-selected="${ui.tab === 'result'}" tabindex="${ui.tab === 'result' ? '0' : '-1'}">运行结果</button></div></div>
        <div class="workflow-workspace"><main class="workflow-main-column">
          <div id="workflow-config-panel" role="tabpanel" aria-labelledby="workflow-config-tab" ${ui.tab !== 'config' ? 'hidden' : ''}>
          <section class="panel node-panel workflow-node-config">
            <header class="node-head"><div><h2>准备任务资料</h2><p>${escape(node.description || '整理当前节点的资料、来源与版本。')}</p></div><span class="workflow-section-number" aria-hidden="true">01</span></header>
            <div class="panel-content">
              ${!this.currentRun ? `<div class="workflow-source-heading">需求来源<span>按需展开，可同时使用</span></div><div class="workflow-source-options"><button data-workflow="source:links" aria-expanded="${ui.links}" aria-controls="workflow-links-source">${icon('link')}<span>飞书 / 文档链接<small>保存来源链接</small></span>${icon('chevron')}</button><button data-workflow="source:file" aria-expanded="${ui.file}" aria-controls="workflow-file-source">${icon('upload')}<span>本地文件<small>读取文字资料</small></span>${icon('chevron')}</button></div>
              <div class="workflow-source-expanded" id="workflow-links-source" ${ui.links ? '' : 'hidden'}><label for="workflow-links">来源链接</label><textarea id="workflow-links" data-workflow-links placeholder="每行一个已核实的需求链接">${escape(ui.linkText)}</textarea><p>仅将链接加入输入，不自动读取文档正文。请同时提供可供分析的需求内容。</p>${button('加入输入','append-links',!editable)}</div>
              <div class="workflow-source-expanded" id="workflow-file-source" ${ui.file ? '' : 'hidden'}><label for="workflow-source-file">导入文件</label><input id="workflow-source-file" data-workflow-source-file type="file" accept=".txt,.md,text/plain,text/markdown" ${editable ? '' : 'disabled'}><p>支持 TXT / Markdown。读取后添加到当前草稿，保存后生效。</p></div><p class="workflow-source-feedback" data-workflow-source-feedback role="status">${escape(ui.feedback)}</p>` : '<p class="workflow-frozen-hint">本次运行的输入与 Skill 已冻结。修改请切换至“准备下次运行”。</p>'}
              <div class="field"><label for="workflow-node-input">输入内容 / 来源与版本<span data-workflow-count>${(draft.inputs || '').length} 字</span></label><textarea id="workflow-node-input" class="node-input" data-workflow-input aria-describedby="workflow-input-hint" placeholder="填写任务资料、来源与版本，作为本节点的执行依据。" ${editable ? '' : 'readonly'}>${escape(draft.inputs || '')}</textarea><p id="workflow-input-hint" class="workflow-field-hint">${this.currentRun ? '所选运行快照 · 只读' : '草稿仅属于当前流程节点，切换节点保留；运行使用已保存配置。'}</p></div>
              ${node.source_node?.startsWith('testing:') ? `<div class="workflow-source-link">${button('打开原测试工作台','testing')}<p class="small muted">关联真实批次并核对证据后才能继续。</p></div>` : ''}
            </div>
            <div class="workflow-skill-bar"><span class="workflow-skill-emblem">${icon('spark')}</span><div class="node-skill-inline">${skillVisible ? `<button class="skill-label" data-workflow="skill-toggle" aria-expanded="${ui.skill}">${escape(skillLabel)} · <span data-workflow-skill-name>${escape(skillName)}</span></button><div class="skill-actions">${button('选择 Skill','skill-select',!editable || p.skill_import === false)}${button('导入 Skill','skill-import',!editable || p.skill_import === false)}${button('导出 Skill','skill-export',p.skill_export === false || !!this.currentRun)}${button('恢复默认','skill-default',!editable || p.skill_edit === false)}</div>` : '<span class="small muted">没有 Skill 查看权限</span>'}</div></div>
            ${skillVisible ? `<details class="workflow-skill" ${ui.skill ? 'open' : ''}><summary>${escape(skillName)} · ${escape(skillLabel)}</summary><label class="field">Skill 规则<textarea data-workflow-skill ${editable && p.skill_edit !== false ? '' : 'readonly'}>${escape(this.currentRun ? '本次规则已冻结；运行记录不返回 Skill 正文。' : draft.skill)}</textarea></label></details>` : ''}
            <footer class="node-bottom"><span data-workflow-save-status role="status">${this.currentRun ? '已冻结 · 本次运行配置' : draft.dirty ? '有未保存修改' : '配置修订 '+escape(this.flow.revision)+' · 已保存'}</span><div class="row">${button('保存节点配置','save-node',!editable || !draft.dirty)}</div></footer>
            <input type="file" accept=".md,.txt,text/plain,text/markdown" data-workflow-skill-file hidden>
          </section></div>
          <div id="workflow-result-panel" role="tabpanel" aria-labelledby="workflow-result-tab" ${ui.tab !== 'result' ? 'hidden' : ''}>
          <section class="panel workflow-node-runtime"><div class="panel-title"><div><h2>运行结果</h2><p>交付、证据与审核分别记录，按真实步骤推进。</p></div><span class="workflow-section-number" aria-hidden="true">02</span></div><div class="panel-content"><div data-workflow-state-banner>${this.stateBannerMarkup()}</div><div id="builder-run-detail">${this.currentRun && this.builder.runMarkup ? this.builder.runMarkup(node.id) : '<div class="workflow-runtime-empty"><span class="workflow-empty-mark" aria-hidden="true">'+icon('file')+'</span><div><h3>尚未开始运行</h3><p>准备并保存节点配置后，开始工作流。未接通执行器的节点需要人工交付。</p></div></div>'}</div></div></section></div>
          <div class="workflow-primary-action" data-workflow-primary>${this.primaryMarkup()}</div>${this.currentRun ? button('查看运行详情','progress') : ''}
        </main><aside class="workflow-context-column"><section class="panel workflow-preparation"><div class="panel-title"><h2>本节点准备</h2><span class="eyebrow">CHECKLIST</span></div><div class="panel-content"><div class="workflow-check-row"><span data-workflow-input-check class="${draft.inputs?.trim() ? 'ready' : ''}">${icon(draft.inputs?.trim() ? 'check' : 'circle')}</span><div>输入资料<small data-workflow-input-summary>${draft.inputs?.trim() ? '已补充节点输入' : '可补充资料，或在执行步骤填写'}</small></div></div><div class="workflow-check-row"><span class="${skillVisible ? 'ready' : ''}">${icon(skillVisible ? 'check' : 'circle')}</span><div>执行 Skill<small>${escape(skillVisible ? skillName : '无正文查看权限')}</small></div></div>
          <div class="workflow-handoff"><span class="eyebrow">下一节点</span><strong>${escape(next?.name || '本流程结束')}${icon('arrow')}</strong>${next ? `<label class="workflow-auto-control"><input type="checkbox" role="switch" data-workflow-auto="${escape(node.id)}" ${node.auto_next ? 'checked' : ''} ${editable ? '' : 'disabled'}><span>${node.auto_next ? '自动执行' : '手动继续'}</span></label><p>${this.currentRun ? '运行快照只读，开关修改作用于下次运行。' : '自动执行不会跳过人工资料、审核和测试证据门禁。'}</p>` : '<p>完成当前节点后结束本流程。</p>'}</div></div></section>
          <section class="panel workflow-node-logs"><div class="panel-title"><h2>操作日志</h2><span class="tiny muted">北京时间</span></div><div class="log-body" data-workflow-logs>${this.logsMarkup()}</div></section><div class="workflow-context-selector">${this.runSelector()}</div></aside></div>`;
    },
    stateBannerMarkup() {
      const p = nodePresentation(this.selectedNode,this.currentRun,this.builder.readOnly);
      return `<div class="workflow-result-state" data-status="${p.status}" role="status">${icon(['queued','running'].includes(p.status) ? 'circle' : p.status === 'completed' ? 'check' : 'file')}<div><h3>${escape(p.title)}</h3><p>${escape(p.hint)}</p></div></div>`;
    },
    primaryMarkup() {
      const p = nodePresentation(this.selectedNode,this.currentRun,this.builder.readOnly);
      return `<div class="workflow-next-copy"><span class="workflow-action-icon">${icon('play')}</span><div><strong>${escape(p.title)}</strong><p>${escape(p.hint)}</p></div></div>${p.action ? button(p.label,p.action,!this.access().flowExecute && p.action === 'start',true) : ''}`;
    },
    logsMarkup() {
      return nodeEvents(this.currentRun,this.selectedNode).map(event => `<article><time>${escape(beijingTime(event.created_at))}</time><strong>${escape(actions[event.action] || '运行操作')}</strong><p>${escape(typeof event.detail === 'string' ? event.detail : event.detail?.message || event.detail?.reason || '')}</p></article>`).join('') || '<p class="muted">当前节点暂无操作记录。</p>';
    },
    redraw() { if (this.current()) { this.host.render(); this.mount(); } },
    setTab(tab, focus = false) {
      this.panel().tab = tab;
      const container = root.document?.querySelector('#content');
      if (!container) return;
      for (const name of ['config','result']) {
        const button = container.querySelector('#workflow-'+name+'-tab'), panel = container.querySelector('#workflow-'+name+'-panel');
        if (button) { button.setAttribute('aria-selected',String(name === tab)); button.tabIndex = name === tab ? 0 : -1; if (focus && name === tab) button.focus({preventScroll:true}); }
        if (panel) panel.hidden = name !== tab;
      }
      this.resizeRail?.();
    },
    refreshDraftUI() {
      if (this.currentRun) return;
      const node = this.nodes().find(item => item.id === this.selectedNode);
      if (!node) return;
      const container = root.document?.querySelector('#content'); if (!container) return;
      const draft = this.draft(node), status = container.querySelector('[data-workflow-save-status]'), button = container.querySelector('[data-workflow="save-node"]');
      if (status) status.textContent = draft.dirty ? '有未保存修改' : '配置修订 '+this.flow.revision+' · 已保存';
      if (button) button.disabled = !this.canEdit(node) || !draft.dirty || this.busy;
      const count = container.querySelector('[data-workflow-count]'); if (count) count.textContent = draft.inputs.length+' 字';
      const check = container.querySelector('[data-workflow-input-check]');
      if (check) { check.classList.toggle('ready',!!draft.inputs.trim()); check.innerHTML = icon(draft.inputs.trim() ? 'check' : 'circle'); }
      const summary = container.querySelector('[data-workflow-input-summary]'); if (summary) summary.textContent = draft.inputs.trim() ? '已补充节点输入' : '可补充资料，或在执行步骤填写';
    },
    refreshList() {
      const content = root.document?.querySelector('#content');
      if (!content) return;
      const result = filterPage(this.items,this.runs,this.memory()); this.memory().page = result.page;
      content.querySelector('[data-workflow-list]').innerHTML = this.rowsMarkup(result);
      content.querySelector('[data-workflow-pagination]').innerHTML = this.paginationMarkup(result);
    },
    mount() {
      this.abort?.abort(); this.abort = new AbortController();
      this.resizeObserver?.disconnect();
      const container = root.document?.querySelector('#content');
      if (!container) return;
      const signal = this.abort.signal;
      container.addEventListener('toggle', event => {
        if (event.target.matches('.workflow-skill')) { this.panel().skill = event.target.open; container.querySelector('[data-workflow="skill-toggle"]')?.setAttribute('aria-expanded',String(event.target.open)); }
      }, {signal,capture:true});
      container.addEventListener('keydown', event => {
        if (!event.target.matches('[role="tab"][data-workflow]') || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
        event.preventDefault(); this.setTab(event.key === 'Home' ? 'config' : event.key === 'End' ? 'result' : this.panel().tab === 'config' ? 'result' : 'config',true);
      }, {signal});
      container.addEventListener('click', event => {
        const target = event.target.closest('[data-workflow]');
        if (!target || target.disabled) return;
        event.preventDefault(); event.stopPropagation();
        this.action(target.dataset.workflow).catch(error => this.host.toast(error.message));
      }, {signal});
      container.addEventListener('input', event => {
        const target = event.target;
        if (target.matches('[data-workflow-search]')) { this.memory().query = target.value; this.memory().page = 1; this.refreshList(); }
        if (target.matches('[data-workflow-start-input]')) this.startInput = target.value;
        if (target.matches('[data-workflow-links]')) this.panel().linkText = target.value;
        if (target.matches('[data-workflow-input],[data-workflow-skill]') && !this.currentRun) {
          const node = this.nodes().find(item => item.id === this.selectedNode);
          if (!node || !this.canEdit(node)) return;
          const draft = this.draft(node); draft[target.matches('[data-workflow-input]') ? 'inputs' : 'skill'] = target.value;
          draft.dirty = true; if (target.matches('[data-workflow-skill]')) draft.skillDirty = true; this.host.dirty(true); this.refreshDraftUI();
        }
      }, {signal});
      container.addEventListener('change', event => this.change(event.target).catch(error => this.host.toast(error.message)), {signal});
      this.builder.bindRuntime?.(container);
      this.builder.schedule?.();
      const main = container.querySelector('.workflow-main-column'), rail = container.querySelector('.workflow-context-column'), strip = container.querySelector('.workflow-sticky-strip');
      this.resizeRail = () => {
        if (!main || !rail || !main.isConnected) return;
        rail.style.setProperty('--workflow-main-height',main.getBoundingClientRect().height+'px');
        container.querySelector('.workflow-pages')?.style.setProperty('--workflow-sticky-height',(strip?.getBoundingClientRect().height || 100)+'px');
      };
      if (root.ResizeObserver && main && rail) { this.resizeObserver = new root.ResizeObserver(this.resizeRail); this.resizeObserver.observe(main); if (strip) this.resizeObserver.observe(strip); this.resizeRail(); }
    },
    async change(target) {
      if (target.matches('[data-workflow-status],[data-workflow-size]')) {
        this.memory()[target.matches('[data-workflow-status]') ? 'status' : 'size'] = target.value;
        this.memory().page = 1; this.refreshList();
      } else if (target.matches('[data-workflow-run]')) {
        if (this.busy) { target.value = this.currentRun?.id || ''; return; }
        const ticket = ++this.sequence;
        const run = target.value ? await this.host.api(this.path + '/block-runs/' + encodeURIComponent(target.value)) : null;
        if (ticket !== this.sequence || !this.current()) return;
        if (run && run.flow_id !== this.flow.id) throw Error('运行记录不属于当前工作流');
        this.currentRun = run; root.RunProgress?.update('workflow:'+this.path+':'+run.id,run); this.syncBuilder(); this.redraw();
      } else if (target.matches('[data-workflow-auto]')) {
        const node = projectNodes(this.flow).find(item => item.id === target.dataset.workflowAuto);
        if (!this.canEdit(node)) return;
        if (this.busy) { target.checked = !target.checked; return; }
        this.busy = true; target.disabled = true;
        try { await this.savePatch(node.id,{auto_next:target.checked},{redraw:false}); target.closest('label').querySelector('span').textContent = target.checked ? '自动执行' : '手动继续'; }
        catch (error) { target.checked = !target.checked; throw error; }
        finally { this.busy = false; target.disabled = false; this.refreshDraftUI(); }
      } else if (target.matches('[data-workflow-source-file]')) {
        const file = target.files?.[0]; if (!file) return;
        const node = this.nodes().find(item => item.id === this.selectedNode), identity = [this.path,this.flow.id,this.selectedNode].join('/');
        if (!this.canEdit(node)) throw Error('当前节点只读');
        if (file.size > 700000) throw Error('文件不得超过 700KB');
        if (!/\.(txt|md)$/i.test(file.name)) throw Error('此入口仅支持 TXT / Markdown');
        const text = await file.text();
        if (!this.current() || this.currentRun || identity !== [this.path,this.flow.id,this.selectedNode].join('/')) return;
        const draft = this.draft(node); draft.inputs += '\n\n## 文件：'+file.name+'\n'+text; draft.dirty = true;
        this.panel().feedback = file.name+' · 读取成功，保存后生效'; this.host.dirty(true);
        const input = root.document.querySelector('[data-workflow-input]'); if (input) input.value = draft.inputs;
        root.document.querySelector('[data-workflow-source-feedback]').textContent = this.panel().feedback; this.refreshDraftUI();
      } else if (target.matches('[data-workflow-skill-file]')) {
        const file = target.files?.[0]; if (!file) return;
        if (file.size > 64000) throw Error('Skill 最多 16000 个字符');
        const node = this.nodes().find(item => item.id === this.selectedNode), path = this.path, flowId = this.flow.id;
        if (!this.canEdit(node) || node.permissions?.skill_import === false) throw Error('没有导入 Skill 权限');
        const content = await file.text();
        if (content.length > 16000) throw Error('Skill 最多 16000 个字符');
        if (!this.current() || this.path !== path || this.flow.id !== flowId || this.selectedNode !== node.id || this.currentRun) return;
        await this.savePatch(node.id,{skill:content,skill_name:file.name});
      }
    },
    discardDrafts() {
      if (this.path && this.flow) {
        const prefix = this.path + '/' + this.flow.id + '/';
        for (const key of this.drafts.keys()) if (key.startsWith(prefix)) this.drafts.delete(key);
      }
      this.host.dirty(false);
    },
    allowLeave() {
      const dirty = this.flow && projectNodes(this.flow).some(node => this.draft(node).dirty);
      if (!dirty) return true;
      if (!root.confirm('放弃未保存的节点配置？')) return false;
      this.discardDrafts(); return true;
    },
    async savePatch(id, patch, {redraw = true} = {}) {
      const path = this.path, flowId = this.flow.id, key = [path,flowId,id].join('/');
      const previousDraft = this.drafts.has(key) ? copy(this.drafts.get(key)) : null;
      await this.host.api(path + '/custom-flows',patchNode(this.flow,id,patch));
      const updated = await this.host.api(path + '/custom-flows/' + encodeURIComponent(flowId));
      if (!this.current() || this.path !== path || this.flow.id !== flowId) return;
      this.flow = updated; this.drafts.delete(key);
      const updatedNode = projectNodes(updated).find(node => node.id === id);
      if (previousDraft?.dirty && updatedNode) {
        const next = this.draft(updatedNode);
        if (!Object.hasOwn(patch,'inputs')) next.inputs = previousDraft.inputs;
        if (!Object.hasOwn(patch,'skill') && previousDraft.skillDirty) { next.skill = previousDraft.skill; next.skill_name = previousDraft.skill_name; next.skillDirty = true; }
        next.dirty = next.inputs !== (updatedNode.inputs || '') || next.skillDirty;
      }
      let dirty = false;
      for (const [key,draft] of this.drafts) { if (key.startsWith(path + '/' + flowId + '/')) { draft.revision = updated.revision; dirty ||= draft.dirty; } }
      this.host.dirty(dirty); this.syncBuilder(); if (redraw) this.redraw(); this.host.toast('已保存，作用于下次运行');
    },
    async action(code) {
      const [action,...parts] = code.split(':'), id = parts.join(':');
      if (this.busy) return;
      this.busy = true;
      try {
        if (['open','list','edit','create','template'].includes(action) && !this.allowLeave()) return;
        if (action === 'list') await this.open();
        else if (action === 'open') await this.open(id);
        else if (action === 'home') { this.view = 'home'; this.selectedNode = null; this.redraw(); }
        else if (action === 'node') { this.selectedNode = id; this.view = 'node'; this.redraw(); }
        else if (action === 'tab' || action === 'result') this.setTab(action === 'result' ? 'result' : id);
        else if (action === 'source') {
          const ui = this.panel(); ui[id] = !ui[id];
          root.document.querySelector('#workflow-'+(id === 'links' ? 'links' : 'file')+'-source').hidden = !ui[id];
          root.document.querySelector('[data-workflow="source:'+id+'"]').setAttribute('aria-expanded',String(ui[id]));
        } else if (action === 'append-links') {
          const node = this.nodes().find(item => item.id === this.selectedNode);
          if (!this.canEdit(node)) throw Error('当前节点只读');
          const text = this.panel().linkText.trim(); if (!text) throw Error('请先填写来源链接');
          const draft = this.draft(node); draft.inputs += '\n\n## 来源链接（未读取正文）\n'+text; draft.dirty = true;
          root.document.querySelector('[data-workflow-input]').value = draft.inputs; this.host.dirty(true);
          this.panel().feedback = '来源链接已加入草稿，请补充正文并保存'; root.document.querySelector('[data-workflow-source-feedback]').textContent = this.panel().feedback; this.refreshDraftUI();
        } else if (action === 'current') {
          const step = this.currentRun?.steps?.[this.currentRun.cursor]; if (step) { this.selectedNode = groupId(step); this.view = 'node'; this.panel().tab = 'result'; this.redraw(); }
        }
        else if (action === 'progress' && this.currentRun) root.RunProgress?.open('workflow:'+this.path+':'+this.currentRun.id,this.flow?.name || '工作流',this.currentRun);
        else if (action === 'page') { this.memory().page += Number(id); this.refreshList(); }
        else if (action === 'create' || action === 'template' || action === 'edit') {
          if (!(action === 'edit' ? this.access().flowEdit : this.access().flowCreate)) throw Error('没有编辑或创建工作流权限');
          this.dispose(); await this.builder.openFlowEditor(action === 'edit' ? this.flow : null);
        } else if (['copy','rename','archive'].includes(action)) await this.collectionAction(action,id);
        else if (action === 'start' || action === 'continue') {
          if (!this.access().flowExecute) throw Error('没有工作流执行权限');
          if (!activeRun(this.currentRun) && this.hasDrafts()) throw Error('请先保存所有已修改节点的配置，再开始工作流');
          if (!activeRun(this.currentRun)) {
            const path = this.path, flowId = this.flow.id;
            const run = await this.builder.startWorkflow(this.flow,this.startInput || '');
            if (!this.current() || this.path !== path || this.flow.id !== flowId) return;
            this.currentRun = run || this.builder.currentRun;
            this.runs = this.builder.runs || this.runs;
          }
          const step = this.currentRun?.steps?.[this.currentRun.cursor];
          this.selectedNode = step ? groupId(step) : this.nodes()[0]?.id;
          this.view = 'node'; this.panel().tab = 'result'; this.syncBuilder(); this.redraw();
          if(this.currentRun) root.RunProgress?.open('workflow:'+this.path+':'+this.currentRun.id,this.flow?.name || '工作流',this.currentRun);
        } else if (action === 'save-node') {
          const node = this.nodes().find(item => item.id === this.selectedNode);
          if (!this.canEdit(node)) throw Error('当前为只读视图');
          const draft = this.draft(node);
          if (draft.skillDirty && draft.skill.length > 16000) throw Error('Skill 最多 16000 个字符');
          const patch = {inputs:draft.inputs};
          if (draft.skillDirty && node.permissions?.skill_edit !== false && node.permissions?.skill_view !== false) Object.assign(patch,{skill:draft.skill,skill_name:draft.skill_name});
          const control = root.document?.querySelector('[data-workflow="save-node"]');
          if (control) { control.disabled = true; control.textContent = '保存中…'; control.setAttribute('aria-busy','true'); }
          try { await this.savePatch(node.id,patch,{redraw:false}); }
          finally { if (control) { control.textContent = '保存节点配置'; control.removeAttribute('aria-busy'); } }
        } else if (action.startsWith('skill-')) await this.skillAction(action);
        else if (action === 'testing') this.host.openTesting?.(this.nodes().find(node => node.id === this.selectedNode)?.source_node,{flow:this.flow.id,run:this.currentRun?.id,node:this.selectedNode});
      } finally { this.busy = false; this.refreshDraftUI(); }
    },
    async collectionAction(action,id) {
      const path = this.path, ticket = this.sequence;
      const flow = await this.host.api(path + '/custom-flows/' + encodeURIComponent(id));
      if (!this.current() || this.path !== path || ticket !== this.sequence) return;
      const p = this.access();
      if (action === 'archive') {
        if (!p.flowDelete) throw Error('没有归档权限');
        if (!root.confirm('归档工作流？历史运行仍会保留。')) return;
        await this.host.api(path + '/custom-flows',{action:'archive',id,revision:flow.revision});
      } else {
        if (!(action === 'copy' ? p.flowCreate : p.flowEdit)) throw Error('没有创建或编辑权限');
        const name = root.prompt('工作流名称',flow.name + (action === 'copy' ? ' 副本' : ''));
        if (!name?.trim()) return;
        await this.host.api(path + '/custom-flows',{id:action === 'copy' ? undefined : id,revision:action === 'copy' ? 0 : flow.revision,name:name.trim(),description:flow.description || '',blocks:flow.blocks,sources:flow.sources || []});
      }
      const result = await this.host.api(path + '/custom-flows');
      if (!this.current() || this.path !== path || ticket !== this.sequence) return;
      this.items = result.items || []; this.refreshList();
    },
    async skillAction(action) {
      const node = this.nodes().find(item => item.id === this.selectedNode), p = node.permissions || {};
      if (action === 'skill-toggle') {
        if (p.skill_view === false) throw Error('没有 Skill 查看权限');
        const details = root.document?.querySelector('.workflow-skill');
        if (details) { details.open = !details.open; this.panel().skill = details.open; root.document.querySelector('[data-workflow="skill-toggle"]')?.setAttribute('aria-expanded',String(details.open)); }
        return;
      }
      if (action === 'skill-export') {
        if (this.currentRun || p.skill_export === false || p.skill_view === false) throw Error('没有导出当前 Skill 权限');
        this.builder.download(this.draft(node).skill,this.draft(node).skill_name + '.md'); return;
      }
      if (!this.canEdit(node)) throw Error('当前为只读视图');
      if (action === 'skill-default') {
        if (p.skill_edit === false) throw Error('没有 Skill 编辑权限');
        if (root.confirm('恢复来源默认 Skill？仅修改当前流程实例。')) await this.savePatch(node.id,{skill:null});
      } else if (action === 'skill-import') {
        if (p.skill_import === false) throw Error('没有 Skill 导入权限');
        root.document.querySelector('[data-workflow-skill-file]').click();
      } else if (action === 'skill-select') {
        if (p.skill_import === false) throw Error('没有 Skill 导入权限');
        const path = this.path, flowId = this.flow.id, revision = this.flow.revision;
        await root.StudioSkillPicker.open({api:this.host.api,path,department:node.source_node?.split(':')[0] || 'all',target:node.name,modal:this.host.modal,close:()=>this.host.closeModal?.(),
          isCurrent:()=>this.current() && this.flow?.id === flowId && this.flow.revision === revision && this.selectedNode === node.id && !this.currentRun,
          save:async skill => { if (skill.content.length > 16000) throw Error('Skill 最多 16000 个字符'); if (!this.current() || this.flow?.id !== flowId || this.flow.revision !== revision || this.selectedNode !== node.id || this.currentRun) throw Error('当前节点已变化'); await this.savePatch(node.id,{skill:skill.content,skill_name:skill.name}); this.host.closeModal?.(); }});
      }
    },
    updateRun(run) {
      if (!this.current() || !run || run.flow_id !== this.flow?.id || this.currentRun && run.id !== this.currentRun.id) return;
      const previous = this.currentRun;
      this.currentRun = run; root.RunProgress?.update('workflow:'+this.path+':'+run.id,run); this.syncBuilder();
      const container = root.document?.querySelector('#content'); if (!container) return;
      for (const element of container.querySelectorAll('.workflow-node-enter')) {
        const id = element.dataset.workflow.slice(5), status = nodeStatus(id,run), dot = element.querySelector('.workflow-node-status');
        if (dot) { dot.dataset.status = status; dot.title = statuses[status] || status; dot.setAttribute('aria-label',statuses[status] || status); }
      }
      const summary = container.querySelector('[data-workflow-run-summary]'); if (summary) summary.innerHTML = this.summaryMarkup();
      const status = container.querySelector('[data-workflow-run-status]');
      if (status) { status.textContent = statuses[run.status] || run.status; status.dataset.status = run.status; }
      const nodeState = container.querySelector('[data-workflow-node-state]'), presentation = nodePresentation(this.selectedNode,run,this.builder.readOnly);
      if (nodeState) { nodeState.textContent = statuses[presentation.status] || presentation.status; nodeState.dataset.status = presentation.status; }
      const banner = container.querySelector('[data-workflow-state-banner]'); if (banner) banner.innerHTML = this.stateBannerMarkup();
      const primary = container.querySelector('[data-workflow-primary]'); if (primary) primary.innerHTML = this.primaryMarkup();
      const continueTarget = container.querySelector('[data-workflow-continue]');
      if (continueTarget) continueTarget.innerHTML = run.steps?.[run.cursor]?.type === 'boundary' && run.status === 'waiting_user' ? button('继续下一节点','continue',!this.access().flowExecute,true) : '';
      const startButton = container.querySelector('[data-workflow="start"]');
      if (startButton) startButton.textContent = activeRun(run) ? '继续本次运行' : '开始新运行';
      const logs = container.querySelector('[data-workflow-logs]');
      if (logs) { const scroll = logs.scrollTop; logs.innerHTML = this.logsMarkup(); logs.scrollTop = scroll; }
      const progress = container.querySelector('[data-workflow-progress]');
      if (progress) { progress.textContent = root.StudioWorkbench?.progressSummary(run.progress) || ''; progress.hidden = run.status !== 'running' || !progress.textContent; }
      const runtime = container.querySelector('#builder-run-detail');
      const runtimeChanged = !previous || JSON.stringify([previous.cursor,previous.status,previous.steps,previous.error,previous.output]) !== JSON.stringify([run.cursor,run.status,run.steps,run.error,run.output]);
      if (runtime && this.builder.runMarkup && runtimeChanged) {
        const draft = runtime.querySelector('#builder-step-value'), value = draft?.value, start = draft?.selectionStart, end = draft?.selectionEnd, draftScroll = draft?.scrollTop;
        const checks = [...runtime.querySelectorAll('#builder-run-checks input')].map(input => input.checked);
        const focused = runtime.contains(root.document.activeElement), scroll = runtime.scrollTop;
        const details = [...runtime.querySelectorAll('details')].map(detail => detail.open);
        runtime.innerHTML = this.builder.runMarkup(this.selectedNode);
        if (previous?.id === run.id && previous?.cursor === run.cursor) {
          const next = runtime.querySelector('#builder-step-value');
          if (next && value !== undefined) { next.value = value; next.scrollTop = draftScroll; if (focused) { next.focus({preventScroll:true}); next.setSelectionRange(start,end); } }
          runtime.querySelectorAll('#builder-run-checks input').forEach((input,index) => { if (checks[index] !== undefined) input.checked = checks[index]; });
        }
        runtime.querySelectorAll('details').forEach((detail,index) => { if (details[index] !== undefined) detail.open = details[index]; });
        runtime.scrollTop = scroll;
      }
      const runtimeProgress = runtime?.querySelector('[data-builder-progress]');
      if (runtimeProgress) { runtimeProgress.textContent = root.StudioWorkbench?.progressSummary(run.progress) || ''; runtimeProgress.hidden = run.status !== 'running' || !runtimeProgress.textContent || (this.selectedNode && run.steps?.[run.cursor]?.group !== this.selectedNode); }
    }
  };
  if (typeof module !== 'undefined') module.exports = {projectNodes,filterPage,nodeStatus,nodePresentation,patchNode,nodeEvents,beijingTime,escape};
})(globalThis);
