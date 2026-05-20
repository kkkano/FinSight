# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T21:24:36`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `1` PASS, `2` REVIEW, `0` FAIL
- Elapsed: `324.5s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q06 | multi_simple | PASS | chat | research | 44516 | - |
| Q20 | quick_brief | REVIEW | brief | research | 106168 | quick brief exceeded 60000ms latency budget |
| Q39 | multiple_simple_complex_url | REVIEW | chat | research | 171989 | compound query missed MSFT URL research task<br>compound query missed final focus sentence |

## Full Answers

### Q06 - multi_simple

**Query:** 苹果、微软、谷歌现在分别多少？

**Expected:** 多标的自然分组，不输出“本轮问题包含”。

**Session:** `eval-multi-simple`

**Eval Session:** `eval-multi-simple-smoke-fixed-artifact-render`

**Observed:** mode=`chat`, route=`research`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "AAPL"
    ],
    "operation": "price"
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
      "GOOGL"
    ],
    "operation": "price"
  }
]
```

**Plan Steps:**

```json
[
  {
    "kind": "tool",
    "name": "get_stock_price",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_stock_price",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_stock_price",
    "inputs": null,
    "task_ids": null,
    "optional": null
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
    "subject_hint": "AAPL, MSFT, GOOGL"
  },
  "relation": "new_topic",
  "domain_intent": "quote",
  "confidence": 0.9,
  "needs_tools": true,
  "reason": "用户要求获取苹果、微软、谷歌的当前价格，需要实时行情数据",
  "reply_guidance": "获取三个股票的实时价格后，以简洁列表形式回复，例如：AAPL: $xxx, MSFT: $xxx, GOOGL: $xxx",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "AAPL",
      "tickers": [
        "AAPL"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户查询苹果当前价格"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户查询微软当前价格"
    },
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户查询谷歌当前价格"
    }
  ]
}
```

**Full Answer:**

