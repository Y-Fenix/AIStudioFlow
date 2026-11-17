# 版本测试工作台与用例库 Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan sequentially. No delegation or Git operations.

**Goal:** 落地已确认的 A：当前工作台 + 用例库，按项目版本及独立测试批次管理，旧批次不占用新批次。

**Architecture:** 公共 `server/core/testing_library.py` 管理新增版本表、批次归属和不可变用例快照。旧任务、revision、节点 ID 与权限含义不变；未分配版本的旧批次保留。公共路由授权后调用服务，测试页面通过独立 JS 模块接入。后台成功、编辑和确认在原事务内捕获快照；复制明确新建批次并清除所有审核与下游结论。

**Tech Stack:** Python/SQLite，现有 HTTP/Policy，原生 JS/CSS，unittest + Playwright。

## 兼容与权限设计（平台维护）

仅新增 testing_versions、testing_batch_versions、testing_case_snapshots 表；不重命名/改义原字段，不猜旧任务版本。旧任务当前用例在首次迁移保存为可追溯快照，快照标记捕获时点，不声称还原已丢失的历史。旧 API 路由保持兼容。版本建立和新建批次复用 node testing:0 edit 与 content testing create；复制另外要求 node export/import 及 Skill view/export/import。用例查看要求 testing:0 view；Skill、基线按额外权限过滤。所有动作按工作室和项目隔离。个人用例库不自动发布到公区。现有独立流程绑定不覆盖，从该流程新建批次应进入默认工作台。

## Steps

- [x] 1. 编写用例库服务测试：旧数据迁移、跨版本隔离、自动草稿/确认快照、历史不变、复制不继承结论、项目及权限隔离、分页筛选；运行验证预期失败。
- [x] 2. 公共服务 + schema 迁移 + Store 事务接线 + 授权路由；运行专项测试。
- [x] 3. 测试工作台独立前端模块：当前工作台/用例库、版本与批次选择、新建/复制弹窗、历史快照详情、明确生成阻塞原因，保留原节点工作区。
- [x] 4. 编写运行真实 HTTP/临时 SQLite 的浏览器回归：旧批次进入执行后新建 1.1.0、旧用例保留、用例库分页/历史/复制、重启持久化、ESC/窄屏/可用高度。
- [x] 5. 跑部门规定检查及现有工作台浏览器回归；截图检查后更新验收文档。
- [x] 6. 检查实际服务在途任务，安全加载新版本供本机访问；不执行模型、Unity、外部发布或 Git。
