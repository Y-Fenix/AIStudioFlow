# 真实Android记忆配对原型

2026-11-10 实际验证：本机Unity 2022.3.62f2c1无Android模块；原Android SDK仅含adb，JDK21可用。本次在常规用户Android SDK目录配置了命令行工具、Android35平台、build-tools35、arm64 Google APIs系统镜像及模拟器。没有启动或修改GagaSort工程。

构建使用固定受控Java Canvas模板，执行真实javac → d8 → aapt2 → zipalign → apksigner。模型只返回JSON规格，不生成/执行任意代码或shell。当前能力仅支持记忆配对，其他玩法明确拒绝；配对内容使用系统水果emoji，未接入设计部真实图片资产。

## 使用

```json
{"game_type":"memory_match","title":"Memory Garden","pairs":6,"time_limit_seconds":90,"accent_color":"#54B49B"}
```

```sh
python3 tools/DEV_build_android_game.py --spec /absolute/game-spec.json --output /absolute/new-game-run
```

SDK路径可以用 `STUDIOFLOW_ANDROID_SDK`、`ANDROID_SDK_ROOT` 或 `ANDROID_HOME` 指定。JDK路径用 `JAVA_HOME` 或PATH。SDK安装及许可由本机操作者预先完成，执行器不自动安装。每次输出使用新空目录，拒绝符号链接、路径穿越和覆盖工程。失败留下failure.json和已产生的日志；取消终止当前构建子进程，后续步骤不执行。

可选 `STUDIOFLOW_ANDROID_TEST_SERIAL=emulator-5554`，只支持已启动的明确模拟器，拒绝真机serial。验收实际安装本次APK，冷启动后通过adb触控开始/配对/重开；使用Intent中的QA seed固定牌组、QA seconds把超时缩短为2秒验证失败分支，随后以90秒运行并逐对触控到胜利。这是debug包的测试控制，不是正式发布功能。单服务进程验收串行，跨进程共用模拟器需部署侧串行。

## 已验证证据

真实验证目录 `/private/tmp/studioflow-game-validation-20261110-c`：

- `artifacts/game-debug.apk`：16854 bytes；SHA256 `b7f10c8c5558b3b4e314d23a8534809a46c77881837b6dae58e722bac69d07f3`。
- `build.log`：真实JVM规则测试、Java/DEX编译、APK签名及manifest检查。
- `android-smoke.log`：Android35 arm64模拟器安装、冷启动、开始、触控、失败、重开、胜利日志。
- `android-ready.png`、`android-lost.png`、`android-won.png`：真实截图，已人工查看开始和胜利画面。

后续构建的包名按run目录哈希隔离；此文记录的是上述具体已验证产物，新增源码ZIP与CLI之后的构建需另记对应证据。生成源工程README给出实际安装/启动/规则测试命令，源码ZIP不包含debug私钥。

最终CLI复跑目录 `/private/tmp/studioflow-game-validation-20261110-final` 同样通过JVM规则、APK签名和模拟器触控三项实际检查；`verification.json`保存工具路径和检查证据。最终 `artifacts/game-debug.apk` 为16854 bytes，SHA256 `7661cb340e9a6e66596893808ed2462af6cb242ad2484af80dbd1edd5b40b09d`；`artifacts/game-source.zip` 为5122 bytes，SHA256 `ce63a07e5878c2b7e3068dfd4ad90a70bb9dd1e36344c16d5c89a182b9e7af63`。ZIP内容已检查，仅源码/测试/规格/manifest/README，不含签名私钥。

未验证真实手机、不同屏幕/Android版本、后台恢复和长时间压力；不含iOS、广告/IAP、联网、多玩法任意生成或正式发行。不能以本次原型验收替代商店上架质量验收。
