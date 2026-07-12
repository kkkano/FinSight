# Report 与 Chart 合同

更新时间：2026-07-12　前端基线：ECharts 6

FinSight 支持两类图表：报告 `ReportIR` 中的结构化 chart，以及对话 Markdown 中的 `<chart>` / `<chart_ref>`。优先使用真实数据引用，避免 LLM 重写数值。

## ReportIR chart

```json
{
  "type": "chart",
  "content": {
    "option": {
      "xAxis": {"type": "category", "data": ["2023", "2024"]},
      "yAxis": {"type": "value"},
      "series": [{"type": "line", "name": "Revenue", "data": [100, 120]}]
    }
  },
  "metadata": {"chart_type": "line", "title": "Revenue", "unit": "USD bn", "as_of": "2024-12-31"},
  "citation_refs": ["SRC-1"]
}
```

也兼容 `labels + values`、`labels + datasets` 或直接 `xAxis/yAxis/series`，前端会补成 ECharts option。

## 对话标签

- `<chart>`：小型内联数据；必须来自本轮证据，不允许模型编造。
- `<chart_ref>`：引用后端真实数据或已生成 artifact；推荐用于行情、财务和回测。

引用对象至少包含可解析的资源/series 标识、图表类型、标题和单位。找不到引用时显示明确错误/降级文本，不用示例数据顶替。

## 安全与质量

- `citation_refs` 必须指向报告 citations 中存在的 source id。
- 所有时间序列标明时区/as-of、币种、单位和复权口径（适用时）。
- 前端不得执行任意函数、HTML 或由模型提供的 JavaScript；只接受数据型 ECharts option。
- 限制点数、series 数和字符串长度；超大数据在后端抽样/聚合。
- 缺失值使用 `null`，不要用 0 冒充。
- 图表说明不得与 series 数值或引用证据冲突。

修改合同必须同步后端 ReportIR/schema、前端 SmartChart/报告渲染、OpenAPI/TypeScript 类型和单测。
