# 节点间自动继续 Implementation Plan

**Goal:** 两处节点连线提供默认关闭的持久化开关，确认事件驱动服务端一次性续接。
**Architecture:** 公共配置服务保存稳定起止 ID 与拓扑修订，确认事务写 outbox，worker 在事务内复查并借用现有队列。人工审核、静态检测、外部写确认保持原规则。
**Tech Stack:** Python/SQLite/原生 JavaScript/Playwright。按 executing-plans 本会话顺序实施；用户禁止 Git 操作，不创建提交或 worktree，不委派子代理。

## 1 配置和调度
- [x] 新增 tests/test_node_continuation.py：默认关闭/项目隔离、冲突、越权、合法邻接、确认后仅派发一次、缺条件/撤权/修改/关闭/重排停止、崩溃恢复与人工门禁。运行 python3 -m unittest tests.test_node_continuation -v，确认缺失服务导致失败。
- [x] server/core/node_continuation.py 和独立 schema 增量迁移，增加 GET/POST /api/studios/{studio}/projects/{project}/node-continuation?department=...；来源 node.edit、目标 view、布尔校验、修订冲突与审计。
- [x] Workspaces.decide 与 Store.decide 确认事务记录续接意图；现有 enqueue 支持同一事务连接；worker 固定操作者，条件复查后一次排队或记录停止原因。使用唯一确认键，失败不重试、恢复未派发意图，外部写绝不自动触发。

## 2 界面
- [x] 新增共享 web/node-continuation.js/css 与 Node 测试，先运行 node --test tests/node-continuation-ui.test.js 验证缺失实现；switch 位于按钮外，正确 aria/标签、颜色、只读和窄屏。
- [x] web/studio.js 首页/公共节点条和 web/app.js 测试节点条使用同一 API，局部保存并阻止误导航、过期响应；iframe/父页和刷新同步，失败还原。

## 3 验收与交付
- [x] tests/browser/node-continuation.cjs 在临时库运行真实 HTTP，验证五部门、两处同步、开关键盘、刷新、三主题、窄屏、无误导航。
- [x] python3 -m unittest discover -s tests；node --test tests/*.test.js；部门边界检查和关键浏览器回归。
- [x] README、部门公共契约与验收记录标注真实能力与替身范围。
- [x] 检查真实服务活动队列，SQLite API 备份0600，再更新8766；不改凭据、不动8765。

## 实际结果（2026-10-20）

- 352 项 Python、28 项 Node 测试通过；全量 Python 日志保留预期故障注入及资源清理警告。
- 五部门续接、原测试节点导航/三主题吸顶和 Skill 选择器浏览器回归通过，均使用隔离临时数据，不调用真实模型、Unity 或飞书。
- 测试部门静态依赖/命名检查通过；不代表运行时沙箱隔离。
- 已检查两类任务队列与外部发送状态均为空，一致性备份权限0600，重启8766。31张旧表行数及内容哈希未变化，外键检查无异常；新增两表为空，默认不开启续接。登录仍为password，未登录API返回401。
- 未执行 Git 拉取、提交、推送或 Figma 修改；项目版本设计仍未实施。
