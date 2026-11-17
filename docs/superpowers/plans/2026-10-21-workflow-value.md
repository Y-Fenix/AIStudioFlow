# StudioFlow 工作流产品化实施计划

目标：交付设计稿中的 P0；P1/P2 明确为后续路线。本会话顺序开发并进行独立只读复核，不执行 Git 拉取、提交或推送。

## 任务清单

- [x] 1. 在 tests/test_QA_review_checkpoints.py 添加两条用例中断、复用、输入变化、损坏引用、取消测试，确认行为失败；实现 departments/testing/QA_review_checkpoints.py，接入 server/static_review.py 与 server/jobs.py。
- [x] 2. 在 tests/test_job_telemetry.py 添加合并与凭据隔离测试，确认失败；实现 server/core/job_telemetry.py 并接入队列进度回调。保持 Store.operation_progress 原协议。
- [x] 3. 在 tests/workflow-insights.test.js 验证真实关联、未决项、分页、XSS、Skill 检查限制；实现 web/workflow-insights.js，接入 web/testing.html 与 web/app.js。只消费当前授权 task。
- [x] 4. 为测试入口及提醒预设补 UI 测试；调整 web/studio.js 的测试场景入口、web/app.js 的未配置仓库提示、web/notifications.js 的事件预设。不改变原保存语义。
- [x] 5. 新增 tests/browser/workflow-insights.cjs，隔离服务器验证折叠入口、筛选分页、Skill 弹窗和无凭据泄漏；运行部门规定检查与相关通知/任务回归。
- [x] 6. README 和测试部门文档同步能力、限制与配置方式；记录真实检查结果。服务若有活动任务不重启，空闲时重启并验证页面可访问。

## 运行命令

每项先执行对应测试确认预期行为失败，再实现后重跑。

```sh
python3 -m unittest tests.test_QA_review_checkpoints tests.test_job_telemetry
node --test tests/workflow-insights.test.js
python3 tools/check_department_boundaries.py --department testing
python3 -m unittest tests.test_case_validation tests.test_generation tests.test_static_review tests.test_execution tests.test_attribution tests.test_triage tests.test_bugs tests.test_regression tests.test_node_settings tests.test_node_reset tests.test_workflow_e2e
node --test tests/*.test.js
STUDIOFLOW_PLAYWRIGHT_MODULE=/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright node tests/browser/workflow-insights.cjs
STUDIOFLOW_PLAYWRIGHT_MODULE=/Users/yf/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright node tests/browser/notifications.cjs
```

本地测试使用固定样例和模型/飞书传输替身；不调用真实 AI、不发飞书消息。新增数据不入仓库。
