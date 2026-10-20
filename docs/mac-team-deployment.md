# StudioFlow 单台 Mac 团队部署

当前项目仍使用 Python 标准库 HTTP + SQLite。默认使用本地账号密码，首次设置负责人仅允许 127.0.0.1 回环直接访问；团队访问必须经过带 HTTPS 的反向代理。服务进程可以监听局域网地址，但**不要将未 TLS 的 8766 端口暴露给团队或公网**。

## 启动

```sh
cd /path/to/StudioFlow
python3 -m server.app --host 127.0.0.1 --port 8766 --database data/platform.sqlite
```

生产可由 `launchd` 管理此命令，运行用户须为专用、非管理员 macOS 账号；数据库和凭据目录设置为仅服务账号可读写。对团队提供的域名应由反向代理终止 TLS、限制 body 大小、设置合理超时并转发 Cookie 与原始 Host。后端拒绝来自 LAN 的无会话和跨站写入，不应加一个绕过认证的网段白名单。

推荐先使用配置生成工具，避免手工改多份路径。只需提供目标 Mac 已存在的专用标准账号、真实 HTTPS 域名和一个新输出目录：

```sh
python3 tools/mac_prepare.py \
  --public-url https://你的真实团队域名 \
  --service-user 目标Mac的服务账号 \
  --output dist/mac-deployment
```

工具默认使用当前代码目录和当前 Python，并从系统读取该服务账号的主目录，生成 launchd plist、Caddyfile、路径清单和带实际路径的 `DEPLOY.md`；需要时可显式传入 `--python`、`--app-root`、`--data-dir`、`--log-dir`、`--codex-home`。Python 路径必须可运行且版本至少3.11。路径中的空格会保留，安装说明中的命令参数会正确引用。已有输出目录不会覆盖，请为新方案指定新目录。

生成阶段不创建服务账号或运行目录、不复制 Codex/飞书凭据、不安装或启用 launchd，也不修改 Caddy 配置。先审阅生成的 `DEPLOY.md`，在服务器本机设置负责人账号，在权限后台保存团队 HTTPS 地址，再运行只读预检后按目标环境安装。域名和 macOS 系统权限需要维护者提供；生成成功不代表团队服务上线。不需要飞书应用、企业安装授权或 OAuth 回调。

可从 [`deploy/mac/com.studioflow.server.plist.example`](../deploy/mac/com.studioflow.server.plist.example) 和 [`deploy/mac/Caddyfile.example`](../deploy/mac/Caddyfile.example) 开始配置。部署前必须替换服务账号、代码目录、Python 路径和真实域名；确认数据库目录及日志目录由服务账号拥有。LaunchDaemon 示例只监听回环地址，外部访问经 Caddy HTTPS 反代。示例不会自动创建服务账号、开放防火墙端口或启动服务。

每位使用“在 Codex 使用 Skill”的团队成员还需在自己的 Mac 安装 [`StudioFlow Codex Bridge`](../deploy/mac/codex-bridge/README.md)。该桥接通过短时单次票据获取当前节点 Skill，不使用服务器服务账号的 Codex 凭据，也不自动发送提示。维护者可运行 `python3 tools/build_codex_bridge.py` 生成对应 Mac 架构的应用 ZIP，成员解压到自己用户的 Applications 目录并打开一次即可注册协议，无需安装编译器。当前包只有本机临时签名，尚未 Developer ID 签名或公证。

复制并修改模板、通过平台保存登录设置后，可先运行只读预检：

```sh
python3 tools/mac_preflight.py \
  --plist /Library/LaunchDaemons/com.studioflow.server.plist \
  --caddyfile /opt/homebrew/etc/caddy/Caddyfile \
  --auth-config "/Users/_studioflow/Library/Application Support/StudioFlow/team-auth.json"
```

预检检查 launchd 仅绑定 `127.0.0.1`、路径占位符、Caddy 回环上游和站点域名、登录 HTTPS 地址及 `team-auth.json` 的 `0600` 权限。它不会输出密钥，也不会安装或启动任何服务；通过结果不代表真实团队登录、证书签发、launchd 运行或目标网络已经验收。若服务账号或文件路径不同，命令参数必须改成目标 Mac 上实际路径。

LaunchDaemon 以服务账号运行，因此“自动读取本机 Codex 配置”指该服务账号的 `CODEX_HOME`，不是管理员桌面账号的 `~/.codex`。若要复用 Codex CLI 登录或本地中转站，需在服务账号环境中准备相应登录/配置，并保证中转站对服务进程可达；本机回环地址允许 HTTP，远端模型服务必须 HTTPS。也可以在平台中单独保存自定义 API。不要把个人 Codex 凭据直接复制到共享目录。

