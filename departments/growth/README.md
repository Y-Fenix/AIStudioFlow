# 发行与增长模块

本目录由发行增长部门负责人维护：`manifest.json` 定义首页和节点，`ui.js` 定义发行增长专属首页/节点插槽，`skills/` 保存默认工作方法，`adapter.py` 是执行器接入点。当前执行器仍为占位实现，节点按人工整理与审核运行；广告平台、商店和实时数据接口尚未接入。

公共壳负责登录、工作室/项目隔离、权限、共享存储、队列、模型凭据和审批。发行增长模块通过公共 `ExecutionContext`、`ModelAccess` 和 `GmAccess` 契约工作，不直接访问核心数据库、模型密钥或其他部门工作区。不得将无来源的数据当作事实，也不得把上传文档或 Skill 当 Python/JavaScript 执行。

节点 key（如 `growth:0`）是持久化数据和授权规则的一部分，不能因改名、排序而复用或改变含义。新增、删除节点，或修改输入/输出契约时，先补迁移和测试，再更新 manifest。

交付前运行 `python3 -m unittest tests.test_team_platform.DepartmentManifestTests tests.test_department_execution tests.test_department_jobs_api` 和 `node --test tests/department-ui-contract.test.js`，并为本部门适配器加入固定输入输出、错误输入和越权测试。共享接口约定、最小适配器示例及安全边界见 [`部门模块协作约定`](../../docs/departments/README.md)。

## 默认 Skill 来源（2026-10-22）

本部门 `skills/<index>.md` 为固定 GitHub commit 的单文件方法移植版，含原文方法片段、节点输入输出、证据边界与 MIT 许可。来源注册由平台 `server/skill_catalog.py` 和 `server/skills/github-defaults.json` 统一维护；部门维护本目录正文时同步来源和回归，不改变稳定节点 ID。详见[完整节点映射与生效规则](../../docs/default-skill-sources.md)。

未配置覆盖的节点使用新默认；已导入、已保存覆盖规则及历史任务快照不批量改写。恢复默认须走已有权限与修订检查。Skill 文字规则不代表执行器已接通或上游辅助文件已安装。
