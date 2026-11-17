# 来源、图片与视频覆盖门禁

读取需求及交付前使用本规范。目的：防止只读正文、遗漏媒体或只看摘要后声称完整覆盖。两个测试 Skill 各自携带校验脚本，无需安装另一 Skill。

## 读取顺序与证据

1. 先冻结用户已选文件、文件内全部有效链接或明确选区。记录来源 ID、原始路径/URL、标题、版本/revision、获取时间。失败来源保留；耦合依赖增加 `basis`，不默默扩大选择范围。
2. 保存未经裁剪的原始响应/文件及 SHA256，不用自己重写的 Markdown 摘要代替原始快照。读取全部分页并核对选区闭合；只收到目录、节选或截断响应不能标完整。链接索引及其实际目标均保留追溯；索引本身无业务规则时注明依据。
3. 先运行 `scan`，再逐个读取列出的图片、视频、画板、嵌入表或附件。保留原素材/实际导出与真实工具读取回执，记录对应 hash、位置、实际发现的规则。相同素材在不同位置按引用统计；可复用实际查看证据，但逐处核对上下文。DOCX 盘点关系引用，重复显示及未使用关系另据实说明，不能把引用数说成唯一图片数。
4. 图片必须实际用图像工具查看原图的足够清晰区域；细字/长图分块补看。OCR、alt、下载、文件存在或缩略图只能辅助，不能替代原图检查。视频读取完整时间线，记录实际时长和已观察区间；封面/单帧/稀疏抽帧不能证明中间流程已读。不可观察的片段记缺口，不虚填全时长。嵌入表读取相关数据及分页，附件按真实类型继续解析。
5. 从正文及媒体逐条提炼可判定规则，映射主表实际用例；一图可多规则，多图可合并同一规则。已读的装饰、重复示意可以有据说明不新增规则，不要求一图一条、不设条数指标。矛盾和未定义策略保留待确认，不按实现补造预期。
6. 单独从原始来源反查遗漏，运行门禁，保存实际命令/退出码/摘要。机器不能判断规则摘录是否完整、原始响应是否人为裁剪或看图理解是否正确；仍须语义审阅，禁止制造读取回执填满字段。

通过 CLI/工具取证只使用当前已具备的读取能力。图片 URL 或下载权限失败时记录确切失败和受影响规则，继续其他明确需求；不能仅因第一次未取到就将可继续读取的内容归为需人工测试。未读取媒体可能还有未知规则，报告不得宣称范围完整。

## `source-coverage.json` 契约

示例仅说明结构，所有路径、SHA256、版本、读取回执、规则及用例映射必须换为实际值，不把示例当证据。

```json
{
  "schema_version": 1,
  "selected_source_ids": ["req-a"],
  "sources": [{
    "id": "req-a",
    "title": "实际需求标题",
    "origin": "实际原始URL或路径",
    "version": "实际revision或文件版本",
    "accessed_at": "实际获取时间及其时区",
    "snapshot": {"path": "原始需求响应.json", "sha256": "实际文件SHA256"},
    "state": "read",
    "closure": {"complete": true, "note": "实际分页、截断和选区闭合核对依据"},
    "inspection": {
      "method": "text",
      "artifact_sha256": "原始需求响应的实际SHA256",
      "evidence": {"path": "实际正文读取回执.json", "sha256": "实际回执SHA256"},
      "locator": "实际工具结果位置",
      "findings": "从正文读到的关键规则"
    },
    "media": [{
      "key": "media:1",
      "kind": "image",
      "ref": "scan返回的实际src或token",
      "locator": "scan返回的原样位置",
      "state": "read",
      "artifact": {"path": "实际原图.png", "sha256": "实际原图SHA256"},
      "inspection": {
        "method": "image",
        "artifact_sha256": "实际原图SHA256",
        "evidence": {"path": "实际图像查看回执.json", "sha256": "实际回执SHA256"},
        "locator": "实际图像工具结果位置",
        "findings": "图中实际数值、状态、交互及文案规则"
      }
    }]
  }],
  "rules": [{
    "id": "REQ-001",
    "source_id": "req-a",
    "locator": "正文条款及图中实际位置",
    "text": "可判定的需求规则",
    "media_keys": ["media:1"],
    "state": "covered",
    "case_keys": ["测试用例!2"]
  }]
}
```

