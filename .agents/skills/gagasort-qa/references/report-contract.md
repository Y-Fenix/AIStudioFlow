# HTML 报告契约 v2.1

全量数据范围另受[固定测试范围](audit-scope.md)约束。报告的 `features` 必须完整保留本轮固定 ID、分类、组和业务名；只发现两条 Bug 不代表只显示两项功能。`scope-lock.json` 与 `scope-check.json` 随本轮交付。功能盘点、深审数由实际明细计算，不能用手填 `agent_audit` 数量盖过遗漏；`static_audit.cases[].scope_targets` 关联每项必查内容，缺场景的功能保持未完成。HTML 布局、五类页签和颜色规则保持现有模板。

默认交付按[便携报告协议](portable-report.md)使用固定 `查看报告.html` 读取同级时间戳目录中的 `report.md + bugs.csv + images/`。内部输入仍沿用本文 v2.1，便携存储契约为 `gagasort-report-v1`，不改变审计结论及完成度。固定使用 `assets/portable-viewer.html`、`assets/report-template.html`、`scripts/export_portable_report.py`；渲染数据准备复用 `scripts/render_report.py`。这是用户已确认的五类布局、功能结果表、详情弹窗及绿色/棕色/红色规则；执行者只填数据，不逐轮重新设计页面。模板不得包含某次运行的日期、数量、问题 ID、探针路径或结论。模板指纹由 `assets/delivery-profile.json` 锁定，渲染器拒绝未确认改版；全量收尾使用[固定交付入口](repeatable-delivery.md)，不能只渲染 HTML 省略导表、源码复核和浏览器检查。

## 阅读路径与颜色

首屏给一句大白话结论、实际执行范围、已确认根因数（区分静态已证与动态已复现）和待核实风险数。方法问题与真实玩家可达性分开，执行未完成不得说“全量通过”。功能数、运行数、断言数不能相加；无失败不自动等于通过。

主导航固定为“总览”加五类检查页签，默认打开总览。总览独占整体状态、汇总数字和实际执行范围，并列五模块结论入口。业务页签不重复整体总览；顶部固定本模块结论，随后问题与风险清单，再显示检查明细。切换页签后回到内容顶部；模块、筛选和图片深链刷新保持对应页签。五类检查页签内再按实际功能分组：

| 分类 | 内容 |
| --- | --- |
| 玩法 | 局内泳池、水道、鸭子、机关、道具、失败与残局 |
| 关卡 | 每关有解性、布局异常，以及生成、保存、预览与回放工具 |
| 系统 | 支付、礼包、商城、活动、排行榜、头像、设置、多语言等非关卡功能 |
| 配置 | 后台参数边界、默认值、组合、解析、接纳与实际消费 |
| 埋点 | 固化埋点表与代码事件双向覆盖、属性字段、统一上报出口、重复/异步和 SDK 自动采集边界 |

多语言在“系统”内独立分组，细分语言表与缺失文案、参数格式、语言切换、字体资源、偏好恢复等实际检查项；缺陷注明语言、key、受影响页面、原因和复现步骤，沿用现有功能与问题结构，不新增页签或人工待办。

### 模块内交互（固定）

- 模块第一屏回答“纳入哪些内容、有无已确认问题、有哪些风险、哪些还没查完”。四个指标固定为已确认问题、风险待核实、功能检查未完成、检查未见问题；均可点击定位或筛选。
- 问题集合由归属于本模块的 findings 与功能 / 配置组引用的 findings 取并集、按 ID 去重；没有功能引用的问题仍须展示。已确认问题直接列标题，点击看步骤、预期 / 实际与归因。风险列出条件入口；已有图片解释的风险直接跳图。
- 完成度独立于问题数计算：发现问题的功能也可能尚未查完；问题按根因、进度按功能 / 配置组，不能相加。缺静态场景或源码已变均计未完成，不能被红色主状态遮住。空模块、零 finding、未查完均不得给“无问题”结论。
- 关卡额外区分功能审查数与逐关数；视觉风险按唯一关号去重，岸壁 / 水面可重叠；不将关数与业务问题数相加。逐关未定不能被功能摘要覆盖，功能未审完也不能抹掉已完成逐关检查。
- 功能与配置组统一支持全部、问题 / 风险、未完成、未见问题筛选；配置业务功能也须参与筛选。数字显示实际筛选数 / 纳入数。未关联功能的问题仍保留在问题区，空表不可暗示无问题。
- `#module-<play|levels|systems|config|tracking>-<all|confirmed|risks|problem|incomplete|clear>` 为稳定定位；刷新保留筛选，关闭详情返回原筛选。切换和定位转移键盘焦点，筛选按钮提供 `aria-pressed`。390px 下无横向溢出。

