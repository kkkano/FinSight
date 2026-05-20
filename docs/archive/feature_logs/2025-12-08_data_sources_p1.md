# Feature Log - 数据源可靠性增强（P1）- 时间：2025-12-08 00:19:30
- 负责人：Codex

## 背景 / 范围
- 启动 P1「更可靠的数据源与源健康」：在价格与 K 线链路中增加低成本/免费兜底源，减少限流导致的空返回，并让 Orchestrator 能统计新源健康。

## 实施内容
1) 价格多源  
   - 新增 `_fetch_with_twelve_data_price`，纳入 `get_stock_price` 策略顺序：Alpha Vantage → Finnhub → yfinance → Twelve Data → 网页抓取 → Stooq → 搜索。  
   - Orchestrator / tools_bridge 注册 `twelve_data` 源（带速率权重），健康面板可见调用统计。
2) K 线多源  
   - 新增 `_fetch_with_twelve_data` 使用 `time_series`(1day)，依据 period 选择 outputsize，返回 `source`/`as_of`，回退顺序置于 Tiingo 之后、Marketstack 之前。  
   - 统一策略文档/异常分支编号，保持 Stooq 兜底。  
3) 测试  
   - `python -m pytest backend/tests/test_orchestrator_metadata.py backend/tests/test_langgraph_selfcheck.py`  
   - `python -m pytest backend/tests/test_kline.py -q`  
   - 结果：均通过（`test_kline` 既有 PytestReturnNotNoneWarning 仍保留）。

## 影响 / 下一步
- 价格/K 线回退链条更长，覆盖 Twelve Data 免费额度，Orchestrator 健康统计包含新源。  
- 下一步：监控 Twelve Data 失败率与额度消耗；按 P1 计划评估 IEX/Tiingo 的动态优先级与熔断恢复策略。
