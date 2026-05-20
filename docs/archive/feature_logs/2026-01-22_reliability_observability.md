# 2026-01-22 可靠性与可观测性补强

- 论坛冲突检测：ForumHost 显式标注冲突并下调置信度
- 反思循环：BaseFinancialAgent 引入 LLM gap detection + 定向补检
- SSRF 防护：统一到 DeepSearch + `fetch_url_content`
- HTTP 连接池：工具层统一 Session + Retry
- 缓存策略：TTL 抖动 + 负缓存，降低雪崩/穿透
- 熔断分源：支持按源配置 failure/recovery 阈值
- Trace 规范化：统一输出结构，便于前端分层展开
- Prometheus 指标：新增 `/metrics` 入口（可选依赖）
- pytest 路径：收集 `backend/tests` + `test/`
