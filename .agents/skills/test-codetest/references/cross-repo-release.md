# 跨库发版检查契约 v1

涉及内购、埋点、广告、安装恢复，且提供 SDK/服务器代码时读取。公共规则与工具先在全局 skill 更新并验证，再同步项目副本，最后归档到 `RuneSkills/test/common/release-contract/` 及三个分发目录；全局三个 skill 内打包同版资源，维护时校验一致性，不分别演化；同事单独复制任一 skill 即可使用，不依赖维护者绝对路径。`assets/cross-repo-gagasort.json` 是项目定位模板，不是审查结果。通用 skill 对其他项目复制并调整本轮 profile，不套用 GagaSort 分支或商品规则。

## 三个入口的职责

| 入口 | 范围和产物 |
| --- | --- |
| gagasort-qa | 无需 Excel；四条链全部进入原有功能 dossier、埋点与安装矩阵，仍使用原 90 功能 ID。跨库账本是附加证据，不替代全量门禁，不另造一套报告 UI |
| test-case | 按需求及真实耦合选链，细化为原六列用例；设计不执行测试。跨库来源、交接点与待执行命令放 sidecar，不增加 Excel 主表列，不把设计场景写成已通过 |
| test-codetest | 对原用例逐断言追跨库消费者，默认静态；明确要求本地运行或项目强制检查时执行已审阅的测试。来源、静态、运行和真实外部观察分别计数 |

已提供的原生 SDK/服务端处理源码属于可审查的本地代码。真实支付授权、平台采集入库、已部署实例、实际安装与包内版本对应关系属于其他证据层。查完源码不能称“支付可拉起、已到账、埋点已入库、广告实播正常、覆盖安装实测通过”。本地版本与已发包/已部署版本对应关系未知，直接标 unknown；不阻塞其余本地源码结论。

## 先建立本轮项目与来源配置

1. 从会话和项目 AGENTS 定位客户端、Android、iOS、SDK 服务端、游戏服务端；同事用本机路径 JSON（`client/android/ios/sdkserver/gameserver`），不把绝对路径写回公共模板。缺库只限制依赖它的断言。
2. 模板的 39 个锚点仅用于开始定位，不保证覆盖全部依赖。按实际调用补入项目专属奖励、存档、商品、平台初始化、构建依赖、路由/配置、锁文件和测试/夹具；使用 `--dependencies` 的 JSON `{仓库ID: [仓库相对路径]}`。追到新增文件时必须重建快照、更新关联证据，不沿用旧指纹。
3. 核实项目路由、包名/pg、平台、环境、商品 ID、SDK 构建版本、服务分支与配置来源。当前已定位服务端 `src/ccommon.js` 的 `GagaSort/igagasort/gpgagasort` 分支，但包名、事件映射及部署对应关系仍逐项查证；不得直接当成同义词。共享实现和项目条件分支都读，同一函数的其他项目分支不算本项目证据。
4. 模板 16 项只是四条链的最低检查入口，不能当完整断言分母。全量保留这些入口，按真实商品、广告位、事件/属性、身份/存档字段和三种安装路径扩展 `targets`（独立 ID）；需求模式按明确选择裁剪并记录排除依据。`repositories` 只列本断言真实必经库，条件转发加入实际库；直连平台的事件不伪造服务器交接，保留旁路源码依据。
5. 保存本轮 profile 与路径配置、独立规则来源/版本、基线和断言清单。同一轮三个 skill 共用。profile 的 `release_mapping` 默认全部 unknown；只有可信构建清单/依赖锁定/部署记录支持时才记录具体对应版本。工具仍不自动判发版已验证。

## 四条链的具体断言