功能表固定为“功能 / 检查了什么 / 检查结果 / 详情”。名称与摘要用业务语言，不把脚本名、类名、编译错误当作功能说明。详情先看结果与复现步骤，再看归因；命令、日志、源码、依赖错误和升级重装分析收在详情中。保留每功能三条安装数据条件的静态分析，不执行实际安装或卸载。

### 总览 Bug 列表与导出（固定）

固定查看器保留列表、步骤、归因、证据摘录、图片、CSV 导出和飞书表头更新及手动提单。仅用户点击读取时连接本机飞书桥接，加载报告不访问网络；默认文件夹加载使用便携协议的交互与校验，不承诺刷新后自动恢复用户已选文件夹。

- 总览在模块结论前展示 Bug 列表，顶部问题数直接定位 `#bug-register`，刷新保留定位，不先弹证据。五类模块内不重复该表。
- 表头以 `assets/bug-columns.json` 为唯一来源，取自用户 `BUG管理.base` 的“未解决”视图。完整保留23列、原名称和顺序；空列仍存在，不提供隐藏列开关。横向滚动限制在表格内，桌面固定首列和表头，窄屏不挤出整个页面。
- 每个已确认 finding 按 ID 生成一行，包含无功能引用的已确认问题。只包含 `静态缺陷已证 / 方法问题已证 / 产品问题已证`；条件风险、几何风险和未完成项保留原区域，不作为可提单 Bug 混入。零问题保留23列表头和明确空状态，不能暗示检查已完成。
- “缺陷描述”直接展开编号、白话标题、证据层级、条件、前置/入口、步骤、实际表现、归因和影响，保留适用的判定依据、矛盾点、恢复方式、范围限制与源码变动提示。准确黑盒路线优先展示，并保留已有白盒补证；无核定玩家路线使用原白盒步骤。静态证据不得写成真机已复现。
- “期望描述”取白话预期；“日志信息”取实际日志位置与源码链，不能伪造运行日志。新问题的本地导入初值为“缺陷状态=未解决”“问题类型=BUG缺陷”，不表示已在飞书提单或读取了飞书状态。
- Bug 单的“版本号”固定填写 `Codex`，HTML 列表、提单预览、配套/浏览器 CSV 及飞书提单使用同一值；即使 finding 的 `bug_fields` 带有其他版本号也不覆盖该固定值。这是提单标签，不替代报告中的真实游戏版本、HEAD 或基线。平台、严重程度、优先级、复现率、功能模块及发现构建号只填有依据的数据。不凭大类猜飞书功能模块选项，不因白盒成立填玩家必现；创建人/修复人、系统时间、滞留时长、验收资料和父记录等无数据就留空。页面空值显示“—”，CSV 保留真正空字段。
- 需要填已知信息时，在 finding 内可选提供 `bug_fields`，键只允许 `版本号 / 操作平台 / 严重程度 / 优先级 / 复现率 / 功能模块 / 发现Jenkins构建号 / 截图/视频`，值为有来源的字符串；其中版本号仅兼容读取旧输入，输出始终为 `Codex`。不得覆盖描述、预期、系统/验收字段。模板内历史选项仅供参考；飞书选项字段仍须包含 `Codex` 才可写入，不自动创建选项。CSV 中的附件列只能承载已知文本引用，不表示文件已上传到飞书。
- 搜索和分类筛选仅影响页面显示；“导出 CSV”始终下载全部已确认问题和当前表头。默认表头为固化的完整23列；UTF-8 BOM、CRLF、引号转义、多行字段和公式前缀防护固定处理。`scripts/bug_register.py` 生成默认表头的配套 `bugs.csv`，远程表头仅在 HTML 运行时生效。
- 飞书交互参照 `test-case` / `test-codetest`，仅处理 Bug 表单，不启动它们的用例任务。弹窗标题“新建 Bug 单”，显示本次已确认问题数、URL、“读取表头”、全部内容预览、“关闭”和“直接更新并提单”。支持 HTTPS 飞书/Lark Base/Wiki URL；不展示 Bearer、授权二维码或接口实现说明。不从 MD 继承授权信息；用户点击读取表头才发起只读请求，实时校验本机登录，用户检查预览并手动确认提单才写入。
- 提单弹窗使用接近全屏的可用区域：紧凑顶部、预览占剩余高度、底部操作固定可见，不限制预览为320px。预览字号11px、缺陷描述列800px、步骤列640px、其他长文本列320～380px，短字段120px；全部列保留且仅表格内部滚动。常见桌面视口须能在不纵向滚动时看完整个首条问题，长内容不截断、不省略。
- 用 `base +url-resolve` 解析真实 table_id，用 `+field-list` 完整分页读取字段；URL 有 view 时调用 `+view-get-visible-fields`，保留真实可见列名、顺序和空列，未知字段或不完整结果失败，不丢列、不猜表 ID。精确名称优先，受控别名映射：标题→带【静态检测】的标题，复现步骤→证据层级/方式/准备/入口/全部步骤/限制，期望结果→期望描述，实际结果→实际表现，归因→根因。日志保持真实日志和源码链，未知字段留空。全部行直接预览，表头与下方列表、CSV 同步；读取成功只启用按钮，不写入。URL 变化或读取失败立即失效旧表与预览。
- 真正写入仅由弹窗“直接更新并提单”触发，通过本机桥接使用 `--as user` 和 `base +record-batch-create`。提交前重新读取并核对表头；按真实类型检查数值、布尔和已有选项，系统/附件不作为普通字段写入。不凭条数推断成功：必须完整返回 record_id_list 且无 ignored_fields。连点只发一个请求，成功锁定；超时、部分结果或未知结果显示“提交未确认”，禁止自动重试。`assets/delivery-profile.json` 锁定模板和默认表头指纹；浏览器回归验证授权门禁、完整空列、映射、读取无写入、URL变化失效、全部CSV导出、成功防重、失败不伪报成功及原模块交互。

