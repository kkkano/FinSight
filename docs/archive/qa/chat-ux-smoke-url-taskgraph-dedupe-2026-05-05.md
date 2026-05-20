# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T22:12:14`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `1` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `268.9s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q20 | quick_brief | REVIEW | brief | research | 137650 | quick brief exceeded 60000ms latency budget |
| Q39 | multiple_simple_complex_url | PASS | chat | research | 129604 | - |

## Full Answers

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-smoke-url-taskgraph-dedupe`

**Observed:** mode=`brief`, route=`research`, verdict=`REVIEW`

**Tasks:**

```json
[
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
    "operation": "fetch"
  }
]
```

**Plan Steps:**

```json
[
  {
    "kind": "tool",
    "name": "get_company_news",
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
  "reason": "用户要求快速比较 GOOGL 和 MSFT 的实时表现，需要获取最新行情、新闻和风险数据",
  "reply_guidance": "提供简洁的比较：先判断谁更强，然后分别用一句话描述 GOOGL 和 MSFT 的新闻、涨跌幅和风险点。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "fetch",
      "params": {
        "topic": "news"
      },
      "reason": "用户要求 GOOGL 的新闻、涨跌幅和风险点"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "fetch",
      "params": {
        "topic": "news"
      },
      "reason": "用户要求 MSFT 的新闻、涨跌幅和风险点"
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

MSFT 我找到几条比较相关的消息：
- [MSFT Yahoo Finance news](https://finance.yahoo.com/quote/MSFT/news)（Yahoo Finance / 2026-05-05）
- [MSFT latest stock news search](https://www.google.com/search?q=MSFT+latest+stock+news)（Search / 2026-05-05）

我先只列出可引用消息；这轮没有足够证据支撑进一步影响判断。

- 关注：后续公告/财报指引、交付数据、监管与诉讼进展。
- 验证：价格反应/成交量/波动是否与叙事一致。

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

**Eval Session:** `eval-nested-smoke-url-taskgraph-dedupe`

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
    "subject_type": "research_doc",
    "tickers": [
      "MSFT"
    ],
    "operation": "qa"
  },
  {
    "subject_type": "macro",
    "tickers": [],
    "operation": "analyze_impact"
  },
  {
    "subject_type": "unknown",
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
  "reason": "用户需要实时价格、URL 内容分析和金融概念解释，涉及多个工具调用",
  "reply_guidance": "先获取 AAPL 实时价格，然后读取 URL 内容评估其对 MSFT 的相关性，接着解释高估值股票对利率敏感的原因，最后总结用户应关注的关键点。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "AAPL",
      "tickers": [
        "AAPL"
      ],
      "operation": "price",
      "params": {},
      "reason": "获取 AAPL 实时价格"
    },
    {
      "subject_type": "research_doc",
      "subject_label": "MSFT 相关文档",
      "tickers": [
        "MSFT"
      ],
      "operation": "qa",
      "params": {
        "url": "https://example.com/msft-rates"
      },
      "reason": "评估 URL 内容对 MSFT 的用处"
    },
    {
      "subject_type": "macro",
      "subject_label": "利率与高估值",
      "tickers": [],
      "operation": "analyze_impact",
      "params": {},
      "reason": "解释为什么高估值股票怕利率上升"
    },
    {
      "subject_type": "unknown",
      "subject_label": "投资关注点",
      "tickers": [],
      "operation": "qa",
      "params": {},
      "reason": "总结用户应关注什么"
    }
  ]
}
```

**Full Answer:**

---
利率与高估值 我找到几条比较相关的消息：
- [Major Economic Indicators Latest Numbers](https://www.bls.gov/bls/)（BLS / 2026-05-05）

AAPL 最新价格约为 279.49 USD，变动 2.62 / 0.95%。

MSFT 相关链接这次没有拿到可读正文（fetch_failed）：https://example.com/msft-rates。所以我先不把它当作支持证据，只能说需要换成可访问正文后再判断。

- 高估值股票对利率敏感，主要因为未来现金流的折现率上升会直接压低估值。当前宏观数据显示，2026年3月美国CPI环比上涨0.9%，通胀压力可能支撑利率维持高位，这对高估值成长股构成挑战。市场分析也指出，高利率与高估值同现时，投资者风险偏好易受抑制。

- 一句话关注：接下来重点观察美联储政策信号及 AAPL 基本面能否匹配当前估值水平。

来源：
- [Major Economic Indicators Latest Numbers](https://www.bls.gov/bls/)（BLS / 2026-05-05）
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q20 `quick_brief`: quick brief exceeded 60000ms latency budget
