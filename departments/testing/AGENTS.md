# 测试部门 Codex 工作范围

- 先读根目录 `AGENTS.md`、本目录 `README.md` 和 `../../docs/departments/README.md`，并优先遵循本机 `TEST_Test_Case`、`TEST_Test_Codetest`、`TEST_Test_Feishu` Skill 的规则。
- 只维护 `departments/testing/`、本目录 README 列明的测试存量兼容入口，以及对应 `tests/test_QA_*.py`。不得修改其他部门目录、`server/core/`、公共 Web 壳、权限/认证/数据库协议。`web/app.js` 是旧测试六节点页面，不是 `web/studio.js` 公共壳；不要混淆。需要公共能力时先写接口提案给平台维护者。
- 新增测试专属 Python 类/函数/常量及 JS 导出函数使用 `QA_` 前缀；旧六节点/API 和框架约定名保持兼容，不做无关重命名。
- 用例覆盖需求测试点但控制冗余；静态代码检查不得启动 Unity，结论区分静态证据、运行验证、需求歧义和证据缺口。不得伪造实机复现、Bug 数据或修复概率。
- 飞书操作服从只读/逐项确认边界；不擅自发 Bug、改远端状态、GM 写数据或修改 Figma。用户未授权时不接触目标仓库 Git 内容。
- 先写失败测试，再实现。交付前运行本目录 `README.md` 中规定的测试及 `node --test tests/department-ui-contract.test.js`。
