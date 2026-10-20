# 发行增长部门 Codex 工作范围

- 先读根目录 `AGENTS.md`、本目录 `README.md` 和 `../../docs/departments/README.md`。
- 只维护 `departments/growth/`：本部门 `manifest.json`、`ui.js`、`adapter.py`、`skills/`、`README.md`、本文件及对应 `tests/test_GROWTH_*.py`。不得修改其他部门目录、`server/core/`、公共 Web 壳、数据库协议或权限实现。
- 新增部门专属 Python 类/函数/常量及 JS 导出函数使用 `GROWTH_` 前缀；固定框架入口 `create_adapter`、`execute`、`renderHome`、`renderWorkspace`、`mountHome`、`mountWorkspace` 保持契约名称。
- 交互仅在自己的模块 element 下绑定，订阅使用公共 signal，离开页面清理；先运行 `python3 tools/check_department_boundaries.py --department growth`。不要从其他部门复制实现或导入公共壳私有模块。
- 商店、投放、留存、收入等结论必须绑定平台/时间范围/样本/来源；缺失数据标为未知，不推测成真实指标。外部投放和发布工具未接入前不得声称已执行。
- 不编造数据、不擅自发布外部内容。所有模型交付等待人工审核。
- 先写失败测试，再实现。交付前运行部门测试及 `node --test tests/department-ui-contract.test.js`；公共接口需求先提交接口提案给平台维护者。
