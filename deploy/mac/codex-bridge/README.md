# StudioFlow Codex Bridge for macOS

每位要使用“在 Codex 使用”的用户都需要在自己的 Mac 上安装此工具。服务器不会写入客户端目录。工具兑换短时单次票据，将当前节点 Skill 放入剪贴板、打开 Codex 并尝试粘贴；它绝不发送 Enter。

## 团队成员安装

要求 macOS 13+ 和已安装的 Codex 桌面 App。向维护者取得对应架构的 ZIP（Apple Silicon 用 arm64，Intel 用 x86_64），解压后将 `StudioFlow Codex Bridge.app` 放到自己用户的 `~/Applications`，打开一次以注册协议；它在后台等待交接，没有普通主窗口。团队成员使用成品时不需要 Python 或 Xcode。

首次粘贴需在 macOS「系统设置 → 隐私与安全性 → 辅助功能」中添加并允许桥接工具。安装后在 StudioFlow 节点点“在 Codex 使用”；请检查粘贴位置和正文，再自行按 Enter。工具按 `com.openai.codex` bundle ID 查找应用，不依赖 `.app` 文件名；本机已验证能找到文件名为 `ChatGPT.app`、bundle ID 实为 Codex 的安装。粘贴前会定位唯一的 Codex 发送框，已有草稿、焦点变化或无法辨认时停止；不会把搜索框当作发送框。粘贴后还会核对正文，不以快捷键已触发作为成功依据。

如果系统中已经开启授权，但实际 App 仍报告辅助功能拒绝，可能是临时签名构建更新后，系统条目仍绑定旧的代码签名。2026-10-19 本机只读检查确实发现这一情况，系统日志明确记录 `Failed to match existing code requirement`。此时在辅助功能中删除旧条目，再重新添加当前安装的 App 并开启；只切换开关可能仍保留旧签名。不要修改系统权限数据库，也不要把终端继承的权限当作 App 本身已获授权。正式团队发布仍需稳定的 Developer ID 签名方案。

当前生成包只有本机临时签名，尚无 Developer ID 签名/公证。正式分发由维护者使用受信任渠道，并完成目标 Mac 安装验收；不把本机构建包称为已公证发布版。

## 维护者构建

构建机器需要 Xcode Command Line Tools 和 Python 3；在仓库根目录运行：

```sh
python3 tools/build_codex_bridge.py
```

结果位于 `dist/codex-bridge/`，包含 ZIP 与 SHA-256 文件。脚本按当前 Mac 的 arm64 / x86_64 架构编译，显式设定最低系统 macOS 13，并生成本机临时签名；不会安装、启动、注册 App 或操作剪贴板。Intel 包请在 Intel Mac 构建，不把 arm64 包当通用包分发。`dist/` 已排除在 Git 跟踪之外。

安装后可先只读检查目标应用查找（不启动 Codex、不操作剪贴板）：

```sh
"$HOME/Applications/StudioFlow Codex Bridge.app/Contents/MacOS/StudioFlowCodexBridge" --check-target
"$HOME/Applications/StudioFlow Codex Bridge.app/Contents/MacOS/StudioFlowCodexBridge" --check-composer
"$HOME/Applications/StudioFlow Codex Bridge.app/Contents/MacOS/StudioFlowCodexBridge" --diagnostics
```

`--check-composer` 只读检查已运行 Codex 的空白发送框，不聚焦或粘贴；从已授权终端运行通过，仍不能代替桥接 App 自身的辅助功能授权。`--diagnostics` 仅显示最近交接阶段与时间，不记录来源、票据或正文。初次链接处理器在进入 AppKit 事件循环之前注册，避免桥接尚未运行时丢失第一条链接。

HTTPS 部署为必需；本机开发允许 `localhost`、`127.0.0.1` 和 `::1`。卸载时退出桥接 App 后删除该 `.app`。

默认编译当前 Mac 的架构（Apple Silicon 或 Intel），不硬编码 arm64。来源地址、票据格式与正文校验可独立运行，不启动 Codex、不操作剪贴板：

```sh
swiftc deploy/mac/codex-bridge/BridgeURLPolicy.swift tests/codex-bridge-policy.swift -o /tmp/studioflow-bridge-policy-test
/tmp/studioflow-bridge-policy-test
swiftc -parse-as-library -framework AppKit \
  deploy/mac/codex-bridge/BridgeURLPolicy.swift \
  deploy/mac/codex-bridge/BridgeComposer.swift \
  tests/codex-bridge-composer.swift -o /tmp/studioflow-composer-test
/tmp/studioflow-composer-test
```

## 使用与隐私

- 协议只接收受限来源、票据和交接地址；服务器正文只在兑换时通过 HTTPS 返回。桥接使用临时网络会话并拒绝重定向，避免把票据转发到其他站点。
- 票据在两分钟内有效且只能兑换一次。若打开 Codex 失败，内容可能已兑换，但仍留在剪贴板，可手动粘贴。
- 交接正文最大 500,000 UTF-8 字节，JSON 响应最大 600,000 字节；接收过程中检查上限并停止超量下载。来源必须为不含凭据、路径、查询或片段的站点地址。桥接不会执行 Skill 正文，也不会自动按 Enter。Codex 仍按自身配置处理文件写入和覆盖审批。
- 当前交接一个 Markdown 文件，不包含原 Skill 的脚本、参考资料或附件。安装提示会要求 Codex 规范化安装副本的 YAML 名称并保留正文；如果引用的依赖没有提供，必须列出缺失项，不能报告完整部署成功。平台和用户原始 Skill 不会因此被改写。
- 源码和构建脚本可生成本机临时签名的应用 ZIP；尚无 Developer ID 签名或公证。正式团队部署时应由维护者签名并通过可信渠道分发。

## 真机验收仍需完成

本机已通过真实交接验证：协议启动、单次票据兑换、定位唯一 Codex 发送框、粘贴后独立核对精确597字符正文均通过；没有发送 Enter。测试输入已清除、剪贴板已恢复、桥接测试进程已停止。证据 `data/codex-native-bridge-validation.json`。没有执行 Skill 安装，不能将粘贴成功称为部署完成。

此前辅助功能拒绝来自旧临时签名绑定。删除/添加仍沿用旧记录时，先退出桥接，再由维护者执行 `tccutil reset Accessibility studioflow.codex-bridge`，用户重新添加当前 App 并允许；本机按此恢复并实测通过。不要重建或替换当前已授权 App 后假设旧授权仍有效。其他 Mac 仍需各自授权并验收；正式团队分发的稳定 Developer ID 签名/公证尚未完成。
