# 2025-12-08 DeepSearch KV 二阶段（数据不足回退 & LLM 链接保留）

- 时间：2025-12-08（本地时区）
- 内容：
  - ChatHandler 新闻查询：先查 KV（`deepsearch:news:{ticker}`），未命中触发 DeepSearch 聚合；失败再回退旧新闻工具；保持 LLM 改写，但摘要后要求列出链接。
  - DeepSearch 高召回：Tavily + DuckDuckGo + 搜索聚合，统一返回 as_of/source/text，并附标准外链。
  - 前端链接样式：Markdown 链接高亮蓝色、可点击。
- 测试：`pytest backend/tests/test_validator.py::test_news_validation`（通过，含 PytestReturnNotNoneWarning 来自测试本身）；手动查询“特斯拉最新新闻”验证聚合输出含链接。
