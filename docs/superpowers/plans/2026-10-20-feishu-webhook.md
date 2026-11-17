# 飞书 Webhook 节点通知实施计划

Goal: 配置即可启用节点结束提醒，支持公司局域网、持久化发送记录与补发。
Architecture: 公共平台在结果提交事务内写通知 outbox，独立线程发送飞书卡片；凭据保存数据库旁的 0600 私密 JSON。工作室、项目、部门、节点逐级覆盖，未启用不发送、不补发历史。
Tech Stack: Python 标准库、SQLite、现有 Web 公共壳。
用户已批准 Webhook 首期及实际发送；禁止 Git 操作、Figma 修改、子代理。

- [x] 配置与发送器：先测试精确 Webhook 域名、签名算法、HTTP/业务返回、凭据隐藏、权限和继承；实现 server/core/notification_settings.py、server/connectors/feishu_webhook.py。
- [x] 持久化 outbox：先测事务回滚、事件去重、网络超时不自动重发、显式失败、重启 sending→unknown、凭据更改不改投、手动补发；实现 server/core/notifications.py 和增量 schema。
- [x] 公共落库：测试队列结束、产物保存、人工交付和服务中断；修改 store、department_jobs、studio_workspaces，以真实事件触发，不把人工交付或静态结论称为客户端通过。
- [x] HTTP/UI：配置、测试消息、历史、补发接口要求范围管理权限；连接与模型添加折叠通知区。卡片链接回准确节点，网页鉴权保留。
- [x] 局域网：仅密码模式可显式允许私有网段 HTTP；不开放免认证、不允许公网 HTTP。先测后改，记录适用范围。
- [x] 验证：相关 Python/Node、隔离 HTTP/浏览器；备份现有数据库/配置，检查无活动任务，再启用用户 Webhook 发一条明确测试卡片，核验业务响应；恢复正式服务并检查 LAN 访问。

检查命令：python3 -m unittest tests.test_notifications tests.test_notification_api tests.test_notification_events tests.test_local_accounts；node --test tests/*.test.js；使用本机 Playwright 运行 tests/browser/notifications.cjs。


实际验证（2026-10-20，北京时间）：
- 最终全量 Python 393 项通过，Node 31 项通过；通知相关 24 项通过。
- 隔离浏览器验证通知配置/继承/节点覆盖/敏感字段清空/历史轮询不破坏草稿/节点与配置深链接/移动端；另外节点续接和筛选合并浏览器验证通过，均使用临时数据库，不外发测试替身消息。
- 正式配置保存为工作室默认，私密文件均为 0600；SQLite 一致性备份后重启正式服务，项目/批次/需求/用户/本地账号行数保留。
- 真实 Webhook 测试通知 #1，一次发送，被飞书业务响应接受，状态 sent；不代表群成员已读。未补发历史。
- 正式本机与 LAN 地址 HTTP 200；未登录项目 API 401，初始负责人认领关闭。另一台同事设备的网络访问仍待实际确认。
- 服务当前为后台进程，未配置开机自启；HTTPS 部署工具仍沿用原契约。飞书应用读取与提单保持现有 CLI 授权，不将 Webhook 描述为应用 API 接通。
