# 测试工作区操作布局验收

日期：2026-10-22。对应已确认的 `superpowers/specs/2026-10-22-testing-workspace-action-layout-design.md`。

## 实现范围

- 六个测试节点共用主内容列底部常驻操作栏，保存评审和确认无需滚到底；发布、重置和取消收进更多操作菜单，保留原业务门禁和权限。
- Skill 标题栏保留名称、选择 Skill 和 Skill 工具入口；Codex 交接、检查、导入、导出收进菜单。长名称省略，悬停显示完整名称。
- 菜单支持点击外部、Escape、方向键、Home/End；同工作区重绘保留编辑、展开项、焦点和滚动。保存及确认阻止重复提交，失败保留输入，保存期间撤销权限后不会重新启用按钮。
- 独立页面与嵌入页面按实际可见视口定位操作栏；三套主题使用不透明表面色，窄屏分层排列。修正 ATELIER 测试页画布与外层主题底色不一致。

本次调整测试兼容前端，不修改 API、数据库协议和实际任务数据，未重启现有服务。

## 已执行检查

- `node --check web/app.js`：通过。
- `node --test tests/*.test.js`：80 项通过。
- `python3 tools/check_department_boundaries.py --department testing`：4 个文件通过；该检查不提供运行时沙箱证明。
- 部门规定 Python 套件：60 项通过，覆盖 `test_case_validation`、`test_generation`、`test_static_review`、`test_execution`、`test_attribution`、`test_triage`、`test_bugs`、`test_regression`、`test_node_settings`、`test_node_reset`、`test_workflow_e2e`。

浏览器脚本均在临时数据库、随机端口服务上通过：

| 脚本 | 实际验证 |
| --- | --- |
| `tests/browser/qa-workspace-actions.cjs` | 1,200 条评审项顶部、中部、底部操作可达，末项无遮挡；独立/嵌入、三主题、390px 窄屏、菜单键盘、重绘保留、409 失败、重复提交、权限撤销、分页选择 |
| `tests/browser/skill-picker.cjs` | 22 个默认 Skill、六节点选择保存、隔离/冲突、ESC/窄屏，实际默认 Markdown 导出内容一致 |
| `tests/browser/testing-workspace-navigation.cjs` | 节点删除/排序、权限、三主题吸顶画布及安全回退 |
| `tests/browser/workflow-insights.cjs` | 证据分页、重绘、Skill 检查菜单、ESC/窄屏 |
| `tests/browser/qa-automation.cjs` | 350 项风险保存同步、替身静态执行/归因、基线刷新、一个内部草稿，无外部发布 |

Skill 导出回归遇到的任务选择异步竞争，已通过等待指定任务加载完成修正测试，保留完整导出内容断言。新增布局测试曾在旧布局失败，权限与分页回归也在修复前确认失败。

截图保存在本机 `data/visual-review/qa-actions-*.png`，已查看嵌入页标题栏和窄屏截图。

## 验证边界

浏览器使用本机 Chrome，菜单依赖原生 Popover API；未验证所有浏览器。自动执行回归替换模型传输和 Git 基线，不代表真实 Codex、游戏执行、Unity、Webhook 或项目公区上传已在本轮验证。本轮未执行上述外部操作。