| 链 | 必查分支与最终消费者 |
| --- | --- |
| 内购 | 商品/币种/平台/测试正式环境→拉起/取消/失败/成功→订单/收据→原生待处理交易→服务验单与项目路由→游戏奖励→幂等落账→持久化与补单。模拟重复、乱序、断网、发货成功响应丢失、重启恢复；区分购买成功、服务发货确认、客户端到账、存档成功。iOS 查 unfinished/updates/finish 与恢复；Android 查 pending/acknowledge/consume 及订单恢复。只验退避时间不算到账验证 |
| 四种上报 | 数数/Adjust/Firebase/BI 分开，逐事件、属性类型/单位、身份/账号切换、初始化/同意门禁、构建条件、禁用/过滤、队列/持久化/重试/去重、直连或 S2S 最终出口取证。源事件→原生映射→后端映射不是同一套事件名；区分业务事件、广告收入、自动采集；禁止把 HTTP 2xx、mock 接收或写 WAL 等同平台入库 |
| 广告 | 插屏/激励按实际广告位逐项推导连续至少两次完整循环；初次未就绪、展示失败、关闭、无奖励关闭、reward/close 乱序与重复、页面退出/重入/超时、播放后重新加载。追暂停/遮罩/按钮恢复，激励发奖次数/数量/资格/存档。广告收入 S2S 测试不证明广告播放或道具下发 |
| 安装 | 覆盖安装保留旧数据、清本地恢复同身份、清本地创建新身份分别检查；旧字段缺失/默认/版本迁移、服务档优先级/冲突/覆盖、身份绑定与队列恢复。资源、去广告、购买资格、未结订单、活动/广告次数逐消费者检查。删除 App 不代表平台 Keychain/云档一定删除；可信旧发布包缺失只限制真实跨版本结论 |

所有通过/失败断言都要有独立预期依据、具体输入与事件顺序、实际推导、调用双方及落点证据。源码定位不证明产品策略正确；需求缺失标明策略问题，不用实现自证预期。

## 可运行的基线与账本校验

在所用 skill 目录运行（输出路径换成本轮证据目录；以下 `<...>` 为参数占位符）：

```sh
python3 -B scripts/cross_repo.py snapshot --profile <本轮profile.json> --roots <本机roots.json> --dependencies <实际依赖.json> --run-id <本轮ID> --output <snapshot.json>
python3 -B scripts/cross_repo.py prepare --profile <本轮profile.json> --snapshot <snapshot.json> --output <ledger.json>
python3 -B scripts/cross_repo.py check --profile <本轮profile.json> --snapshot <snapshot.json> --ledger <ledger.json> --output <cross-repo-validation.json>
```

`prepare` 全部为 unreviewed，不生成通过。逐项补写 `status=pass/fail/blocked/unreviewed/not_applicable`、`reason`；通过/失败另填 `input/expected/actual/rule`。`rule` 指向独立规则资料，仍由原报告证据门禁核实；本工具不验证规则语义。`evidence` 条目为 `{"repo":"client","path":"实际相对路径","line":123,"quote":"该行非敏感的实际片段"}`；`handoffs` 为 `{"from":0,"to":1,"contract":"订单字段/回调映射","reason":"双方如何对应"}`，索引指向本条 evidence。多库断言必须形成交接链；多个平台分支分别取证。`not_applicable` 也须具体理由和源码，不能用于掩盖缺库。

工具核对 profile/快照摘要、仓库身份/分支/HEAD、**已声明文件**的当前 SHA256、缺失/重复目标、证据行与片段、必经库和交接引用。相同 HEAD 下文件改动也拒绝；缺库可保留 blocked，不能以它作通过证据。仅保存哈希与路径，不复制源码全文/密钥。工作区状态摘要用于追溯，不是全仓内容快照；未声明的传递依赖、交接语义、需求正确性必须由审查补齐。格式通过不等于代码审查完成，检查输出含未审/阻塞时只能交阶段结果。

### test-codetest 报告绑定

