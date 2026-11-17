# 部门模块协作约定

## 个人运行与项目公区

个人模式由每人独立安装隔离数据，公区是单独部署的发布存储服务。部门仍使用原公共工作区/执行契约；快照选择、导出权限、版本、上传、下载和通知由平台的 `server/core/public_area/` 维护。部门不得直接写公区表或读取连接会话，不得因节点全自动运行而自动发布。公区副本是独立内容，不会覆盖个人节点或执行上传 Skill；新部门需要额外导出字段时先提出公共契约扩展，不序列化完整私有任务。部署及当前限制见[个人工作区与项目公区](../personal-public-area.md)。

## 目录与所有权

每个部门独立维护 `departments/<department-id>/manifest.json`、`ui.js`、`skills/`、自己的 `adapter.py` 和 `README.md`。公共壳提供两个部门前端插槽：`renderHome(context)` 与 `renderWorkspace(context)`。模块只负责本部门专属内容；登录、顶部/侧栏、权限、Skill 导入导出、保存、执行入口、操作日志和人工审批由公共壳负责。模块缺失或加载失败时回退到公共工作区。模块 ID 永久稳定，是数据库节点与授权规则的组成部分；不要为了重命名或重排 UI 顺序而变更 ID。节点按项目保存稳定 ID 与展示顺序；manifest 提供首次默认模板。节点协议变化必须提供向前迁移。

产品、设计、开发的 `adapter.py` 已通过 manifest `execution.adapter=adapter` 接入模型文字交付；每部门四个固定节点使用各自职责契约，公共层核对结构、非空内容与逐字输入引用，不代表联网调研、反编译、生图、源码修改或构建已经接通。增长仍为 `manual` 兼容骨架，不加载为自动执行器。测试部门继续复用现有专属静态审查工作台。新执行器仍须通过评审后显式启用，不自动加载占位实现。

`manifest.json` 可声明 `{ "frontend": { "entry": "ui.js" } }`。当前只允许模块目录中的固定 `ui.js` 路径；服务器不提供模块目录中的其他文件，也不接受浏览器上传或远程模块。前端模块与 `adapter.py` 都是受信任代码，需通过代码评审随平台部署；不能将用户上传的 Skill、需求或项目文件作为脚本执行。

前端默认导出对象可实现以下任一方法：

```js
export default {
  renderHome(context) {
    return `<h3>${context.escape(context.department.title)}</h3>`;
  },
  renderWorkspace(context) {
    if (!context.node) return '';
    return `<p>预期交付：${context.escape(context.node.outputContract)}</p>`;
  }
};
```

需要交互时，可增加 `mountHome(element, context, tools)` 或 `mountWorkspace(element, context, tools)`。公共壳先插入 `render*` 的 HTML，再调用对应 `mount*`；每次重绘或离开页面都会中止 `tools.signal` 并执行返回的清理函数。异步挂载可以返回 Promise，但任何异步请求和事件订阅都应使用该 signal；迟到的清理函数也会执行。不要使用内联 onclick 或全局事件处理器。

```js
export default {
  renderWorkspace() {
    return '<button data-product-action="organize">整理当前输入</button>';
  },
  mountWorkspace(element, context, tools) {
    element.querySelector('[data-product-action="organize"]').addEventListener('click', () => {
      const draft = tools.readDraft();
      tools.updateDraft({inputs: draft.inputs.trim()});
      tools.notify('已更新草稿，请通过公共保存按钮确认保存');
    }, {signal: tools.signal});
    // 如有定时器、观察器等，返回 () => { /* 清理 */ }。
  }
};
```

`tools.readDraft()` 返回当前输入和交付物的副本；`tools.updateDraft({inputs?, deliverable?})` 只更新未保存草稿，不支持 Skill、revision、权限或审批字段。公共壳仍负责保存、版本校验与审核。导航开始后旧 tools 立即失效，不能写入下一项目/节点；无编辑权限或正在保存时拒绝更新。`tools.notify(text)` 显示普通文字提示。部门模块为受信任的同源代码，这些工具及 signal 是协作接口，并非 JavaScript 沙箱；不能因此跳过代码评审或服务端授权。

`context.node.id` 是稳定节点 ID，`index` 仅为本次展示位置；保存、依赖和日志必须使用稳定 ID，不能将排序后的 index 当成旧业务阶段。测试固定六节点仍保留原 ID，新增测试节点使用公共人工工作区。