| 颜色 | 含义与边界 |
| --- | --- |
| 绿色 `#21704b` | 所列代码检查范围未发现问题，或关联局部测试通过。静态检查写“代码检查未见问题”，不得暗示跑过游戏或完整验收 |
| 棕色 `#8a5d35` | 未检查、检查未完成、执行受阻、风险待核实，或源码变化后当前版待复核 |
| 红色 `#b43836` | 有完整源码证明的静态缺陷，或已动态复现方法/产品问题；标明证据层级，环境错误不算产品问题 |

颜色由生成器根据证据状态计算，数据不能指定 `tone` 冒充绿色。已证问题优先红色；风险、版本变化、未完成使用棕色。动态失败记录照实保留；本地执行受阻不覆盖已经独立完成的静态结论。主状态按静态场景完成度判断，不以必须跑游戏为门槛。

## 数据字段

新巡检输入为 UTF-8 JSON，`report_contract_version: "2.1"`、`presentation.audit_mode: "静态检查"`。生成器仍可渲染历史2.0数据；旧报告不自动补造新静态场景，也不因升级skill改成通过。布局继续使用用户确认的五类样式。

保留来源结构：`baseline / external_change / source_changed / features / findings / suites / additional_runs / configuration_cases / configuration_fields`。

`presentation` 必填：

- `overall`：`执行不完整 / 检查完成且发现问题 / 检查完成且范围内未见问题`。
- `conclusion`：一句真实结论；`execution_scope / not_executed / supplement_summary`：执行层级、未执行范围与补证口径。
- `format_only`：布尔；`product_test_run_id` 必须等于 `baseline.run_id`；`evidence_head` 为实际证据对应版本。
- 可选 `configuration_summary`：配置范围的大白话概述，数字须来自输入或运行证据。

每功能保留 `checks / installation / source_paths / related_findings`，以及 `assessment`：

- `code_review`：`未审查 / 局部静态审查 / 完成静态审查`；`code_conclusion` 为实际代码事实。
- `run_ids`：Agent按真实覆盖范围核定后引用 `suites` 或 `additional_runs` 的稳定 ID，禁止按名称相似猜覆盖。
- `verdict`：`发现静态缺陷 / 发现方法级问题 / 发现产品问题 / 风险待确认 / 局部检查未见问题 / 证据不足 / 当前版本待复审`。
- `conclusion`：业务结论；`follow_up` 只列具体未查代码分支，可空。普通功能不必填人工字段，默认无需人工。
- 新增 `display`，必填 `category / group / name / check_summary`：五类之一、子分组、白话功能名、白话检查内容；可选 `result` 为白话结论。不用代码标识代替说明。

