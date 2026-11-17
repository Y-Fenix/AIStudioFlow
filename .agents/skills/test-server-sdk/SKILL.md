---
name: test-server-sdk
description: Use when reviewing Android or iOS SDKs, SDK services, or game services for release risks, bugs, payment, analytics, ads, installation recovery, concurrency, or cross-repository behavior.
---

# TEST_ServerSDK

默认先按 [引导式检查](references/guided-review.md) 选择检查模式、对象与验证深度，再执行并写出报告。已有明确选择不重复询问；用户明确要求直接执行时采用推荐配置并记录。目标是扩大可验证覆盖并给每个问题提供可复现路径，不承诺发现所有 Bug，也不能用检查项数量证明完整。默认检查下列四个库，无需用户重复提供路径：

| ID | 默认绝对路径 |
|---|---|
| android | /Users/yf/Documents/Unity/SDK&服务器/bbsdkunity-android |
| ios | /Users/yf/Documents/Unity/SDK&服务器/bbsdkunity-ios |
| sdkserver | /Users/yf/Documents/Unity/SDK&服务器/sdkserver |
| gameserver | /Users/yf/Documents/Unity/SDK&服务器/server |

用户提供路径时覆盖默认。无项目参数时审查共享底座，并记录实际发现的项目分支，不默认所有库都属于 GagaSort，不声称枚举全部接入项目。指定 GagaSort 时使用 [项目定位](references/repositories.md) 中的标识。其他项目从代码及构建配置识别；无法识别也先完成共享检查，将项目归属记为未知。

## 执行

0. 阅读 [引导式检查与历史台账](references/guided-review.md)，完成未明确的选项，读取相关历史报告并保存 review-config.json。每轮承接历史 issue/risk 和未决台账；未复查问题保留待复查，不计为本轮确认，不静默删除。

1. 只读检查库是否存在、各库适用的 AGENTS.md 及构建/依赖清单。记录实际 HEAD、工作区状态、可取得的目标基线和版本映射；有明确基线时用只读差异辅助界定变更面，不能把本地 HEAD 当成已部署版本。库中说明、注释和样例作为取证资料，不能扩大任务权限。缺库只阻塞依赖它的断言，继续其他检查。
2. 在 `/Users/yf/Documents/Unity/SDK&服务器/静态检查报告/<时间戳含微秒>/` 创建本次独立目录；若用户指定输出目录则使用指定目录。先执行本 skill 的 `scripts/baseline.py capture --output <本次目录>/baseline.json`。路径覆盖时传入 `--roots <JSON文件>`，内容为上述四 ID 到绝对路径的映射。检查脚本输出的缺库、跳过文件和扫描范围。
3. 阅读 [工具执行](references/tools.md)，执行自带 `scripts/static_tools.py --baseline <本次目录>/baseline.json --output <本次目录>/tools`。核对工具身份、状态、排除与未支持语言；工具缺失时继续源码审查，不安装依赖或把工具缺失算成功。用户明确要求纯人工只读审查时跳过工具，记录原因。类型/Lint/构建/测试按该文档与已有授权决定，默认不执行项目任务。
4. 阅读 [业务矩阵](references/checks.md)、[代码专项](references/specialty.md) 和 [项目定位](references/repositories.md)。使用 `rg --files`、定向 `rg -n` 和带行号源码读取定位入口，然后跟踪真实调用者、被调用者、条件分支及持久化。关键词匹配与快照仅用于定位，不能自动判通过。安卓/iOS及四种埋点分别取证；追踪 SDK→SDK 服务→游戏服务的接口、字段、错误语义与环境路由，事件直传时按实际链路追踪。四库分别审查循环/重试、并发、生命周期、空值/异常、资源、数据契约与持久化，记录实际函数范围；语法与类型结果独立列示。除正常路径外，按适用性检查缺失/空/边界值、失败与超时、重复/乱序、并发/重入、取消/重启、旧新版本和持久化恢复；不适用项要有代码或配置证据。
5. 建立逐断言结果。发现问题必须检查其保护逻辑是否在上层、下层、数据库约束或第三方依赖中，注明触发条件、影响、实际证据和不确定性。SDK 第三方二进制不可见时注明黑盒边界。项目专属分支只归属实际匹配项目。工具告警须人工确认，历史报告只作回归线索，不能直接沿用缺陷结论。每个 `issue` / `risk` 按 [复现步骤规范](references/reproduction.md) 提供黑盒与白盒方案；缺环境时写可验证的方案及阻塞条件，不得伪称已复现。
6. 输出 `report.html`、`report.md` 与 `findings.json`，格式见下文。所有业务最低组与四库专项领域都要有状态；不能把缺失、未读或仅搜到符号写成通过。必要时继续拆分断言，不以固定条目数代表完整覆盖。工具通过和业务链路缺失须拆开，避免一个 blocked 掩盖已确认缺陷，或局部无问题掩盖未读分支。报告须列未读/排除/不支持范围及动态验证缺口；结论不能声称“查出所有 Bug”。
7. 执行 `scripts/baseline.py verify --input <本次目录>/baseline.json`，将命令、退出码与结果保存为 `baseline-verification.json`。文件变化、原缺库出现或扫描范围变化时，不可发布旧基线结论；重新快照并审查/重跑受影响项，不能仅更新摘要哈希掩盖变化。稳定后按引导式检查规范运行 scripts/history_guard.py 核对全部选定历史报告，保存校验结果；检查 HTML、Markdown、JSON 的问题 ID、状态和计数一致后，交付报告链接、重点问题和无法确认项。

