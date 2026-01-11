# ReportIR Chart 输出规范

> 更新日期: 2026-01-11

本规范用于约定 ReportIR 中 `ReportContent.type === "chart"` 的输出结构，确保前后端一致渲染。

---

## 1. 推荐格式（ECharts option 直通）

后端直接输出 ECharts 的 `option`，前端将优先使用该字段。

```json
{
  "type": "chart",
  "content": {
    "option": {
      "title": { "text": "Revenue Growth" },
      "tooltip": { "trigger": "axis" },
      "xAxis": { "type": "category", "data": ["2021", "2022", "2023"] },
      "yAxis": { "type": "value" },
      "series": [
        { "type": "line", "data": [120, 150, 190], "smooth": true }
      ]
    }
  },
  "metadata": {
    "chart_type": "line",
    "title": "Revenue Growth",
    "unit": "USD (M)"
  },
  "citation_refs": ["SRC-1", "SRC-2"]
}
```

---

## 2. 可接受的简化格式（前端自动补全）

前端支持以下轻量结构并自动转换为 ECharts `option`。

### 2.1 单序列 labels/values

```json
{
  "type": "chart",
  "content": {
    "chart_type": "bar",
    "labels": ["Q1", "Q2", "Q3", "Q4"],
    "values": [12, 18, 15, 21]
  },
  "metadata": {
    "title": "Quarterly EPS",
    "unit": "USD"
  }
}
```

### 2.2 多序列 datasets

```json
{
  "type": "chart",
  "content": {
    "labels": ["2022", "2023", "2024"],
    "datasets": [
      { "label": "Apple", "data": [100, 120, 140] },
      { "label": "Microsoft", "data": [90, 110, 135] }
    ],
    "chart_type": "line"
  },
  "metadata": {
    "title": "Revenue Comparison",
    "unit": "USD (B)"
  }
}
```

### 2.3 直接 series/xAxis/yAxis

```json
{
  "type": "chart",
  "content": {
    "tooltip": { "trigger": "axis" },
    "xAxis": { "type": "category", "data": ["Jan", "Feb", "Mar"] },
    "yAxis": { "type": "value" },
    "series": [{ "type": "line", "data": [1, 3, 2] }]
  }
}
```

---

## 3. 字段约定

- `content` 支持对象或 JSON 字符串，前端会尝试解析字符串。
- `metadata.chart_type` 优先级高于 `content.chart_type`，推荐值：`line`/`bar`/`pie`。
- `metadata.title` / `metadata.unit` / `metadata.source` 用于 UI 提示，不影响渲染。
- `citation_refs` 指向 `report.citations` 的 `source_id` 列表。

---

## 4. 兼容性与性能

- 前端使用 `echarts-for-react` 渲染，若 `option` 缺失但存在 `labels/values` 或 `datasets`，会自动补全。
- 数据量过大时建议抽样或压缩，以避免渲染卡顿。
