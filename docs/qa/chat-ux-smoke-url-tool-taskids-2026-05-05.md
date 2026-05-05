# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T23:20:48`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `2` PASS, `0` REVIEW, `0` FAIL
- Elapsed: `43.0s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q20 | quick_brief | PASS | brief | research | 17929 | - |
| Q39 | multiple_simple_complex_url | PASS | chat | research | 23337 | - |

## Full Answers

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-url-tool-taskids-2026-05-05`

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
    "reason": "brief turn has explicit current-turn subject and no prior context to bind",
    "subject_hint": "GOOGL, MSFT"
  },
  "relation": "new_topic",
  "domain_intent": "analysis",
  "confidence": 0.72,
  "needs_tools": true,
  "reason": "explicit brief request can be decomposed by request understanding without context binding",
  "reply_guidance": "",
  "task_hints": []
}
```

**Full Answer:**

---
我先按 GOOGL, MSFT 这组代表标的看。

GOOGL:
- GOOGL 最新价格约为 388.59 USD，变动 5.34 / 1.39%。
- 相关消息：[GOOGL Yahoo Finance news](https://finance.yahoo.com/quote/GOOGL/news)（Yahoo Finance / 2026-05-05）；[GOOGL latest stock news search](https://www.google.com/search?q=GOOGL+latest+stock+news)（Search / 2026-05-05）

MSFT:
- MSFT 最新价格约为 410.47 USD，变动 -3.15 / -0.76%。
- 相关消息：[MSFT Yahoo Finance news](https://finance.yahoo.com/quote/MSFT/news)（Yahoo Finance / 2026-05-05）；[MSFT latest stock news search](https://www.google.com/search?q=MSFT+latest+stock+news)（Search / 2026-05-05）

按这次拿到的涨跌幅，GOOGL 暂时更强（1.39% vs MSFT -0.76%）。
风险上先看新闻标题能不能落实到收入、利润率或指引；只靠标题还不能证明基本面已经变化。

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

**Eval Session:** `eval-nested-url-tool-taskids-2026-05-05`

**Observed:** mode=`chat`, route=`research`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "research_doc",
    "tickers": [
      "AAPL",
      "MSFT"
    ],
    "operation": "qa"
  },
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
    "operation": "qa"
  }
]
```

**Plan Steps:**

```json
[
  {
    "kind": "tool",
    "name": "fetch_url_content",
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
    "reason": "brief turn has explicit current-turn subject and no prior context to bind",
    "subject_hint": "AAPL, MSFT"
  },
  "relation": "new_topic",
  "domain_intent": "analysis",
  "confidence": 0.72,
  "needs_tools": true,
  "reason": "explicit brief request can be decomposed by request understanding without context binding",
  "reply_guidance": "",
  "task_hints": []
}
```

**Full Answer:**

---
AAPL 最新价格约为 280.23 USD，变动 3.36 / 1.21%。
MSFT 最新价格约为 410.47 USD，变动 -3.15 / -0.76%。

AAPL 相关链接这次没有拿到可读正文（fetch_failed）：https://example.com/msft-rates。所以我先不把它当作支持证据，只能说需要换成可访问正文后再判断。

利率影响估值，核心是折现率和机会成本：利率上行会降低远期现金流的现值，也会让无风险收益率更有吸引力。
所以 AAPL, MSFT 更敏感，后面要看利率预期是否继续压低估值倍数，以及业绩指引能不能抵消这部分压力。
这类问题我不硬给单点结论，先看利率预期、业绩指引和价格反应能否互相验证。

一句话：先关注利率和通胀预期是否继续压估值，再看 AAPL/MSFT 的业绩指引和价格反应能不能抵消压力。

来源：
- [https://example.com/msft-rates](https://example.com/msft-rates)（url）
---

## Follow-Up Analysis

All deterministic checks passed. Manual review should still read the full answers above for tone and usefulness.
