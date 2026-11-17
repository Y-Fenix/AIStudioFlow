# 实际工具检查

## 默认调用：本地语法检查 + 人工审查

在 capture 后执行 skill 自带脚本（输出目录必须是本次报告下尚不存在的子目录）：

```sh
python3 -B /Users/yf/.codex/skills/test-server-sdk/scripts/static_tools.py --baseline <本次目录>/baseline.json --output <本次目录>/tools --timeout 15
```

脚本仅调用本机 PATH 中的 Node 和 Swift 编译器的版本/解析模式；执行前确认工具路径为本地安装工具，不是库内自定义包装脚本。Node 用 `node --check <绝对路径>`；Swift 用 `swiftc -frontend -parse <绝对路径>`。脚本去除 NODE_OPTIONS/NODE_PATH 等预加载环境，工作目录在报告目录，不运行源码、包管理器、项目脚本、构建 hook 或插件，不安装工具、不联网。工具本身为可信安装是前提；源码语法检查不提供安全沙箱。

扫描范围来自基线：仅检查基线中 JS/CJS/MJS/Swift；其他识别的源码后缀逐文件记录 unsupported；基线排除项仍不在范围。每文件有超时；超时终止该进程组，继续其他文件。哈希不一致或出现符号链接标 stale，不能用该结果发布旧基线报告。结束仍须完整 verify 基线。

`tool-results.json` 逐文件记录命令、工具路径/版本、退出码、时长、诊断行列和状态：

- executed_ok：该解析命令成功，仅代表该文件在该工具版本下语法被接受。
- syntax_error：工具诊断支持解析错误；需定向读源码确认并脱敏后写断言，不代表已经完成类型检查。
- tool_error / timeout / unavailable / unsupported / stale / missing_repository：均不算检查成功。

脚本返回码：0=纳入的源码检查全成功且基线无读取错误；2=存在解析错误；3=部分检查未完成/工具失败。检查 JSON，不把 3 当脚本崩溃，也不把 0 当发版通过。`complete` 仅指本脚本纳入的语法检查，不含被基线排除文件、所有文件类别或业务检查。诊断可能含源码密钥，脚本不保存原始 stdout/stderr，只保留定位；报告用定向读取后的脱敏证据补充原因。

## 类型、Lint、构建与测试：按授权及实际项目配置执行

用户要求“优化 skill”不等于执行四库构建。常规 skill 调用默认不启动以下项目任务；用户要求执行工具/构建/测试时，先检查已有会话授权、AGENTS、任务定义和副作用。已授权的本地可逆步骤直接完成，无需再次问。不能运行的记 blocked，给出最小前置条件；不要为了只读审查停止全部报告。

| 项目 | 候选方式 | 执行前必须确认 |
|---|---|---|
| Android Kotlin/Java | 项目现有 Gradle compile/lint/detekt 任务 | 实际模块/variant/任务；Gradle 与 JDK；wrapper/插件/配置阶段执行代码；Android SDK 和离线依赖；输出与缓存位置。不要猜任务名或自动下载。 |
| iOS Swift/ObjC | 实际 scheme 的 xcodebuild，已有 SwiftLint | scheme、SDK、依赖、条件编译、脚本阶段、插件、签名需求；使用独立 DerivedData；不开启自动签名/依赖解析。Swift parse 不证明模块能链接。 |
| Node JS/TS | 现有 ESLint/tsc 配置及本地安装工具 | 配置/插件会执行代码；npm script 的真实内容；不使用 --fix、不发起 npx 临时下载；JS 语法模式不替代 tsc/类型推导。 |
| 测试 | 已有离线单元测试/隔离替身 | 是否连真实 DB、MQ、商店、GM 或第三方；是否发奖/扣费/清数据。报告必须区分真实依赖与 mock。 |

审查锁定文件、实际安装工具版本及执行环境。依赖缺失时不自动安装，不用脱离项目的单文件编译制造假阳性。超时、失败、部分模块、排除文件、禁用规则必须呈现。对业务上需要运行而当前未授权或缺环境的命令，写入待执行清单；不把候选工具写成“已接入”。

专项循环/死锁审查没有通用完备判定器。若使用已有规则引擎，记录引擎版本、规则集、配置和覆盖范围；只有匹配模式而无可达性/状态证据时保留为候选，不自动升级缺陷。
