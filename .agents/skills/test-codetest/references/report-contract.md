# 代码检查报告契约

跨库输入须按[跨库发版检查契约](cross-repo-release.md)绑定 `cross_repo.profile/snapshot/ledger` 的路径与 SHA256；两份输入绑定一致，`baseline` 为快照摘要，原断言用 `cross_repo_targets` 关联本地链路断言。校验器重新核对当前源码与账本结论，HTML 复用该门禁；原来源、需求和运行证据要求仍全部保留。未启用跨库的旧报告无需增加字段。

Bug 单“版本号”固定为 `Codex`；报告中的 `baseline`、分支、提交和游戏真实版本仍保留实际值，不能互相替代。

生成结果表前读取本文件。校验脚本仅用 Python 3 标准库；同事复制完整 `test-codetest/` 目录即可携带，无个人路径或第三方依赖。它不执行账本中的命令、不读取账号接口，也不修改业务文件。

## 输入与输出

先从真实 Excel 全部用例行提取 `input-manifest.json`，独立于审查结果生成。六列按原文本读取，空单元格统一 `""`；不 trim、不改写步骤。公式单元格用原公式文本，日期等非字符串按已声明的稳定显示方式转换，回读采用相同方式。

```json
{
  "schema_version": 1,
  "cases": [{
    "key": "测试用例!2",
    "cells": ["到期边界", "核对资格", "等级8", "时间设为200", "不可领取", "活动需求.docx"],
    "assertions": [{"id": "eligibility", "text": "时间等于200时不可领取"}]
  }]
}
```

`key` 是内部关联位置，不输出用例编号。每行全部独立期望都要拆入 assertions，不能为了容易通过只列部分。脚本能检查账本是否漏掉已列断言，不能自行理解 Excel 来发现提取阶段遗漏，因此生成清单后仍需从原需求/期望反向审阅。

输入清单还必须保留从本次用户选择建立的 `selected_source_ids`，与来源账本集合对账，不能只列读取成功项。输入清单与下述审查账本还必须各自带相同的来源绑定，完整契约先读 [media-coverage.md](media-coverage.md)：

```json
{
  "report_stage": "final",
  "source_coverage": {"path": "source-coverage.json", "sha256": "实际账本文件SHA256"}
}
```

默认 `final` 拒绝缺失、未读或未覆盖来源/媒体；只有明确交付阶段结果才两份同时设置 `partial`。旧用例表确无来源账本时可以仅在 `partial` 下审查现有用例，不能声称需求全覆盖。来源缺口与代码断言分开，已证明的静态/自动化结论仍保留，未知图片内容不能根据代码倒推成需求。以上是需要合入各自顶层的字段，不是替代完整输入或审查账本。

审查账本 `review.json`：

```json
{
  "schema_version": 1,
  "scope": "code",
  "baseline": "实际分支/提交及相关工作区指纹",
  "evidence": [
    {"id": "rule", "kind": "requirement", "path": "需求/活动.md", "sha256": "实际文件SHA256", "locator": "活动时间条款"},
    {"id": "code", "kind": "source", "path": "src/event.cs", "sha256": "实际文件SHA256", "locator": "CanClaim调用链", "line": 12, "baseline": "与上面一致"}
  ],
  "cases": [{
    "key": "测试用例!2",
    "input_sha256": "对原六列数组计算的实际指纹",
    "assertions": [{
      "id": "eligibility",
      "text": "时间等于200时不可领取",
      "domain": "local",
      "verdict": "pass",
      "method": "static",
      "input": "level=8, now=200, end=200，其余资格满足",
      "expected": "false",
      "actual": "now < end 为 false，CanClaim 返回 false，拒绝分支不发奖",
      "reason": "追踪已加载配置、时钟与调用方；截止为开区间，返回后不进入发放",
      "evidence": ["rule", "code"]
    }]
  }]
}
```

示例均为结构示意，不代表项目已有这些文件或需求。指纹算法：UTF-8 编码 `json.dumps(cells, ensure_ascii=False, separators=(",", ":"))` 后 SHA256。脚本导出的 `fingerprint(cells)` 可直接复用。

证据文件路径优先项目相对路径，外部需求可绝对路径；分发报告时路径需仍能定位。哈希对文件原始 bytes 计算。`source` 要实际代码/可读资源位置和有效行号；二进制资源由实际解析证据或可读导出承接，注明读取链。不可把此示例、测试夹具或旧报告冒充生产源码。

## 失败断言的提单文案

每条失败断言可以增加 `bug` 对象，字段为 `title`、`precondition`、`steps`、`actual`、`expected`。这五项只表达该失败断言已证明的事实，不改变 `verdict`、原始用例六列或独立需求预期。`steps` 接受字符串或动作字符串数组，输出统一为真实换行和 `1、2、3、` 编号。

