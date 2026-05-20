# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T19:37:52`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `0` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `172.1s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q39 | multiple_simple_complex_url | REVIEW | chat | research | 169919 | compound query missed MSFT news task<br>compound URL query did not plan fetch_url_content as an agent/planner tool<br>compound query missed final focus sentence |

## Full Answers

### Q39 - multiple_simple_complex_url

**Query:** AAPL 价格、看下这个 https://example.com/msft-rates 对 MSFT 有没有用，再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。

**Expected:** 多个简单问题嵌 URL 抓取和复杂解释，fetch 作为可用工具由 planner/agent 自己选择。

**Session:** `eval-nested`

**Eval Session:** `eval-nested-smoke-url-agent-tool`

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
  "reason": "用户请求实时价格（AAPL）和外部 URL 内容（MSFT 相关），需要工具执行；解释部分可直接回答，但整体需工具支持。",
  "reply_guidance": "先获取 AAPL 实时价格，然后读取 URL 内容评估对 MSFT 的相关性，接着解释高估值与利率的关系，最后总结用户应关注什么。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "AAPL",
      "tickers": [
        "AAPL"
      ],
      "operation": "price",
      "params": {},
      "reason": "获取 AAPL 实时价格。"
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
      "reason": "读取 URL 内容并评估对 MSFT 的用处。"
    },
    {
      "subject_type": "macro",
      "subject_label": "利率与估值",
      "tickers": [],
      "operation": "qa",
      "params": {},
      "reason": "解释高估值股票为什么怕利率上升。"
    },
    {
      "subject_type": "portfolio",
      "subject_label": "投资关注点",
      "tickers": [],
      "operation": "qa",
      "params": {},
      "reason": "总结用户应关注什么。"
    }
  ]
}
```

**Issues:**
- compound query missed MSFT news task
- compound URL query did not plan fetch_url_content as an agent/planner tool
- compound query missed final focus sentence

**Full Answer:**

---
我先按你给的持仓看：AAPL, MSFT。

- 你给的链接（example.com/msft-rates）我没能读取到有效内容——返回的是美国劳工统计局（BLS）的宏观指标汇总，包括 3 月 CPI +0.9%、失业率 4.3%、新增非农就业 17.8 万等，这些数据对判断利率环境有参考价值，但并非 MSFT 专属信息。如果你有具体的 MSFT 利率敏感性分析文档，可以换个链接再试。
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q39 `multiple_simple_complex_url`: compound query missed MSFT news task, compound URL query did not plan fetch_url_content as an agent/planner tool, compound query missed final focus sentence