`context` 只包含当前部门及节点契约、当前工作室/项目名称、当前节点工作区摘要和 `escape(text)`。不含模型密钥、其他项目或其他部门工作区。模块应对所有动态文本调用 `escape`；返回值限制为 100KB。插槽内容是受信任的同源 HTML，因此只能由仓库代码维护。模块不得自建授权判断；服务端仍会对每次保存、执行和审批重新检查权限。

部门负责人负责本部门 manifest、默认 Skill、接入实现和本部门测试。平台核心维护者负责身份、组织授权、工作室/项目隔离、共享存储、节点版本、公共接入协议、安全头与审计。部门代码不得直接写核心表或绕过公共服务。

## 接入协议

- `manifest.json` 用 JSON schema version 1 描述唯一部门 id、标题、工作首页、静态节点、输入输出契约、默认执行方式和固定前端入口。
- `adapter.py` 导出 `create_adapter()`；返回对象实现 `execute(context)`。
- context 包含已授权用户、工作室/项目/节点、输入 revision、当前 Skill 哈希、当前 Skill 正文、输入文本、`model` 能力和受限的 `gm` 能力。导入 Skill 会替换该节点默认 Skill；执行器每次运行读取当前版本，执行期间版本变化会拒绝写入。
- `context.model.request_json(prompt)` 使用平台当前已启用的 Codex 中转站或自定义兼容 API，固定本次执行开始时的模型选择与 Skill 快照，提示词上限 500KB，只接受 JSON 对象。部门模块不读取 API 密钥、不自行选择模型，也不应通过其它客户端绕过本机配置。
- 推荐通过公开 `generate_document(context, contract)` 生成有专业章节、逐字输入引用、缺口和下一步的文字交付，契约包含 `id/title/sections/limitations`。该辅助器最多修正一次结构/引用错误，不做事实或语义质量认证。
- 结果是 `{deliverable: str, evidence?: list, gaps?: list, quality?: dict}`；`quality` 仅报告结构/引用检查，不是评分或批准。空白交付会拒绝。公共层校验版本、授权仍有效、结果大小，然后保存为待人工审核；执行器不能审批、授予权限或发布外部记录。
- 非测试部门执行通过 SQLite 持久化队列运行；页面可轮询当前节点任务并在刷新后恢复状态。服务重启会将仍在运行的任务标记为 `interrupted`，不会自动重试，以免重复执行部门工具的外部副作用。成功结果仍停在待人工审核状态。
- `context.gm.call_read(tool, arguments)` 只允许已登记的只读 GM MCP 工具；每次调用都按当前项目、部门、节点复查 `gm.execute` 授权。除 `gm_health` 外，参数必须明确包含 `{"env":"test"}`；授权不会隐式选环境。GM 写入工具永远不会暴露给部门执行器。
- 插件仅从受信任部署仓库加载，绝不执行上传的 Skill / 需求文件 / 客户项目 Python。Skill 是提示规则，无法自行增加系统工具权限。
- 飞书 CLI 当前使用服务器本机 CLI 登录身份，不能代表多家企业中的网页登录用户。因此飞书能力仍限测试部门原有工作流，尚未注入通用执行器；需先实现并验证按租户隔离的身份绑定。不能读服务器私密配置文件或把用户导入文本当代码运行。

最小执行器示例：

```python
class PRODUCT_Research:
    def execute(self, context):
        # 平台会把当前 Skill 与提示词一同交给已选模型；此调用只返回 JSON。
        result = context.model.request_json(
            '根据输入资料撰写研究简报，返回 {"deliverable": "...", "evidence": [], "gaps": []}。\n'
            + context.inputs
        )
        return {
            'deliverable': result['deliverable'],
            'evidence': result.get('evidence', []),
            'gaps': result.get('gaps', []),
        }


def create_adapter():
    return PRODUCT_Research()
```

`ExecutionContext`、`ModelAccess`、`GmAccess` 的类型定义和工作区版本语义在 `server/core/integrations.py`。每次执行都重新读取当前节点，因此该部门无需复制 Skill 解析逻辑。

权限规则中的工作室、项目、部门、节点字段定义授权作用范围。工作室必填；项目留空表示覆盖该工作室内所有项目，因此可为某部门设置跨项目权限。节点授权仍要求明确项目和对应部门。Skill 资源可按部门/项目范围授权全部节点的 Skill，也可指定节点缩小范围。资源类型（项目、部门、节点、Skill、GM 等）必须精确匹配，不会因为节点授权自动获得 Skill 权限。撤销规则后，下一次请求立即按最新授权重新判定。

