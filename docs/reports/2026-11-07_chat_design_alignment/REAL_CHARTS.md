# 真实图表产物前端渲染验收

本次直接加载 `.omx/live-charts` 中已完成真实模型研究生成的 artifact JSON，使用当前 `ResearchArtifactView` 与真实 ECharts 实例渲染。页面为 1440×960 的独立产物验收容器；仅传入原始 artifact 和其实际 `source_refs` 对应的来源投影。未加载候选 terminal 正文，没有额外模型调用、生产请求或数值改写。

本报告保留该阶段的数值/区间渲染证据；后续来源去重、友好日期与自然文案以[结果、过程与图标验收](RESULT_PROCESS_ICONS.md)的最新复验为准。完整研究质量另见[本次响应与计算复验](../2026-11-07_natural_response_compute/README.md)，不能由本页图表通过推出全文通过。

## 最终图表

| 产物 | 实例核对 | 图表 / 数据与方法 |
| --- | --- | --- |
| AAPL 近一年日线 | 251 个点逐点一致，2025-11-07 至 2026-11-06；首末值 268.47 / 342.37，USD。 | [图表](real-chart-aapl.png) · [数据](real-chart-aapl-data.png) · [机器记录](real-chart-aapl.json) |
| NVDA / AMD 年初至今 | 215 个点、双序列逐点一致；基准 2025-12-31。末值分别为 0.07506702412867217 / 109.67501354127754，单位 %，没有再乘 100。 | [图表](real-chart-nvda-amd.png) · [数据与口径](real-chart-nvda-amd-data.png) · [机器记录](real-chart-nvda-amd.json) |
| SOXX 连续下跌区间 | 主图 1322 点逐点不变；9 个区间的 18 个端点均匹配真实 x 轴类目，像素坐标有效。6 小图分别为 6/8/7/6/6/6 个点，均包含前一期真实基准点和结束周。 | [最终图表](real-chart-soxx-rerender.png) · [真实悬停](real-chart-soxx-rerender-tooltip.png) · [数据与方法](real-chart-soxx-rerender-data.png) · [机器记录](real-chart-soxx-rerender.json) |

比较图的 `price_basis=unknown`、`dividends_included=null` 在方法区均显示“未注明”。本报告不将它们改述为未复权、已含或未含股息。没有附带计算代码的产物明确显示未附代码。

## SOXX 修复前后

原文件保留为 [before 图](real-chart-soxx-original.png) 与 [before 记录](real-chart-soxx-original.json)。旧输入的六个小图只有 4/6/5/4/4/4 个点，均缺结束周，也不含收益计算所需的前一期基准；前端没有补造缺点。

后端按同一份模型 spec 与既有真实数据确定性重新渲染：

`chart-live-3-7a3ce61cd7/chart-soxx-range-fixed.json`

SHA-256：`00d119dac35fe2fb3e8403c55ecdf3c3ed19e98552e68fb72736d41427a9cf0d`

| 区间 | 下跌周期 | 最终小图点数 | 首点：前一期基准 | 最后观测日 |
| --- | ---: | ---: | --- | --- |
| 1 | 5 | 6 | 2002-05-13 | 2002-06-17 |
| 2 | 7 | 8 | 2002-08-12 | 2002-09-30 |
| 3 | 6 | 7 | 2008-05-26 | 2008-07-07 |
| 4 | 5 | 6 | 2008-09-15 | 2008-10-20 |
| 5 | 5 | 6 | 2018-09-17 | 2018-10-22 |
| 6 | 5 | 6 | 2020-02-10 | 2020-03-16 |

逐个检查了小图第一行与主数据中下跌开始前一行完全相同，而非将首点人工设为 0 或 100。小图使用各自的线性纵轴并标注“各区间独立纵轴”“含前一期基准”，主图保持对数轴。首末日期刻度明确显示，不再因自动抽样隐藏结束周。

## 前端修复与验证

