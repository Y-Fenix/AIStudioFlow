export default {
  renderHome({project, escape}) {
    return `<div class="between"><div><span class="eyebrow">DEVELOPMENT MODULE</span><h3>以需求、代码基线和证据驱动交付</h3><p>${project ? `当前项目：${escape(project.name)}` : '选择项目后整理工程任务。'}</p></div><span class="tag">开发专属前端模块</span></div>`;
  },
  renderWorkspace({node, escape}) {
    if (!node) return '';
    return `<span class="eyebrow">ENGINEERING HANDOFF</span><h3>${escape(node.name)} · 交付检查</h3><p>预期产物：${escape(node.outputContract)}</p><p class="small muted">代码修改、构建和版本发布尚未接入；平台不会自动改动或提交项目源码。</p>`;
  }
};
