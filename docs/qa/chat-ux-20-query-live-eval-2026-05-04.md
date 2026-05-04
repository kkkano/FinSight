# Chat UX 20 Query Live Evaluation - 2026-05-04

本文件记录在部署环境 `http://175.178.159.112:8000/chat/supervisor` 上实际执行的 20 条 query。分析部分只在完整答案全部收集后生成。

## Summary

- Total queries: 20
- Success: 19
- Failed: 1
- Answers with Markdown links: 3
- Answers with forbidden markers: 0

## Query Matrix

| ID | Category | Output mode | Seconds | Chars | Links | Forbidden hits |
| --- | --- | --- | ---: | ---: | --- | --- |
| Q01 | 简单价格问题 | chat | 42.65 | 93 | False | - |
| Q02 | 简单新闻问题 | chat | 60.69 | 50 | False | - |
| Q03 | 简单技术面问题 | chat | 42.6 | 167 | False | - |
| Q04 | 报告问题 | None | 420.01 | 0 | False | - |
| Q05 | 报告后续追问/指代 | chat | 8.07 | 89 | False | - |
| Q06 | 闲聊问题 | chat | 8.05 | 89 | False | - |
| Q07 | 混乱问题 | chat | 54.49 | 359 | True | - |
| Q08 | 多个简单问题 | chat | 48.74 | 105 | False | - |
| Q09 | 简单 + 复杂 + 闲聊嵌套 | chat | 32.41 | 50 | False | - |
| Q10 | 指代上下文第一轮 | chat | 52.96 | 963 | True | - |
| Q11 | 指代上下文第二轮 | chat | 53.16 | 64 | False | - |
| Q12 | 纯泛金融概念问题 | chat | 0.07 | 89 | False | - |
| Q13 | 非金融闲聊/越界 | chat | 9.05 | 89 | False | - |
| Q14 | 含错别字/口语 | chat | 8.05 | 89 | False | - |
| Q15 | 中英混合 | chat | 97.87 | 126 | False | - |
| Q16 | 宏观新闻问题 | chat | 28.25 | 51 | False | - |
| Q17 | 要求不要模板 | chat | 63.05 | 50 | False | - |
| Q18 | 多任务混合 | chat | 118.41 | 353 | True | - |
| Q19 | 报告按钮语义但普通聊天继续 | chat | 45.19 | 89 | False | - |
| Q20 | 复杂混乱嵌套 | chat | 107.53 | 50 | False | - |

## Full Queries And Answers

### Q01 - 简单价格问题

- Session: `public:qa20:simple-price`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `42.65s`; chars: `93`

**Query**

```text
NVDA 今天多少钱？
```

**Full Answer**

```markdown
NVDA 的实时价格这次没有拿到可用报价。可以稍后重试，或切到行情页确认最新成交价。

如果你要做交易判断，我会把它和盘中走势、成交量、重要新闻一起看；单个报价本身只说明当前成交位置。

```

### Q02 - 简单新闻问题

- Session: `public:qa20:simple-news`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `60.69s`; chars: `50`

**Query**

```text
特斯拉最近 24 小时有什么关键新闻？给我链接。
```

**Full Answer**

```markdown
我没有拿到 TSLA 的可用新闻列表，所以这次不能硬编影响结论。可以重试或换一个更明确的时间范围。

```

### Q03 - 简单技术面问题

- Session: `public:qa20:simple-technical`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `42.6s`; chars: `167`

**Query**

```text
AAPL 现在技术面偏强还是偏弱？简单说。
```

**Full Answer**

```markdown
AAPL 的技术面我会先看这几个信号：RSI(14): 69.31；MACD: 4.36；MACD signal: 3.45；MA20: 266.36；MA50: 261.22；趋势: uptrend

更重要的是把指标和价格位置合起来看：RSI 只说明动能冷热，MACD 更偏趋势确认，支撑/阻力需要用近期高低点和成交密集区验证。

```

### Q04 - 报告问题

- Session: `public:qa20:report-followup`
- Requested options: `{"output_mode": "investment_report", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `None`
- Success: `False`; elapsed: `420.01s`; chars: `0`
- Error: `TimeoutError('timed out')`

**Query**

```text
请生成一份 Apple 投资报告，包含结论、催化剂和主要风险。
```

**Full Answer**

```markdown

```

### Q05 - 报告后续追问/指代

- Session: `public:qa20:report-followup`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `8.07s`; chars: `89`

**Query**

```text
刚才那份报告里，最大的风险是什么？不要重新生成报告，直接聊。
```

**Full Answer**

```markdown
我需要知道你想分析的公司、股票、宏观主题、新闻、财报或持仓。

