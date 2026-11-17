# 引导式检查与历史问题核对

## 入口选项

普通调用先引导用户选择；已经明确的选项不重复询问。用可用的用户输入工具展示选项；没有工具则用编号文字提问。每轮只问一个主题，等待回答后继续依赖该答案的操作，可同时只读检查路径和历史报告。推荐选项不等于用户已选择。用户明确要求直接执行时使用推荐配置并记录假设。

1. **检查模式**：转测全面检查（推荐，业务矩阵和专项逐项取证）；变更及耦合检查（需要实际基线，追踪改动调用链与上下游）；历史问题复查（核验旧问题及相关回归）。缺变更基线时询问分支/提交，不擅自用 HEAD 代替。全面模式也不能声称查全；未读项必须展示。
2. **检查对象**：默认四库（推荐）；指定仓库；指定业务链路。选指定项后再询问实际仓库/支付、埋点、广告等范围。范围外旧问题仍列未复查，不计为本轮确认。项目归属和实际发布版本从证据识别，未知写未知。
3. **验证深度**：静态检查＋黑盒白盒方案（推荐）；静态＋本地隔离测试；真实集成/沙盒验证。后两项先核实真实命令、环境及副作用，遵守已有授权；环境不足时保留静态结果和 blocked 项。选择沙盒验证不代表授权生产购买/发货、外部通知或改业务代码。

默认交付 HTML＋Markdown＋JSON。持久化 review-config.json：mode、repositories、focus、baseline、verification_depth、output_formats、choices_source（user/inferred）、previous_reports、excluded_reports 及排除依据。仅保存本次选择，不自动修改以后会话偏好。

## 历史台账：所有模式必做

在同一报告根目录只读发现历史 findings.json，按真实仓库路径、项目和业务归属选出相关报告；不能只读最近一轮，历史首次发现可能早已漏掉。列出读取失败、无法判定归属或被排除的报告及原因。历史材料是线索，不是当前已确认事实；不得把历史数量累加成当前 Bug 总数。

每个相关历史 issue/risk 都必须在本轮 findings.json 的 history_tracking 中有一行：

```json
{
  "source_report": "/absolute/path/to/old/findings.json",
  "source_id": "android.purchase",
  "disposition": "pending_review",
  "current_id": null,
  "reason": "本轮范围外，尚未复查",
  "evidence": []
}
```

- pending_review：未复查；needs_revalidation：基线变化或缺证据，待重新验证。两者保留历史分类，但不冒充本轮 issue/risk。后续每轮都要承接未决台账，即使源问题未出现在上一轮 assertions 中。
- confirmed：已对本轮源码取证，current_id 指向本轮 issue/risk；同一问题保持稳定 ID。历史不同 ID 经人工确认属于同一根因时可映射到同一个 current_id，保留所有来源和合并理由；不可只凭标题相似合并。
- fixed、false_positive、not_applicable：必须有 reason 和 evidence。fixed 明确是源码修复复核还是实际回归通过；测试一次未复现不自动证明修复。缺证据保持待复查。
- issue/risk 分类变化必须记录理由和新证据；严重度变化也记录依据。换版本、没再次发现、用户选择小范围都不是关闭依据。

交付前执行：

```sh
python3 /Users/yf/.codex/skills/test-server-sdk/scripts/history_guard.py --current <本轮>/findings.json --previous <旧轮一>/findings.json --previous <旧轮二>/findings.json
```

每份选定的相关报告都传入 --previous；source_report 使用解析后的绝对路径。没有历史时省略 --previous，并说明首次建账。校验结果及退出码保存到本轮 history-validation.json；失败时补齐遗漏，不通过不能声称历史核对完成。脚本只检查传入台账的结构与遗漏，不验证证据真实性、自动发现全部历史报告或证明无 Bug，人工仍需核对来源和关闭依据。

## 报告与展示

HTML 是本轮 JSON 和 Markdown 的展示，不能重做一轮审查后替换原结论。每个问题的 ID、分类、严重度、影响、证据、黑白盒步骤与执行状态必须一致；交付前核对三种格式的 ID 集合和各状态计数。HTML 默认离线可读，不加载外部脚本或远程数据；源码摘录和其他输入须转义为文本。

分别列本轮确认问题、新增问题、历史未复查/待验证、已关闭及其依据、合并映射、未覆盖范围。历史未复查项展示原报告链接、原结论与当前未验证标识，不静默消失，也不计成本轮确认。对比注明来源与基线；没有充分匹配时写未知。用户只要求格式转换时保持原发现集合，不擅自删改问题。

人工核对：选小范围时范围外旧问题仍存在；无环境时复现写未执行；不同版本无法确认时不关闭；三种格式状态和证据一致。选项固定检查契约，不能保证 AI 每次发现相同问题。
