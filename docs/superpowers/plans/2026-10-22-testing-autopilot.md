# 测试自动决策实施计划

Goal: 已确认设计的三个入口可用，全自动只到内部草稿。
Architecture: 测试纯数据策略与平台持久化/权限/调度隔离；复用现有Store校验与队列。增量表不改变旧节点语义。
Tech Stack: Python、SQLite、原生JS、Playwright。

## 1. 顶部保存
- [x] 新增 `tests/qa-review-ui.test.js`，用VM执行真实caseReviewView/saveCaseReview，验证顶部有确认与保存、确认同步、重复保存不重复请求。
- [x] 运行 `node --test tests/qa-review-ui.test.js`，确认旧实现缺少顶部保存。
- [x] 修改 `web/app.js`、必要样式；保留底部入口，新增共享状态同步与提交反馈。
- [x] 重跑专项，确认通过。

## 2. 只读更新基线与原子排队
- [x] 新增 `tests/test_QA_execution_start.py`，覆盖旧提交更新、同基线不增修订、并发旧版本拒绝及回滚、已有任务不覆盖、授权路由。
- [x] 运行 `python3 -m unittest tests.test_QA_execution_start`，确认新契约缺失。
- [x] 在部门README记录公共契约；公共Store封装带事务的更新和排队，HTTP加最小路由，Gateway要求执行和编辑权限。
- [x] 前端明确入口“更新基线并静态检测 / 继续未完成用例”，请求包含当前修订，不自动切分支。
- [x] 重跑专项及静态检测回归。

## 3. 批次自动委托
- [x] 新增 `tests/test_QA_automation.py`，真实SQLite覆盖从范围评审到内部草稿、无根因证据暂停、已存在手工产物、停止、重启、权限撤回、重复调度与失败不无限重试。
- [x] 运行专项，确认功能缺失。
- [x] 新增 `departments/testing/QA_automation.py` 纯数据策略；平台新增 `server/core/testing_automation.py` 调度及表。配置接口沿用节点权限，自动步骤每次核对委托与修订、使用原Store及严格校验。
- [x] 自动确认使用明确的automation来源记录，人工默认不变；开启模式从当前节点推进，不覆盖已有手工有效产物。普通自动继续不争抢全自动批次。
- [x] 新增全自动状态和停止按钮，后台运行期间前端持续轮询；刷新读持久化配置，页面无需常驻。
- [x] 运行完整Python/Node、边界扫描及真实浏览器隔离链路。真实代码/模型小样本单独验收。

## 交付
- [x] 无在途任务时重启本机服务，验证HTTP和原933条用例保持。
- [x] 更新验收说明，说明实际运行与隔离验证边界，不启动Unity、不发布飞书Bug、不进行Git写操作。
