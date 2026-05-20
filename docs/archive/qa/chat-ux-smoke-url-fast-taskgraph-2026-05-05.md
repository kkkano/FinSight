# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T20:08:12`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `0` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `106.9s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q39 | multiple_simple_complex_url | REVIEW | chat | research | 105029 | compound query missed MSFT URL research task<br>compound URL query did not plan fetch_url_content as an agent/planner tool<br>compound query missed high-valuation/rates explanation<br>compound query missed final focus sentence |

## Full Answers

### Q39 - multiple_simple_complex_url

**Query:** AAPL 价格、看下这个 https://example.com/msft-rates 对 MSFT 有没有用，再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。

**Expected:** 多个简单问题嵌 URL 抓取和复杂解释，fetch 作为可用工具由 planner/agent 自己选择。

**Session:** `eval-nested`

**Eval Session:** `eval-nested-smoke-url-fast-taskgraph`

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
    "subject_type": "unknown",
    "tickers": [
      "MSFT"
    ],
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
  "confidence": 0.9,
  "needs_tools": true,
  "reason": "用户请求涉及实时价格获取和URL内容分析，需要工具支持",
  "reply_guidance": "先查询AAPL当前价格，然后读取URL内容评估对MSFT的相关性，接着解释高估值股票对利率敏感的原因，最后基于分析给出一句话关注点。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "AAPL",
      "tickers": [
        "AAPL"
      ],
      "operation": "price",
      "params": {},
      "reason": "用户请求AAPL价格"
    },
    {
      "subject_type": "unknown",
      "subject_label": "https://example.com/msft-rates",
      "tickers": [
        "MSFT"
      ],
      "operation": "qa",
      "params": {
        "url": "https://example.com/msft-rates"
      },
      "reason": "用户要求分析URL内容对MSFT的相关性"
    }
  ]
}
```

**Issues:**
- compound query missed MSFT URL research task
- compound URL query did not plan fetch_url_content as an agent/planner tool
- compound query missed high-valuation/rates explanation
- compound query missed final focus sentence

**Full Answer:**

---
(empty)
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q39 `multiple_simple_complex_url`: compound query missed MSFT URL research task, compound URL query did not plan fetch_url_content as an agent/planner tool, compound query missed high-valuation/rates explanation, compound query missed final focus sentence
