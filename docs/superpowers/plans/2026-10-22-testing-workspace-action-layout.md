# 测试工作区操作布局实施计划

设计已于 2026-10-22 获用户确认；当前会话顺序执行，不进行 Git 操作。

**目标：** 长评审列表中始终能保存/确认，Skill 标题栏不再平铺五个工具。

**实现：** 保留测试兼容入口与服务端门禁。在 `web/app.js` 中提取 `QA_workspaceActions()`、生成原生弹出菜单、保存同一工作区重绘状态；在 `web/styles.css` 添加主题变量驱动的布局。必要时按嵌入页可见视口调整底部位置，不修改正在执行的任务。

**技术：** 原生 JavaScript/CSS、Popover API、Python 临时 HTTP 服务、Playwright Chrome。

## 1. 行为回归先行

- [x] 新增 `tests/browser/qa-workspace-actions.cjs`，自建随机端口临时数据库，生成 1,200 个评审问题。
- [x] 断言顶部、中部、底部常驻栏可见，末项不被遮挡，长 Skill 名称不挤出按钮，工具菜单支持 Escape、外点、键盘和重绘保留，拒绝未授权操作。
- [x] 执行浏览器回归，确认旧布局因操作栏不可见而失败。

## 2. 实现布局和交互

- [x] `web/app.js`：六节点共用底部主要操作、更多操作菜单、Skill 工具菜单；复用原动作函数和权限。
- [x] `web/app.js`：菜单定位/键盘处理、同上下文重绘状态保留、保存/确认在途拦截。
- [x] `web/styles.css`：主列常驻栏、短名称省略、窄屏明确两层布局、遮挡预留、主题表面色。
- [x] 更新直接点击旧 Skill 工具的既有浏览器测试，让其先打开菜单；不删减原验证。

## 3. 验证与交付

- [x] 运行 `STUDIOFLOW_PLAYWRIGHT_MODULE=/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright node tests/browser/qa-workspace-actions.cjs`，三套主题/窄屏/独立与嵌入模式验证。
- [x] 运行测试部门边界检查、README 规定的 Python 测试以及 `node --test tests/*.test.js`。
- [x] 运行受影响的 Skill 选择、证据面板、测试导航浏览器脚本，截图检查实际布局。
- [x] 更新验收记录，仅报告实际通过的检查，不调用真实模型或外部发布。

验收已完成，实际结果及验证边界见 [验收记录](../../qa-workspace-actions-acceptance.md)。
