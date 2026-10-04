# Report 与 Chart 合同

更新时间：2026-10-04　前端基线：ECharts 6

FinSight 支持两类图表：报告 `ReportIR` 中的结构化 chart，以及对话 Markdown 中的 `<chart>` / `<chart_ref>`。优先使用真实数据引用，避免 LLM 重写数值。

## 报告与研究结果

报告消费唯一 `research_result` 中的任务结果、事实、受支持 Claim、引用和缺口。renderer 展示已确定的主体/维度，不重新选择意图，也不另生成竞争正文。

质量由 `evaluate_result_quality` 统一合并为 `pass/warn/block`，已有阻断不可被报告构建覆盖。完整报告必须有规范化受支持论据并满足必需维度；facts-only 或缺口结果可以返回 `blocked_report` 预览，但不能进入报告索引、分享或最终缓存。内部 conflict ID 留在诊断数据，正文说明实际冲突的指标和期限。

`done`、`publishable`、`archived`、`persistence_status` 各有独立含义。正文生成后须保存服务器终态与助手消息，报告归档失败或会话保存失败均保留预览并明确提示。刷新恢复按 run/message ID 读取权威内容，不能依赖浏览器最后一次快照。

缺总体判断时 `report_quality.conclusion_status=unavailable`、`sentiment=unknown`、`confidence_score=null`。不把未知写成中性，重验和历史回放不补默认 0.5/0.7。没有校准依据的方向、证据、来源置信度不显示百分比；前端展示可追溯来源数量和实际缺项。有依据的 neutral 仍可显示为中性，partial 保留有效正文与证据。

卡片、全屏与历史只读页共用 `ReportPresentation`；未完成项在正文前说明，来源及执行详情默认收起。纯展示派生不改写服务器 canonical 正文。

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

价格语义是强约束：`line_price`、K 线/量价等价格图，以及标题、series 名或精确币种单位明确表示“股价/收盘价/价格走势”的普通 `line`，前端必须改走真实 K 线接口，不能消费 `<chart>` 内的模型数组。价格线展示收盘价，不得把累计收益率伪装成金额；收益率图必须明确使用 `%` 单位。

引用对象至少包含可解析的资源/series 标识、图表类型、标题和单位。找不到引用时显示明确错误/降级文本，不用示例数据顶替。

## 安全与质量

- `citation_refs` 必须指向报告 citations 中存在的 source id。
- 所有时间序列标明时区/as-of、币种、单位和复权口径（适用时）。
- 财务序列保留实际财期、单季/累计频率与指标定义；不能把非日历财年改成日历季末，也不能混画季度与年度值而不说明。
- 多标的图表逐项核对发行人和证据绑定；官方 URL 不等于已核验属于目标公司。
- 前端不得执行任意函数、HTML 或由模型提供的 JavaScript；只接受数据型 ECharts option。
- 限制点数、series 数和字符串长度；超大数据在后端抽样/聚合。
- 缺失值使用 `null`，不要用 0 冒充。
- 图表说明不得与 series 数值或引用证据冲突。
- tooltip 与坐标轴必须按币种/百分比格式化并限制小数位，不显示二进制浮点长尾。
- 客户端异步注入的图表标记不属于服务器权威正文，不能通过整份会话快照覆盖已保存回复；需要刷新可恢复的图表应使用服务器 artifact 或明确的持久视图数据。

修改合同必须同步后端 ReportIR/schema、前端 SmartChart/报告渲染、OpenAPI/TypeScript 类型和单测。
