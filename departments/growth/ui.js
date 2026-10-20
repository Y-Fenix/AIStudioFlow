export default {
  renderHome({project, escape}) {
    return `<div class="between"><div><span class="eyebrow">GROWTH MODULE</span><h3>将上线假设连接到可追溯数据</h3><p>${project ? `当前项目：${escape(project.name)}` : '选择项目后整理发行计划。'}</p></div><span class="tag">增长专属前端模块</span></div>`;
  },
  renderWorkspace({node, escape}) {
    if (!node) return '';
    return `<span class="eyebrow">GROWTH HANDOFF</span><h3>${escape(node.name)} · 交付检查</h3><p>预期产物：${escape(node.outputContract)}</p><p class="small muted">广告平台、商店和实时数据工具尚未接入；指标结论须附可核对的数据来源。</p>`;
  }
};
