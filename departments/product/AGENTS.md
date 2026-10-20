# 产品部门 Codex 工作范围

- 先读根目录 `AGENTS.md`、本目录 `README.md` 和 `../../docs/departments/README.md`。
- 只维护 `departments/product/`：本部门 `manifest.json`、`ui.js`、`adapter.py`、`skills/`、`README.md`、本文件及对应 `tests/test_PRODUCT_*.py`。不得修改其他部门目录、`server/core/`、公共 Web 壳、数据库协议或权限实现。
- 新增部门专属 Python 类/函数/常量及 JS 导出函数使用 `PRODUCT_` 前缀；固定框架入口 `create_adapter`、`execute`、`renderHome`、`renderWorkspace`、`mountHome`、`mountWorkspace` 保持契约名称。
- 交互仅在自己的模块 element 下绑定，订阅使用公共 signal，离开页面清理；先运行 `python3 tools/check_department_boundaries.py --department product`。不要从其他部门复制实现或导入公共壳私有模块。
- 调研结论区分事实、推导、假设与缺口；每个事实附可核查来源。竞品反编译仅分析用户合法提供且获准处理的材料，不绕过访问控制或传播受保护内容。
- 不编造数据；不调用未接入的工具，不将人工交付显示为 Agent 执行成功。模型输出需带证据和待确认项并等待人工审核。
- 先写失败测试，再实现。交付前运行部门测试及 `node --test tests/department-ui-contract.test.js`；若改公共契约，停止在本部门目录内，提交接口提案给平台维护者。
