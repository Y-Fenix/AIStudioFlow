# 开发部门模块

本目录由开发部门负责人维护：`manifest.json` 定义首页和节点，`ui.js` 定义本部门插槽，`skills/` 保存默认工作方法。`adapter.py` 通过公共 `generate_document(context, contract)` 使用本次已选模型和当前 Skill，生成待人工审核的文字交付。`DEV_contracts.py` 定义四个固定节点的具体章节与能力边界。

公共壳负责登录、工作室/项目隔离、权限、共享存储、队列、模型凭据和审批。开发模块通过公共 `ExecutionContext`、`ModelAccess` 和 `GmAccess` 契约工作，不直接访问核心数据库、模型密钥或其他部门工作区。不得在执行器中自动拉取、提交或推送 Git；源码变更必须保留可审查边界。

节点 key（如 `development:0`）是持久化数据和授权规则的一部分，不能因改名、排序而复用或改变含义。新增、删除节点，或修改输入/输出契约时，先补迁移和测试，再更新 manifest。

交付前运行 `python3 -m unittest tests.test_team_platform.DepartmentManifestTests tests.test_department_execution tests.test_department_jobs_api` 和 `node --test tests/department-ui-contract.test.js`，并为本部门适配器加入固定输入输出、错误输入和越权测试。共享接口约定、最小适配器示例及安全边界见 [`部门模块协作约定`](../../docs/departments/README.md)。

## 默认 Skill 来源（2026-10-22）

本部门 `skills/<index>.md` 为固定 GitHub commit 的单文件方法移植版，含原文方法片段、节点输入输出、证据边界与 MIT 许可。来源注册由平台 `server/skill_catalog.py` 和 `server/skills/github-defaults.json` 统一维护；部门维护本目录正文时同步来源和回归，不改变稳定节点 ID。详见[完整节点映射与生效规则](../../docs/default-skill-sources.md)。

未配置覆盖的节点使用新默认；已导入、已保存覆盖规则及历史任务快照不批量改写。恢复默认须走已有权限与修订检查。Skill 文字规则不代表执行器已接通或上游辅助文件已安装。


## 模型文字执行器（2026-10-22）

节点卡片中的输入均指用户已提供的可读文字：链接、文件名、截图或包体路径本身不代表已读取其内容。需要分析的观察、代码、配置或工具记录须先整理为节点输入；本执行器不会自行获取。输出为待审文字草案、规格或计划，节点名称保留原业务阶段含义。

- 技术方案：项目基线、架构、接口、数据迁移、任务、验证计划。
- 功能实现：基线、需求映射、未应用代码提案、配置、建议测试、审查。
- 集成与自检：基线、依赖矩阵、静态推导、测试计划、证据分级、交接。
- 版本交付：版本基线、变更、交测门槛、已知问题、回退计划、交接。

`execution.adapter=adapter` 和 `automatic=true` 表示四个固定节点支持模型文字生成；不表示外部工具已接通、不自动审核，也不授予发布权限。自定义节点或其他部门节点拒绝套用这些固定契约。输入和 Skill 必须为非空文本；用户导入 Skill 仍优先于默认规则，运行使用当前快照。

每份交付含具体业务章节、事实/推导/假设及原文引用、缺口与下一步。公共生成器核对章节结构和引用是否逐字存在于输入；最多修正一次结构或引用错误。结构齐全、引用匹配不证明事实真实、推导正确或业务质量达标，仍需人工审核。

未读取本地工程、修改源码/配置/资源、执行 Git 拉取/提交/推送、编译、构建、运行测试、启动 Unity、交包或发布。代码提案必须依据用户提供的项目和代码基线；缺少基线或可读代码时，只给缺口及伪代码方向，不冒充真实补丁。

验证：`python3 -m unittest tests.test_DEV_executor` 覆盖四节点固定模型 fixture、当前导入 Skill、非法/跨部门节点、空输入、空 Skill、执行权限拒绝与待人工审核；fixture 使用临时数据库和协议模型替身，不代表真实模型、外部工具或业务效果验收。另运行本部门边界检查及既有公共契约测试。

## 真实Android原型构建能力（2026-11-10）

新增受控能力 `DEV_game_builder.DEV_build_game(output_root, brief, *, progress=None, check_cancelled=None, model=None)`，供平台生产链显式调用；原四节点文字适配器保持原契约。平台提供经过权限与授权校验的独立新目录、输入、当前模型能力和取消回调。能力不访问数据库、不读取模型凭据、不执行模型输出代码、不修改既有用户游戏工程。

当前只实现 **memory_match 离线触控记忆配对**：开始、洗牌、翻两张牌、错配延时遮盖、配对计数、限时胜负和重开。模型只能设置标题、2–8对、30–300秒和主题色；非配对需求会明确拒绝，不擅自生成别的玩法。没有广告、IAP、联网、原生Unity支持或正式发布签名。

返回 `{artifacts, checks, gaps, project_path, package_name, spec}`；产物含真实debug签名APK、源码ZIP、规格、构建日志和校验记录，文件带SHA256和大小。checks严格区分JVM规则测试、APK构建/签名和可选Android模拟器触控验收；无模拟器时保留未验收缺口。平台仍负责审批、下载权限和是否继续后续节点，不能把JVM测试当成手机实测。

工具通过 `STUDIOFLOW_ANDROID_SDK` / `ANDROID_SDK_ROOT` / `ANDROID_HOME` 或操作系统常规SDK路径探测，JDK通过 `JAVA_HOME` / PATH探测。需要Android SDK平台35、build-tools35和JDK；构建器不会自动下载SDK或接受许可证。设置 `STUDIOFLOW_ANDROID_TEST_SERIAL=emulator-5554` 可在已启动的指定模拟器自动安装并执行开始、触控、QA加速时钟失败、重开和确定性牌组胜利，保存截图/日志。严禁将此变量用于真机；代码会拒绝非 `emulator-*` serial。同一服务进程的模拟器验收串行；不要让其他服务进程或人工同时控制同一模拟器。

本机命令：`python3 tools/DEV_build_android_game.py --spec /绝对路径/game-spec.json --output /绝对路径/新目录`。新目录及父路径不得为符号链接，禁止路径穿越或覆盖已有内容。每run使用独立包名和独立debug签名；不上传商店。详细环境、真实验证与边界见 [Android构建验证](../../docs/DEV_android-game-build.md)。

### Loop 构建模板

`game_type=loop` 支持1000个确定性、不重复初始盘面：1–100关4×4、101–400关5×5、401–1000关6×6；非空格均为直管或弯管，允许多个闭环。点击顺时针旋转计一步；不限次提示调整一格，单独计提示次数。包含首次规则说明、重开二次确认、关卡列表和顺序解锁、末关封顶、完整盘面/步数/提示/完成集合事务保存与备份恢复。模板不提供人工难度验证、自动认知难度排序、广告/IAP或正式发布签名。

构建执行1000关JVM旋转、可解性、提示和初始盘面去重检查，并导出 `level-validation.json` 逐关记录。明确指定模拟器后，真实验证首次说明、触控、进程重启后的已保存盘面与计数、重开确认、可见提示通关、下一关及完成集合保存；读取debug包自己的真实偏好文件比对，不写入胜利状态。模拟器验收仍不等同真机、无障碍或人工解谜体验验收。最新独立验证目录：`data/loop-delivery/build-009/`；全链路运行另有自己的产物和记录，不能互相冒充。
