# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T09:25:34`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `4` PASS, `0` REVIEW, `0` FAIL
- Elapsed: `236.6s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q35 | history_switch_a | PASS | chat | research | 32409 | - |
| Q36 | history_switch_b | PASS | chat | research | 23040 | - |
| Q37 | history_switch_a_followup | PASS | - | direct | 23770 | - |
| Q38 | history_switch_b_followup | PASS | chat | research | 49385 | - |

## Full Answers

### Q35 - history_switch_a

**Query:** AAPL 最近新闻怎么看？

**Expected:** 会话 A 建立 AAPL 上下文。

**Session:** `eval-switch-A`

**Eval Session:** `eval-switch-A-20260505092534-eeb00c`

**Observed:** mode=`chat`, route=`research`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "AAPL"
    ],
    "operation": "fetch"
  }
]
```

**Conversation Router:**

```json
{
  "execution_route": "research",
  "context_binding": {
    "source": "none",
    "confidence": 0.0,
    "reason": "current user turn contains explicit subject(s), so implicit history was ignored",
    "subject_hint": "AAPL"
  },
  "relation": "new_topic",
  "domain_intent": "news",
  "confidence": 0.7,
  "needs_tools": true,
  "reason": "用户询问 AAPL 的最近新闻，需要实时新闻数据来提供分析。",
  "reply_guidance": "先获取 AAPL 的最新新闻，然后基于新闻内容提供分析或评论。"
}
```

**Stream Spot Check:**

```json
{
  "present": true,
  "status_code": null,
  "output_mode": "chat",
  "response_len": 1823,
  "token_len": 1823,
  "event_count": 75,
  "body_preview": null
}
```

**Full Answer:**

