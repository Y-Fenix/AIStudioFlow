# StudioFlow 开发边界

## 公共平台

- `server/core/`、`server/store.py`、`server/studio_schema.py`、`web/studio.js`、`web/team-ui.js`、`web/studio.css`、`web/themes.css` 是平台公共壳，由平台维护者负责。部门负责人不得修改这些文件来实现部门需求。
- 部门功能只能通过 `departments/<部门>/` 中的模块和 `docs/departments/README.md` 约定的公共契约扩展。不要直接读写核心数据库、跳过服务端权限检查、修改其他部门的工作区或调用私有内部接口。
- 如果发现公共契约缺口，先在本部门 README 记录需求和最小接口提案，不要自行修改公共壳；由平台维护者审核后统一扩展。
- 不执行 Git 拉取、提交或推送；不修改 Figma；不将真实密钥、用户数据或工作室数据库加入代码。

## 所有变更

- 先读根目录 README、`docs/departments/README.md` 和目标部门 `AGENTS.md`。
- 先补针对预期行为的测试，确认失败原因正确，再改实现；完成后运行部门 AGENTS 指定的检查。
- 只报告实际验证的结果。协议替身、占位执行器和手工交付不得描述为真实工具已接通。
- 部门代码变更先运行 `python3 tools/check_department_boundaries.py --department <部门ID>`，检查直接跨部门/私有平台依赖与命名；该检查不代替代码评审，也不提供运行时沙箱。
- 不变更稳定部门 ID、节点 ID、权限资源含义或持久化字段语义；需要变化时先提交兼容迁移设计供平台维护者审核。

## 部门命名

新建部门代码文件使用职责前缀，避免多人协作时混淆所有权。跨部门通用代码归平台目录，不放入任一部门目录。

| 部门 | 前缀 | 维护目录 |
|---|---|---|
| 产品 | `PRODUCT_` | `departments/product/` |
| 设计 | `DESIGN_` | `departments/design/` |
| 开发 | `DEV_` | `departments/development/` |
| 测试 | `QA_` | `departments/testing/` |
| 发行增长 | `GROWTH_` | `departments/growth/` |

新增加的 Python 类、部门专属函数/常量及 JS 导出函数使用对应前缀，例如 `QA_build_case_matrix`、`QA_CASE_LIMIT`、`PRODUCT_create_research_brief`。现有公共协议方法（如 `create_adapter`、`execute`、`renderHome`、`renderWorkspace`、`mountHome`、`mountWorkspace`）由框架契约规定，不得为了前缀而改名。测试文件遵循 `test_<PREFIX>_*.py`；技能文件名继续使用节点索引，不能破坏现有加载协议。

## 测试部门存量兼容入口

测试六节点早于部门模块框架，保留已用的文件名、路由与节点 ID。其业务文件维护范围在 `departments/testing/README.md` 明确列出；仅测试负责人可维护这些兼容入口。`server/app.py`、`server/store.py`、`server/core/` 和模型/队列/通用连接器仍是平台所有，不因服务测试流程而转为部门私有。新测试逻辑优先放入 `departments/testing/QA_*.py`，新增部门测试用 `tests/test_QA_*.py`，不要继续扩张公共壳。