每问题保留 `id / title / status / kind / condition / cause / impact / expected / actual / missing`；v2.1的 `manual / manual_readiness` 可省略，默认无需人工。保留适用的 `log / local_steps / source_paths / source_drift`。新增 `display`：

- 必填 `category / title / condition / cause / impact / expected / actual`，用白话解释已有事实。
- `whitebox_steps`：准确输入、调用顺序与观察点，对应原始 `local_steps` 和日志；已证问题缺完整黑盒时必填。
- 可选 `review_steps`：静态核查步骤，明确“尚未动态复现”。
- `kind` 为 `方法问题已证` 或 `产品问题已证` 时须有复现日志与步骤。前者只说明方法层成立，不自动升级线上 Bug；其他类别按风险显示。

运行记录保留 `id / status / command / exit_code / reason / summary / evidence`。状态以“未执行”开头时 `command` 缺省、`exit_code=null`；聚合无单一退出码须明确并附逐场景记录。退出码 0 也可能表示成功观察到缺陷。

固定交付规范启用后的新巡检，每条实际命令增加 `execution_receipt`，指向 `record_run.py` 执行时生成的本轮回执，绑定运行 ID、基线、输入、原日志和直接产物哈希。聚合记录拆成原始命令记录后分别回链；非零退出码不得标通过。历史数据仍允许底层渲染阅读，但不补签回执后宣称新批次通过。

## 逐功能静态场景（v2.1必填）

执行[逐功能静态协议](static-first-audit.md)，每功能新增：

```json
{
  "static_audit": {
    "status": "已完成",
    "summary": "基于所列初态和源码路径的具体结论",
    "cases": [{
      "id": "功能内稳定场景ID",
      "dimension": "边界与异常",
      "scenario": "具体检查了什么",
      "preconditions": "可达初态与资格",
      "input": "准确输入值或事件顺序",
      "basis": "已查业务规则或技术不变量",
      "expected": "允许和禁止的结果",
      "actual": "沿源码分支推导的结果",
      "verdict": "未见问题",
      "trace": [{"path": "仓库相对源文件路径", "line": 1, "note": "本节点的条件、写入或消费作用"}],
      "finding_ids": [],
      "run_ids": []
    }]
  },
  "external_checks": []
}
```

示例只展示字段，不能直接复制成产品证据。每功能的cases须覆盖入口与正常链路、边界与异常、重复与异步、状态与持久化、配置变化、升级与重装、跨模块影响七个维度；不适用给 `reason` 和源码依据，不要求无意义地堆场景。维度内实际存在多个输入/分支要逐条检查，不能用一条模板话冒充穷举。

场景结论：`未见问题 / 发现问题 / 待核实 / 未检查 / 不适用`。后三种须给 `reason`。已判未见问题/发现问题/不适用须有可读取源码快照与真实行号；发现问题须通过 `finding_ids` 回链本功能具体已证问题。`status=已完成` 不得含未检查/待核实场景，不能全部不适用；同时 `assessment.code_review=完成静态审查`。源码变化后继续降级当前版待复核，不改旧证据。

新巡检的整体完成条件按静态场景判断：适用功能、配置和逐关数据检查均完成，才说静态范围检查完成。可选本地执行受阻、没有Editor/设备或没有人工黑盒，不自动把已完成静态检查改为未完成。未运行仍不得标成动态通过。

`external_checks[]` 仅记录无法从本地决定的最小外部事实，字段必填 `id / assertion / dependency / why_not_local / local_case_ids / remaining_fact`。dependency仅允许 `真实设备表现 / 真实平台/SDK行为 / 真实服务端合同或下发 / 可信已发布版本差异`；local_case_ids须回链本功能已完成场景。本地时间、回调、旧档、缓存或配置处理不得以缺设备为由转人工。外部事实只作范围限制，不是人工待办，不计入静态未完成数；客户端对应处理必须查完，具体条件风险仍单列。

`kind=静态缺陷已证` 时新增 `static_proof`：`basis / preconditions / entry / trace / contradiction / steps`。须有有效规则、可达初态、真实调用/数据消费链、确定矛盾与复核步骤，源码快照与行号可核查；无需伪造动态日志。显示“静态已证·未动态运行”，不显示“已实机复现”。入口或合同未核定时只能报条件风险。


## deep-v2 深审结构

当 `agent_audit.protocol` 为 `multi-agent-v2` 时，每个功能和配置组的 `static_audit` 必须包含：

