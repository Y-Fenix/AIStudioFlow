export default {
  renderHome({project, escape}) {
    return `<div class="between"><div><span class="eyebrow">TESTING MODULE</span><h3>逐用例静态审查，不启动 Unity</h3><p>${project ? `当前项目：${escape(project.name)}` : '选择项目后开始测试工作流。'}</p></div><span class="tag">测试专属六节点工作区</span></div>`;
  }
};
