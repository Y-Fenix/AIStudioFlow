# 固定执行与同事交付

本文件是全量模式总控必读的收口协议。运行规范版本与 HTML 模板指纹记录在 `assets/delivery-profile.json`；深审与证据字段继续以原有专项协议、报告契约为准，不再新增平行数据格式。

## 同事只需要做什么

在 GagaSort 项目打开 Codex，输入 `$gagasort-qa`。不需要给需求、选模块、填用例或执行测试。Skill 是 Agent 工作流，专项源码审查由 Agent 执行；辅助脚本不冒充一条能识别所有业务 Bug 的扫描器。

本机优先维护独立的全局目录 `/Users/yf/.agents/skills/gagasort-qa`，验证后先同步项目 `/Users/yf/Documents/Unity/gagasort/文档/测试文档/gagasort-qa/`，最后同步 `/Users/yf/Documents/Unity/RuneSkills/test/gagasort/`。全局目录不再软链接到 RuneSkills。用户明确调用项目内文件时按指定目录加载；同事按其安装位置加载并记录路径/版本，不因维护者的本机路径改变调用目标。

## 本机同步规则

用户已确认三个 skill 均按“全局 → GagaSort 项目 → RuneSkills”的顺序维护。仅限已授权位置，不扩展到其他同名副本。

1. 在全局完成修改与适用验证；比较项目及 RuneSkills 副本，保留与本次无关的改动，冲突不静默覆盖。
2. 写项目仓库前按其 `AGENTS.md` 完成限定路径 preflight 与 Worktree 身份配置；仅同步 skill 不启动游戏巡检、Unity 或 Figma。
3. 先同步项目完整有效目录，再同步 RuneSkills。包括 `SKILL.md`、`README.md`、`agents/openai.yaml`、scripts、references 和 assets；排除 `.DS_Store`、`__pycache__`、`.pyc/.pyo`、认证与运行产物。不得使用 `--delete` 覆盖目标独有内容。
4. 对三个独立目录的文件清单及字节内容校验一致性，确认 `policy.allow_implicit_invocation: false`，运行 skill 格式校验和项目限定范围 `tools/agent-task verify`；只报告实际结果。
5. 跨库共享资源在全局三个 skill 保持同版，最后同步 RuneSkills 的 `test/common/release-contract/`，再运行其中 `sync_bundle.py` 的只读一致性检查。不能用旧归档反向覆盖新全局版本。

不自动 Git 暂存、提交、拉取或推送。删除源文件时先明确归属和本次删除范围，不做全目录镜像删除。被测项目仍从本次上下文定位，`--root / --repo` 不能指向 RuneSkills；skill 资源取实际加载目录。

## 每次执行的固定顺序

