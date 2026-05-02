# Dashboard P0 数据来源追踪规范

更新时间：2026-02-17

## 1. 目标

Dashboard 每个关键数据块都必须满足：

1. 可追溯来源（provider/source_type）
2. 可追溯时效（as_of + stale 分级）
3. 可追溯回退（fallback_used + fallback_reason）
4. 可追溯计算口径（calc_window + currency + confidence）

---

## 2. 后端契约

`GET /api/dashboard` 的 `data.meta` 字段：

```json
{
  "snapshot": {
    "provider": "yfinance",
    "source_type": "snapshot",
    "as_of": "2026-02-17T12:34:56+00:00",
    "latency_ms": 210,
    "fallback_used": false,
    "confidence": 0.85,
    "currency": "USD",
    "calc_window": "",
    "fallback_reason": null
  }
}
```

字段定义：

- `provider`: 实际数据提供方或聚合层
- `source_type`: 数据类型（snapshot/timeseries/fundamental/news/cache 等）
- `as_of`: 数据时间戳（ISO8601）
- `latency_ms`: 请求/处理时延（毫秒）
- `fallback_used`: 是否发生降级
- `confidence`: 当前结果可信度（0~1）
- `currency`: 币种（可空）
- `calc_window`: 统计口径（可空）
- `fallback_reason`: 降级原因（可空）

---

## 3. 当前覆盖范围

已接入 `meta` 的块：

- `snapshot`
- `market_chart`
- `revenue_trend`
- `segment_mix`
- `sector_weights`
- `top_constituents`
- `holdings`
- `news_market`
- `news_impact`
- `valuation`
- `financials`
- `technicals`
- `peers`

---

## 4. 前端展示规范

入口组件：`frontend/src/components/dashboard/DataSourceTrace.tsx`

展示规则：

1. 顶部按钮统一打开“数据来源抽屉”
2. 抽屉列表展示每个数据块的来源、更新时间、延迟、口径、置信度、币种
3. `fallback_used=true` 时，显示 `fallback_reason`
4. stale 分级显示：
   - `正常`
   - `偏旧`
   - `陈旧`

---

## 5. 验收（P0-6）

上线前人工验收清单：

1. 随机抽查 6 个块：`snapshot/market_chart/valuation/financials/technicals/news_market`
2. 核对数值与来源一致
3. 人工制造上游失败，确认降级原因可见
4. 手工修改 `as_of` 为过期时间，确认 stale 颜色分级正确

