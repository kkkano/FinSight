# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T22:28:20`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `0` PASS, `2` REVIEW, `0` FAIL
- Elapsed: `165.2s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q20 | quick_brief | REVIEW | brief | research | 66305 | quick brief exceeded 60000ms latency budget |
| Q39 | multiple_simple_complex_url | REVIEW | chat | research | 97072 | compound query missed high-valuation/rates explanation<br>compound query missed final focus sentence |

## Full Answers

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-smoke-url-taskgraph-support`

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
    "operation": "analyze_impact"
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
  "reason": "需要获取 GOOGL 和 MSFT 的最新行情、新闻和风险点信息以进行快速比较。",
  "reply_guidance": "由于需要实时数据，将通过工具获取信息后，以简洁格式回答：新闻一句、涨跌幅一句、风险点一句，并比较谁更强。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "price",
      "params": {
        "date": "today"
      },
      "reason": "获取 GOOGL 今天的涨跌幅。"
    },
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "fetch",
      "params": {
        "date": "today",
        "topic": "news"
      },
      "reason": "获取 GOOGL 今天的相关新闻。"
    },
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "analyze_impact",
      "params": {
        "aspect": "risk"
      },
      "reason": "分析 GOOGL 的风险点。"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "price",
      "params": {
        "date": "today"
      },
      "reason": "获取 MSFT 今天的涨跌幅。"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "fetch",
      "params": {
        "date": "today",
        "topic": "news"
      },
      "reason": "获取 MSFT 今天的相关新闻。"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "analyze_impact",
      "params": {
        "aspect": "risk"
      },
      "reason": "分析 MSFT 的风险点。"
    }
  ]
}
```

**Issues:**
- quick brief exceeded 60000ms latency budget

**Full Answer:**

---
GOOGL 我找到几条比较相关的消息：
- [GOOGL Yahoo Finance news](https://finance.yahoo.com/quote/GOOGL/news)（Yahoo Finance / 2026-05-05）
- [GOOGL latest stock news search](https://www.google.com/search?q=GOOGL+latest+stock+news)（Search / 2026-05-05）
- GOOGL 最新价格约为 388.10 USD，变动 4.85 / 1.27%。

MSFT 我找到几条比较相关的消息：
- [MSFT Yahoo Finance news](https://finance.yahoo.com/quote/MSFT/news)（Yahoo Finance / 2026-05-05）
- [MSFT latest stock news search](https://www.google.com/search?q=MSFT+latest+stock+news)（Search / 2026-05-05）
- MSFT 最新价格约为 410.63 USD，变动 -2.99 / -0.72%。
- 关注下一财报季的营收指引和利润率变化
- 跟踪行业政策和竞争格局变化

来源：
- [GOOGL Yahoo Finance news](https://finance.yahoo.com/quote/GOOGL/news)（Yahoo Finance / 2026-05-05）
- [GOOGL latest stock news search](https://www.google.com/search?q=GOOGL+latest+stock+news)（Search / 2026-05-05）
- [MSFT Yahoo Finance news](https://finance.yahoo.com/quote/MSFT/news)（Yahoo Finance / 2026-05-05）
- [MSFT latest stock news search](https://www.google.com/search?q=MSFT+latest+stock+news)（Search / 2026-05-05）
---

### Q39 - multiple_simple_complex_url

**Query:** AAPL 价格、看下这个 https://example.com/msft-rates 对 MSFT 有没有用，再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。

**Expected:** 多个简单问题嵌 URL 抓取和复杂解释，fetch 作为可用工具由 planner/agent 自己选择。

**Session:** `eval-nested`

**Eval Session:** `eval-nested-smoke-url-taskgraph-support`

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
    "operation": "qa"
  },
  {
    "subject_type": "macro",
    "tickers": [],
    "operation": "qa"
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
    "name": "fetch_url_content",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_current_datetime",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_official_macro_releases",
    "inputs": null,
    "task_ids": null,
    "optional": null
  },
  {
    "kind": "tool",
    "name": "get_authoritative_media_news",
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
    "confidence": 0.0,
    "reason": "current user turn contains explicit subject(s), so implicit history was ignored",
    "subject_hint": "AAPL, MSFT"
  },
  "relation": "new_topic",
  "domain_intent": "analysis",
  "confidence": 0.8,
  "needs_tools": true,
  "reason": "用户需要实时价格、URL内容分析和金融概念解释，涉及多个工具调用",
  "reply_guidance": "执行研究：先获取AAPL当前价格，然后读取URL内容评估对MSFT的有用性，接着解释高估值股票对利率敏感的机制，最后基于结果总结用户应关注的一句话。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "AAPL",
      "tickers": [
        "AAPL"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户请求AAPL的当前价格"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "qa",
      "params": {
        "url": "https://example.com/msft-rates"
      },
      "reason": "用户要求评估URL内容对MSFT的相关性，需先获取内容"
    },
    {
      "subject_type": "macro",
      "subject_label": "利率与估值",
      "tickers": [],
      "operation": "qa",
      "params": {},
      "reason": "用户请求解释为什么高估值股票害怕利率上升，属于金融概念解释"
    }
  ]
}
```

**Issues:**
- compound query missed high-valuation/rates explanation
- compound query missed final focus sentence

**Full Answer:**

---
AAPL 最新价格约为 281.16 USD，变动 4.29 / 1.55%。
MSFT 的实时价格这次没有拿到可用报价。可以稍后重试，或切到行情页确认最新成交价。
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q20 `quick_brief`: quick brief exceeded 60000ms latency budget
- Q39 `multiple_simple_complex_url`: compound query missed high-valuation/rates explanation, compound query missed final focus sentence