- 日期边界按整日包含，并转换成实际类目字符串；包含时间的边界保持盘中精度。原始 `rows` 与 artifact 文件内容不变。
- 主图用区间 1–9 短编号，标签错开；完整起止、周数与跌幅进入对应列表及悬停提示。实际鼠标悬停后从 Canvas 显示内容验证了“区间9 · 5周 -30.4% 进行中”，验证了实际行为。
- 原来的 ECharts 全局 axis tooltip 会覆盖 markArea 的单项 tooltip；已由应用自有 formatter 将所属区间说明附到价格提示，模型自带 formatter 仍不执行。
- 数据表把 source/provider/as_of 与序列字段映射为可读标签；百分比、价格及其他数值使用原值。来源、方法及可见数据中不再出现 `twelve_data`、`market_chart`、`get_stock*` 等内部标识。
- 13 项相关单测通过。3 份原始产物完成真实实例渲染验收，SOXX 修复产物完成独立复验；所有实际系列数据均与输入逐点比较，文件 SHA 在验收前后不变。
- 仅表格预览沿用前 200 行的可见上限，并明确说明下载包含完整数据；图表与下载均使用全部原始行。

重现入口：`frontend/e2e/real-chart-artifacts.spec.ts`。SOXX 修复文件通过 `FINSIGHT_RENDER_SOXX_ARTIFACT` 指定，未指定时仍检查原始 before 文件。当前验收未提交 Git，构建部署由主代理统一执行。

## Fresh AAPL 收盘价与 MA20

新成功产物来自 `fresh/acceptance-natural-1f4f06023d-2/chart_c6c33cc93acfc677.json`，取代之前没有出图的 SMA 失败例作为当前图形证据；旧失败仍保留在 before，不改判其当时结果。

- [图表](real-chart-fresh-aapl-ma20.png) · [数据与原计算代码](real-chart-fresh-aapl-ma20-data.png) · [逐点复算与 Source proof](real-chart-fresh-aapl-ma20.json)
- SHA-256：`aba688ddee0bd1bee777ddcad6a1fd4dfbd1119f2501f0264f440dc8ad811e33`，验收前后未变。
- 2026-10-06 至 2026-11-06，共 24 行、收盘价和 MA20 双序列，ECharts 每点与 artifact 完全相同；两条 coverage 均为 valid=24、missing=0、leading_missing=0。
- 另从该任务的 65 行真实历史数据逐点重算 20 日均值。原 Python 代码将写图的全部数值保留两位小数，独立复核按此声明精度检查；未舍入末值约 343.3844995，图内 MA20 末值为 343.38，不能把图内精度说成 343.3845。
- 真实历史已提供均线预热，显示窗口的第一个 MA20 点就有效；不能对该图再说“前19点缺失”。
- 来源去重为 1 个 Twelve Data 数据来源，显示日期 2026-11-06；计算方法不计额外来源。只加载图和 datasets 的来源/历史数据，不加载 terminal 长正文，没有新增模型或生产调用。

该项真实渲染复验通过；它证明图表和数学输入的一致性，不替代旁支语言或其他 after 问题的完整性验收。

## 最终 S3 涨跌幅比较图

当前最终 S3 产物为 `final-s3/acceptance-natural-e2e58933cf-6/chart_a4bfb4bb672a4c16.json`，SHA-256：`629faa7babadb8661b0cbc7de88bc6a762e4ee041ff859397d257bc61703d849`。

- [图表](real-chart-final-nvda-amd.png) · [数据与方法](real-chart-final-nvda-amd-data.png) · [实例数值/交叉统计/Source proof](real-chart-final-nvda-amd.json)
- 215点双序列逐点等于原 artifact，单位为 %，末值 NVDA=0.07506702412867217、AMD=109.67501354127754，没有重复乘100，原文件SHA不变。
- 从原序列独立检查领先方变化，与 `comparison_stats.crossovers` 一致：4次，日期2026-01-06、01-13、02-05、03-19；初始共同基准的首次分离不计，未使用旧5次统计补图。
- 图保持原spec的两条价格涨跌曲线，没有人工增加交叉标记。数据来源去重为1个Twelve Data，日期友好显示2026-11-06。
- 只读取新图与同目录datasets来源/统计，没有加载候选terminal长文，没有新增模型或生产请求。

该真实渲染用例通过。最终八题核心结果与250秒harness/生产180秒预算的区别，见[核心验收与限制](../2026-11-07_natural_response_compute/README.md)。
