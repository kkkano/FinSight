# 2025-12-08 BettaFish 项目借鉴与改进建议（时间：2025-12-08，本地时区）

参考：https://github.com/666ghj/BettaFish

## 借鉴要点
- 多 Agent 分工：BettaFish 拆分 Query/Media/Insight/Report，论坛式协作（主持人汇总辩论）。可映射到我们 News/Tech/Fund/Macro/Report 子链路，加一个轻量主持节点做观点融合。
- 数据收集高召回：并行抓取、多轮反思→过滤→总结；适合我们的 DeepSearch（新闻/基本面/估值要点）并落 KV。
- 中间表示（IR）：Report Engine 先生成 IR、校验，再渲染 HTML/PDF；我们可为报告/长答复增加 IR 片段结构与校验。
- 工具专属化：不同 Agent 绑定专属工具与 prompt，减少“大杂烩”工具池。
- 部署与监控：模块化、compose；建议我们补子 Agent 配置/开关与诊断，区分缓存命中/重搜。

## 针对当前项目的分阶段改进
1) 子链路与触发
   - News 子 Agent：并行 Tavily+DDG+搜索聚合，LLM 摘要 + 链接列表，写 KV (ticker, field=news, as_of)。
   - Tech 子 Agent：行情/K线/指标；当工具失败或 as_of 过旧时触发。
   - Fund 子 Agent：财报/估值/财务比率；工具缺失或为空时触发。
   - Macro/Context 子 Agent：指数/宏观事件（可选）；用于“今天大新闻影响股市”类问题。
   - 主链路：先查 KV（含 as_of 过期判定），不足再触发子链路；主持节点聚合多子 Agent 结论（优先 IR 结构）。

2) KV / 缓存策略
   - Key: `{ticker}:{field}`；字段如 news/tech/fund/macro/report。
   - Value: `{as_of, source, text, structured?}`；TTL 可按字段：news 30-60min，tech 10-30min，fund 12-24h，macro 2-6h。
   - 命中判定：存在且 as_of 未过期；否则触发重搜并回写。

3) IR / 结构化输出
   - 定义简版 IR：`{summary, bullets[3-5], links[], risks?, next_steps?}`。
   - 报告/长答复使用 IR→渲染；前端可选展示摘要+链接。

4) Prompt / 链接保留
   - 新闻/报告类提示词：要求保留全部 URL，Markdown 链接格式；摘要后“链接”小节。
   - 工具返回空/限流/Too Many Requests 判定为“数据不足”，触发子 Agent。

5) 前端/UX
   - 链接高亮可点击（已做）；展示“来源/刷新/缓存命中”信息。
   - 诊断面板：展示 KV 命中、重搜触发、来源列表。

6) 监控/测试
   - 手动/自动检查：新闻聚合含链接、KV 命中/过期重搜、工具失败触发 DeepSearch。
   - 日志字段：source_used、as_of、fallback_reason。

## 优先顺序（短期）
P1: KV 过期判定 + 子 Agent 触发（news/tech/fund）；LLM 提示词统一保留链接。  
P2: 简版 IR 定义与渲染；主持节点聚合多子链路。  
P3: 前端诊断（KV 命中/重搜/来源显示），测试清单补全。  
