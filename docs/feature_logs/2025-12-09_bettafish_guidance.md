# 2025-12-09 BettaFish 多 Agent 参考与改进建议（时间：2025-12-09，本地时区）

参考仓库：https://github.com/666ghj/BettaFish

## BettaFish 核心做法摘录
- 议会式多 Agent：Query/Media/Insight/Report 分工，主持节点融合冲突结论，保证输出一致性。
- 高召回并行搜集：多源搜索 + 过滤 + 再总结，先收集证据再让 LLM 摘要。
- 中间表示（IR）：先产出结构化 IR，再渲染 HTML/PDF，利于校验与重用。
- 工具专属化：每个 Agent 绑定有限的工具和提示词，避免“大杂烩”工具池。
- 监控与开关：模块化/Compose，具备可配置的开关、缓存、重搜策略。

## 对 FinSight 的落地方案
1) 子链路与触发
- News 子 Agent：并行 Tavily + DDG + 搜索兜底，高召回，LLM 只做 2-5 句摘要并保留 Markdown 链接，写入 KV（ticker:news）。
- Tech 子 Agent：K 线/指标，工具失败或 as_of 过旧触发；同样写 KV（ticker:tech）。
- Fund 子 Agent：财报要点/估值比率，工具缺失或为空触发；写 KV（ticker:fund）。
- Macro/Context 子 Agent（可选）：宏观事件/指数情绪，用于“今天大新闻影响股市？”场景。
- 主链路：先查 KV（含 TTL/过期判断），未命中或过期触发子 Agent，主持节点融合输出。

2) KV / 缓存策略
- Key: `{ticker}:{field}`；字段示例 news/tech/fund/macro/report。
- Value: `{as_of, source, text/ir, links[], risks?, next_steps?}`；按字段设 TTL：news 30-60min、tech 10-30min、fund 12-24h、macro 2-6h。
- 过期判定：命中且 as_of 在 TTL 内直接返回，否则重搜并覆盖。

3) IR / 结构化输出
- 简版 IR：`summary`、`bullets[3-5]`、`links[]`、`risks?`、`next_steps?`。
- 长回答/报告：先生成 IR，再渲染为最终文本，便于前端折叠展示与后续复用。

4) Prompt / 链接保留
- 新闻/报告提示词统一要求：先写 2-5 句摘要，再用 Markdown 列出可点击链接（不丢失 URL）。
- 将“工具空/限流/Too Many Requests”归为“数据不足”，自动触发子 Agent 重搜。

5) 可观测性
- 日志/诊断面板展示：来源、耗时、fallback/skip 原因、KV 命中/过期重搜标记。
- 前端诊断：显示“KV 命中/重搜”“来源/数据时间”，帮助调优优先级与冷却。

## 近期优先级（建议）
P1：补 KV 过期判定 + 子 Agent 触发（news/tech/fund）；统一新闻/报告提示词保留 Markdown 链接；诊断面板展示 KV 命中/重搜。
P2：定义并落地简版 IR；主持节点融合多个子链路；前端可选择展示摘要 + 链接。
P3：完善监控/测试：用例覆盖“工具限流→DeepSearch 触发→KV 写入→再次命中不重搜”。

## 验证计划
- 单测：KV 过期判定、空数据/限流触发子 Agent。
- 集成：新闻查询时强制空数据，验证触发 DeepSearch 并返回可点击链接；重复查询命中 KV 不重搜。
- 前端：链接蓝色可点击；诊断面板显示来源/过期与否。
