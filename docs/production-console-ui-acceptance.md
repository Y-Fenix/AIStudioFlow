# 全自动生产控制台 UI 验证

2026-11-10。范围仅为前端与隔离 API 交互；不将浏览器验证描述为真实模型、游戏构建或实机测试成功。

## 入口与接口

- 侧栏“全自动生产”、项目总览主按钮进入 `/?view=production&studio=…&project=…`。
- 启动 `POST /api/studios/{s}/projects/{p}/production-runs`，提交 `brief` / `idea`、`delegation:true`、幂等 `request_id`。明确勾选仅授权本次自动执行与委托审核。
- 列表 GET 读取 `items/runs` 与 `can_create`；缺少明确创建权限时禁用开始按钮。
- 详情 GET `…/production-runs/{id}`，消费 `steps/stages`、`events`、`artifacts`、`error/gaps`、`allowed_actions`。运行 ID 写入 `production_run` URL 参数，刷新恢复。
- 暂停、恢复、取消、重试通过详情 POST `{action}`，仅展示服务端允许的动作。
- 下载只构造同项目受鉴权 `…/{id}/artifacts/{artifact_id}`，不使用任意远端 URL。
- 已关联独立流程的节点可打开本次节点工作区，保留原节点/流程权限门禁。

## 真实反馈与交互边界

进度仅统计服务端实际 `completed` 步骤，不用时间或推测计算百分比。四部门步骤数量动态读取；构建步骤及测试阶段跟随后端返回，不写死成四节点。运行时长为创建至当前时间，终止/暂停状态采用服务端更新时间，不在结束后继续递增。

开始及控制动作即时 pending 并阻止重复提交；错误保留输入，提交状态不明确时明确提示先核对记录。同一提交重试使用原请求 ID。页面每四秒读取真实状态，无变化时保留详情 DOM，保留展开状态和键盘焦点；离开页面停止轮询。撤权/登录失效后隐藏缓存详情与历史，禁止继续启动。普通网络失败保留已知结果并明确标记刷新失败。

界面明确当前构建器支持记忆配对 Android 原型。未验证的 APK、模型文字报告和客户端测试不会显示为已交付/实测成功。飞书页面只提示以通知记录核对送达，不展示 Webhook 或凭据。

## 已执行验证

- 先创建 `tests/production-console.test.js`，缺实现时红灯；实现后全部断言通过。
- `node --test tests/*.test.js`：110 项通过，0 失败。
- `node tests/browser/production-console.cjs`：隔离临时 SQLite、真实本地 HTTP API、Chrome；测试脚本明确关闭生产 worker，因此不会调用模型、构建器、飞书或真实用户任务。
- 浏览器验证真实创建持久记录、pending/防重复、刷新深链恢复、真实 pause/resume/cancel、动态显示全部实际节点、零虚假进度、无成果不显示下载、键盘控制、减弱动画、三个主题渲染、375/768/1024/1512 宽度无横向溢出。
- 网络提交失败与撤权响应使用明确的浏览器协议替身，验证输入保留与隐藏敏感缓存；不称为真实撤权集成验收。
- 仅对主题做渲染/操作可用性验证，没有声明已完成全页面自动色彩对比度审计。
- 截图 `/tmp/studioflow-production-console-desktop.png`、`/tmp/studioflow-production-console-mobile.png`。截图是明确隔离验收项目的排队状态，不是实际游戏生产成功证据。

不涉及 Git 拉取、提交、推送、Figma 修改、生产服务重启或真实任务操作。真实模型链、APK 生成/安装与飞书送达由完整生产验收单独验证。

## 生产交付正文滚动回归（2026-11-10）

在同一隔离 Chrome / HTTP / SQLite 脚本补充真实轮询复现：给两个节点写入长交付文本，将独立 `pre` 置于 `(scrollTop,scrollLeft)=(240,65)` 与 `(395,105)`，只在服务端更新运行摘要。修改前四秒轮询重建详情后两者均归零，新增断言失败，证实问题。

最小修复在 `renderRun` 重建前后按 `data-step` 保存/恢复每个正文的双轴滚动位置；保留现有展开状态与焦点恢复，不修改窗口滚动、不锁定页面。浏览器新增原生滚轮继续阅读后再次服务端更新的断言，确认以用户最新滚动位置为准。为覆盖横轴，脚本仅在该测试期间给 `pre` 加 `white-space:pre`；正式样式仍按原规则换行。
