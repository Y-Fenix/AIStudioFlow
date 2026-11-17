# 固定查看器与批次报告（默认交付）

固定查看器只负责读取，不存某次报告数据。每轮数据只有三个项目：

```text
质量报告/
├── 查看报告.html                 固定查看器，复用一次
└── YYYYMMDD-HHMMSS/              每轮独立目录
    ├── report.md                 结论、功能明细、必要证据摘录及结构数据
    ├── bugs.csv                  完整表头及全部已确认 Bug，空列保留
    └── images/                   图片原文件，按内容去重
```

查看器直接放在 `质量报告/查看报告.html`，各时间戳目录与它同级，不增加“便携报告预览”中间层。已有同名历史目录时使用新的导出时间戳，保留 MD 中的原审计批次与源码基线；目录时间仅代表导出时间。该方式已确认为默认交付；旧 `report.html + bugs.csv` 保留，不修改历史目录。不改变审计范围、门禁或任何检查结论。

## 阅读与分享

1. 用 Chrome / Edge 打开固定 `查看报告.html`。
2. 点“选择报告文件夹”，选包含 `report.md` 和 `bugs.csv` 的时间戳目录，不选外层根目录。
   浏览器的目录选择器不能强制指定 HTML 所在路径，可能记住上次选择位置。页面显示可复制的“当前目录”；Mac 在选择窗口按 `⌘⇧G` 粘贴路径，即可回到查看器所在目录，再选时间戳文件夹。自动复制受限时选中路径手动复制。
3. 保留总览、五模块、完整 Bug 单和问题详情；关卡风险入口直接跳图片说明。
4. 点“导出”保存全部 Bug 的 CSV，搜索筛选不缩减导出范围。

目录完整复制给同事即可，路径不绑定作者机器。查看器离线读取，无需服务；同事也可让 Codex 直接读取 MD、CSV 和图片。MD 的源码路径仅作定位说明，不要求接收方有作者的工程路径。

图片保存在 `images/`，不重复塞进 HTML 或 MD。必要文本证据以带行号的源码窗口、日志摘录存入 MD，不需要第四个“证据文件夹”。完整源码、运行日志、探针和原始结果继续留在内部 `QA/results/`；页面明确区分摘录与全文，不提供指向丢失全文的下载入口。

查看器保留飞书功能：点“更新表格”→粘贴 Base/Wiki URL→读取真实表头→自动映射全部 Bug 内容，空列保留→预览→导出当前列的 CSV 或手动确认提单。读取不创建记录；切换 URL 清除旧目标，提交不明时锁定防重复。查看和导出无需服务；飞书操作需要本机桥接及有效登录。连接不可用时在弹窗明确提示回 Codex 恢复连接，入口保持可点击。历史 MD 不携带授权或凭据，实时登录在用户点击时检查。

## 导出新批次

先完成正常审计和续查，由 `finalize_report.py` 核对本轮源码、执行证据和完成度，直接生成便携批次并真实执行浏览器交互检查，不预先渲染几百 MB 的内嵌 HTML：

```sh
python3 -B <skill目录>/scripts/finalize_report.py \
  --root <游戏仓库绝对路径> \
  --evidence-dir <本轮QA/results/full-audit-YYYYMMDD-HHMMSS>
python3 -B <skill目录>/scripts/publish_report.py \
  --run-dir <本轮QA/results/full-audit-YYYYMMDD-HHMMSS> \
  --output-root <游戏仓库绝对路径>/文档/测试文档/质量报告
```

发布器校验 `delivery-check.json`、`portable-manifest.json`、`portable-interaction-check.json`，绑定本轮 `report-data.json` 和所有已验证文件的哈希后复制发布，不再重新导出。文件变化、回执缺失、版本变化、已有批次或不同版本查看器均拒绝发布。目标查看器同版复用，不同版须独立验收并获明确升级要求后处理；不自动覆盖。

内部 `QA/results/` 保留全部审查数据、原始证据和交互回执；对外批次严格只有 MD、CSV、images 三项，无图片时也保留空 images/。`finalize_report.py` 退出 2时读取门禁：证据或交互失败不得发布；仅执行未完成且报告已验证时，仍须按续查协议处理，任何已发布部分报告保留未完成标识，不能宣称全量通过。

`export_portable_report.py --run-dir` 仅用于独立格式转换或界面调试，不是跳过最终证据和浏览器校验的发布通道。只有用户明确要求旧联机报告时才用 `finalize_report.py --legacy-html`，该格式不走便携发布器。

## 转换历史报告

只用于历史格式转换与界面验收，不冒充当前代码的新巡检。保留原 Bug 数、基线、完成度与限制，页面持续显示历史转换说明。既有文件只读：

```sh
python3 -B <skill目录>/scripts/export_portable_report.py \
  --source-html <旧目录/report.html> \
  --csv <旧目录/bugs.csv> \
  --output-dir <质量报告/新导出时间戳> \
  --viewer-output <质量报告/查看报告.html>
```

CSV 保留原字节，列顺序、空列、多行步骤和引号不丢。导出会拒绝已有批次目录、CSV 编号与已确认问题不一致、图片缺失及路径越界；不修改旧文件。

## 数据契约与验证

MD 附带唯一 `gagasort-report-v1` JSON 围栏区块。它是查看器所需结构数据，不是单独的第四个文件；包含功能、问题关系、完整度、关卡解释、证据摘录，以及 CSV/图片的 SHA256、大小和编号清单。Bug 提单字段值从 CSV 读取，不重复内嵌另一份字段值。

加载时校验批次结构、五模块、Bug 编号、CSV 表头/行数/哈希、每张图的引用/大小/哈希和摘录哈希。缺文件、混入其他批次、手改 CSV 或不完整 MD 均提示错误；失败不会变成“0 Bug”，切换失败保留上一份有效报告。此校验防意外混文件，不是签名或防伪保证。需要改内容时重新导出整轮，不能单改 CSV 后冒充原批次。

单测和浏览器交互回归：

```sh
python3 -B -m unittest discover -s <skill目录>/scripts -p 'test_*portable*.py' -v
python3 -B -m unittest discover -s <skill目录>/scripts -p test_publish_report.py -v
NODE_PATH=<实际Node模块目录> node <skill目录>/scripts/check_portable_report.cjs \
  <查看报告.html> <时间戳目录> <可选Chrome执行文件>
```

浏览器回归使用真实报告，错误输入副本、下载文件只放系统临时目录。检查表头、内容导出、模块页签、问题步骤/归因、关键摘录、实际图片解码、缺文件拦截、切换关闭、窄屏及本地加载零网络请求；飞书交互另用模拟桥接验证读取、映射、导出及手动提交，不向真实表格写入。只有真实执行成功才可宣称相应功能已验证。
