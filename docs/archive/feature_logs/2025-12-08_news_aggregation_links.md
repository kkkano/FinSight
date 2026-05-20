# 2025-12-08 新闻聚合与链接可点击改动

- 时间：2025-12-08（本地时区）
- 内容：
  - 新闻获取改为“全源收集后汇总”，依次收集 yfinance/Finnhub/Alpha Vantage/Tavily/DuckDuckGo/搜索兜底，再统一输出，附标准外链（Yahoo/Google News/Reuters）。
  - 前端消息 Markdown 链接样式调整为蓝色可点击，新窗口打开，避免链接被渲染成纯文本。
  - 保留 LLM 二次改写，但提示词要求保留所有链接，先摘要后“链接”小节。
- 验证：手动在本地 `uvicorn` 运行下，询问“特斯拉最新新闻”验证返回包含链接（若上游源限流仍有标准外链可用）。
- 后续：准备进入 sub-agent/DeepSearch 前，确保 scheduler 开关按需配置。***