- `depth.protocol = "deep-v2"`；
- `depth.branches[]`：真实分支的 `id / dimension / condition / consumer / evidence`；
- `depth.coverage[]`：七个维度各一项，状态为 `已闭合 / 部分闭合 / 未检查 / 不适用`，并回链 `branch_ids / case_ids`；
- `static_audit.cases[]` 中的场景必须来自 dossier 的 `checks[]`，每项回链 `branch_ids` 和显式 `finding_ids`。

渲染器会校验七维、分支/场景双向引用、源码快照和行号。缺口会以棕色显示在功能列表和详情顶部，并明确“这是代码审查缺口，不是必须人工测试”。

## 黑盒与白盒步骤

`manual_readiness` 默认 `无需人工`，无需创建 `manual`。只有确有可核定玩家路线时才填 `步骤草案 / 完整待执行 / 已执行`；草案不得成为所有功能的统一收尾。新巡检不显示正常功能的空黑盒待办。

完整黑盒使用 `manual.prepare / steps / abnormal / restore / status`；每步含 `action / observe`。准备、玩家入口、动作、观察及恢复须可核实。已执行还须 `manual.evidence` 和每步 `actual`。静态场景和结论始终展示；有真实可执行的黑盒复核资料再附，不作为静态完成前置。

没有黑盒时直接展示实际静态推导或本地白盒步骤，不让同事补齐一套玩家操作来替代 Agent 的静态检查。草案须填 `manual_missing`，具体说明缺关号、入口、账号数据或恢复办法等。不得把 SDK 回调注入、配置构造伪装成玩家操作，也不得编造按钮或必现入口。

## 逐关检查与真实异常图

顶层 `level_audit` 必填，即使本轮未检查也要明确记录。逐关检查必须保留三份机器可读结果：`levels/level-inventory.json`、`levels/layout-results.json`、`levels/solvability-results.json`；顶层增加 `inventory_file` 指向枚举清单。每维度条目增加 `result_file` 指向对应结果文件；关卡结果 JSON 顶层含 `schema_version=1 / inventory / total / checked / results`，每关 `results[]` 含唯一 `level_id / verdict / checks / evidence`。报告 `total / checked` 必须与结果文件和枚举清单一致，不能手工填数。示例：

```json
{
  "inventory_file": "levels/level-inventory.json",
  "solvability": {"status": "未检查", "summary": "没有逐关求解结果", "run_ids": [], "evidence": [], "result_file": "levels/solvability-results.json"},
  "layout": {"status": "未检查", "summary": "没有全量布局检查结果", "run_ids": [], "evidence": [], "result_file": "levels/layout-results.json"},
  "anomalies": []
}
```

状态为 `未检查 / 检查未完成 / 检查完成未见问题 / 发现问题`。任何已经开始的逐关检查都必须有 `result_file` 和可读取证据。完整结论须有正整数 `total`、`checked == total`，逐关结果文件中的唯一 ID 集合须与枚举清单完全一致，且每项都有确定 verdict 和证据；预算耗尽/异常/缺入口须为未定并使维度保持 `检查未完成`。工具代码审查、某个映射测试通过、手工填写数量均不等于逐关检查完成。生成器拒绝完成状态缺少结果文件、ID 重复/缺漏、清单外关卡、数量不一致或未定项。

确认布局异常时，`anomalies[]` 填 `level_id / caption / image / evidence / steps`：真实关号、说明、由实际关卡数据绘制并标出异常的 PNG/JPG/WebP、原始布局/判定证据和复现步骤。路径相对证据目录，生成器内嵌原图。每张图必须能回链 `layout-results.json` 中同一关卡的已确认异常 verdict；图片与原始输入均须存在。无异常时展示空状态，不画虚构关卡代替检查结果。异常列表为空不代表扫描完成，仍须完整逐关结果文件。

### 关卡管线 v2（全量模式必须使用）

`level_audit.pipeline_version=2`，固定 `summary_rows` 五项 ID：`structure / package / solver / wall / water`，以白话说明实际查了什么、结果、边界和证据。`table[]` 与 inventory 全集一一对应，包含 `level_id / number / structure / layout / solvability / visual / evidence`；逐关表可筛选并点击证据。不能只贴大段工具说明。

