# Dashboard 六标签数据来源盘点

> 盘点日期：2026-07-12。事实源以当前代码和 `/api/dashboard`、`/api/dashboard/insights` 响应为准。

## 公共链路

- 页面入口：`frontend/src/pages/Dashboard.tsx`。
- 六标签容器：`frontend/src/components/dashboard/DashboardTabs.tsx`。
- 主数据：`useDashboardData(symbol)` → `GET /api/dashboard?symbol=...` → `backend/api/dashboard_router.py:get_dashboard` → `backend/dashboard/data_service.py` / `peer_service.py`。
- 快速洞察：`useDashboardInsights(symbol)` → `GET /api/dashboard/insights` → `backend/dashboard/insights_engine.py` → 五个 scorer；scorer 只消费已经获取的真实 Dashboard 数据，LLM/规则只生成评分与解释，不生成行情序列。
- 深度研究补充：`useLatestReport` → report index/replay API；属于已归档报告证据，不覆盖 `/api/dashboard` 的真实行情与财务数据。
- 来源展示：数据卡/图表读取 `DashboardData.meta[metaKey]`，由 `DashboardSourceBadge` 展示 provider、`as_of` 与 fallback 警告；多来源派生卡使用 `DashboardSourceBadges`。

## 逐标签审计

| tab | 数据与前端组件 | 真实来源 / 后端服务 | 降级路径 | 标注状态 |
|---|---|---|---|---|
| Overview | `StockHeader`、`MiniPriceChart`、`ScoreRing`、`FearGreedGauge`、`KeyInsightsCard`、`AnalystRatingCard`、`DimensionRadar`、`RiskMetricsCard`、`HighlightsCard`、新闻/同行摘要、分析师目标价 | `snapshot`/`market_chart`：行情管线；`valuation`：基本面管线；`technicals`：真实 OHLCV 确定性计算；`macro_snapshot`：CNN Fear & Greed 文本 + FRED；`news_market`：公司/市场新闻工具；`peers`：peer service；`analyst_targets`/`recommendations`：yfinance | OHLCV：yfinance → Stooq → 共享 price pipeline；估值：yfinance → Finnhub → CN/HK 行情工具；宏观允许 partial/unavailable；新闻/同行失败返回空态并在 meta 标 fallback | 已标：每张真实数据卡/图表显示对应一个或多个来源徽标；派生卡明确列出其输入来源 |
| Financial | `IncomeTable`、`ProfitabilityChart`、`ValuationGrid`、`EarningsSurpriseChart`、`AnalystTargetCard`、`BalanceSheetSummary` | `financials`：yfinance 季报；`valuation`：yfinance 基本面；`earnings_history`、`analyst_targets`、`recommendations`：yfinance | 财务报表：yfinance → CN/HK 财务工具（适用时）→ SEC companyfacts → Finnhub；估值：yfinance → Finnhub → CN/HK；G2 数据失败进入短 TTL failure cache，不伪造 | 已标：包括空态；目标价卡同时列出目标价与评级两个 meta |
| Technical | `SupportResistanceChart`、`TechnicalSummaryCard`、`MovingAverageTable`、`OscillatorTable`、`TechnicalSubCharts`、`BollingerVolumeCard` | `market_chart`：真实 OHLCV；`technicals` / `indicator_series`：在真实 OHLCV 上由 `backend.tools.technical` 确定性计算 | OHLCV：yfinance → Stooq → 共享 price pipeline；缺数据时显示空态和 degraded meta，不使用模型数组 | 已标：K 线、指标表、RSI/MACD 子图与派生技术卡全部展示来源 |
| News | `NewsSentimentOverview`、`SentimentStatsBar`、`NewsCard`、`AiInsightCard` | `fetch_news` 并行调用 `get_company_news`、`get_market_news_headlines`，再按时效、信源可靠度、影响与资产相关性确定性排序；单条新闻保留原 publisher/时间 | 任一新闻工具失败时另一侧仍可返回；整体失败返回空列表、短期重试；客户端情绪聚合明确写为基于 Dashboard 新闻列表 | 已标：聚合卡/图、催化时间线与每条新闻均显示来源和时间 |
| Research | `ResearchOverviewBar`、`ResearchInsightGrid`、`ResearchMetadata`、报告摘要/发现/冲突/引用 | 快速评分来自 `/api/dashboard/insights`，输入为 financials/valuation/technicals/news/peers；深度内容来自受鉴权 report index/replay 与 citations | scorer 超时使用同一真实输入的确定性 fallback card；报告不存在时不跨 ticker 取无关报告，页面显示空态 | 已标：快速评分统一披露“AI/规则评分 · 基于 n 项真实指标 · 置信度”；报告区继续展示引用数、证据质量和报告元数据 |
| Peers | `PeerScoreGrid`、`ValuationBarChart`、`RevenueGrowthChart`、`PeerComparisonTable`、`AiInsightCard` | `peer_service`：yfinance 行业/板块定位，FMP 同行业筛选；逐票指标优先 yfinance，并有 Finnhub、CN/HK 工具路径 | 行业解析失败使用受控 sector/default peer map；单票源失败走 Finnhub 或 CN/HK；无有效指标则空态，不补假数据 | 已标：每张 peer score 卡、两张图和详细表均显示 `peers` meta |

## 本次校准

1. 后端为 `earnings_history`、`analyst_targets`、`recommendations`、`indicator_series` 补齐 meta；缓存命中、failure cache、实时成功和失败均保留 source type、时间与降级原因。
2. `AiInsightCard`、Research 总览与 Research 分卡统一从响应的 `key_metrics`、`score_breakdown` 或 `sub_scores` 计算 `n`，不拿摘要/要点条数冒充真实指标数。
3. 卡片只展示数据来源，不改变既有取数与评分逻辑；真实序列仍只来自行情/财务服务，AI 只解释这些输入。