```sh
sudo install -d -o _studioflow -g staff -m 700 "/Users/_studioflow/Library/Application Support/StudioFlow"
sudo install -d -o _studioflow -g staff -m 700 "/Users/_studioflow/Library/Logs/StudioFlow"
sudo plutil -lint /Library/LaunchDaemons/com.studioflow.server.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.studioflow.server.plist
sudo launchctl print system/com.studioflow.server
```

`_studioflow`、`staff` 和示例目录都需要按目标 Mac 的账户策略调整。代码目录应由发布负责人预先安装并设为只读；服务账号只需要写入数据库、日志及私密配置目录。升级时先停服务并备份数据库，再替换代码、启动并检查日志。Caddy 应单独安装为受 launchd 管理的服务，并先用 `caddy validate` 校验站点配置。

## 本地注册与登录

1. 在服务器 Mac 的浏览器直接打开 `http://127.0.0.1:8766/`，设置负责人账号、姓名和密码。没有默认密码，不能从反向代理或远程页面认领初始负责人。此账号绑定原有负责人身份，保留已有工作室、项目、权限与历史。
2. 登录后，在“权限后台 → 账号登录与部署”保存真实团队 HTTPS 地址。成员无需加入某家飞书企业即可注册。可以关闭新注册，已有账号仍能登录。
3. 新成员注册后为待审批状态，没有项目访问权。负责人在“成员与审批”分配工作室、项目、部门和角色；节点、Skill 等细粒度权限沿用现有授权规则。
4. 账号为 3–32 位英文、数字、点、下划线或连字符，不区分大小写；密码为10–128个字符。使用独立随机盐的 scrypt 保存密码哈希，不存明文。会话有效期12小时，数据库只保存会话 token 的 SHA-256；Cookie 使用 HttpOnly / SameSite，配置 HTTPS 后增加 Secure。
5. 用户在右上角“用户设置 → 修改密码”修改自己的密码。平台负责人可在成员列表重置其他本地账号密码。改密、重置、退出和禁用会撤销相关会话；重置密码不自动审批或提升权限。

负责人忘记密码时，在服务器终端交互重置，密码不会进入命令参数或输出：

```sh
python3 tools/local_account_admin.py --database /实际路径/platform.sqlite --username 负责人账号
```

工具只修改已有账号的密码、撤销会话并记录审计，不创建账号、不变更权限。数据库路径必须与服务一致，运行用户必须有该数据库的读写权。

未配置认证文件时默认 `password` 模式；保存设置后生成权限为0600的 `team-auth.json`，只需 `mode: password`、`public_url`、`registration_open`。旧配置的 `local`（回环免登录开发）和 `team`（OAuth）仅保留迁移兼容；旧部署可在权限后台切换成本地账号，再从服务器本机设置负责人密码。已有飞书身份不会按姓名自动合并成本地账号，避免冒领权限。新成员可注册独立本地账号后由负责人明确重新分配。

隔离测试使用显式 `create_server(..., local_development=True)`，不在默认启动命令中启用。即使开发模式也只允许直接回环免登录，拒绝 LAN 或代理请求。

## 备份与上线边界

停止服务或使用 SQLite 一致性备份 API 后备份 `data/platform.sqlite` 与私密运行配置；备份应加密、限制访问，并定期执行隔离恢复。不得把数据库、Secret、用户需求、Unity 游戏目录或生产运行日志推入版本库。公开仓库只包含代码、无机密示例和测试。

当前单台 Mac 版本没有远端对象存储、水平扩展、跨机容灾或企业 SSO 管理平台；Session 是本地 SQLite，恢复数据库即恢复会话账本。管理员应更新 OS、限制本机账号、监控磁盘和定期恢复演练。项目源码按负责人登记的绝对路径只读检查，服务不自动 Git clone/pull/push/commit。团队 HTTPS、登录会话和 Mac 关机/恢复必须在目标部署环境验收。

测试与非测试部门的排队任务均绑定创建者。执行前、可中止的运行检查点和保存结果前复查账号/节点权限；代码审查还核对负责人登记的源码目录。升级时，旧测试队列中没有创建者身份的未完成任务会标记失败并要求重新提交，历史完成任务保留，不以服务器负责人的身份代跑。已经发出的不可取消 HTTP 模型请求可能等返回后才能丢弃结果，不等于可立即中止远端计算。
