# 2025-12-08 DeepSearch 子 Agent & KV 缓存

- 时间：2025-12-08（本地时区）
- 内容：
  - 新增 `deepsearch_news`：Tavily + DuckDuckGo + 搜索聚合，高召回新闻，包含 Markdown 链接，返回 as_of/source/text。
  - ChatHandler 新闻查询优先查 KV（key=`deepsearch:news:{ticker}`），未命中则触发 DeepSearch 聚合，失败再回退原有新闻工具；成功写入 orchestrator DataCache（data_type=news）。
  - LLM 提示词调整：新闻类依旧二次改写，但要求摘要后列出链接列表，保留可点击 URL。
  - 计划文档标注启动 DeepSearch/KV 阶段。
- 验证：本地手动查询 “特斯拉最新新闻” 在限流情况下返回聚合结果（含链接）；未跑自动化测试。***