## 验收

每个变更至少包含：本部门契约测试、一次错误输入/越权测试、固定 fixture 的输入输出样例、真实工具和替身清楚区分、README/manifest 同步。不要提交密钥、数据库、需求、测试证据、Unity 项目源码或生成目录。

先运行 `python3 tools/check_department_boundaries.py --department product`（换成自己的部门 ID）。检查器只读扫描静态 Python/JavaScript 依赖、类/函数与代码文件前缀，禁止直接导入其他部门、公共壳私有实现或 sqlite3；Python 仅允许直接导入 `server.core.integrations` 的公共契约。固定入口文件 `adapter.py`、`ui.js` 以及协议规定的 `create_adapter`、`execute`、`renderHome`、`renderWorkspace`、`mountHome`、`mountWorkspace` 保持名称。动态加载、任意文件访问或恶意代码仍需评审，检查通过不代表沙箱隔离。

公共交互验收可运行 `node tests/browser/department-module-workflow.cjs`。需要本机可用的 Playwright 和 Chromium；可用 `STUDIOFLOW_PLAYWRIGHT_MODULE` 指定 Playwright 模块路径，`STUDIOFLOW_CHROME` 指定浏览器路径。脚本自建随机端口、临时数据库与明确标注的 UI 模块替身，验证挂载/清理、公共草稿保存、Skill 不被草稿接口修改及旧回调拦截；不连接真实模型或飞书。它不代替部门实际工具验收。

## 项目配置与内容生命周期

节点间自动继续由公共平台维护。项目总览的跨部门连接使用同一接口的 `department=__project__` 范围，仍以实际来源末节点和目标首节点的稳定 ID 保存，与部门内配置独立。来源部门全部活动节点已人工确认且末节点新确认后才尝试跨部门排队；进入测试部门停在人工选择批次/导入需求。首页与工作区使用同一 `GET/POST /api/studios/{studio}/projects/{project}/node-continuation?department=<id>`；读取返回配置 `revision`、可见 `edges` 和相关操作事件，保存提交 `{revision, source, target, enabled}`。`enabled` 必须是布尔值，起止节点必须是当前有效相邻稳定 ID；保存要求来源 `node.edit` 和目标 `node.view`，冲突拒绝覆盖。部门模块不自行存储开关或调度下一节点。

全部连接默认关闭。当前节点通过公共人工确认后，在同一事务中保存一次续接意图；后台在派发前重新检查来源审批、操作者权限、拓扑、开关修订、目标修订和 Skill。普通节点还要求目标已有输入、没有待覆盖交付物且注册了真实执行器。缺条件就停止并记日志，条件补齐后由用户手动执行，不追溯旧确认。配置改变或撤权不能复活旧意图；事务失败可恢复尚未提交的意图，已提交派发不重复。节点结构变化关闭原连接，测试固定阶段仍遵守原证据依赖。此契约不允许执行器审批、自动发布外部记录或启动 Unity。

项目节点通过公共“管理节点”入口新增、删除（归档）、排序和恢复，create/delete/reorder 分开授权。部门仓库默认节点 ID 不可修改；自定义节点使用 `<department>:custom-<UUID>`，不会冒充原有自动执行器。排序不改变测试证据依赖；历史批次保留创建时节点与 Skill 快照。

工作台 Skill 与实际节点规则绑定。所有导入入口记录版本、真实操作者与时间；旧数据未记录的字段显示“未记录”。项目规则用于新测试批次，旧批次保持原快照。删除由范围管理员操作并进入30天回收站，删除后不自动恢复默认规则；服务定时清理，停机期间到期项在下次启动补清理。现阶段仅单 Markdown，依赖文件不自动打包。

`content.create/delete` 独立控制部门启停、默认工具/首页信息的隐藏恢复、自定义工具、信息块、资料及手工交付条目。普通成员和部门负责人不默认获得，范围管理员默认允许。工具只接受无凭据 HTTPS；正文是纯文本。普通节点保存与执行仍使用 edit/execute/approve。