- `selected_source_ids` 从本次选择记录建立，并在输入清单独立保留；脚本核对输入清单与账本的选择集合一致，不能为凑完整而删除失败来源。非选定依赖放 `sources` 并加 `basis`。标题与来源可读，内部 ID 不变成 Excel 用例编号。两份清单仍须反查用户原始选择，机器无法证明两份清单未被同时缩小。
- 相对路径以 `--root` 为基准；文件引用均有真实 SHA256。JSON 飞书快照读取 `document.content` 或 `data.document.content` 及 revision；JSON 成功信封不是读取完整证明。原始分页响应必须保留，不能仅留合成摘要。
- `source.state` 指正文读取；媒体另有逐项状态，两者不能互相替代。`read/partial/unread` 是允许状态；后两种填写具体 `gap`。完全取不到快照时保持未读与 `media: []` 并说明尚不能盘点，不能填写已确认无图。
- `closure.complete` 记录所选范围是否全部取得；`note` 记录实际核对依据。已读正文也可能因媒体未读或范围未闭合使整份账本为 `partial`。
- `media` 必须包含扫描结果全部 `key/kind/ref/locator`，不得漏、增或重复 key；零媒体也显式 `[]`。PDF、RTF 等未支持扫描的格式须 `manual_inventory`：`evidence: {path,sha256}`、`method`、`note`、`media`；用真实渲染/嵌入对象盘点结果记录相同四字段，不能把“不支持解析”写成零媒体。JSON 结构不支持则先按真实类型补解析，不将改扩展名当读取证明。
- 每条已读媒体要求 `artifact`、`inspection`。image 使用 `method=image`；video 使用 `video` 并补 `duration_seconds` 和 `intervals: [[0, 5], [5, 10]]` 等实际连续观察区间；audio 使用 `audio`；table 使用 `data/document`；whiteboard 使用 `image/document`；embed/attachment 选与真实内容匹配的 method。回执 `artifact_sha256` 必须绑定实际素材，`evidence` 是真实工具读取结果，不是事后伪造的已读声明。
- 每个媒体至少有一条规则关联，或 `no_rules_reason` 说明已读后为何无独立规则；每个来源也须规则或有据排除。纯正文规则显式 `media_keys: []`。
- 规则状态：`covered` 必须有真实主表 `case_keys`；`uncovered/ambiguous/excluded` 必须有 `reason`。前两种保留覆盖缺口；排除依据需要语义审阅，不能拿任意说明排除有效规则。每条实际用例都必须关联已覆盖规则。
- 此处 `covered` 仅表示设计有用例承接，不表示测试通过。门禁不从媒体数量推算该生成多少用例，也不证明摘录语义正确。
- 脚本检查常见图片文件签名，并根据 MIME/扩展名阻止视频按图片读取；这不是完整解码或来源真实性认证。未支持的图像先用真实工具转换并保留原图与转换链，不能只改扩展名。读取回执需反查真实工具结果，hash 一致不能证明回执不可伪造。

## 运行与联用

在当前 Skill 目录执行，替换为本次已核实的绝对路径：

```sh
python3 scripts/validate_source_coverage.py scan --snapshot /本次/原始需求响应.json
python3 scripts/validate_source_coverage.py check \
  --ledger /本次/source-coverage.json \
  --input /本次/input-manifest.json \
  --root /项目绝对路径 \
  --output /本次/source-validation.json
```

`input-manifest.json` 从生成后回读的 Excel 主表建立，至少包含 `selected_source_ids: ["req-a"]` 与 `cases: [{"key": "测试用例!2"}]`；选择集合直接来自本次用户确认的来源，不能从已读成功项反推。联用代码检查时同时采用其完整六列和断言契约。输出必须用新路径，脚本拒绝覆盖，默认缺口导致非零退出。选定范围、原始来源盘点和实际主表回读仍需核对，不能用自制的更小输入替代用户范围。

确有外部资料阻塞而需交付阶段结果时，可显式加 `--allow-partial` 获取完整缺口摘要；这不将缺口变为通过。Excel 同一主表保留全部可设计用例，不增加必读页签；在摘要/对话列来源与媒体读取数、未覆盖规则及影响。已读明确规则继续设计，不为缺图把其余逻辑全转黑盒。

联用代码检查时，`input-manifest.json` 另保留上述独立 `selected_source_ids`；两份文件顶层均加入：

```json
{
  "report_stage": "final",
  "source_coverage": {"path": "source-coverage.json", "sha256": "实际账本SHA256"}
}
```

默认 `final` 必须来源完整；只能在明确阶段交付时两份都设置 `partial`。旧表未有来源账本仅允许阶段审查；已证明代码断言照常报告，未知范围单列限制。修改来源、图片、规则或用例映射后重新核对并重跑门禁；HTML 会重新检查当前内容，拒绝旧摘要。
