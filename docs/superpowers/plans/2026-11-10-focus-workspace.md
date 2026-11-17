# A / FOCUS 工作台落地计划

用户已选择 2026-11-10 样板 A，授权落地；只改界面与交互，不变更业务状态、权限和数据协议，不执行 Git 提交/拉取/推送。

目标：浅色聚焦布局、紧凑流程、用例优先、需求/评审页签、日志/助手侧滑、固定主要操作。

架构：增加独立 focus-workspace.js/css 作为 UI 布局增强，复用测试页面既有生成/审核/日志/助手与权限函数；公共壳切换部门时释放增强状态。所有样式以 focus 类限定，保留三主题和独立测试入口。旧数据和节点 ID 不变。

- [x] 1. 在 tests/browser/focus-workspace.cjs 建临时服务和真实 UI fixture，验证默认用例、需求页签、批量评审输入保持、抽屉 ESC/遮罩关闭、日志滚动保持、底部固定、窄屏；先运行确认缺少新 UI 导致失败。
- [x] 2. 新增 web/focus-workspace.js，原地组织 DOM、保留上下文内页签和滚动、抽屉焦点与生命周期。测试页面增加明确的语义分区和增强挂载点，不复制业务操作。
- [x] 3. 新增 web/focus-workspace.css；index/testing 页面加载。公共壳紧凑布局，修正 iframe 占用与双重滚动。图标、层级、对比度按 A，兼容其他主题。
- [x] 4. 运行新浏览器回归、既有 QA 操作栏/节点助手及 JS 回归，按失败修正兼容。实际截图审阅桌面/窄屏。更新 README 和验收说明。

验证命令：`node --test tests/*.test.js`，`node tests/browser/focus-workspace.cjs`，`node tests/browser/qa-workspace-actions.cjs`，`node tests/browser/department-flows-memory.cjs`；浏览器使用本机 Playwright，临时库/替身不代表真实模型质量。只改前端，无需启动真实 AI、Unity 或外部写入。
