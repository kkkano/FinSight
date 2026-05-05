# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T22:37:49`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `0` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `108.4s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q20 | quick_brief | REVIEW | brief | research | 106748 | quick brief exceeded 60000ms latency budget |

## Full Answers

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-smoke-quick-brief-fast-route`

**Observed:** mode=`brief`, route=`research`, verdict=`REVIEW`

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
- quick brief exceeded 60000ms latency budget

**Full Answer:**

---
我先按 GOOGL, MSFT 这组代表标的看。

GOOGL:
- GOOGL 最新价格约为 388.61 USD，变动 5.36 / 1.40%。
- 相关消息：[GOOGL Yahoo Finance news](https://finance.yahoo.com/quote/GOOGL/news)（Yahoo Finance / 2026-05-05）；[GOOGL latest stock news search](https://www.google.com/search?q=GOOGL+latest+stock+news)（Search / 2026-05-05）

MSFT:
- MSFT 最新价格约为 409.96 USD，变动 -3.66 / -0.88%。
- 相关消息：[MSFT Yahoo Finance news](https://finance.yahoo.com/quote/MSFT/news)（Yahoo Finance / 2026-05-05）；[MSFT latest stock news search](https://www.google.com/search?q=MSFT+latest+stock+news)（Search / 2026-05-05）

按这次拿到的涨跌幅，GOOGL 暂时更强（1.40% vs MSFT -0.88%）。
风险上先看新闻标题能不能落实到收入、利润率或指引；只靠标题还不能证明基本面已经变化。

来源：
- [GOOGL Yahoo Finance news](https://finance.yahoo.com/quote/GOOGL/news)（Yahoo Finance / 2026-05-05）
- [GOOGL latest stock news search](https://www.google.com/search?q=GOOGL+latest+stock+news)（Search / 2026-05-05）
- [MSFT Yahoo Finance news](https://finance.yahoo.com/quote/MSFT/news)（Yahoo Finance / 2026-05-05）
- [MSFT latest stock news search](https://www.google.com/search?q=MSFT+latest+stock+news)（Search / 2026-05-05）
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q20 `quick_brief`: quick brief exceeded 60000ms latency budget