你可以这样做：
- 输入公司名或 ticker，例如 谷歌 / GOOGL
- 输入宏观主题，例如 美联储利率路径
```

### Q06 - 闲聊问题

- Session: `public:qa20:smalltalk`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `8.05s`; chars: `89`

**Query**

```text
你今天状态怎么样？顺便告诉我你能帮我做什么。
```

**Full Answer**

```markdown
我需要知道你想分析的公司、股票、宏观主题、新闻、财报或持仓。

你可以这样做：
- 输入公司名或 ticker，例如 谷歌 / GOOGL
- 输入宏观主题，例如 美联储利率路径
```

### Q07 - 混乱问题

- Session: `public:qa20:messy`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `54.49s`; chars: `359`

**Query**

```text
那个苹果还是英伟达吧不对我想问马斯克那个车企今天咋样新闻和价格随便说下别太长
```

**Full Answer**

```markdown
NVDA, AAPL 这次最值得先看的新闻是：
- Nvidia Stock Is Pushing Toward $200. What Could Get It There.

对股价的影响要看两点：第一，事件是否会改变收入、利润率、交付或监管预期；第二，价格是否已经提前反映。短线更看情绪和成交量，中期还是要回到业绩指引和估值。

来源：
- [Nvidia Stock Is Pushing Toward $200. What Could Get It There.](https://www.barrons.com/articles/nvidia-stock-price-ai-chips-35da78b6?siteid=yhoof2&yptr=yahoo)（Barrons.com / 2026-05-04）

```

### Q08 - 多个简单问题

- Session: `public:qa20:multi-simple`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `48.74s`; chars: `105`

**Query**

```text
NVDA 多少钱？TSLA 多少钱？AAPL 多少钱？分别一句话。
```

**Full Answer**

```markdown
NVDA, TSLA, AAPL 的实时价格这次没有拿到可用报价。可以稍后重试，或切到行情页确认最新成交价。

如果你要做交易判断，我会把它和盘中走势、成交量、重要新闻一起看；单个报价本身只说明当前成交位置。

```

### Q09 - 简单 + 复杂 + 闲聊嵌套

- Session: `public:qa20:nested`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `32.41s`; chars: `50`

**Query**

```text
先告诉我 MSFT 现在价格，然后分析一下如果美联储继续高利率对它估值的影响，最后像朋友一样给我一句提醒。
```

**Full Answer**

```markdown
我没有拿到 MSFT 的可用新闻列表，所以这次不能硬编影响结论。可以重试或换一个更明确的时间范围。

```

### Q10 - 指代上下文第一轮

- Session: `public:qa20:reference-amd`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `52.96s`; chars: `963`

**Query**

```text
帮我看一下 AMD 最近的股价和新闻。
```

**Full Answer**

```markdown
AMD 这次最值得先看的新闻是：
- Why AMD Stock Skyrocketed 74% in April
- How Riot’s AI Data Center Pivot and Wider AMD Deal May Reshape Riot Platforms (RIOT) Investors
- Jobs Report, Palantir, Pinterest, AMD, PayPal, Disney, and More to Watch This Week

对股价的影响要看两点：第一，事件是否会改变收入、利润率、交付或监管预期；第二，价格是否已经提前反映。短线更看情绪和成交量，中期还是要回到业绩指引和估值。

来源：
- [Why AMD Stock Skyrocketed 74% in April](https://www.fool.com/investing/2026/05/03/amd-stock-amd-earnings-date-when-best-ai-stocks/)（Motley Fool / 2026-05-04）
- [How Riot’s AI Data Center Pivot and Wider AMD Deal May Reshape Riot Platforms (RIOT) Investors](https://finance.yahoo.com/markets/stocks/articles/riot-ai-data-center-pivot-180555774.html)（Simply Wall St. / 2026-05-03）
- [Jobs Report, Palantir, Pinterest, AMD, PayPal, Disney, and More to Watch This Week](https://www.barrons.com/articles/jobs-report-palantir-pinterest-amd-paypal-disney-and-more-to-watch-this-week-83bd97e1?siteid=yhoof2&yptr=yahoo)（Barrons.com / 2026-05-03）

```

### Q11 - 指代上下文第二轮

- Session: `public:qa20:reference-amd`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `53.16s`; chars: `64`

**Query**

```text
那它接下来最该关注什么？
```

**Full Answer**

```markdown
我理解你的问题是：那AMD接下来最该关注什么？。这次可用数据不足，我会先保留上下文；你可以继续补充标的、时间范围或想看的维度。

```

### Q12 - 纯泛金融概念问题

- Session: `public:qa20:concept`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `0.07s`; chars: `89`

**Query**

```text
什么是市盈率？给初学者解释一下。
```

**Full Answer**

```markdown
我需要知道你想分析的公司、股票、宏观主题、新闻、财报或持仓。

你可以这样做：
- 输入公司名或 ticker，例如 谷歌 / GOOGL
- 输入宏观主题，例如 美联储利率路径
```

### Q13 - 非金融闲聊/越界

- Session: `public:qa20:offtopic`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `9.05s`; chars: `89`

**Query**

```text
给我推荐一部今晚看的电影，不要金融相关。
```

**Full Answer**

```markdown
我需要知道你想分析的公司、股票、宏观主题、新闻、财报或持仓。

你可以这样做：
- 输入公司名或 ticker，例如 谷歌 / GOOGL
- 输入宏观主题，例如 美联储利率路径
```

### Q14 - 含错别字/口语

- Session: `public:qa20:typo`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `8.05s`; chars: `89`

**Query**

```text
英伟哒今添跌了嘛？要不要慌
```

**Full Answer**

```markdown
我需要知道你想分析的公司、股票、宏观主题、新闻、财报或持仓。

你可以这样做：
- 输入公司名或 ticker，例如 谷歌 / GOOGL
- 输入宏观主题，例如 美联储利率路径
```

### Q15 - 中英混合

- Session: `public:qa20:bilingual`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `97.87s`; chars: `126`

**Query**

```text
Can you compare Apple and Microsoft quickly? 用中文回答，重点说 valuation and growth。
```

**Full Answer**

```markdown
我理解你的问题是：Can you compare Apple and Microsoft quickly? 用中文回答，重点说 valuation and growth。。这次可用数据不足，我会先保留上下文；你可以继续补充标的、时间范围或想看的维度。

```

### Q16 - 宏观新闻问题

- Session: `public:qa20:macro-news`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `28.25s`; chars: `51`

**Query**

```text
今天美联储利率预期有什么新变化？对纳斯达克影响大吗？要有来源链接。
```

**Full Answer**

```markdown
我没有拿到 ^IXIC 的可用新闻列表，所以这次不能硬编影响结论。可以重试或换一个更明确的时间范围。

```

### Q17 - 要求不要模板

- Session: `public:qa20:no-template`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `63.05s`; chars: `50`

**Query**

```text
别给我模板，像正常聊天一样说：TSLA 现在风险大不大？
```

**Full Answer**

```markdown
我没有拿到 TSLA 的可用新闻列表，所以这次不能硬编影响结论。可以重试或换一个更明确的时间范围。

```

### Q18 - 多任务混合

- Session: `public:qa20:multi-mixed`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `118.41s`; chars: `353`

**Query**

```text
查一下 NVDA 最新价格、相关新闻链接，再告诉我如果只能看一个指标你看什么。
```

**Full Answer**

```markdown
NVDA 这次最值得先看的新闻是：
- Nvidia Stock Is Pushing Toward $200. What Could Get It There.

对股价的影响要看两点：第一，事件是否会改变收入、利润率、交付或监管预期；第二，价格是否已经提前反映。短线更看情绪和成交量，中期还是要回到业绩指引和估值。

来源：
- [Nvidia Stock Is Pushing Toward $200. What Could Get It There.](https://www.barrons.com/articles/nvidia-stock-price-ai-chips-35da78b6?siteid=yhoof2&yptr=yahoo)（Barrons.com / 2026-05-04）

```

### Q19 - 报告按钮语义但普通聊天继续

- Session: `public:qa20:report-without-mode`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `45.19s`; chars: `89`

**Query**

```text
先不要报告模式，你就告诉我如果之后生成 Amazon 报告，应该重点看哪三块？
```

**Full Answer**

```markdown
我理解你的问题是：先不要报告模式，你就告诉我如果之后生成 Amazon 报告，应该重点看哪三块？。这次可用数据不足，我会先保留上下文；你可以继续补充标的、时间范围或想看的维度。

```

### Q20 - 复杂混乱嵌套

- Session: `public:qa20:complex-messy-nested`
- Requested options: `{"output_mode": "chat", "confirmation_mode": "skip", "trace_raw_override": "off"}`
- Observed output mode: `chat`
- Success: `True`; elapsed: `107.53s`; chars: `50`

**Query**

```text
我有点乱：一边想知道 NVDA 价格，一边又想知道 AI 泡沫会不会影响它，另外你别太严肃，最后问一句我还想不想看报告。
```

**Full Answer**

```markdown
我没有拿到 NVDA 的可用新闻列表，所以这次不能硬编影响结论。可以重试或换一个更明确的时间范围。

```

## Post-Answer Gap Analysis

### Repeated Issues

- `3`x 仍出现机械兜底话术
- `2`x 用户要求链接但答案没有 Markdown 链接
- `1`x 答案过短
- `1`x 请求失败

### Per-Query Findings

- Q01: 未发现明显问题
- Q02: 用户要求链接但答案没有 Markdown 链接
- Q03: 未发现明显问题
- Q04: 请求失败; 答案过短
- Q05: 未发现明显问题
- Q06: 未发现明显问题
- Q07: 未发现明显问题
- Q08: 未发现明显问题
- Q09: 未发现明显问题
- Q10: 未发现明显问题
- Q11: 仍出现机械兜底话术
- Q12: 未发现明显问题
- Q13: 未发现明显问题
- Q14: 未发现明显问题
- Q15: 仍出现机械兜底话术
- Q16: 用户要求链接但答案没有 Markdown 链接
- Q17: 未发现明显问题
- Q18: 未发现明显问题
- Q19: 仍出现机械兜底话术
- Q20: 未发现明显问题

### Recommended Next Fixes

- 新闻/宏观/多任务查询中，只要用户要求“链接/来源”，答案必须降级为“带引用的回答”；没有拿到 URL 时要明确说没有可用链接，而不是泛泛总结。
- 彻底删除普通 chat 的“我理解你的问题是”兜底，改成更短的人话澄清或基于已有工具结果回答。
- 为简单问答设置最低信息量：价格类至少包含价格、涨跌、时间/数据源或无法获取原因；新闻类至少包含 2-3 条事件或明确无结果。

## Manual Review After Reading Full Answers

This section was written after reading all 20 full answers above. The automatic checks were too weak: they caught forbidden template/tool markers, but missed many answers that were still bad conversation.

### High-Level Result

- Hard-template leakage improved: 0/20 answers contained `???`, `?????`, `??????`, `????`, tool names, or `Suggested ladder`.
- Actual assistant quality is still not acceptable: at least 13/20 answers are poor or failed for normal users.
- The main failure is no longer only wording. It is routing, task decomposition, answer composition, context use, and latency.
- Report mode cannot be synchronous in its current form: Q04 timed out after 420 seconds and therefore Q05 could not use `last_report` memory.

### Manual Per-Query Verdicts

| ID | Verdict | Why |
| --- | --- | --- |
| Q01 | Bad | Simple price query took 42.65s and still said no usable quote. This is unacceptable for a price question. Either the price tool result is not reaching chat rendering, or the parser does not understand the real tool output shape. |
| Q02 | Bad | User explicitly asked for news links. Answer only says no TSLA news and offers retry. It does not provide links, alternate source explanation, or a useful fallback. |
| Q03 | Acceptable | Technical answer uses actual RSI/MACD/MA values and reads like a concise explanation. It still lacks a direct ???/??? first sentence. |
| Q04 | Failed | Report request timed out at 420s. Report generation needs async job mode, progress, resume, and partial result handling. |
| Q05 | Bad | Follow-up failed because Q04 produced no report. It fell back to generic missing-target clarification instead of saying the previous report did not finish. |
| Q06 | Bad | Small talk was treated as missing financial target. This is exactly the non-GPT-like behavior the user complained about. |
| Q07 | Bad | Messy query intended ?Musk car company? (TSLA), but answer focused on NVDA/AAPL. Entity disambiguation picked stale/earlier mentions instead of the final corrected intent. |
| Q08 | Bad | Multi-price query collapsed NVDA/TSLA/AAPL into one generic ?no quote? answer. It should answer each ticker separately, including per-ticker failures. |
| Q09 | Bad | Nested request asked price + macro valuation impact + friendly reminder. Answer only gave a news-data failure for MSFT. It ignored most sub-requests. |
| Q10 | Mixed | AMD news answer has links and is useful, but the user asked ???????; price is missing. |
| Q11 | Bad | Reference resolution injected AMD, but answer still used mechanical fallback and did not use prior AMD news context. Context memory exists but answer planning does not use it well. |
| Q12 | Bad | Basic financial concept question (?????) was treated as missing target. The assistant must answer general finance education questions directly. |
| Q13 | Bad | Explicit non-financial movie recommendation was treated as missing target. If product scope forbids it, say so naturally; otherwise answer normally. Current response feels broken. |
| Q14 | Bad | Typo/colloquial ?????????? was not normalized to NVDA/???. Need fuzzy ticker/company/entity correction. |
| Q15 | Bad | Bilingual Apple vs Microsoft compare was not decomposed into AAPL/MSFT compare. It returned mechanical insufficient-data wording. |
| Q16 | Bad | Macro/news request asked for Fed-rate expectation changes and sources. System routed to `^IXIC` news and returned no links. Macro topic routing is too shallow. |
| Q17 | Bad | User explicitly said ?don?t template, normal chat?. Answer was short generic news-failure text and did not discuss risk. |
| Q18 | Mixed | Has one NVDA news link, but ignores latest price and the ?if only one indicator? instruction. Multi-intent composition is incomplete. |
| Q19 | Bad | User explicitly asked not to enter report mode and wanted three report-focus areas for Amazon. This should be easy advisory chat, but it fell into mechanical fallback. |
| Q20 | Bad | Complex nested request asked price + AI bubble impact + casual tone + ask if report wanted. Answer only says no NVDA news list. Almost all requested intent was dropped. |

### Root Causes Inferred From The Full Answers

1. **Normal chat still depends too much on research-target routing.** If `understand_request` cannot identify a company/ticker/tool plan, the assistant does not have a general conversational path for small talk, finance concepts, non-finance questions, or advisory planning.
2. **Answer composition is single-dominant-task, not multi-intent.** Multi-part queries often execute or render only one selected operation, so price + news + macro + tone instructions collapse into one failure sentence.
3. **Entity resolution is too literal and not correction-aware.** It misses typo variants like ?????, and in messy corrections it keeps earlier entities instead of the user?s final intended entity.
4. **Tool output extraction is unreliable for price.** Live logs showed price fetch attempts, but Q01/Q08 still reported no quote. The chat renderer must parse the actual `get_stock_price` output shape and expose per-ticker results.
5. **Report generation should not run as a blocking chat response.** A 420s timeout breaks both the report and follow-up memory. Report mode needs a job/progress lifecycle or stream-first UX.
6. **Context memory is stored but not sufficiently used for follow-up answer planning.** Q11 resolved AMD but did not reuse prior AMD news; Q05 did not gracefully explain that the report did not complete.
7. **Data/link fallback is too weak.** If news sources return empty, the assistant should say which source failed, whether a broader web/news search was attempted, and what it can still infer without links.
8. **Latency is too high for simple chat.** Many ordinary questions took 40-120s. Simple price, concept, typo normalization, small talk, and advisory questions need fast-path routing under a few seconds.

### Architecture Recommendation

A small prompt tweak is not enough. The current graph needs a clearer split between conversational intent handling and report/research orchestration.

Recommended architecture change:

1. Add a **conversation router** before research planning with routes: `smalltalk`, `finance_education`, `out_of_scope`, `single_quote`, `single_news`, `multi_intent_chat`, `report_job`, `followup_context`.
2. Add a **chat answer planner** that preserves all user sub-requests as checklist items, then renders a conversational answer that covers each item or explicitly says why an item could not be answered.
3. Keep `investment_report` as an async/streaming report job, not a synchronous chat response.
4. Make quote/news renderers consume normalized evidence objects, not raw tool output shapes. Normalize once after execution, then render from that contract.
5. Add fast deterministic handlers for small talk, finance concepts, fuzzy ticker normalization, and simple advisory ?what should I look at?? questions before expensive agent/RAG execution.
6. Make session follow-up use the last successful answer/report artifacts, and if a report failed or timed out, say that directly instead of asking for a target again.

### Priority Fix List

1. **P0: Fix simple quote path.** Q01 and Q08 must return per-ticker quote or per-ticker source failure in under 10s.
2. **P0: Add non-research chat fallback.** Q06/Q12/Q13/Q19 should never show ?I need a company/ticker? when the user asked a general or advisory question.
3. **P0: Make report mode async or stream-first.** Q04 timing out makes report follow-up impossible.
4. **P1: Multi-intent answer planner.** Q09/Q18/Q20 must cover all sub-requests instead of one operation.
5. **P1: Fuzzy entity and correction handling.** Q07/Q14/Q15 need corrected company/ticker recognition.
6. **P1: Stronger context follow-up.** Q11 should answer from prior AMD result; Q05 should handle failed report state explicitly.
7. **P2: Better source/link fallback.** Q02/Q16 should either provide links or explain precisely which source path failed and what remains uncertain.