---
AAPL 最新价格约为 276.83 USD，变动 -3.42 / -1.22%。
MSFT 最新价格约为 413.62 USD，变动 -0.57 / -0.14%。
GOOGL 最新价格约为 383.25 USD，变动 -2.44 / -0.63%。
---

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-smoke-fixed-artifact-render`

**Observed:** mode=`brief`, route=`research`, verdict=`REVIEW`

**Tasks:**

```json
[
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
      "GOOGL"
    ],
    "operation": "news_impact"
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
  },
  {
    "subject_type": "company",
    "tickers": [
      "MSFT"
    ],
    "operation": "news_impact"
  }
]
```

**Plan Steps:**

```json
[
  {
    "kind": "tool",
    "name": "get_stock_price",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_company_news",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_stock_price",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_company_news",
    "inputs": null,
    "task_ids": null,
    "optional": null
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
  "reason": "用户要求实时比较GOOGL和MSFT的新闻、涨跌幅和风险点，需要工具获取最新行情和新闻数据。",
  "reply_guidance": "获取GOOGL和MSFT的实时涨跌幅和最新新闻，基于数据简要分析风险点，以简洁格式（各一句）回答。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "price",
      "params": {},
      "reason": "获取GOOGL今日涨跌幅"
    },
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "news_impact",
      "params": {},
      "reason": "获取GOOGL最新新闻以分析风险点"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "price",
      "params": {},
      "reason": "获取MSFT今日涨跌幅"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "news_impact",
      "params": {},
      "reason": "获取MSFT最新新闻以分析风险点"
    }
  ]
}
```

**Issues:**
- quick brief exceeded 60000ms latency budget

**Full Answer:**

---
GOOGL 我找到几条比较相关的消息：
- [Tokio Marine Asset Management Co. Ltd. Trims Stock Position in Alphabet Inc. $GOOGL](https://www.marketbeat.com/instant-alerts/filing-tokio-marine-asset-management-co-ltd-trims-stock-position-in-alphabet-inc-googl-2026-05-05/)（MarketBeat / 2026-05-05）
- [Celestica and Ethan Allen have been highlighted as Zacks Bull and Bear of the Day](https://www.tradingview.com/news/zacks:3eea71cc0094b:0-celestica-and-ethan-allen-have-been-highlighted-as-zacks-bull-and-bear-of-the-day/)（TradingView / 2026-05-05）
- [Bosman Wealth Management LLC Has $9.38 Million Stock Holdings in Alphabet Inc. $GOOGL](https://www.marketbeat.com/instant-alerts/filing-bosman-wealth-management-llc-has-938-million-stock-holdings-in-alphabet-inc-googl-2026-05-05/)（MarketBeat / 2026-05-05）
- GOOGL 最新价格约为 383.25 USD，变动 -2.44 / -0.63%。

MSFT 我找到几条比较相关的消息：
- [1 Unstoppable Stock to Buy Before It Joins Nvidia, Alphabet, Microsoft, and Apple in the $3 Trillion Club](https://finance.yahoo.com/search?p=1+Unstoppable+Stock+to+Buy+Before+It+Joins+Nvidia%2C+Alphabet%2C+Microsoft%2C+and+Apple+in+the+%243+Trillion+Club)（Yahoo / 2026-05-05）
- [Here’s What RBC Capital Thinks About Microsoft (MSFT) After Amended Deal With OpenAI](https://finance.yahoo.com/search?p=Here%E2%80%99s+What+RBC+Capital+Thinks+About+Microsoft+%28MSFT%29+After+Amended+Deal+With+OpenAI)（Yahoo / 2026-05-05）
- [Market Chatter: OpenAI Discussed Spinoff of Robotics, Consumer-Hardware Divisions](https://finance.yahoo.com/search?p=Market+Chatter%3A+OpenAI+Discussed+Spinoff+of+Robotics%2C+Consumer-Hardware+Divisions)（Yahoo / 2026-05-05）
- MSFT 最新价格约为 413.62 USD，变动 -0.57 / -0.14%。
- 关注下一财报季的营收指引和利润率变化
- 跟踪行业政策和竞争格局变化

来源：
- [Tokio Marine Asset Management Co. Ltd. Trims Stock Position in Alphabet Inc. $GOOGL](https://www.marketbeat.com/instant-alerts/filing-tokio-marine-asset-management-co-ltd-trims-stock-position-in-alphabet-inc-googl-2026-05-05/)（MarketBeat / 2026-05-05）
- [Celestica and Ethan Allen have been highlighted as Zacks Bull and Bear of the Day](https://www.tradingview.com/news/zacks:3eea71cc0094b:0-celestica-and-ethan-allen-have-been-highlighted-as-zacks-bull-and-bear-of-the-day/)（TradingView / 2026-05-05）
- [Bosman Wealth Management LLC Has $9.38 Million Stock Holdings in Alphabet Inc. $GOOGL](https://www.marketbeat.com/instant-alerts/filing-bosman-wealth-management-llc-has-938-million-stock-holdings-in-alphabet-inc-googl-2026-05-05/)（MarketBeat / 2026-05-05）
- [Alphabet Inc. $GOOGL Shares Sold by First Horizon Corp](https://www.marketbeat.com/instant-alerts/filing-alphabet-inc-googl-shares-sold-by-first-horizon-corp-2026-05-05/)（MarketBeat / 2026-05-05）
- [Graphene Investments SAS Decreases Stock Position in Alphabet Inc. $GOOGL](https://www.marketbeat.com/instant-alerts/filing-graphene-investments-sas-decreases-stock-position-in-alphabet-inc-googl-2026-05-05/)（MarketBeat / 2026-05-05）
---

### Q39 - multiple_simple_complex_url

**Query:** AAPL 价格、看下这个 https://example.com/msft-rates 对 MSFT 有没有用，再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。

**Expected:** 多个简单问题嵌 URL 抓取和复杂解释，fetch 作为可用工具由 planner/agent 自己选择。

**Session:** `eval-nested`

**Eval Session:** `eval-nested-smoke-fixed-artifact-render`

**Observed:** mode=`chat`, route=`research`, verdict=`REVIEW`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "AAPL"
    ],
    "operation": "price"
  },
  {
    "subject_type": "company",
    "tickers": [
      "MSFT"
    ],
    "operation": "price"
  },
  {
    "subject_type": "macro",
    "tickers": [],
    "operation": "analyze_impact"
  }
]
```

**Plan Steps:**

```json
[
  {
    "kind": "tool",
    "name": "get_stock_price",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_stock_price",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "fetch_url_content",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "search",
    "inputs": null,
    "task_ids": null,
    "optional": null
  }
]
```

**Conversation Router:**

```json
{
  "execution_route": "research",
  "context_binding": {
    "source": "none",
    "confidence": 0.6,
    "reason": "",
    "subject_hint": ""
  },
  "relation": "new_topic",
  "domain_intent": "analysis",
  "confidence": 0.62,
  "needs_tools": true,
  "reason": "explicit subject context",
  "reply_guidance": "",
  "task_hints": []
}
```

**Issues:**
- compound query missed MSFT URL research task
- compound query missed final focus sentence

**Full Answer:**

---
AAPL, MSFT 这次先看这些来源：
- [https://example.com/msft-rates](https://example.com/msft-rates)（url）

- 高估值股票怕利率上升，主要因为：利率上升会提高贴现率，降低未来现金流的现值，从而压低估值；同时增加借贷成本，影响公司融资和资本开支；并可能降低风险偏好，导致资金从成长股流出。

AAPL, MSFT 最新价格约为 276.83 USD，变动 -3.42 / -1.22%。

MSFT 相关链接这次没有拿到可读正文（fetch_failed）：https://example.com/msft-rates。所以我先不把它当作支持证据，只能说需要换成可访问正文后再判断。

来源：
- [https://example.com/msft-rates](https://example.com/msft-rates)（url）
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q20 `quick_brief`: quick brief exceeded 60000ms latency budget
- Q39 `multiple_simple_complex_url`: compound query missed MSFT URL research task, compound query missed final focus sentence
