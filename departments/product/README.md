# 产品部门模块

本目录由产品部门负责人维护：`manifest.json` 定义首页和节点，`ui.js` 定义本部门插槽，`skills/` 保存默认工作方法。`adapter.py` 通过公共 `generate_document(context, contract)` 使用本次已选模型和当前 Skill，生成待人工审核的文字交付。`PRODUCT_contracts.py` 定义四个固定节点的具体章节与能力边界。

公共壳负责登录、工作室/项目隔离、权限、共享存储、队列、模型凭据和审批。产品模块通过公共 `ExecutionContext`、`ModelAccess` 和 `GmAccess` 契约工作，不直接访问核心数据库、模型密钥或其他部门工作区。不得把上传文档或 Skill 当 Python/JavaScript 执行。

节点 key（如 `product:0`）是持久化数据和授权规则的一部分，不能因改名、排序而复用或改变含义。新增、删除节点，或修改输入/输出契约时，先补迁移和测试，再更新 manifest。

交付前运行 `python3 -m unittest tests.test_team_platform.DepartmentManifestTests tests.test_department_execution tests.test_department_jobs_api` 和 `node --test tests/department-ui-contract.test.js`，并为本部门适配器加入固定输入输出、错误输入和越权测试。共享接口约定、最小适配器示例及安全边界见 [`部门模块协作约定`](../../docs/departments/README.md)。

## 默认 Skill 来源（2026-10-22）

本部门 `skills/<index>.md` 为固定 GitHub commit 的单文件方法移植版，含原文方法片段、节点输入输出、证据边界与 MIT 许可。来源注册由平台 `server/skill_catalog.py` 和 `server/skills/github-defaults.json` 统一维护；部门维护本目录正文时同步来源和回归，不改变稳定节点 ID。详见[完整节点映射与生效规则](../../docs/default-skill-sources.md)。

未配置覆盖的节点使用新默认；已导入、已保存覆盖规则及历史任务快照不批量改写。恢复默认须走已有权限与修订检查。Skill 文字规则不代表执行器已接通或上游辅助文件已安装。


## 模型文字执行器（2026-10-22）

节点卡片中的输入均指用户已提供的可读文字：链接、文件名、截图或包体路径本身不代表已读取其内容。需要分析的观察、代码、配置或工具记录须先整理为节点输入；本执行器不会自行获取。输出为待审文字草案、规格或计划，节点名称保留原业务阶段含义。

- 市场调研：范围、玩家、市场证据、机会、验证计划、交接。
- 竞品拆解：材料与授权、对照、机制/商业化、实现证据缺口、差异化、交接。
- 玩法与商业化：循环、成长、经济、广告/IAP、指标实验、MVP 取舍。
- PRD 与原型：范围、需求编号、状态边界、文本线框、验收追溯、交接。

`execution.adapter=adapter` 和 `automatic=true` 表示四个固定节点支持模型文字生成；不表示外部工具已接通、不自动审核，也不授予发布权限。自定义节点或其他部门节点拒绝套用这些固定契约。输入和 Skill 必须为非空文本；用户导入 Skill 仍优先于默认规则，运行使用当前快照。

每份交付含具体业务章节、事实/推导/假设及原文引用、缺口与下一步。公共生成器核对章节结构和引用是否逐字存在于输入；最多修正一次结构或引用错误。结构齐全、引用匹配不证明事实真实、推导正确或业务质量达标，仍需人工审核。

未执行外部调研、网页抓取、实机竞品体验、包体解析或反编译；不会读取链接/附件背后的内容。原型为文本结构，不是生成图片或可点击原型。

验证：`python3 -m unittest tests.test_PRODUCT_executor` 覆盖四节点固定模型 fixture、当前导入 Skill、非法/跨部门节点、空输入、空 Skill、执行权限拒绝与待人工审核；fixture 使用临时数据库和协议模型替身，不代表真实模型、外部工具或业务效果验收。另运行本部门边界检查及既有公共契约测试。
