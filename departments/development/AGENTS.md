# 开发部门 Codex 工作范围

- 先读根目录 `AGENTS.md`、本目录 `README.md` 和 `../../docs/departments/README.md`。
- 只维护 `departments/development/`：本部门 `manifest.json`、`ui.js`、`adapter.py`、`skills/`、`README.md`、本文件及对应 `tests/test_DEV_*.py`。不得修改其他部门目录、`server/core/`、公共 Web 壳、数据库协议或权限实现。
- 新增部门专属 Python 类/函数/常量及 JS 导出函数使用 `DEV_` 前缀；固定框架入口 `create_adapter`、`execute`、`renderHome`、`renderWorkspace`、`mountHome`、`mountWorkspace` 保持契约名称。
- 交互仅在自己的模块 element 下绑定，订阅使用公共 signal，离开页面清理；先运行 `python3 tools/check_department_boundaries.py --department development`。不要从其他部门复制实现或导入公共壳私有模块。
- 代码建议必须绑定用户指定项目和代码基线；运行命令、构建、文件写入、网络访问须遵循平台授权和执行器契约。不得拉取、提交或推送 Git，不得擅自修改用户源码或发布版本。
- 将静态推导、编译证据和运行结果分开；未运行的构建/测试不得标记通过。交付等待人工审核。
- 先写失败测试，再实现。交付前运行部门测试及 `node --test tests/department-ui-contract.test.js`；公共接口需求先提交接口提案给平台维护者。
