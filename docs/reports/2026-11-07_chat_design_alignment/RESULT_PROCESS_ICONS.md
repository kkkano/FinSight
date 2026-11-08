# 结果、过程与图标验收

这里保留两类独立证据：前端事件 fixture 的交互验收，以及既有真实模型图表的数值渲染验收。前者不代表真实后端研究通过；后者也不代表原会话的文字结论正确。本次没有调用模型或生产接口。

## 前端事件 fixture

入口：`frontend/e2e/result-process-icons.spec.ts`。按实际 SSE 字段结构走发送、事件解析、store 和当前组件，包含 progress、被清空的旧候选、最终 answer、5 次工具调用、子研究员、一个工具失败和图表。

| 视口 | 截图 | 完整事件与 Source proof |
| --- | --- | --- |
| 1440×960 亮色 | [截图](result-process-icons-light.png) | [记录](result-process-icons-light.json) |
| 1440×960 深色 | [截图](result-process-icons-dark.png) | [记录](result-process-icons-dark.json) |
| 390×960 窄屏 | [截图](result-process-icons-narrow.png) | [记录](result-process-icons-narrow.json) |

验收结果：

- 最终回答在 DOM 中只有一份，存储的 `content` 与最终 answer 完全相同。progress 不混入其中，删除的候选不生成“已撤回”占位。
- progress 为 13px、弱色、1px 左分隔线；正式回答为 14px、较强文字色。亮暗主题均验证实际 computed style。
- 思考入口为“思考过程”，无“本次供应商”“思考供应商”等固定话术。
- 工具动作名称在窄屏不被截断；子研究员可展开查看具体读取步骤。
- 新闻工具失败有红色错误图标、原始超时原因，没有成功勾；整体显示“已完成，部分信息待确认”，未把缺失信息当作齐全结果。
- 从真实 ECharts 实例读取的样例数值仍为 `[100, 104, 103]`，artifact 对象不变。最终引用、来源 URL 与 `evidence_pool` 一致。

| 动作 | 图标 | 亮色实际值 | 深色实际值 |
| --- | --- | --- | --- |
| 获取行情 | TrendingUp / amber | rgb(168,84,0) | rgb(242,167,75) |
| 分析数据 | Calculator / violet | rgb(103,65,217) | rgb(173,145,255) |
| 绘制图表 | ChartNoAxesCombined / teal | rgb(11,110,127) | rgb(76,201,216) |
| 基本面分析师 | Users / accent | rgb(59,91,219) | rgb(128,152,255) |

逐图检查发现窄屏图表标题被操作按钮挤成每行几字。唯一产品修改是让 639px 及以下图表标题占整行；已补标题宽度断言并复验。三种视口均通过，未改业务逻辑、数据或图标定义。

## 真实模型产物核对

只加载 `withdrawal_repair` 提供的 case6 图表及同目录 `datasets.json` 的 sources 投影：

`acceptance-natural-9e7eb3eff2-6-retry-34ae/chart_1f82f920da2e5fc3.json`

SHA-256：`fd845dc701fa83644480089a38f584c9805c5d7088a605f4465fe0971c7ab6c4`

- [真实图表截图](real-chart-natural-nvda-amd.png)
- [数据与方法截图](real-chart-natural-nvda-amd-data.png)
- [数值记录和 Source proof](real-chart-natural-nvda-amd.json)

215 个点、两条序列逐点与输入相同，基准日期 2025-12-31，结束日期 2026-11-06。轴和数据表单位均为 %，没有额外乘 100；末值 NVDA 为 0.07506702412867217，AMD 为 109.67501354127754。原文件 SHA 在渲染前后不变，5 个 source_id 均来自该图实际关联来源。价格复权与股息处理继续显示“未注明”。

后续来源/日期显示修复经 17 项聚焦及该真实 artifact 的单项浏览器复验：5 个原始引用保留为审计证据，UI 排除取数包装和衍生计算后去重为 **1 个 Twelve Data 数据来源**，日期显示 **2026-11-06**。不把 `analyze_dataset` 当作新的数据源，也不以当前时间填补未知日期。上述截图已更新，数值和 artifact SHA 仍不变。

未读取或呈现该会话 terminal 全文。未给没有图表产物的会话拼装替代图；case2 的图表生成失败仍由后端验收记录反映。真实多会话的完成情况与文字结论，由后端验收报告负责，本文件只证明上述前端行为和图表值。

验证：3 项视口/交互用例通过，1 项真实模型产物渲染用例通过。无新增模型调用，未提交 Git。
