export default {
  renderHome({project, escape}) {
    return `<div class="between"><div><span class="eyebrow">PRODUCT MODULE</span><h3>从玩家问题到可验证需求</h3><p>${project ? `当前项目：${escape(project.name)}` : '选择项目后开始整理产品输入。'}</p></div><span class="tag">产品专属前端模块</span></div>`;
  },
  renderWorkspace({node, escape}) {
    if (!node) return '';
    return `<span class="eyebrow">PRODUCT HANDOFF</span><h3>${escape(node.name)} · 交付检查</h3><p>预期产物：${escape(node.outputContract)}</p><p class="small muted">市场数据、竞品包体和外部研究工具尚未接入；没有来源的结论必须标记为假设。</p>`;
  }
};
