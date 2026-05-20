# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T11:35:33`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `3` PASS, `0` REVIEW, `0` FAIL
- Elapsed: `88.4s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q20 | quick_brief | PASS | brief | research | 39054 | - |
| Q32 | english_followup | PASS | chat | clarify | 20228 | - |
| Q33 | user_style_constraint | PASS | chat | research | 27087 | - |

## Full Answers

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-20260505113533-9a5316`

**Observed:** mode=`brief`, route=`research`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "GOOGL",
      "MSFT"
    ],
    "operation": "compare"
  },
  {
    "subject_type": "company",
    "tickers": [
      "GOOGL"
    ],
    "operation": "price"
  },
  {
    "subject_type": "company",
    "tickers": [
      "GOOGL"
    ],
    "operation": "fetch"
  },
  {
    "subject_type": "company",
    "tickers": [
      "MSFT"
    ],
    "operation": "price"
  },
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
    "subject_hint": "GOOGL, MSFT"
  },
  "relation": "new_topic",
  "domain_intent": "analysis",
  "confidence": 0.9,
  "needs_tools": true,
  "reason": "用户要求快速比较两只股票的实时表现，需要获取最新数据",
  "reply_guidance": "提供 GOOGL 和 MSFT 的今日涨跌幅、最新新闻摘要和关键风险点，各一句话，简洁明了。"
}
```

**Full Answer:**

---
我先按 GOOGL, MSFT 这组代表标的看。

GOOGL:
- GOOGL 最新价格约为 383.25 USD，变动 -2.44 / -0.63%。
- 相关消息：[Why Alphabet Stock Soared 34% in April -- One Catalyst Is Its Move to Challenge Data Center AI Chip Leader Nvidia](https://finance.yahoo.com/search?p=Why+Alphabet+Stock+Soared+34%25+in+April+--+One+Catalyst+Is+Its+Move+to+Challenge+Data+Center+AI+Chip+Leader+Nvidia)（Yahoo / 2026-05-05）；[Top Stock Reports for Alphabet, Walmart & Micron](https://finance.yahoo.com/search?p=Top+Stock+Reports+for+Alphabet%2C+Walmart+%26+Micron)（Yahoo / 2026-05-04）

MSFT:
- MSFT 最新价格约为 413.62 USD，变动 -0.57 / -0.14%。
- 相关消息：[Microsoft: Continued AI And Software Concerns](https://www.google.com/search?q=Microsoft%3A+Continued+AI+And+Software+Concerns)（SeekingAlpha / 2026-05-04）；[Adeia Announces First Quarter 2026 Financial Results](https://finance.yahoo.com/search?p=Adeia+Announces+First+Quarter+2026+Financial+Results)（Yahoo / 2026-05-04）

来源：
- [Why Alphabet Stock Soared 34% in April -- One Catalyst Is Its Move to Challenge Data Center AI Chip Leader Nvidia](https://finance.yahoo.com/search?p=Why+Alphabet+Stock+Soared+34%25+in+April+--+One+Catalyst+Is+Its+Move+to+Challenge+Data+Center+AI+Chip+Leader+Nvidia)（Yahoo / 2026-05-05）
- [Top Stock Reports for Alphabet, Walmart & Micron](https://finance.yahoo.com/search?p=Top+Stock+Reports+for+Alphabet%2C+Walmart+%26+Micron)（Yahoo / 2026-05-04）
- [Here is Why Alphabet (GOOGL) Is Among the Most Promising AI Stocks to Invest In](https://finance.yahoo.com/search?p=Here+is+Why+Alphabet+%28GOOGL%29+Is+Among+the+Most+Promising+AI+Stocks+to+Invest+In)（Yahoo / 2026-05-04）
- [Alphabet in Focus as U.S. Raises AI Compute Concerns](https://finance.yahoo.com/search?p=Alphabet+in+Focus+as+U.S.+Raises+AI+Compute+Concerns)（Yahoo / 2026-05-04）
- [Reddit CEO delivers bold warning to Google and OpenAI](https://finance.yahoo.com/search?p=Reddit+CEO+delivers+bold+warning+to+Google+and+OpenAI)（Yahoo / 2026-05-04）
---

### Q32 - english_followup

**Query:** So does that hurt NVDA more than MSFT?

**Expected:** 英文追问带上下文，并处理显式 tickers。

**Session:** `eval-english`

**Eval Session:** `eval-english-20260505113533-9a5316`

**Observed:** mode=`chat`, route=`clarify`, verdict=`PASS`

**Conversation Router:**

```json
{
  "execution_route": "clarify",
  "context_binding": {
    "source": "none",
    "confidence": 0.0,
    "reason": "current user turn contains explicit subject(s), so implicit history was ignored",
    "subject_hint": "NVDA, MSFT"
  },
  "relation": "follow_up",
  "domain_intent": "analysis",
  "confidence": 0.3,
  "needs_tools": false,
  "reason": "问题指代模糊，无法安全绑定上下文，需澄清具体事件或因素",
  "reply_guidance": "询问用户'that'指的是什么（如特定事件、报告结论或市场因素），以便提供准确的比较分析。"
}
```

**Full Answer:**

---
我还不能确定你指的是哪份报告或哪一段结论。把报告标题、结论片段或对应标的发我，我就可以接着聊。

可以补充：
- 补充公司、股票代码、宏观主题、持仓，或说明你指的是哪条消息/哪份报告
---

### Q33 - user_style_constraint

**Query:** 帮我看苹果，对了我没睡好，说短一点。

**Expected:** 遵守简短要求，不套模板。

**Session:** `eval-style`

**Eval Session:** `eval-style-20260505113533-9a5316`

**Observed:** mode=`chat`, route=`research`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "AAPL"
    ],
    "operation": "daily_brief"
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
  "domain_intent": "analysis",
  "confidence": 0.8,
  "needs_tools": true,
  "reason": "用户要求查看苹果公司信息，可能需要实时行情、新闻或分析数据",
  "reply_guidance": "调用工具获取AAPL的最新行情或关键信息，以简洁方式回复，忽略用户关于睡眠的闲聊部分"
}
```

**Full Answer:**

---
AAPL 先给你一个很短的快评。
- 关注下一财报季的营收指引和利润率变化
- 跟踪行业政策和竞争格局变化
---

## Follow-Up Analysis

All deterministic checks passed. Manual review should still read the full answers above for tone and usefulness.
