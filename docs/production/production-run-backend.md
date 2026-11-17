# 持久化生产链后端

2026-11-10。新增平台服务 `server/core/production_runs.py`，新增表，不修改已有字段语义。独立部门流程隔离默认工作区；不执行 Git、不写 Figma、不发布外部公区或 Bug。

## 运行协议

`GET/POST /api/studios/{studio}/projects/{project}/production-runs`。创建请求 `{brief,name?,request_id?,delegation:true}`；`idea` 兼容 `brief`。同项目、同操作者非空 request_id 去重。GET 返回 `items` 和 `runs` 别名、`can_create` 与 readiness。

`GET /.../production-runs/{id}` 返回完整运行。`POST` 同路径接收 `{action:"pause"|"resume"|"retry"|"cancel"}`。失败仅显式 retry；重启将 running 暂停，不重放外部工具。完成步骤保存检查点，恢复只继续未完成步骤。暂停或取消在途模型调用不会强杀远端请求，但阻止委托审核及下一步；构建检查取消回调，杀掉其受控子进程。仍在停止中的运行不能恢复。

`GET /.../production-runs/{id}/artifacts/{artifactId}` 每次复核项目与所有来源节点读取权限，限制在当前运行产物目录且 SHA256 必须一致。列表不返回内部产物路径。浏览器下载使用 attachment。

运行字段：`status`, `steps`/`stages`, `events`, `artifacts`, `gaps`, `error`, `summary`, `progress:{completed,total,current}`, `allowed_actions`, `delegation`。

## 执行与委托

先调用当前已注册产品4节点、设计4节点、开发4节点，通过原 ExecutionService 使用当前节点 Skill、模型、版本检查与来源权限。每个部门单独 DepartmentFlows；不覆盖旧工作区。只在创建时明确 delegation=true 且每步重新确认 node view/edit/execute/approve 权限后，记录 `delegated_review`，不会伪装为人工审核。创建独立流程仍需原有 department.edit 和 node.create 权限。

其后调用受信任 `DEV_build_game`。真实构建当前支持原生 Android loop / memory_match 受控模板，不等于任意游戏生成；构建返回 checks 必须非空、全部 passed=true 且有 evidence，下载产物必须真实存在，否则测试步骤失败。

生产运行内测试链使用稳定ID testing:0、1、2、4、5：用当前项目QA Skill生成结构化用例，并复用 validate_cases 核对真实来源原文与步骤；执行阶段消费真实构建检查并调用 QA_review_generated_workspace 逐用例检查生成源码；归因只接收有证据的实际失败，缺陷只生成内部草稿，无缺陷明确无须提单；没有修复版则回归不适用或 awaiting_fix，不伪造通过。每个阶段保存可下载JSON，Skill哈希与revision变化拒绝委托审核。testing:3保留既有ID而不伪造已跑筛选节点。总计18步骤。

完成表示链路完成；不等于客户端全量业务验收。现有专属测试批次没有被伪造执行；其静态审查、提单、发布流程保持独立。源码审查桥接未部署时该步骤明确失败。未联网调研、未反编译、未生成正式签名与商店发布均须保留缺口。

节点完成、失败及重启中断复用项目飞书持久化通知队列；生产origin单独标记委托审核和真实完成n/18，链接带view=production与production_run直达本次运行，不把测试用户引向旧批次。通知run ID必须属于当前工作室/项目。无凭据写入源码或消息payload，通知失败不会重跑生产节点。

## 验证

先建立缺模块失败的 unittest，再实现。替身测试覆盖持久化、全链检查点、默认工作区隔离、显式委托、暂停恢复取消、撤权、跨项目、缺少真实检查失败、产物篡改和请求幂等。隔离 HTTP 测试覆盖真实服务的鉴权项目路由、显式委托400、重复请求与暂停取消。替身不等于真实模型/Android验证；真实构建由开发构建器另行验收。

命令：`python3 -m unittest tests.test_production_runs tests.test_production_api tests.test_department_execution tests.test_department_jobs -q`。

最新验证：上述25项测试通过（包含生产内5测试节点的替身链、真实HTTP服务和原有部门执行回归）。有缺陷不假回归、虚假需求引用拒绝已覆盖。真实模型与完整生产链由主任务另行执行验收。

生产通知补验：先2项失败测试确认原卡片错误显示待人工审核与缺生产深链，再实现最小通知扩展。34项生产/HTTP/原通知测试已通过，补充实际enqueue与重启中断归属测试。

通知扩展最终验证：生产/HTTP/原通知共35项通过；另重跑21项相关通知用例，确认完成与中断均保留真实1/18进度和本次run深链。HTTP测试显式使用受信任adapter替身，避免测试过程中争用真实模型。

## 原生项目Agent桥接与命令行

`ModelCapability.request_project_json` 保留当前模型、推理级别和本节点Skill；生产源码审查默认接 `server.static_review.QA_review_generated_workspace`，缺少该能力明确失败，不切默认模型。新增4项真实服务桥接测试（模型/构建输出为显式fixture，不发网络）：固定custom模型/high/Skill、真实源码引用到内部缺陷草稿、伪造quote拒绝、仅文字模型不回退。源码审查按用例与工作包保存的JSON打包为 `qa-source-evidence.zip`，经原产物鉴权下载；不把原始Agent事件日志放进此包。

`tools/run_production.py` 只通过 Store/ProductionRuns 公共服务操作。create只持久化，status只读取，只有run派发真实模型与工具。run通过定向 `advance(studio,project,id)` 推进指定记录，不误领其他项目或运行。现有Web服务已运行的数据库不要再用CLI run并发调度。

可调用命令：

```sh
python3 tools/run_production.py --database data/platform.sqlite --studio 4558e88ef59142d7b30d899bc0266deb --project baabb6b295714748ac5483d606191b88 status --id d86ad8ef711541b1a7645003a81c9bff
```

2026-11-10已通过公共服务准备“StudioFlow 全链路验收”项目和“记忆配对全链路验收”运行，18步骤，创建时queued、完成0步；brief明确4×4/8对/60秒/离线Android/触控开始配对胜负重开/不含广告IAP。已有工作室通知完整覆盖该项目，无需新增配置规则；本准备动作未发送模型请求或启动构建。真实推进与结果由主任务实际运行记录判定。

CLI create/status/pause/resume/cancel subprocess测试通过，确认create只保存pending步骤及空产物。桥接、模型能力、生产回归和HTTP联合24项测试通过；另CLI1项通过。