文案按[报告交付的 Bug 文案规则](report-delivery.md#bug-文案与字段映射)编写：前置能构造、操作能执行、实际与预期能对照。`bug` 中显式空值不能被默认内容掩盖；缺失必备文案或可定位证据时 HTML 阻断提单。生成器的格式检查不能证明文案语义正确，交付前必须逐条核对失败证据。未提供 `bug` 时只使用该失败断言自身的字段，禁止从通过断言或整行汇总中拼接。

## 断言与未决原因

- `domain`：`local` 为本地规则/数据可判断；`external` 仅外部独有观察。外部断言额外写 `external_variable` 与 `why_local_insufficient`，禁止仅凭名称判外部。
- `verdict`：`pass/fail/unresolved/obsolete`；`method`：`static/automated/observed/none`。本地通过/失败需实际生产源和独立期望来源、具体 input/expected/actual/reason。失败还需 `reachability`、`steps`。外部通过/失败只能 `observed`，提供实际观察文件证据，不能静态冒充投递或真机成功。
- `obsolete` 使用 `none`，需当前权威来源与 `replacement`。不因过时测试失败报产品 Bug。
- `unresolved` 使用 `none`，提供 `blocker`：`kind | variable | why_local_insufficient | next_action | owner`，原因具体到被阻断断言；同根因可共用内容但逐实例核对适用性。
- `kind=external`：仅外部断言可用，还需 `preparation | steps | observation`。说明是否清档/独立账号、入口和正常观察值。
- `kind=environment/automation/seam`：仅本地断言可用，还需 `static_gap | cannot_resolve_locally | attempts`。attempts 列出 `strategy=static_trace/fixture/existing_runner` 三种，每项带 `status=attempted/unavailable` 与实际 `result`；没有接口本身不等于不能受控 patch。不能只写“待补环境”。
- `kind=materials/requirement`：额外写 `searched | missing_or_conflict`，具体缺失物或权威冲突，不使用“还没查完”代替缺材料。

自动化 `run` 证据必须关联真实日志/原生结果文件，带 sha256、locator、baseline，以及 `command`（实际 argv 数组）、`cwd`、`runner`、`run_id`、`exit_code`、`discovered/passed/failed/errors/skipped`。计数口径需互斥且总和一致；原始 runner 非互斥统计先如实规范化，保留原报告。

运行证据的 `results` 是 `{"测试用例!2/eligibility": "passed"}` 形式的断言映射，值为 passed/failed/skipped。只有确认真实测试覆盖该断言及输入才关联。不能用套件总绿代替映射；套件其他测试失败不抹掉本目标真实通过。脚本检查记录和引用，不解析所有 runner 格式，也不证明日志内容和手工映射必然一致；审查者仍须核对原始报告。

## 执行门禁及生成器接入

同次运行还必须按 [四维覆盖契约](coverage-contract.md) 独立运行 `validate_design_coverage.py`，绑定同一输入清单及来源账本。覆盖门禁检查需求、耦合、边界及升级的设计映射；下面的报告门禁检查逐断言结论，不能互相替代。两份校验结果共同保留，覆盖缺口按阶段结果展示，不改变已证实的代码结论。

在实际 Skill 安装目录执行，把占位路径换为已核实路径：

```sh
python3 scripts/validate_report.py \
  --root /绝对路径/项目 \
  --input /绝对路径/input-manifest.json \
  --review /绝对路径/review.json \
  --output /绝对路径/validated-results.json
```

只在退出码为0时生成正式表；`--output` 必须为新路径，防止误读旧成功文件。JSON 结构错、漏行/断言、原文改变、证据文件/哈希或基线不匹配、运行计数错误、缺必要转人工理由，均非零退出。不限制真实失败/残留的数量。真实失败的账本可合法通过校验，校验通过绝不等于产品测试通过。

生成器从 validated-results 的逐行 `result` 和 `counts` 回填，不自行再判状态；从 review 取依据、运行详情及完整外部残留。输出包含 `external_failure_ids`，必须在同页摘要醒目标出，不能因默认 code 范围藏掉已知外部失败。

门禁输出同时包含 `root`、`report_stage`、`manifest_sha256`、`review_sha256` 与 `source_coverage` 摘要。两个内容指纹使用 UTF-8 的 `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`，区别于原六列指纹；来源绑定的 SHA256 则对文件原始 bytes 计算。HTML 会重新运行同一门禁并拒绝旧/篡改摘要；Excel 回读必须核对同一输入与来源账本。来源摘要的 `complete` 仅表示已登记资料/规则的证据和映射对账完成，不等于产品通过。

默认归并 code 范围本地断言，full 范围全部；纯外部行不允许空集合通过。full 已实际观察全部通过可用 `测试通过（真实环境）`，混合静态/运行/观察证明使用 `测试通过（混合证据）`，不冒充全部执行。主 Skill 九种常见状态之外这两种仅用于有真实观察证据的完整验收，统计须容纳。

Excel 生成后按 input 同一读取约定回读，逐行核对原六列指纹、结果、残留及计数，不能只校验 JSON 就宣称 Excel 正确。保存校验命令和退出码。校验失效不得沿用旧 Excel 或旧摘要冒充本轮完成。

该脚本是 Skill 工作流入口，不是已经接入用户项目的强制 CI。忽略执行入口的模型仍可能绕过；若团队需要机器层面禁止交付，应在团队实际报告生成命令或 CI 中调用并检查退出码，这需要另行接入授权。