测试旧工作台的需求导入同时需要 node.import 与 content.create。归档来源需要 content.delete、恢复需要 content.create；保留所有来源版本，归档来源不参与生成。有活动任务或下游产物时拒绝归档，须先重置用例节点。项目部门停用保留可读历史，拒绝普通工作区写入及新任务；原测试批次仍保留创建时配置。

测试筛选合并兼容：只有项目已归档 testing:3 时，testing:2 确认后直接衔接 testing:4；其余必需阶段不可跳过。归因产物新增 filing_scope，复用原 filter_groups 校验每个根因的选择/排除理由；内部 artifacts["3"] 保留兼容投影。任务 API 返回 filter_merged 和供提单节点查看的 filing_scope，不要求已删除筛选节点的编辑/审批权限。原 ID、历史节点快照和发布门禁保持兼容。自动衔接到提单仅准备内部草稿，之后仍人工核对并逐单发布。


## 节点结果通知

测试默认流程的节点开关现支持完成后自动决策：公共层通过 `testing_edge_advances` 保存来源任务、操作者、连接版本与任务修订；来源成功后复用测试范围/证据/归因门禁，确认记录标为自动决策，再由原续接出箱排队。只覆盖用例→执行、执行→归因、合并归因→内部草稿；关闭、撤权、修改及重启均停止，不自动发布或改变飞书状态。独立流程不复用默认图，全自动委托优先，部门执行器不读写该表。

各部门节点的“检查 Skill”为公共只读能力：检查输入、输出、证据和边界声明及未随单 Markdown 导入的相对文件依赖，不改写规则，不代表业务效果评测。部门适配器的原输入输出协议及权限保持不变。

飞书 Webhook 通知由公共平台负责。部门执行器继续返回原契约结果，不直接调用 Webhook 或读取密钥。队列结束、人工提交交付物及可选人工确认后由公共事务记录通知，发送结果独立保存，失败不会重跑部门执行器。工作室/项目/部门/节点范围由负责人配置；人工结果明确标注，未接入执行器不得宣称自动完成。上传 Skill 不能改变通知目的地、权限或事件类型。

## 功能积木与自定义流（公共扩展契约）

普通节点“搭建节点”可组合输入、AI、清单、模板、人工审核和外链；保存后进入节点使用实际运行页。团队模板固定按工作室+部门共享，可跨该工作室的项目复用配置快照；项目输入和结果不进入模板。自定义流按项目保存，将任何已授权节点按顺序组合，人工节点暂停等待操作。发行增长从默认导航移除，历史 growth 数据和 ID 保留。

部门可只新增 `departments/product/PRODUCT_blocks.py`（其他部门换对应前缀），无需修改公共壳或直接访问数据库。模块部署后重启服务，类型进入本部门积木库：

```python
# departments/product/PRODUCT_blocks.py
# 传入的 register 是公共登记能力，不导入公共壳内部实现。
def PRODUCT_outline(context, config, previous):
    return {
        'deliverable': config.get('heading', '研究提纲') + '\n\n' + previous,
        'evidence': [],
        'gaps': ['此积木只整理输入，未执行外部研究'],
    }


def PRODUCT_register_blocks(register):
    register('product.outline', label='研究提纲',
             fields={'heading': 'text'}, execute=PRODUCT_outline)
```

处理器参数是 `(ExecutionContext, validated_config, previous_output)`，返回 `{deliverable: str, evidence?: list, gaps?: list}`。支持字段 `text/bool/list/url`。需要模型时调用 `context.model.request_json(prompt)`；不要读取密钥或私自切模型。GM 沿用原显式授权与 `env=test` 限制。类型私有于部门，流程通过所属节点引用，不直接引用其他部门私有类型。每块结果最大800KB。处理器应无外部写入副作用；中断重试不会重跑已完成块，但当前步骤可能重复进入。注册代码来自受信任仓库，不是网页上传能力，也不是沙箱。

公共接口：