---
AAPL 这次先看这几条消息：
- [Apple Weighs Major AI Deal As Investors Reassess Growth And Valuation](https://finance.yahoo.com/search?p=Apple+Weighs+Major+AI+Deal+As+Investors+Reassess+Growth+And+Valuation)（Yahoo / 2026-05-04）
- [Apple's Tim Cook says AI-fueled 'RAMmageddon' will make your next laptop and phone a lot pricier](https://finance.yahoo.com/search?p=Apple%27s+Tim+Cook+says+AI-fueled+%27RAMmageddon%27+will+make+your+next+laptop+and+phone+a+lot+pricier)（Yahoo / 2026-05-04）
- [Apple Plans to Let Users Build Their Own Passes in iOS 27 Wallet App](https://finance.yahoo.com/search?p=Apple+Plans+to+Let+Users+Build+Their+Own+Passes+in+iOS+27+Wallet+App)（Yahoo / 2026-05-04）

对股价的影响要看两点：第一，事件是否会改变收入、利润率、交付或监管预期；第二，价格是否已经提前反映。短线更看情绪和成交量，中期还是要回到业绩指引和估值。

来源：
- [Apple Weighs Major AI Deal As Investors Reassess Growth And Valuation](https://finance.yahoo.com/search?p=Apple+Weighs+Major+AI+Deal+As+Investors+Reassess+Growth+And+Valuation)（Yahoo / 2026-05-04）
- [Apple's Tim Cook says AI-fueled 'RAMmageddon' will make your next laptop and phone a lot pricier](https://finance.yahoo.com/search?p=Apple%27s+Tim+Cook+says+AI-fueled+%27RAMmageddon%27+will+make+your+next+laptop+and+phone+a+lot+pricier)（Yahoo / 2026-05-04）
- [Apple Plans to Let Users Build Their Own Passes in iOS 27 Wallet App](https://finance.yahoo.com/search?p=Apple+Plans+to+Let+Users+Build+Their+Own+Passes+in+iOS+27+Wallet+App)（Yahoo / 2026-05-04）
- [Morgan Stanley resets Apple stock price target after earnings](https://finance.yahoo.com/search?p=Morgan+Stanley+resets+Apple+stock+price+target+after+earnings)（Yahoo / 2026-05-04）
- [Intel’s Next Chapter Government Backing Foundry Ambitions And AI Partnerships](https://finance.yahoo.com/search?p=Intel%E2%80%99s+Next+Chapter+Government+Backing+Foundry+Ambitions+And+AI+Partnerships)（Yahoo / 2026-05-04）
---

### Q36 - history_switch_b

**Query:** MSFT 最近新闻怎么看？

**Expected:** 会话 B 建立 MSFT 上下文，不污染 A。

**Session:** `eval-switch-B`

**Eval Session:** `eval-switch-B-20260505092534-eeb00c`

**Observed:** mode=`chat`, route=`research`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "MSFT"
    ],
    "operation": "fetch"
  }
]
```

**Conversation Router:**

```json
{
  "execution_route": "research",
  "context_binding": {
    "source": "none",
    "confidence": 0.0,
    "reason": "current user turn contains explicit subject(s), so implicit history was ignored",
    "subject_hint": "MSFT"
  },
  "relation": "new_topic",
  "domain_intent": "news",
  "confidence": 0.8,
  "needs_tools": true,
  "reason": "用户需要 MSFT 的最近新闻分析，需实时工具获取最新数据",
  "reply_guidance": "应通过工具获取 MSFT 最新新闻，并提供分析或摘要"
}
```

**Stream Spot Check:**

```json
{
  "present": true,
  "status_code": null,
  "output_mode": "chat",
  "response_len": 1595,
  "token_len": 1595,
  "event_count": 70,
  "body_preview": null
}
```

**Full Answer:**

---
MSFT 这次先看这几条消息：
- [Adeia Announces First Quarter 2026 Financial Results](https://finance.yahoo.com/search?p=Adeia+Announces+First+Quarter+2026+Financial+Results)（Yahoo / 2026-05-04）
- [Microsoft, Netflix, and 10 More Stocks Unfairly Punished On Earnings](https://finance.yahoo.com/search?p=Microsoft%2C+Netflix%2C+and+10+More+Stocks+Unfairly+Punished+On+Earnings)（Yahoo / 2026-05-04）
- [Microsoft (MSFT): Most Promising AI Stock to Invest In](https://finance.yahoo.com/search?p=Microsoft+%28MSFT%29%3A+Most+Promising+AI+Stock+to+Invest+In)（Yahoo / 2026-05-04）

对股价的影响要看两点：第一，事件是否会改变收入、利润率、交付或监管预期；第二，价格是否已经提前反映。短线更看情绪和成交量，中期还是要回到业绩指引和估值。

来源：
- [Adeia Announces First Quarter 2026 Financial Results](https://finance.yahoo.com/search?p=Adeia+Announces+First+Quarter+2026+Financial+Results)（Yahoo / 2026-05-04）
- [Microsoft, Netflix, and 10 More Stocks Unfairly Punished On Earnings](https://finance.yahoo.com/search?p=Microsoft%2C+Netflix%2C+and+10+More+Stocks+Unfairly+Punished+On+Earnings)（Yahoo / 2026-05-04）
- [Microsoft (MSFT): Most Promising AI Stock to Invest In](https://finance.yahoo.com/search?p=Microsoft+%28MSFT%29%3A+Most+Promising+AI+Stock+to+Invest+In)（Yahoo / 2026-05-04）
- [Azure's Growth Rate Bounces Back in Q3. Is Microsoft's Stock Due for a Rally?](https://finance.yahoo.com/search?p=Azure%27s+Growth+Rate+Bounces+Back+in+Q3.+Is+Microsoft%27s+Stock+Due+for+a+Rally%3F)（Yahoo / 2026-05-04）
- [Nerdio Launches MSP 7.0 Amid Triple-Digit Microsoft 365 Growth](https://finance.yahoo.com/search?p=Nerdio+Launches+MSP+7.0+Amid+Triple-Digit+Microsoft+365+Growth)（Yahoo / 2026-05-04）
---

### Q37 - history_switch_a_followup

**Query:** 那它的风险主要在哪？

**Expected:** 切回会话 A 后仍指 AAPL。

**Session:** `eval-switch-A`

**Eval Session:** `eval-switch-A-20260505092534-eeb00c`

**Observed:** mode=`None`, route=`direct`, verdict=`PASS`

**Conversation Router:**

```json
{
  "execution_route": "direct_answer",
  "context_binding": {
    "source": "last_turn",
    "confidence": 0.9,
    "reason": "用户基于上一轮AAPL新闻讨论追问风险，'它'明确指代AAPL",
    "subject_hint": "AAPL"
  },
  "relation": "follow_up",
  "domain_intent": "analysis",
  "confidence": 0.8,
  "needs_tools": false,
  "reason": "用户追问AAPL的风险，基于已有新闻对话，可直接从上下文分析",
  "reply_guidance": "基于之前提供的AAPL新闻，总结主要风险点，如AI相关成本上升、产品定价压力、市场竞争等，并联系股价影响"
}
```

**Stream Spot Check:**

```json
{
  "present": true,
  "status_code": null,
  "output_mode": null,
  "response_len": 218,
  "token_len": 218,
  "event_count": 23,
  "body_preview": null
}
```

**Full Answer:**

---
先按 AAPL 看，主要风险我会放在这几类：
- 增长预期兑现：如果收入、利润率或指引低于市场预期，估值容易被压缩。
- 估值和利率：利率、美元和风险偏好变化会直接影响成长股估值倍数。
- 竞争和监管：核心业务遇到竞争加剧、监管约束或地区需求走弱，会拖累中期叙事。
- 单一催化失效：如果股价主要靠 AI、新产品、云业务或某个周期催化支撑，兑现慢于预期时回撤会更明显。

如果你要我按最新证据判断，我会再查最近新闻、财报指引和价格反应。
---

### Q38 - history_switch_b_followup

**Query:** 那它的风险主要在哪？

**Expected:** 切回会话 B 后仍指 MSFT。

**Session:** `eval-switch-B`

**Eval Session:** `eval-switch-B-20260505092534-eeb00c`

**Observed:** mode=`chat`, route=`research`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "MSFT"
    ],
    "operation": "qa"
  }
]
```

**Conversation Router:**

```json
{
  "execution_route": "research",
  "context_binding": {
    "source": "last_turn",
    "confidence": 0.9,
    "reason": "用户使用'那它'指代最近对话中讨论的MSFT",
    "subject_hint": "MSFT"
  },
  "relation": "follow_up",
  "domain_intent": "analysis",
  "confidence": 0.9,
  "needs_tools": true,
  "reason": "用户追问MSFT的风险，需要实时数据或分析工具来获取最新风险信息",
  "reply_guidance": "基于工具获取的MSFT风险数据，如财务风险、市场风险、竞争风险等，进行结构化总结和解释"
}
```

**Stream Spot Check:**

```json
{
  "present": true,
  "status_code": null,
  "output_mode": "chat",
  "response_len": 254,
  "token_len": 254,
  "event_count": 45,
  "body_preview": null
}
```

**Full Answer:**

---
先按 MSFT 看，主要风险不一定来自单条新闻，而是这几类：
- 增长预期兑现：市场已经给了较高预期时，收入、利润率或指引只要低于预期，估值就容易被压缩。
- 估值和利率：利率、美元和风险偏好变化会直接影响成长股估值倍数。
- 竞争和监管：核心业务如果遇到竞争加剧、监管约束或地区需求走弱，会拖累中期叙事。
- 单一催化失效：如果股价主要靠 AI、新产品、云业务或某个周期催化支撑，催化兑现慢于预期时回撤会更明显。

如果你要我按最新证据判断，我会再查最近新闻、财报指引和价格反应，避免只靠常识框架下结论。
---

## Follow-Up Analysis

All deterministic checks passed. Manual review should still read the full answers above for tone and usefulness.
