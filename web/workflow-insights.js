/* Read models only: consume the already-authorized response, never fetch private evidence. */
globalThis.WorkflowInsights = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const labels = {passed:'静态证据支持', failed:'发现异常依据', needs_runtime:'需运行验证',
    requirement_unclear:'需求待确认', insufficient_evidence:'证据不足', not_run:'未审查', skipped:'未执行', runner_error:'运行异常'};
  const verdicts = {logic_assertions_passed:'静态回归证据支持，待人工决定', still_reproducible:'仍有异常依据', insufficient_evidence:'回归证据不足'};
  const unresolved = new Set(['needs_runtime','requirement_unclear','insufficient_evidence','not_run','skipped','runner_error']);
  const panels = new Map();

  function QA_traceRows(task) {
    const artifacts = task.artifacts || {}, generated = artifacts['0'] || {}, execution = artifacts['1'] || {};
    const requirements = task.requirements || [], points = generated.points || [], cases = generated.cases || [];
    const sources = new Map(requirements.map(x => [x.id, x])), pointMap = new Map(points.map(x => [x.id, x]));
    const used = new Set(), represented = new Set();
    const rows = cases.map(item => {
      const pointIds = item.point_ids || [], linkedPoints = pointIds.map(id => pointMap.get(id)).filter(Boolean);
      pointIds.forEach(id => used.add(id));
      const linkedSources = [...new Set(linkedPoints.map(p => p.requirement_id))].map(id => sources.get(id)).filter(Boolean);
      linkedSources.forEach(s => represented.add(s.id));
      const mapping = (execution.case_mapping || []).find(m => m.case_id === item.id);
      const results = (execution.results || []).filter(r => execution.method === 'static_code_review'
        ? (r.case_id || r.id) === item.id : mapping?.result_ids?.includes(r.id));
      const status = ['failed','requirement_unclear','insufficient_evidence','needs_runtime','runner_error','not_run','skipped','passed']
        .find(state => results.some(r => r.status === state)) || 'not_run';
      const roots = (artifacts['2']?.groups || []).filter(g => g.result_ids?.some(id => results.some(r => r.id === id)));
      const rootIds = new Set(roots.map(g => g.root_cause_id));
      const gaps = (generated.gaps || []).filter(g => pointIds.includes(g.point_id)).map(g => g.reason);
      const missingPointIds = pointIds.filter(id => !pointMap.has(id));
      if (!pointIds.length || missingPointIds.length) gaps.push('测试点未完整关联');
      if (!linkedSources.length) gaps.push('需求来源不可见或未关联');
      const citations = results.flatMap(r => (r.assertions || []).flatMap(a => a.call_chain || []));
      return {caseId:item.id, title:item.title, pointIds, points:linkedPoints, sources:linkedSources, results, status, roots, isStatic:execution.method === 'static_code_review',
        citations, gaps, unresolved:unresolved.has(status) || gaps.length > 0 || results.some(r =>
          unresolved.has(r.status) || (r.assertions || []).some(a => unresolved.has(a.status) || Boolean(a.gap))),
        bugs:(artifacts['4']?.linked_records || []).filter(b => rootIds.has(b.root_cause_id)),
        regressions:(task.regression?.roots || []).filter(r => rootIds.has(r.root_cause_id))};
    });
    for (const point of points.filter(p => !used.has(p.id))) {
      const source = sources.get(point.requirement_id);
      if (source) represented.add(source.id);
      rows.push({caseId:'',title:point.title,pointIds:[point.id],points:[point],sources:source?[source]:[],results:[],
        status:'not_run',roots:[],bugs:[],regressions:[],citations:[],unresolved:true,
        gaps:[...(generated.gaps || []).filter(g => g.point_id === point.id).map(g => g.reason),'测试点尚无关联用例']});
    }
    for (const source of requirements.filter(r => !represented.has(r.id))) {
      rows.push({caseId:'',title:'来源尚未关联测试点',pointIds:[],points:[],sources:[source],results:[],status:'not_run',
        roots:[],bugs:[],regressions:[],citations:[],unresolved:true,gaps:['需求来源尚未拆解或关联']});
    }
    return rows;
  }

  function QA_page(rows, {filter='all', page=1, size=10}={}) {
    size = [10,20,50,100].includes(Number(size)) ? Number(size) : 10;
    const selected = rows.filter(r => filter === 'all' || (filter === 'unresolved' ? r.unresolved : r.status === filter));
    const pages = Math.max(1, Math.ceil(selected.length / size));
    page = Math.max(1, Math.min(Number(page) || 1, pages));
    return {items:selected.slice((page-1)*size, page*size), total:selected.length, pages, page, size};
  }

  function QA_renderRows(rows) {
    return rows.length ? rows.map(row => `<details class="workflow-trace-row" data-trace-row="${esc(JSON.stringify(row.caseId ? ['case',row.caseId] : row.pointIds.length ? ['points',...row.pointIds] : ['sources',...row.sources.map(s => s.id)]))}"><summary class="workflow-trace-head"><strong>${esc(row.caseId || '待补用例')} · ${esc(row.title)}</strong><span data-trace-status="${esc(row.status)}">${esc((!row.isStatic&&{passed:'关联检查通过',failed:'关联检查异常'}[row.status])||labels[row.status]||'状态未知')}${row.isStatic?'（静态）':''}</span></summary><div class="workflow-trace-body">
      <p><b>需求来源</b> ${row.sources.map(s => esc(s.source)+' · v'+esc(s.version ?? '未记录')).join('；') || '未关联或无查看权限'}</p>
      <p><b>测试点</b> ${row.points.map(p => esc(p.id)+' '+esc(p.title)).join('；') || '未关联'}</p>
      ${row.points.filter(p => p.quote).map(p => `<blockquote>${esc(p.quote)}</blockquote>`).join('')}
      <p><b>源码引用</b> ${row.citations.map(c => esc(c.file)+':'+esc(c.line)).join('；') || '暂无已保存引用'}</p>
      <p><b>已确认根因</b> ${row.roots.map(r => esc(r.title)).join('；') || '未关联'}</p>
      <p><b>飞书 Bug</b> ${row.bugs.map(b => esc(b.record_id)).join('；') || '未关联'} <b>回归</b> ${row.regressions.map(r => esc(verdicts[r.verdict] || '结论待核对')).join('；') || '未记录'}</p>
      ${row.gaps.length?`<p class="workflow-unresolved">缺口：${row.gaps.map(esc).join('；')}</p>`:''}
      ${row.results.flatMap(r => r.assertions || []).filter(a => a.gap).map(a => `<p class="workflow-unresolved">${esc(a.gap)}${a.next_action?' · 下一步：'+esc(a.next_action):''}</p>`).join('')}
    </div></details>`).join('') : '<p class="muted">当前筛选下没有记录。</p>';
  }

  function QA_evidencePanel(task) {
    const rows = QA_traceRows(task), pending = rows.filter(r => r.unresolved).length;
    return `<details class="workflow-insights evidence" id="workflow-insights"><summary>交付与证据 · ${rows.length} 条关联记录 · ${pending} 条待补证据或关联</summary><p class="small muted">仅展示当前可见数据的实际关联；关联数量不代表需求完整覆盖。静态支持不等于客户端实测通过。</p><div class="workflow-trace-controls"><label>查看范围 <select data-trace-filter><option value="all">全部关联</option><option value="unresolved">待补证据 / 未审查</option><option value="failed">异常依据</option><option value="passed">静态证据支持</option></select></label><label>每页 <select data-trace-size>${[10,20,50,100].map(n => `<option>${n}</option>`).join('')}</select></label></div><div data-trace-rows></div><div class="workflow-trace-pagination"><button type="button" data-trace-page="previous">上一页</button><span data-trace-page-label></span><button type="button" data-trace-page="next">下一页</button></div></details>`;
  }

  function QA_mount(root, task) {
    const panel = root.querySelector('#workflow-insights');
    if (!panel) return;
    const key = task.id, saved = panels.get(key) || {open:false,filter:'all',page:1,size:10,expanded:new Set()};
    panels.set(key, saved);
    // Store only UI preferences; never retain task contents across navigation.
    if (panels.size > 100) panels.delete(panels.keys().next().value);
    panel.open = saved.open;
    const filter = panel.querySelector('[data-trace-filter]'), size = panel.querySelector('[data-trace-size]');
    filter.value = saved.filter; size.value = String(saved.size);
    const rows = QA_traceRows(task);
    function paint() {
      const page = QA_page(rows, saved); saved.page = page.page;
      panel.querySelector('[data-trace-rows]').innerHTML = QA_renderRows(page.items);
      panel.querySelectorAll('[data-trace-row]').forEach(row => {
        const key = row.dataset.traceRow;
        row.open = saved.expanded.has(key);
        const remember = open => open ? saved.expanded.add(key) : saved.expanded.delete(key);
        row.querySelector('summary').onclick = () => remember(!row.open);
        row.ontoggle = () => {if (row.isConnected) remember(row.open)};
      });
      panel.querySelector('[data-trace-page-label]').textContent = `${page.page} / ${page.pages} · 共 ${page.total} 条`;
      panel.querySelector('[data-trace-page="previous"]').disabled = page.page === 1;
      panel.querySelector('[data-trace-page="next"]').disabled = page.page === page.pages;
    }
    panel.ontoggle = () => {saved.open = panel.open};
    panel.onchange = event => {
      if (event.target === filter) {saved.filter = filter.value; saved.page = 1}
      if (event.target === size) {saved.size = Number(size.value); saved.page = 1}
      paint();
    };
    panel.onclick = event => {
      const action = event.target.closest('[data-trace-page]');
      if (action) {saved.page += action.dataset.tracePage === 'next' ? 1 : -1; paint()}
    };
    paint();
  }

  function checkSkill(skill={}) {
    const text = skill.content || '', issues = [];
    const rules = [['输入与适用范围',/输入|适用|前置|input|when to use/i], ['输出与交付约定',/输出|交付|返回|output|deliverable/i],
      ['证据与来源要求',/证据|引用|来源|evidence|citation/i], ['边界与失败处理',/边界|失败|缺口|不得|禁止|error|failure|limit/i]];
    if (!text.trim()) issues.push('Skill 正文为空，或当前账号无正文查看权限。');
    const dependencies = [...text.matchAll(/\]\(([^)\s]+)(?:\s+[^)]*)?\)/g)].map(m => m[1])
      .filter(target => !/^(?:[a-z][a-z0-9+.-]*:|#|\/)/i.test(target));
    for (const target of new Set(dependencies)) issues.push(`依赖文件未随单 Markdown 导入：${target}；请将必要规则写入正文。`);
    return {checks:rules.map(([label, pattern]) => ({label,found:pattern.test(text)})), issues,
      sha256:skill.sha256 || '', evaluated:false};
  }

  function renderSkillCheck(skill={}) {
    const result = checkSkill(skill);
    return `<div class="workflow-skill-check"><p><strong>${esc(skill.name || '当前节点 Skill')}</strong></p><p>这是文字规则检查；关键词命中仅表示找到相关声明。<strong>未做样本评测</strong>，不代表业务质量达标。</p><p>来源：${esc(skill.source_kind || '未记录')}<br>规则指纹：<code>${esc(result.sha256 || '未记录')}</code></p><ul>${result.checks.map(c => `<li>${esc(c.label)}：${c.found?'找到相关文字':'未找到明确声明，请核对'}</li>`).join('')}</ul>${result.issues.map(x => `<p>${esc(x)}</p>`).join('')}<p>规则修改不会自动证明质量改善；需用固定需求样例核对漏测、重复、无依据结论与审核修改量。</p></div>`;
  }
  return {QA_traceRows, QA_page, QA_renderRows, QA_evidencePanel, QA_mount, checkSkill, renderSkillCheck};
})();
