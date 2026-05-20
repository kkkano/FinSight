# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T20:57:16`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `2` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `226.7s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q06 | multi_simple | PASS | chat | research | 46989 | - |
| Q20 | quick_brief | PASS | brief | research | 71504 | - |
| Q39 | multiple_simple_complex_url | REVIEW | chat | research | 106041 | compound query missed high-valuation/rates explanation<br>compound query missed final focus sentence |

## Full Answers

### Q06 - multi_simple

**Query:** 苹果、微软、谷歌现在分别多少？

**Expected:** 多标的自然分组，不输出“本轮问题包含”。

**Session:** `eval-multi-simple`

**Eval Session:** `eval-multi-simple-smoke-multiquote-url`

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
    "subject_hint": "AAPL, GOOGL, MSFT"
  },
  "relation": "new_topic",
  "domain_intent": "quote",
  "confidence": 0.9,
  "needs_tools": true,
  "reason": "用户直接询问三个股票的当前价格，需要实时行情数据",
  "reply_guidance": "获取 AAPL、MSFT、GOOGL 的当前价格并呈现给用户",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "AAPL",
      "tickers": [
        "AAPL"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户询问苹果当前价格"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户询问微软当前价格"
    },
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户询问谷歌当前价格"
    }
  ]
}
```

**Full Answer:**

---
(empty)
---

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-smoke-multiquote-url`

**Observed:** mode=`brief`, route=`research`, verdict=`PASS`

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
      "GOOGL",
      "MSFT"
    ],
    "operation": "compare"
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
  "reason": "用户要求实时比较 GOOGL 和 MSFT 的新闻、涨跌幅和风险点，需要工具获取最新数据",
  "reply_guidance": "简洁回答：先比较谁更强，然后各给一句新闻、涨跌幅、风险点。避免长篇大论。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "GOOGL vs MSFT",
      "tickers": [
        "GOOGL",
        "MSFT"
      ],
      "operation": "compare",
      "params": {},
      "reason": "用户要求快速比较两者今日表现，包括新闻、涨跌幅和风险点"
    }
  ]
}
```

**Full Answer:**

---
(empty)
---

### Q39 - multiple_simple_complex_url

**Query:** AAPL 价格、看下这个 https://example.com/msft-rates 对 MSFT 有没有用，再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。

**Expected:** 多个简单问题嵌 URL 抓取和复杂解释，fetch 作为可用工具由 planner/agent 自己选择。

**Session:** `eval-nested`

**Eval Session:** `eval-nested-smoke-multiquote-url`

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
    "subject_type": "research_doc",
    "tickers": [
      "MSFT"
    ],
    "operation": "qa"
  },
  {
    "subject_type": "macro",
    "tickers": [],
    "operation": "qa"
  },
  {
    "subject_type": "portfolio",
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
  "reason": "需要获取实时行情、读取外部文档并解释金融概念",
  "reply_guidance": "分步处理：1. 获取 AAPL 当前价格；2. 读取 URL 内容并评估对 MSFT 的用处；3. 解释高估值股票为什么怕利率上升；4. 基于以上给出一句话关注建议。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "AAPL",
      "tickers": [
        "AAPL"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户请求 AAPL 价格"
    },
    {
      "subject_type": "research_doc",
      "subject_label": "MSFT rates document",
      "tickers": [
        "MSFT"
      ],
      "operation": "qa",
      "params": {
        "url": "https://example.com/msft-rates"
      },
      "reason": "用户要求评估 URL 内容对 MSFT 的用处"
    },
    {
      "subject_type": "macro",
      "subject_label": "利率与估值关系",
      "tickers": [],
      "operation": "qa",
      "params": {},
      "reason": "用户请求解释高估值怕利率的原因"
    },
    {
      "subject_type": "portfolio",
      "subject_label": "投资关注点",
      "tickers": [],
      "operation": "qa",
      "params": {},
      "reason": "用户要求一句话总结该关注什么"
    }
  ]
}
```

**Issues:**
- compound query missed high-valuation/rates explanation
- compound query missed final focus sentence

**Full Answer:**

---
(empty)
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q39 `multiple_simple_complex_url`: compound query missed high-valuation/rates explanation, compound query missed final focus sentence