1. **预检与新基线**：按仓库门禁确认路径、身份、HEAD、工作区和子模块。创建唯一 `QA/results/full-audit-<时间>/`，保留旧结果，记录实际 skill 路径、`workflow_version`、运行时版本和 CodeGraph 实际使用/回退。当前目录和参数从本机发现，禁止复制示例的用户路径、运行目录或临时缓存路径。
2. **默认离线；飞书仅按需。** 本地查看和导出无需飞书；需要表头更新或提单且会话已授权后运行 `python3 scripts/ensure_feishu_auth.py --start-bridge`。已有 `base:block:read`、`base:field:read`、`base:view:read`、`base:record:create` 的有效或可刷新用户会话直接复用；不申请不存在的 `base:record:write` 权限。若脚本退出 3，立即向用户展示本次返回的授权 URL 和二维码并结束该轮；用户完成授权后才用本次设备码继续 `ensure_feishu_auth.py --device-code <本次设备码> --start-bridge`，不阻塞等待、不把设备码或 token 写入报告/分发包。未授权或连接失败只暂停飞书，不影响静态检查和 CSV。用户在 HTML 点击“更新表格”或“提单”打开“新建 Bug 单”，粘贴飞书 Base/Wiki URL → 读取表头 → 检查全部内容预览 → 手动点击“直接更新并提单”。打开、读取和预览不创建记录。
3. **锁定完整范围**：先读[固定测试范围](audit-scope.md)，自动执行 `audit_scope.py prepare`，加载 `assets/audit-scope.json` 的全部功能，复制 `feature-inventory.json` 的完整明细到本轮基础数据，不能从 dossier 反推清单。交叉核对当前代码、入口、配置、存档、开关枚举和模块文档；新增或移除功能要有证据并维护固定清单，不能每轮随意合并或缩水。配置按字段、语言按实际语言表、关卡按 manifest、埋点按事件/属性建立子清单。
4. **小批次专项深审**：执行多 Agent 协议，最多 4 个子 Agent并发；每批 1～3 个真实功能，复杂支付链独立处理。同一功能 dossier 一个写入者，统一使用 `deep-v2` 的真实分支、七维覆盖、逐场景结论、消费者、行号与审查结束时的依赖哈希。总控处理共享链和遗漏，不把一条公共测试分摊成所有功能已测。未能启用子 Agent 时记录真实代行范围，不能伪造独立审查。
5. **自动本地补证**：静态链能闭合就直接判定；有歧义再用真实生产方法、可控时间/回调/配置/旧档补证。保存探针源、具体输入、真实命令、工作目录、退出码和原日志。本地命令通过 `scripts/record_run.py --root <仓库> --evidence-dir <本轮目录> --run-id <唯一执行ID> --source <实际生产/输入依赖> [重复--source] [--output <预期产物>] -- <实际命令及参数>` 执行；wrapper只记录已授权本地命令，不扩大副作用权限。`--source` 包括实际生产依赖而非只列探针文件；大集合由总控从真实编译/读取清单显式传入。把回执输出的 `id / command / exit_code / evidence / execution_receipt` 原样写入运行记录，再补业务状态与总结；不得事后为旧日志补签回执。执行记录由专项输出显式回链功能 ID；合并器不得凭名称猜测覆盖，不能把成功复现 Bug 的 exit 0写成业务通过。
6. **逐关管线**：实际运行 `scan_levels.py`，保留原始输入、Validator、无道具求解、独立回放、岸壁/水面结果与标位图。使用[逐关协议](static-first-audit.md#关卡有解与布局)的预算；预算内未定自动追加 `build_level_solver.py --time-ms 300 --aux-time-ms 3000 --aux-attempt-time-ms 1500` 全量补跑，其他参数取本轮真实路径；通过 `merge_solver_extension.py --levels-dir <本轮levels> --extended <本轮扩展输出> --manifest <本轮扩展编译目录/manifest.json> --run-id <真实执行ID>` 合并，核对输入、输出、源码与基线，保留本轮各次已找到的解和尝试，追加结果不能覆盖其他阶段补证。非平面关调用 `supplement_level_visuals.py --repo <仓库> --levels-dir <本轮levels> --visual-build <本轮visual编译目录> --spline-build <本轮spline编译目录> --build-dir <新临时目录>` 自动选择并导出相同生产网格，调用固化三维检查；不能拿 XY 投影当三维穿插。仅明确旧非平面缺口且相同网格无命中才闭合；其他风险/容差/缺口仍保留，不抹绿。所有参数、尝试和剩余限制保存在本轮，关数与风险数从逐关结果计算，禁止抄历史数量。
7. **反例复核**：总控核对每个候选的有效预期、可达条件、最终消费者和反例；高影响的发货、权益、存档问题交另一专项 Agent 独立复核。配置容错问题标明构造值，资源失败问题标明失败条件；不暗示线上已下发该值或当前资产实际缺失。没有可靠黑盒路线就给可核查白盒步骤，不造玩家按钮，不生成正常功能人工待办。
8. **合并与续查**：按 `multi-agent-audit.md` 合并最新 dossier，显式合并本轮运行记录、配置字段/场景/组和 `levels/report-fragment.json` 全部字段。不同专项对运行字段有差异时，统一到报告契约后再合并，保留原文件；安装分析保留三种数据条件。总控读取 `continuation.json` 逐项续查，直至本地分支闭合。按业务名填 `display`；旧报告和本次结果都不是可复制的“默认通过”数据源。
9. **固定收尾**：只调用下述通用交付入口。它校验 HEAD/分支/子模块、所有 dossier 依赖哈希、当前源码与摘录及行号，执行原有完成门禁，导出配套文件、用固定查看器和模板生成便携批次、自动检查文件夹加载和页面交互，并在交互结束后再核源码。不得另写临时导出器或手改 HTML。

完整 `scan_levels.py` 只执行一次时，登记一个真实聚合命令记录；把它产出的 `level_audit` 各阶段 `run_ids` 显式映射到该记录（如 `RUN-LEVEL-FULL`），阶段原始日志继续保留。不能为默认写入片段的 `RUN-LEVEL-LAYOUT / RUN-LEVEL-SOLVER` 虚构另外两次命令，也不能让多条运行记录复用一个执行回执。后续扩展求解和三维补证分别登记自己的真实命令与回执，再补入对应阶段 `run_ids`。

```sh
python3 -B <实际skill目录>/scripts/finalize_report.py \
  --root <本机仓库绝对路径> \
  --evidence-dir <本轮QA/results目录>
```

校验后执行发布；只复制刚刚通过交互检查的同一批文件，不重新渲染：

```sh
python3 -B <实际skill目录>/scripts/publish_report.py \
  --run-dir <本轮QA/results/full-audit-YYYYMMDD-HHMMSS> \
  --output-root <本机仓库绝对路径>/文档/测试文档/质量报告
```

默认不生成巨型内嵌 `report.html`。仅用户明确要求旧联机格式时，`finalize_report.py --legacy-html` 保留旧方式；它不走便携发布器。

Node、Playwright 或 Chrome 不在 PATH 时，总控使用当前宿主的依赖发现入口取真实路径；可传 `--node`、`--browser`，Node 模块路径使用该进程的 `NODE_PATH`。缺 Python 的 msgpack/Pillow、匹配项目版本的 Unity 内置托管编译器、字体或包时按现有脚本补齐可隔离依赖，不启动 Editor/Player。依赖未解决如实报受阻，由 Agent 保留可恢复证据，不能让同事接管人工检查；不内置某台电脑的缓存路径。

`record_run.py --output` 绑定命令直接生成且保留原字节的阶段结果；后续会更新的汇总、详情或 HTML 不作为前一命令的不可变产物，另存派生文件并按转换命令记录。超过 wrapper 预算时保留 unknown/124和具体限制，只能记超时/受阻，不得作为通过记录；输入发生变化须重审重跑。历史报告没有本轮回执时仍可阅读，但不能补签后作为新批次通过。

## 完成与未完成的明确区分

`finalize_report.py` 退出 0表示报告/交互校验及静态完成门禁均通过，不表示没有 Bug。退出 2须读取 `delivery-check.json`：

- `report_ready=false`：证据、页面或环境校验失败；总控按具体原因修复后重跑，不能交付为本轮成功结果。
- `report_ready=true, audit_complete=false`：报告可读且证据校验通过，但检查仍有未完成项。存在功能、配置或源码复核任务时继续执行，不能以生成 HTML 作为结束依据。
- 仅剩关卡预算内未定或几何风险时，先自动补跑/补证。相同动作两次无新证据后换策略；确因搜索资源或画面事实无法闭合时，在 `continuation-outcome.json` 按任务 ID保存实际尝试、run ID/日志、剩余技术限制和本轮结论，保留棕色及“执行不完整”。不得把超时改成无解，不得把几何风险算已证 Bug，不删除检查项，也不生成同事人工通关任务。

同事获得相同的入口、固定功能清单、审查深度门禁与报告交互。同一 scope_version 的功能编号和业务名必须一致；清单变化须有代码依据并升级版本。Bug 数、有解数及风险数仍从本轮源码、配置、预算和证据重新计算，不能复制历史结果。

每轮还必须保留 `quality-gate.json`。它记录当前基线、功能盘点/深审完成度、逐关完成度、执行记录、已证问题和待续查项，并带有当前报告数据核心哈希（排除嵌入快照本身，避免自引用）。`quality_status` 只有 `通过` 或 `部分完成`；失败由 `delivery-check.json` 的 `report_ready=false` 表示。该快照只由本轮数据计算，禁止从上一轮 HTML、JSON 或 CSV 合并问题、数量或通过状态。

## 固定产物与报告

默认采用[便携报告协议](portable-report.md)：质量报告根目录固定一个 `查看报告.html`，每轮同级时间戳目录只有 `report.md + bugs.csv + images/`。内部校验完成后再发布，旧报告及旧 CSV 只读保留。

查看器复用 `assets/report-template.html` 中已认可 UI：默认总览，五模块独立页签，模块先给问题数、风险、未完成和未见问题四项可点击指标；业务名、检查内容、结论直接可读。问题先展示影响、步骤和归因；有图直接跳图。正常范围绿、未完成或风险棕、已证缺陷红。默认本地读取，CSV 导出可用，“更新表格”可用，读取表头后可手动提单，不在报告中保存授权或凭据。下段飞书约束同样适用于固定查看器。

总览固定 Bug 单列表，默认完整23列，空列保留，顺序取自 `assets/bug-columns.json`。飞书 URL 解析、字段类型和视图顺序参考 `test-case` / `test-codetest`。仅在本次已明确授权提单后运行 `python3 scripts/ensure_feishu_auth.py --start-bridge`。已有 `base:block:read`、`base:field:read`、`base:view:read`、`base:record:create` 的有效或可刷新用户会话直接复用；不申请不存在的 `base:record:write` 权限。若脚本退出 3，立即向用户展示本次返回的授权 URL 和二维码并结束该轮；用户完成授权后才用本次设备码继续 `ensure_feishu_auth.py --device-code <本次设备码> --start-bridge`，不阻塞等待、不把设备码或 token 写入报告/分发包。未授权或连接失败只暂停飞书，不影响静态检查和 CSV。用户在 HTML 点击“更新表格”或“提单”打开“新建 Bug 单”，粘贴飞书 Base/Wiki URL → 读取表头 → 检查全部内容预览 → 手动点击“直接更新并提单”。打开、读取和预览不创建记录。目标表头、预览、页面列表与浏览器 CSV 使用同一受控映射；标题、步骤、预期、实际、归因分别对应，不把实际或根因误写日志列。没有依据的信息留空；系统、人员和附件不猜值、不用普通记录接口写。URL 变化或读取失败禁止沿用旧表；写入时复核表头和类型，成功必须完整确认 record_id_list，未知结果不得报成功或自动重发。

同轮内部配套文件包括 `report-data.json`、`audit.md`、`coverage.csv`、`configuration.csv`、`installation.csv`、`findings.md`、`continuation.json`、`portable-manifest.json`、`final-evidence-check.json`、`portable-interaction-check.json`、`delivery-check.json`，以及原始 dossier、源码快照、逐关结果、图片与执行日志。`portable-manifest.json` 记录浏览器验证目录和逐文件哈希；发布器复核回执、数据和当前查看器版本。未完成时额外保留续查结果，不用人工用例表代替本轮结论。只有显式 `--legacy-html` 才输出旧 `html-manifest.json` 和 `html-interaction-check.json`。

另固定交付 `bugs.csv`，即使零问题也保留模板23列表头；运行时远程表头导出只存在于浏览器下载文件，不改写原始 `bugs.csv`。CSV 本身不会自动上传附件或填写飞书系统字段。

浏览器自动检查默认总览、五页签与筛选刷新、颜色、所有实际问题的步骤/归因、适用风险图与深链、关键证据摘录、CSV 全字段导出、目录切换、缺文件和混批次拦截、390px无横溢及JS错误；默认离线零网络请求。没有问题或某类风险时只检查真实空状态，不造问题凑交互；跳过项记录具体数据条件。

收尾再运行仓库限定范围 `agent-task verify`，核对根目录与分支，更新 `QA/current-run.txt` 指向已校验的本轮结果。聊天只给报告入口、实际审查数、已证问题数与关键关卡限制，不能宣称查出所有 Bug。

## 分享范围

交付 RuneSkills 的整个 `test/gagasort/` 目录，包括 instructions、references、固化埋点契约、scripts、HTML模板和 `delivery-profile.json`；不漏 C# 离线探针。依赖被测 GagaSort 仓库中的源码、资产、模块文档、`tools/agent-task` 和现有测试，不是跨项目通用扫描器。被测项目 `.codex/agents/` 的现有角色按仓库配置使用；不复制用户认证、私人缓存或本机运行环境配置。

`QA/results/` 是每次产物，无需全部分发或提交；`.pyc`、`__pycache__`、构建缓存不在 skill 分享范围。可运行 `scripts/package_skill.py --output <skill目录之外的新zip路径>` 生成含文件哈希的干净分发包；同事解压后的 `gagasort-qa/` 放到其同项目的 `.agents/skills/`，然后在项目中调用。项目原有 `QA/run.py`/tests若存在则按映射复用；缺少时从正式 tools/原生测试发现入口，不得假称已执行该 Runner。后续维护仍按全局 → 项目 → RuneSkills 顺序同步，明确指定项目路径时在该目录使用。未经用户明确授权不提交、不拉取、不自动同步其他同名 skill。

模板指纹是防止无意改版的检查，不是安全签名。只有用户明确要求改版时，才一起更新模板、版本、指纹和交互回归；执行者不得通过重算指纹掩盖本轮擅自修改。
