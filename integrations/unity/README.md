# Unity Editor 本机桥接（待安装）

源码：`TestFlowEditorBridge.cs`。编译检查：在AutoTest根目录执行 `python3 tools/check-unity-bridge.py`，仅引用本机Unity程序集，不启动Unity。此检查不能代替Editor导入与运行验收。

需先获准修改目标游戏项目，再将源码安装到其Editor目录；当前未安装，不修改项目。项目门禁仍须按GagaSort/AGENTS.md执行。

安装后，用户在已经运行的Editor中选择Tools/TestFlow/连接本机平台邮箱，选择AutoTest/data/editor-bridge。此连接只在当前Editor会话启用，需明确确认。不会自动开始Play Mode；需用户自行进入正常首页。测试占用鼠标，切换并恢复音乐/音效。

协议：heartbeat.json声明真实项目路径、运行器SHA256和播放/编译状态。平台仅在心跳新鲜、项目与代码绑定一致时原子写入UUID.request.json。Editor永久领取为UUID.claimed.json，再输出UUID.result.json。仅支持settings_smoke，禁止GM模式及账号条件变更；过期、目标不符、源码变化、已有运行任务均拒绝。断开、域重载或结果不确定后不自动重跑，需要人工核对；异常时请在原测试窗口检查恢复状态。

目前已完成桥接源码、程序集编译检查、本地邮箱发送与只读预检接口；尚未完成安装、Editor实测、Web启动按钮、报告归一化及执行队列接入。没有用该设置冒烟替代连胜分组需求验证。
