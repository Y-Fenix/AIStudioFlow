# 默认 Skill 来源与适配范围

本次替换覆盖产品、设计、开发、测试及历史发行增长的 22 个内置节点。采用 6 个 GitHub 仓库中的节点相关方法，30 份固定版本 Markdown（含 ADR 方法与模板参考）；不是把仓库 stars 当单个 Skill 的效果评分。核验记录时间：2026-10-22 14:09:20（北京时间）；新增 ADR 参考文件与主 Skill 使用相同固定 commit。

## 来源仓库

| 仓库 | 核验时 stars | 固定 commit | 许可证 |
| --- | ---: | --- | --- |
| [phuryn/pm-skills](https://github.com/phuryn/pm-skills) | 27,283 | `07b34f64ee828df08953f505b7f747aef85ae7c6` | MIT |
| [Donchitos/Claude-Code-Game-Studios](https://github.com/Donchitos/Claude-Code-Game-Studios) | 27,073 | `05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418` | MIT |
| [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 138,600 | `623a9a9037d006ea727f8213f084d02a6b6f11b5` | MIT |
| [obra/superpowers](https://github.com/obra/superpowers) | 303,256 | `2ce8aa15d05bd57213e6f746f953aafb7ded7a8b` | MIT |
| [wshobson/agents](https://github.com/wshobson/agents) | 41,502 | `0874a27b17a22e2b7c2e2bcd725768e0803cad06` | MIT |
| [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) | 55,873 | `e85f3cbc2e4a79bf33b2a12e9bdd9087d414735b` | MIT |

星数来自 GitHub API 的仓库级计数，不是单 Skill 星数、安装数或质量验收。原始文档按固定 commit 经 HTTPS 读取，未执行 Git 拉取、提交或推送。MIT 原始许可保留于 `third_party/skills/`，同时内嵌到导出规则。

## 每个节点的方法

| 稳定节点 ID | 节点 | 采用方法（固定来源链接） |
| --- | --- | --- |
| `product:0` | 市场调研 | [market-sizing](https://github.com/phuryn/pm-skills/blob/07b34f64ee828df08953f505b7f747aef85ae7c6/pm-market-research/skills/market-sizing/SKILL.md) |
| `product:1` | 竞品拆解 / 反编译 | [competitor-analysis](https://github.com/phuryn/pm-skills/blob/07b34f64ee828df08953f505b7f747aef85ae7c6/pm-market-research/skills/competitor-analysis/SKILL.md)、[reverse-document](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/reverse-document/SKILL.md) |
| `product:2` | 玩法与商业化 | [quick-design](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/quick-design/SKILL.md)、[monetization-strategy](https://github.com/phuryn/pm-skills/blob/07b34f64ee828df08953f505b7f747aef85ae7c6/pm-product-strategy/skills/monetization-strategy/SKILL.md) |
| `product:3` | PRD 与原型 | [create-prd](https://github.com/phuryn/pm-skills/blob/07b34f64ee828df08953f505b7f747aef85ae7c6/pm-execution/skills/create-prd/SKILL.md) |
| `design:0` | 视觉定调 | [art-bible](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/art-bible/SKILL.md) |
| `design:1` | UX 与界面 | [ui-ux-pro-max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/623a9a9037d006ea727f8213f084d02a6b6f11b5/.claude/skills/ui-ux-pro-max/SKILL.md) |
| `design:2` | 资产生产 | [asset-spec](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/asset-spec/SKILL.md) |
| `design:3` | 设计验收 | [asset-audit](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/asset-audit/SKILL.md) |
| `development:0` | 技术方案 | [writing-plans](https://github.com/obra/superpowers/blob/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b/skills/writing-plans/SKILL.md)、[architecture-decision](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/architecture-decision/SKILL.md)、[architecture-decision-method](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/architecture-decision/references/4-decide.md)、[architecture-decision-template](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/architecture-decision/references/5-generate.md) |
| `development:1` | 功能实现 | [test-driven-development](https://github.com/obra/superpowers/blob/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b/skills/test-driven-development/SKILL.md) |
| `development:2` | 集成与自检 | [code-review-excellence](https://github.com/wshobson/agents/blob/0874a27b17a22e2b7c2e2bcd725768e0803cad06/plugins/developer-essentials/skills/code-review-excellence/SKILL.md)、[verification-before-completion](https://github.com/obra/superpowers/blob/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b/skills/verification-before-completion/SKILL.md) |
| `development:3` | 版本交付 | [release-checklist](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/release-checklist/SKILL.md)、[verification-before-completion](https://github.com/obra/superpowers/blob/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b/skills/verification-before-completion/SKILL.md) |
| `testing:0` | 用例 | [qa-plan](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/qa-plan/SKILL.md)、[test-scenarios](https://github.com/phuryn/pm-skills/blob/07b34f64ee828df08953f505b7f747aef85ae7c6/pm-execution/skills/test-scenarios/SKILL.md) |
| `testing:1` | 执行 | [test-evidence-review](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/test-evidence-review/SKILL.md)、[intended-vs-implemented](https://github.com/phuryn/pm-skills/blob/07b34f64ee828df08953f505b7f747aef85ae7c6/pm-ai-shipping/skills/intended-vs-implemented/SKILL.md) |
| `testing:2` | 归因 | [systematic-debugging](https://github.com/obra/superpowers/blob/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b/skills/systematic-debugging/SKILL.md) |
| `testing:3` | 筛选 | [bug-triage](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/bug-triage/SKILL.md) |
| `testing:4` | 提单 | [bug-report](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/bug-report/SKILL.md) |
| `testing:5` | 回归 | [test-evidence-review](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/test-evidence-review/SKILL.md)、[regression-suite](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/regression-suite/SKILL.md)、[verification-before-completion](https://github.com/obra/superpowers/blob/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b/skills/verification-before-completion/SKILL.md) |
| `growth:0` | 上线准备 | [launch-checklist](https://github.com/Donchitos/Claude-Code-Game-Studios/blob/05ad7c8a5b8aa2aa86bbd3439ae7cf7295cac418/.claude/skills/launch-checklist/SKILL.md) |
| `growth:1` | 素材与投放 | [ad-creative](https://github.com/coreyhaines31/marketingskills/blob/e85f3cbc2e4a79bf33b2a12e9bdd9087d414735b/skills/ad-creative/SKILL.md) |
| `growth:2` | 数据与运营 | [analytics](https://github.com/coreyhaines31/marketingskills/blob/e85f3cbc2e4a79bf33b2a12e9bdd9087d414735b/skills/analytics/SKILL.md) |
| `growth:3` | 迭代决策 | [ab-test-analysis](https://github.com/phuryn/pm-skills/blob/07b34f64ee828df08953f505b7f747aef85ae7c6/pm-data-analytics/skills/ab-test-analysis/SKILL.md) |

## 实际使用与保留边界

- 正式运行读取 `departments/<department>/skills/<index>.md`；`server/skill_catalog.py` 负责加载，`server/skills/github-defaults.json` 记录来源。`third_party/skills/**/UPSTREAM.md` 只是原始资料快照，不运行其中命令。
- 每个默认规则包含节点输入、方法步骤、输出、证据、人工决定和原文片段。已将测试输出适配为平台 JSON、游戏静态审查及原有证据门禁；不会启动 Unity、猜测复现事实或编造修复概率。
- 原始游戏工作室 Skill 依赖 Claude hooks、代理、项目配置和外部 references；UI/UX Pro Max 原包也包含搜索脚本与数据库。本次只移植单文件可用方法和必要模板，未安装完整插件或这些脚本，不能据此宣称工具已经接通。上游模型选择不迁移，仍由平台当前连接和模型配置决定。
- 用例生成仍按原有分批设计与反向审计执行。部分节点使用固定逻辑和人工门禁，替换 Skill 不会让这些节点自动变成模型执行器。非测试部门仍需负责人实现相应工具执行器。
- 已导入 Skill、已保存的项目覆盖规则、旧测试批次及运行中的快照保留原文；未覆盖节点及新批次使用新默认。旧工作区可通过现有“恢复默认”/选择与保存流程更新，仍执行权限、并发和人工确认检查。默认更新不重算已有产物。
- 本机 TEST_Test_Case / TEST_Test_Codetest 等仍可显式导入；个人机器文件不再静默覆盖团队默认。用户归档的筛选节点及退出主流程的增长节点不因此重新显示。
- 自定义节点没有固定业务职责，继续由用户选择 Skill；引用内置节点的新流程获取当前有效规则，已有保存覆盖及冻结运行不改写。

## 验证范围

来源测试核对全部内置节点的运行时正文、固定版本链接、原始快照 SHA256、MIT 许可、可导出 Markdown 及本机隔离；另检查导入覆盖和历史批次保留。初次替换时 462 项 Python 回归和 70 项前端测试通过；五部门静态边界检查通过。浏览器验证了 22 个默认规则的真实 HTTP 返回、测试节点默认名称与 Markdown 导出、选择保存及项目/批次隔离，另验证自定义流引用与历史快照。验证使用临时数据库和本机 Chrome，不调用真实模型、Unity 或飞书。未对所有节点进行真实模型调用或业务质量评测，高星不保证输出质量。后续测试部门的真实小样例验收单独记录在 [测试链路验收](qa-static-pipeline-acceptance.md)。


## 测试链路补强（2026-10-22）

用例补入 qa-plan 的游戏验收分类，执行与回归补入 test-evidence-review 的边界/公式证据核对。执行节点只保留 intended-vs-implemented 的意图与代码比较方法，删除“只有跨安全边界才算问题”的上游限定；普通玩法错误同样需要报告。上游按断言数量、关键词和测试名做粗筛的方法不移植为通过条件。新增原文与既有游戏仓库同 commit、同许可证；stars 沿用上表核验快照，未重新计数。

从提单页触发回归时，执行 Skill 固定取已授权的 testing:5，而非页面阶段 testing:4。归因保留准确引用行号，重复代码且行号无法确定时拒绝猜测；同一失败不能重复归入不同根因。混合报告优先暴露已发现缺陷，未验证项仍保留计数和逐项状态。

生成、静态执行、归因及静态回归调用模型并加载对应 Skill。筛选和草稿准备继续使用固定合并/证据门禁，Skill 作为人工审核规则，不宣称它们已由模型改写提单内容。已归档筛选不重新展示。自动发布、修改飞书状态不属于这次验收。
