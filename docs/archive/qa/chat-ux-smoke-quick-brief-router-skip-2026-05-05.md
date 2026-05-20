# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T22:43:21`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `0` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `95.8s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q20 | quick_brief | REVIEW | brief | research | 94144 | quick brief exceeded 60000ms latency budget |

## Full Answers

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-smoke-quick-brief-router-skip`

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
- GOOGL 最新价格约为 388.07 USD，变动 1.73 / 0.45%。
- 相关消息：[GOOGL Yahoo Finance news](https://finance.yahoo.com/quote/GOOGL/news)（Yahoo Finance / 2026-05-05）；[GOOGL latest stock news search](https://www.google.com/search?q=GOOGL+latest+stock+news)（Search / 2026-05-05）

MSFT:
- MSFT 最新价格约为 410.62 USD，变动 -4.51 / -1.09%。
- 相关消息：[MSFT Yahoo Finance news](https://finance.yahoo.com/quote/MSFT/news)（Yahoo Finance / 2026-05-05）；[MSFT latest stock news search](https://www.google.com/search?q=MSFT+latest+stock+news)（Search / 2026-05-05）

- 今日 GOOGL 胜出：涨跌幅 +0.45% vs -1.09%，方向和幅度都拉开差距。

来源：
- [GOOGL Yahoo Finance news](https://finance.yahoo.com/quote/GOOGL/news)（Yahoo Finance / 2026-05-05）
- [GOOGL latest stock news search](https://www.google.com/search?q=GOOGL+latest+stock+news)（Search / 2026-05-05）
- [MSFT Yahoo Finance news](https://finance.yahoo.com/quote/MSFT/news)（Yahoo Finance / 2026-05-05）
- [MSFT latest stock news search](https://www.google.com/search?q=MSFT+latest+stock+news)（Search / 2026-05-05）
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q20 `quick_brief`: quick brief exceeded 60000ms latency budget
