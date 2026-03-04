# -*- coding: utf-8 -*-
"""
Dashboard Data v2 契约定义 — 前后端共同遵守。

修改此文件前须协商前后端同时更新。

字段说明:
  - snapshot:    SnapshotData | None (v1, 核心行情快照)
  - charts:      dict | None         (v1, K线/MA 图表数据)
  - news:        dict | None         (v1, 新闻列表)
  - valuation:   ValuationData | None          (v2 新增, 估值指标)
  - financials:  FinancialStatement | None     (v2 新增, 财务报表)
  - technicals:  TechnicalData | None          (v2 新增, 技术指标)
  - peers:       PeerComparisonData | None     (v2 新增, 同行对比)

所有 v2 新增字段为 None 时, 必须附带对应的 *_fallback_reason 字段,
前端据此统一展示降级提示。

前端对 None 字段统一显示 '--' 或 DataFallback 组件。

性能预算表:
┌──────────────┬─────────┬───────────┬──────────┬───────────────────┐
│ 数据源       │ 超时(s) │ 缓存 TTL  │ 并行上限 │ fallback          │
├──────────────┼─────────┼───────────┼──────────┼───────────────────┤
│ snapshot     │ 5       │ 30s       │ 1        │ 返回 None         │
│ market_chart │ 8       │ 60s       │ 1        │ 返回空 charts     │
│ valuation    │ 5       │ 300s(5m)  │ 1        │ 返回 None         │
│ financials   │ 8       │ 3600s(1h) │ 1        │ 返回 None         │
│ technicals   │ 5       │ 60s       │ 1        │ 返回 None         │
│ news         │ 8       │ 300s(5m)  │ 2(双源)  │ 返回空列表        │
│ peers        │ 10      │ 3600s(1h) │ 3(批量)  │ 返回 None         │
└──────────────┴─────────┴───────────┴──────────┴───────────────────┘
"""

from backend.contracts import DASHBOARD_DATA_SCHEMA_VERSION

DASHBOARD_CONTRACT_VERSION = DASHBOARD_DATA_SCHEMA_VERSION

# Timeout defaults (seconds)
SNAPSHOT_TIMEOUT = 5
MARKET_CHART_TIMEOUT = 8
VALUATION_TIMEOUT = 5
FINANCIALS_TIMEOUT = 8
TECHNICALS_TIMEOUT = 5
NEWS_TIMEOUT = 8
PEERS_TIMEOUT = 8

# Cache TTL defaults (seconds)
SNAPSHOT_CACHE_TTL = 30
MARKET_CHART_CACHE_TTL = 60
VALUATION_CACHE_TTL = 300
FINANCIALS_CACHE_TTL = 3600
TECHNICALS_CACHE_TTL = 60
NEWS_CACHE_TTL = 300
PEERS_CACHE_TTL = 3600


__all__ = [
    "DASHBOARD_CONTRACT_VERSION",
    "SNAPSHOT_TIMEOUT",
    "MARKET_CHART_TIMEOUT",
    "VALUATION_TIMEOUT",
    "FINANCIALS_TIMEOUT",
    "TECHNICALS_TIMEOUT",
    "NEWS_TIMEOUT",
    "PEERS_TIMEOUT",
    "SNAPSHOT_CACHE_TTL",
    "MARKET_CHART_CACHE_TTL",
    "VALUATION_CACHE_TTL",
    "FINANCIALS_CACHE_TTL",
    "TECHNICALS_CACHE_TTL",
    "NEWS_CACHE_TTL",
    "PEERS_CACHE_TTL",
]
