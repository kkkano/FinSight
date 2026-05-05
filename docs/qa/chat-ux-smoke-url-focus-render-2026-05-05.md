# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T19:58:03`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `0` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `111.8s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q39 | multiple_simple_complex_url | REVIEW | chat | research | 109748 | compound query missed final focus sentence |

## Full Answers

### Q39 - multiple_simple_complex_url

**Query:** AAPL 价格、看下这个 https://example.com/msft-rates 对 MSFT 有没有用，再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。

**Expected:** 多个简单问题嵌 URL 抓取和复杂解释，fetch 作为可用工具由 planner/agent 自己选择。

**Session:** `eval-nested`

**Eval Session:** `eval-nested-smoke-url-focus-render`

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
      "MSFT",
      "URL"
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
  "reason": "用户请求实时价格、URL内容分析、概念解释和总结，需要工具支持",
  "reply_guidance": "先获取AAPL价格和读取URL内容，然后解释高估值与利率的关系，最后基于结果给出一句话总结建议",
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
      "subject_type": "research_doc",
      "subject_label": "URL内容",
      "tickers": [
        "MSFT",
        "URL"
      ],
      "operation": "qa",
      "params": {
        "url": "https://example.com/msft-rates"
      },
      "reason": "用户要求分析URL对MSFT的相关性"
    },
    {
      "subject_type": "macro",
      "subject_label": "高估值与利率关系",
      "tickers": [],
      "operation": "analyze_impact",
      "params": {},
      "reason": "用户请求解释为什么高估值怕利率"
    },
    {
      "subject_type": "unknown",
      "subject_label": "总结建议",
      "tickers": [],
      "operation": "qa",
      "params": {},
      "reason": "用户要求用一句话总结关注点"
    }
  ]
}
```

**Issues:**
- compound query missed final focus sentence

**Full Answer:**

---
(empty)
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q39 `multiple_simple_complex_url`: compound query missed final focus sentence