| 方法与路径 | 用途 |
| --- | --- |
| GET/POST `/api/studios/{s}/projects/{p}/node-blueprint?node={stable_id}` | 节点组合；写入 `{revision, blocks, sources?:[]}` |
| GET `/api/studios/{s}/block-templates?department={d}` | 同工作室部门模板列表 |
| GET 同路径 `&id={id}&version={revision}` | 模板指定版本；省略 version 则最新 |
| POST `/api/studios/{s}/block-templates` | `{department,name,revision,blocks,kind:'node'或'flow',id?:...}`；新建 revision=0；归档加 `action:'archive'` |
| GET/POST `/api/studios/{s}/projects/{p}/custom-flows` | 项目流列表/保存；归档 `{action:'archive',id,revision}` |
| GET/POST `/api/studios/{s}/projects/{p}/block-runs` | 可见运行列表/启动 `{node或flow,revision,input}` |
| GET/POST `.../block-runs/{id}` | 读取/操作 `{revision,action,value?}`；action 为 save-draft / submit / retry / cancel |
| POST `.../block-runs/{id}/publish` | 独立节点完成运行保存为原节点待审交付；校验源版本和 Skill |

块格式 `{id,type,config}`；模板交换格式 `{schema_version:1,kind,blocks}`。来源记录 `sources` 为 `[{id,department,revision}]`，是配置来源追踪，不授予任何资源权限。运行记录提供逐块 output/evidence/gaps/actor/acknowledgement，不返回快照 Skill 正文或模型密钥。

模板权限资源 `block` 仅接受工作室+部门范围；工作流资源 `workflow` 仅接受工作室+项目范围。节点编辑不隐含结构增删，蓝图结构增加/删除分别检查 content.create/delete。测试固定节点继续专用证据工作台，不能用通用 AI 替代；自定义流的测试步骤要求关联真实批次，完成审核后才能继续。旧节点自动继续尚不派发积木蓝图，请通过自定义流组织搭建节点。

## GitHub 默认方法目录

内置 22 节点默认方法的来源注册统一在 `server/skills/github-defaults.json`，运行时读取部门目录下的实际 Markdown；不读取个人机器 Skill 来覆盖团队默认。每条记录固定上游 commit、核验时间、仓库星数、MIT 许可和原始快照 SHA256，详见[默认 Skill 来源](../default-skill-sources.md)。部门可维护自身正文，跨部门来源加载由公共平台维护。上传/绑定优先和历史运行冻结语义不变；自定义节点按用户选择使用规则，不自动套用相近名称的方法。


## 部门独立流程与节点记忆

平台 `ModelCapability.request_project_json(prompt, root, schema, progress=None, audit_dir=None)` 是受信任执行器的项目 Agent 能力，绑定该次执行的模型选择和 Skill 快照；不得用默认模型替换配置、不开放给浏览器任意路径调用。当前用于生产内生成工程的静态审查，要求本机 Codex CLI 与 Responses 连接。返回仍必须经过部门证据校验；只读 sandbox 不构成不可信多租户文件隔离。普通文字节点继续 `request_json`。

公共壳提供 `GET/POST /api/studios/{studio}/projects/{project}/department-flows`：GET 使用 `department` 查询；POST 新建 `{department,name}`，归档使用 `{action:"archive",id}`。详情为 `GET .../department-flows/{id}`。创建复用部门编辑和节点创建权限，归档复用节点删除权限。默认工作区保持原协议；独立流程在 workspace、decision、execute、job 和 skill-export 请求上附加 `flow=<id>`，仍要求原有节点/Skill权限和修订锁。固定测试节点使用流程绑定的 `task_id`，不得写入通用流程工作区。新流程不触发默认自动续接图。

执行器上下文新增可选 `flow_id` 和 `memory`，原构造保持兼容。`memory.sources` 带来源 ID、节点、流程/批次、修订、完整文本哈希、受预算限制的正文与截取标记。公共层注入允许访问的同流程资料与显式关联交付，并在保存输出前重新核对来源权限及版本；部门只使用契约，不自行查表或调度线程。

节点助手路由 `.../node-memory?node=<id>&flow=<flow>&task=<task>`：GET 历史，POST `{question}` 排队；`/sources` GET 当前可用上下文，`/catalog` GET 可关联交付，`/links` GET 关联及 POST `{node,flow,remove?}` 增删关联。缺省 flow/task 表示默认工作区；跨部门与跨流程只自动使用明确关联且当前已确认的交付。提问需要节点 edit + execute，读取需要 view；关联不扩张来源权限。失效关联可取消，撤权不返回其正文或名称。

普通部门任务/测试任务/问答分别使用 3 / 3 / 2 个工作线程；任务领取和同节点去重由数据库约束完成。执行器不得假设全平台串行，不得依赖全局可变的当前流程。服务重启将运行中问答标记中断，历史问答最多返回最近 50 条。助手只读，不能以对话绕过审批或外部发布门禁。