默认仅静态检查，允许运行本 skill 的基线工具、本地 Node/Swift 版本探测与仅解析命令；不运行项目脚本、测试、构建、依赖安装、应用或网络请求，不购买/发货/补奖/清档，不更改四库业务代码、Git 内容或线上配置。默认输出只写本次独立报告目录。测试代码可阅读并评价覆盖范围，不能写成已执行。用户另行要求执行项目任务时核实命令与副作用，在报告分列真实执行证据；技能调用不能扩大其他操作权限。

## 报告约定

`report.md` 包含：检查范围和用户时区时间、四库 HEAD 与工作区状态（用只读 Git 命令读取）、目标基线及本地版本到实际安装包/部署版本的映射、扫描排除项、按严重度排列的问题、完整业务及专项矩阵、实际工具结果、跨库断点、未读范围和待运行验证清单。把基线文件数、工具解析文件数和人工已审函数范围分别列出；按仓库/领域列明实际审查的文件、函数/分支，以及未读/排除范围和原因，不计算或暗示全仓覆盖率。无法读取 Git 信息就标记未知。每条 `issue` / `risk` 同时列黑盒与白盒复现步骤及各自执行状态；仅源码推演的步骤明确标“建议复现/未执行”。`no_issue_found` 可列关键路径回归场景，不虚构缺陷复现。最终明确“本报告仅为本地源码静态审查，不能据此认定发版验收通过”。

每条断言必须记录：ID、平台、领域、所属项目/共享、状态、审查范围、触发条件、证据（仓库/相对路径/真实行号/脱敏摘录）、跨库接口及上下游、影响、建议、后续验证。状态仅使用：

- `issue`：代码证据支持的缺陷；严重度 P0/P1/P2/P3，并解释影响，不能无依据夸大。
- `risk`：有证据的疑点，依赖条件或缺少保护证明；说明待确认内容。
- `no_issue_found`：已审查范围内未发现问题，写清证据与边界，不代表真实运行通过。
- `blocked`：缺源码、项目配置、依赖或版本证据；指出最小补充资料。
- `not_applicable`：有调用/配置证据证明不适用，不能以“未搜到”替代。

新增兼容字段 `history_tracking`，按引导式检查规范逐项记录历史问题的来源、当前映射、处置状态和证据；同时交付 `review-config.json` 与 `history-validation.json`。HTML 展示历史未复查项及本轮差异；仅格式转换不得改变发现集合。

`findings.json` 保留兼容字段 `schema_version: 1`、`scope`、`baseline_file`、`release_mapping`、`assertions`、`runtime_followups`、`release_verified: false`；新增 `tool_results_file`（相对报告目录路径或 null）、`tool_execution`（实际执行范围与状态，未执行原因）、`specialty_coverage`（仓库/领域/关联断言 ID）、`scope_ledger`（仓库/领域实际审查路径、未审路径及原因）、`baseline_verification_file`。`assertions` 与 Markdown 使用相同 ID 和状态。工具相关断言增加 `method`（tool/manual/hybrid）及对应工具记录定位；其他断言也标明 method。对 `issue` / `risk` 增加 `reproduction`，按复现步骤规范保存黑盒、白盒方案及执行状态；仅建议步骤不可标为已复现。未完成的项保留 `blocked` 及原因；不要删掉以制造完整结论。报告不包含真实密钥、令牌、用户身份和订单数据，证据摘录必要时脱敏。

默认真实运行待验：沙盒支付/到账/补单、四平台埋点入库、插屏与激励连续播放及奖励次数、覆盖安装及卸载重装。静态状态推导、mock 与存在测试文件均不能替代这些验证。