跨库输入 manifest 与 review 顶层都加相同 `cross_repo`：`profile/snapshot/ledger` 各为 `{path,sha256}`（文件原始字节 SHA256，路径相对被测仓库或绝对路径）。两边共用 `baseline=snapshot.digest`。原输入断言的 `cross_repo_targets` 列出关联账本 ID；同一用例可混合本地与真实外部断言，后者仍按原外部证据规则处理。只给真实跨库本地断言加此字段。

`validate_report.py` 会重读三份产物、验哈希及当前源码、核对逐断言状态，不能靠一份旧“校验通过” JSON 免检；源文件变动后 HTML 再生成也须重新通过。保留来源覆盖、独立需求、运行日志等原门禁，不替代或削弱它们。

### GagaSort 固定交付绑定

本轮 `report-data.json.cross_repo` 同样放 `profile/snapshot/ledger` 的 `{path,sha256}`，另加 `baseline=snapshot.digest`；保留原 `report-data.baseline` 对象，不把客户端 HEAD 替换成组合摘要。快照 run_id 与原巡检 run_id 相同。`finalize_report.py` 会核对本项目、本轮、客户端根目录/HEAD，开始和结束都重新校验各库已声明文件；写入内部 `cross-repo-validation.json`。跨库 blocked/unreviewed 自动进入续查队列，不能生成全量完成回执。未配置跨库的历史报告仍按原协议校验；本次已提供多库的四条链巡检必须带此绑定，不能省略以规避门禁。

## 本地执行测试与证据限度

先读候选测试及其 imports、依赖、初始化与副作用，再决定是否能运行；没有统一 npm test 不猜命令，不运行 install/build/release 部署脚本。模板 `candidate_tests` 仅供发现，先映射实际测试名→精确断言→未覆盖段，确认失败会针对该行为。缺测试的可静态闭合；明确要动态时复用真实实现与隔离夹具，不复制生产算法自测。

SDK 服务有 `scripts/test-no-network.cjs`。核对当前版本确实阻断 net/tls 后，可在该仓库运行 `node --require ./scripts/test-no-network.cjs --test <已审阅.test.js>`。这不是沙箱，不阻止文件写入、子进程或其他网络方式；仍须先读代码。无需服务启动，不安装依赖；缺依赖记具体受阻。

每次实际运行保留 argv/cwd、运行 ID、各库前后指纹、生产/测试/夹具哈希、原始日志及 SHA256、退出码、发现/通过/失败/错误/跳过数、真实测试名和逐断言映射。SDK 库单独执行，不能把它的路径塞进客户端 `record_run.py --source` 绕过目录约束；GagaSort 原 runner 仍只签本仓库执行。跨库命令单独留原始回执并以同一 snapshot.digest 关联，最终再次 verify/check；未接入原 runner 的回执不得伪称已有签名。test-codetest 的 run 证据继续走原日志/计数/逐断言门禁。

退出码 0、只有 suite/零测试、全 skipped、mock 的成功回调不能计业务通过。`deliver.test.js` 当前仅测重试退避、`gp_purchase.test.js` 仅测分页、`measurementProtocol.test.js` 测 mock 转发与错误分类、`bi_event_wal.test.js` 测 WAL/替身去重、`ad_revenue_s2s.test.js` 测收入上报响应/重试，均不能扩大覆盖到到账、真机播放或平台入库。每轮重读测试，不能永远信这份定位说明。

## 报告必须呈现

复用原报告结构，在相关功能/用例详情及总结中写：各库真实基线与缺库、项目/平台/环境映射及版本对应的 unknown；四条链各自已审/未审/失败/受阻的断言 ID；本地代码结论；实际执行测试数与精确覆盖段；真实平台/设备的未验证事实及影响。不把侧文件单独通过当整体完成，不为全部变绿删除断言，也不默认生成同事人工待办。测试未运行写 0，来源未读写未读。分发只含模板、规则和工具，不含本机路径配置、凭据、用户数据、运行日志或审计结果。
