# 设计部门模块

本目录由设计部门负责人维护：`manifest.json` 定义首页和节点，`ui.js` 定义设计专属首页/节点插槽，`skills/` 保存默认工作方法，`adapter.py` 是执行器接入点。当前执行器仍为占位实现，设计节点按人工整理与审核运行；图片生成、Figma 和资产工具尚未接入。

公共壳负责登录、工作室/项目隔离、权限、共享存储、队列、模型凭据和审批。设计模块通过公共 `ExecutionContext`、`ModelAccess` 和 `GmAccess` 契约工作，不直接访问核心数据库、模型密钥或其他部门工作区。不得把上传文档或 Skill 当 Python/JavaScript 执行。

节点 key（如 `design:0`）是持久化数据和授权规则的一部分，不能因改名、排序而复用或改变含义。新增、删除节点，或修改输入/输出契约时，先补迁移和测试，再更新 manifest。

交付前运行 `python3 -m unittest tests.test_team_platform.DepartmentManifestTests tests.test_department_execution tests.test_department_jobs_api` 和 `node --test tests/department-ui-contract.test.js`，并为本部门适配器加入固定输入输出、错误输入和越权测试。共享接口约定、最小适配器示例及安全边界见 [`部门模块协作约定`](../../docs/departments/README.md)。
