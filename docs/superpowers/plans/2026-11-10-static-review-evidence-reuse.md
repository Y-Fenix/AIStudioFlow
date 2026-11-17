# 静态审查证据复用实施计划

**Goal:** 在不共享结论和不放宽证据门禁的前提下减少跨用例重复源码探索。

**Architecture:** 测试部门纯函数定义关联键及请求压缩；源码目录维护执行期证据池；线程池依关联键调度。平台数据字段、权限和模型协议的结论结构保持。

**Tech Stack:** Python 标准库、unittest，现有三路线程池。

1. 在 `tests/test_QA_shared_evidence.py`、`tests/test_QA_review_concurrency.py` 写精确测试点复用、缺失关联、源码变化、同组调度和独立断言测试；运行确认预期失败。
2. 新建 `departments/testing/QA_review_context.py`，实现 `QA_evidence_keys(case)`、`QA_primary_affinity(case)`、`QA_compact_source_search(requests, sources)`；仅依赖标准库。
3. 修改 `server/static_review.py` 的证据发布和种子获取，按关联键合并原文、限制总量，读取时验证哈希；请求时只压缩已在 sources 中逐字存在的搜索文本，保留 trace；检查点纳入策略版本。
4. 修改 `departments/testing/QA_review_pool.py` 增加可选 affinity 回调，同键串行、不同键并行、输出原顺序。集成现有取消、错误退出行为，测试默认调度兼容。
5. 跑针对性测试与部门规定的 Python/JS 回归和边界检查。用已有证据检查精确测试点可复用范围；不启动模型或改现有任务。
6. 更新测试部门 README 和验证记录，明确部署需后台重新加载、当前运行不会热更新、真实速度待用户试跑。不拉取、提交或推送 Git。