增加独立 `visual`，包含 `status / total / checked / summary / result_file / evidence / wall_risk_count / water_risk_count`。结果文件为 `levels/visual-summary.json`，逐关 verdict 为 `未见问题 / 风险待确认 / 未定`，含 `wall_risk / water_risk` 布尔及证据；checked 只计明确结果，风险数按唯一关卡分别统计，不按三角片或 Resources/Hotfix 双份重复计数。视觉状态允许 `有风险待确认`（棕色）；不能把几何相交直接升级为已确认游戏 Bug。

`risks[]` 字段同异常图并加 `kind=visual-risk`；每张图回链同关视觉风险结果。来源、真实坐标、三角形与判断保存在 detail；默认折叠风险图，展开可见定位与白盒复核步骤。原 `anomalies[]` 继续只收已确认的基础布局异常（红色）。三项总状态分别为有解、基础布局、表现网格；基础布局全绿不覆盖另外两项的棕色。生成器不得因 `risks=[]` 自动推断未跑过的视觉检查通过。

报告优先给接手的测试看结论和图：岸壁、水面摘要的主链接必须直接跳到对应类别的图片解释区，自动展开首张图，提供可点击关号；逐关表中有风险图的关卡直接链接该关图片。类别由逐关结果的 `wall_risk / water_risk` 布尔值生成，不能靠标题关键词猜测。同关两类风险都命中时，两类入口均可找到该关。图片下先用白话说明“看哪里、有什么风险”，再列核查步骤；原始 JSON、日志和哈希放入折叠的“开发核对”，不得作为已有图片解释的默认点击结果。刷新深链仍须显示对应类别/关卡图片，点击图片入口不打开原始证据弹窗。

## 配置组

`configuration_groups[]` 每组包含：

- `id / name / status / conclusion / case_indices`：稳定 ID、白话名称、结果、结论和引用 `configuration_cases` 的零起始索引数组。所有实例恰好分组一次，不得遗漏或重复计数。
- `run_ids / issue_ids`：真实关联；`log / source` 为相对证据目录的日志和准确输入源码；可选 `check_summary / steps` 为白话摘要与具体白盒步骤。
- `status`：`未检查 / 测试未完成 / 代码检查未见问题 / 局部测试通过 / 有风险待核实 / 发现问题`。静态绿色须有已完成场景且无关联问题，不要求动态运行；“局部测试通过”仍须真实通过日志。红色须关联静态/动态已证问题。v2.1每组同样填写 `static_audit`，但不强制七个功能维度。
- 配置实例可填 `display_name`；原始 `name / input / status / evidence / limits` 保留追溯。字段盘点数与已测试输入数分开。

## 生成与交付

默认便携报告使用 `portable-manifest.json` 和 `portable-interaction-check.json` 记录查看器、MD、CSV、图片及真实交互的哈希。以下为旧格式底层渲染命令，仅适用于显式要求的旧联机格式或定向调试；全量巡检必须执行 `scripts/finalize_report.py --root <仓库> --evidence-dir <本轮目录>`，同时生成固定配套文件和真实浏览器回执。完整参数及完成语义见[固定交付协议](repeatable-delivery.md)。

```bash
python3 -B <skill目录>/scripts/render_report.py \
  --data QA/results/<批次>/report-data.json \
  --evidence-dir QA/results/<批次> \
  --output QA/results/<批次>/report.html
```

缺字段、重复 ID、引用不闭合、证据缺失、完成结论与未测项冲突时须修正数据后再生成，不绕过校验或手改产物。`report.html` 对应 `html-manifest.json`；其他名称对应 `<文件名>-manifest.json`，记录模板和产物 SHA256。结构校验不证明业务正确。

交付前核对：总览与五类导航和分组、默认总览、模块顶部不重复总览、切换及刷新深链保持正确页签；绿色静态无问题、棕色未完成/待核、红色已证各一个适用条目；问题→步骤→归因→日志；静态场景直接可读、不再给正常功能造人工草案；计数随数据变化；关卡无证据时不显示已测或假图；关键摘录和 CSV 导出、目录切换、缺文件阻断、搜索筛选、390px无横溢、链接无下划线。浏览器不可用如实记录，不用文本校验冒充视觉验收。


### 最终交付门禁

`audit_completion.py` 生成 Agent 续查队列：缺 dossier、未闭合分支、自由文本 gaps、源码变化、配置或逐关缺项均返回 2；由总控继续执行。0 还须经过现有报告结构与证据校验。允许渲染中间报告供追踪，但不得以此声明全量完成。已有历史报告不因 skill 更新改绿，不重新计算历史 Bug 结论。
