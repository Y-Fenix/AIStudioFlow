export default {
  renderHome({project, escape}) {
    return `<div class="between"><div><span class="eyebrow">DESIGN MODULE</span><h3>让体验规则与视觉资产可交接</h3><p>${project ? `当前项目：${escape(project.name)}` : '选择项目后整理设计交付。'}</p></div><span class="tag">设计专属前端模块</span></div>`;
  },
  renderWorkspace({node, escape}) {
    if (!node) return '';
    return `<span class="eyebrow">DESIGN HANDOFF</span><h3>${escape(node.name)} · 交付检查</h3><p>预期产物：${escape(node.outputContract)}</p><p class="small muted">图片生成、Figma 和资源生产工具尚未接入；需记录资源来源、规格与未完成项。</p>`;
  }
};
