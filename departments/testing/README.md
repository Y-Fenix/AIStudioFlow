# 测试部门模块

维护本目录的 manifest.json、skills/ 和本部门实现。公共登录、权限、数据库、队列不得在本目录绕过。

节点标识 `testing:0` 等保持稳定；调整顺序或删除节点需要迁移方案。执行器通过公共注册接口接入，未接通的自动能力保持人工模式。测试模块复用原六节点，不复制执行链路。

## 测试负责人维护范围

新代码放在本目录，使用 `QA_` 前缀。既有业务实现暂保留以下兼容入口，可由测试负责人维护：

- 用例与 Skill：`server/requirements.py`、`server/node_skills.py`、`server/skills/`。
- 执行与归因：`server/static_review.py`、`server/execution.py`、`server/attribution.py`、`server/triage.py`。
- 提单与回归业务：`server/bugs.py`、`server/regression.py`。
- 六节点前端：`web/app.js`、`web/testing.html`、`web/styles.css`、`web/testing-themes.css`。

这些存量入口不属于其他部门的可编辑范围。它们仍须调用公共权限、持久化、模型、发布台账和状态更新服务；不得在业务文件内自行授予权限、直写核心表或绕过人工确认。`server/app.py` 的 HTTP 分发、`server/store.py`、队列、模型和通用连接器由平台维护者负责；需要新接口时先写接口提案，不在公共大文件中随意插入部门功能。现有 Python 导入路径与 API 保持兼容，新增代码才采用部门前缀，不为重命名打断已有测试。

交付前运行 `python3 tools/check_department_boundaries.py --department testing`、`python3 -m unittest tests.test_case_validation tests.test_generation tests.test_static_review tests.test_execution tests.test_attribution tests.test_triage tests.test_bugs tests.test_regression tests.test_node_settings tests.test_node_reset tests.test_workflow_e2e` 和 `node --test tests/*.test.js`。该静态命名/依赖检查只覆盖 `departments/testing/`，存量兼容文件依赖由业务回归和评审检查；没有把旧目录检查冒充全面架构隔离。
