# 工作流交互改造验收

日期：2026-10-22。用户确认独立交互稿后，将其接入正式自定义工作流。正式入口为 http://127.0.0.1:8766/；8767 仍为独立原型。

## 实现范围

- 保留 ATELIER，调整公共外壳的信息层级、蓝色主操作、键盘焦点及减少动态效果；兼容现有三主题。
- 自定义工作流使用吸顶节点条、箭头、选中背景、配置/结果页签和右侧准备清单、操作日志；吸顶背景跟随主题，右栏高度跟随主区和视口。
- 节点输入、Skill 草稿和来源展开状态按流程节点独立保留。草稿为浏览器内存，不承诺刷新后恢复；保存后才用于运行。未保存配置会阻止启动工作流。
- 飞书/文档链接和本地文字文件可分别展开。链接只记录来源，不在此入口读取正文；TXT/Markdown 读取成功后加入草稿，保存后生效。
- 复用真实 Skill 列表、权限与版本校验，公共选择器以右侧抽屉展示，支持搜索、选择保存、ESC、遮罩关闭和焦点返回。
- 主操作跟随真实运行步骤变化。保存和人工确认提交显示处理中，拦截重复请求，失败保留输入并允许重试。
- 运行快照保持只读，不改人工审核、测试证据、版本及服务端权限门禁。部门专用工作台未被通用页面替换。

## 实际验证

- `node --test tests/*.test.js`：70 项通过。
- `python3 -m unittest tests.test_custom_workflows tests.test_node_builder -q`：47 项通过。
- `node tests/browser/interaction-refresh.cjs`：真实本地 HTTP/SQLite/Chrome 验证独立节点草稿、来源独立展开、文字文件输入、保存失败恢复、延迟保存反馈及重复点击、Skill 抽屉真实选择保存、ESC/遮罩/焦点、键盘页签、冻结配置、人工审核与手动继续、三主题吸顶、375/768/1024/1512px 无水平溢出。
- `node tests/browser/custom-workflows.cjs`：101 个流程、搜索分页及返回、流程节点、输入与 Skill、手动门禁、编辑器、历史快照、深链和窄屏通过。更新旧视觉断言以匹配已确认的流程标题及 Skill 工具栏位置。
- `node tests/browser/skill-picker.cjs`：六个测试节点、共享部门 Skill 选择、真实保存、默认规则、目标隔离、冲突、ESC/遮罩及窄屏通过。
- `node tests/browser/node-builder.cjs`：拖放、配置保存、模板跨项目复用、清单草稿、人工交付、待审发布、跨部门流程、快照深链及窄屏通过。模板发布断言等待真实完成反馈后再读取，避免将异步提交误判为失败。
- `node --check web/workflow-pages.js`、`node --check web/node-builder.js` 通过；测试部门静态边界检查通过。
- 正式服务首页 HTTP 返回 200。截图存于 `/tmp/studioflow-interaction-production-desktop.png`、`/tmp/studioflow-interaction-production-mobile.png`、`/tmp/studioflow-interaction-production-review.png`，内容来自隔离验收项目。

## 保留的问题

额外运行 `tests/browser/department-module-workflow.cjs`：部门模块交互、公共保存、Skill 不变、手工交付提示、清理和迟到回调拒绝通过；后续部门首页几何断言失败。六个测试节点实测为 165×211px，四个部门卡片为 240×196px，脚本要求两者完全相等。临时拦截本轮 `interaction-refresh.css` 返回空样式后，同一断言仍以相同尺寸失败，确认不由本轮公共样式引入。保留原断言与布局，此项未修复，不能声称所有浏览器套件通过。

## 能力边界

浏览器验收使用隔离数据库和人工节点；保存失败通过明确的 HTTP 故障注入验证。没有调用真实模型或发送飞书消息，不将这些交互测试描述为业务执行质量验收。本轮不改登录、数据库或执行协议，不执行 Git 操作，不修改 Figma。
