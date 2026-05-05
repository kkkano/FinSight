# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T19:21:07`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `0` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `64.4s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q20 | quick_brief | REVIEW | brief | research | 62251 | quick brief exceeded 60000ms latency budget |

## Full Answers

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-smoke-brief-takeaway`

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
  "reason": "用户需要最新行情、新闻和风险点来比较 GOOGL 和 MSFT 的今天表现。",
  "reply_guidance": "获取 GOOGL 和 MSFT 的最新价格、涨跌幅、相关新闻和风险点，然后简洁比较谁更强，各用一句话总结。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "analyze_impact",
      "params": {
        "info": [
          "news",
          "price_change",
          "risk"
        ]
      },
      "reason": "获取 GOOGL 的新闻、涨跌幅和风险点。"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "analyze_impact",
      "params": {
        "info": [
          "news",
          "price_change",
          "risk"
        ]
      },
      "reason": "获取 MSFT 的新闻、涨跌幅和风险点。"
    }
  ]
}
```

**Issues:**
- quick brief exceeded 60000ms latency budget

**Full Answer:**

---
GOOGL 我找到几条比较相关的消息：
- [Move Over Nvidia: Why Alphabet's Surprising Decision to Sell Custom AI Chips Changes Everything.](https://finance.yahoo.com/search?p=Move+Over+Nvidia%3A+Why+Alphabet%27s+Surprising+Decision+to+Sell+Custom+AI+Chips+Changes+Everything.)（Yahoo / 2026-05-05）
- [Zacks Investment Ideas feature highlights: Meta Platforms, Amazon, Alphabet, Microsoft and Nebius](https://finance.yahoo.com/search?p=Zacks+Investment+Ideas+feature+highlights%3A+Meta+Platforms%2C+Amazon%2C+Alphabet%2C+Microsoft+and+Nebius)（Yahoo / 2026-05-05）
- [Will Ulta’s (ULTA) Gemini-Powered “Ulta AI” and NielsenIQ Tie-Up Change Its Digital Narrative?](https://finance.yahoo.com/search?p=Will+Ulta%E2%80%99s+%28ULTA%29+Gemini-Powered+%E2%80%9CUlta+AI%E2%80%9D+and+NielsenIQ+Tie-Up+Change+Its+Digital+Narrative%3F)（Yahoo / 2026-05-05）
- GOOGL 最新价格约为 383.25 USD，变动 -2.44 / -0.63%。

MSFT 我找到几条比较相关的消息：
- [Market Chatter: OpenAI Discussed Spinoff of Robotics, Consumer-Hardware Divisions](https://finance.yahoo.com/search?p=Market+Chatter%3A+OpenAI+Discussed+Spinoff+of+Robotics%2C+Consumer-Hardware+Divisions)（Yahoo / 2026-05-05）
- [Zacks Investment Ideas feature highlights: Meta Platforms, Amazon, Alphabet, Microsoft and Nebius](https://finance.yahoo.com/search?p=Zacks+Investment+Ideas+feature+highlights%3A+Meta+Platforms%2C+Amazon%2C+Alphabet%2C+Microsoft+and+Nebius)（Yahoo / 2026-05-05）
- [Nscale to Deliver 66,000+ NVIDIA Rubin GPUs to Microsoft at Start Campus' Site in Portugal](https://finance.yahoo.com/search?p=Nscale+to+Deliver+66%2C000%2B+NVIDIA+Rubin+GPUs+to+Microsoft+at+Start+Campus%27+Site+in+Portugal)（Yahoo / 2026-05-05）
- MSFT 最新价格约为 413.62 USD，变动 -0.57 / -0.14%。
- 关注下一财报季的营收指引和利润率变化
- 跟踪行业政策和竞争格局变化

来源：
- [Move Over Nvidia: Why Alphabet's Surprising Decision to Sell Custom AI Chips Changes Everything.](https://finance.yahoo.com/search?p=Move+Over+Nvidia%3A+Why+Alphabet%27s+Surprising+Decision+to+Sell+Custom+AI+Chips+Changes+Everything.)（Yahoo / 2026-05-05）
- [Zacks Investment Ideas feature highlights: Meta Platforms, Amazon, Alphabet, Microsoft and Nebius](https://finance.yahoo.com/search?p=Zacks+Investment+Ideas+feature+highlights%3A+Meta+Platforms%2C+Amazon%2C+Alphabet%2C+Microsoft+and+Nebius)（Yahoo / 2026-05-05）
- [Will Ulta’s (ULTA) Gemini-Powered “Ulta AI” and NielsenIQ Tie-Up Change Its Digital Narrative?](https://finance.yahoo.com/search?p=Will+Ulta%E2%80%99s+%28ULTA%29+Gemini-Powered+%E2%80%9CUlta+AI%E2%80%9D+and+NielsenIQ+Tie-Up+Change+Its+Digital+Narrative%3F)（Yahoo / 2026-05-05）
- [Alphabet Returns to Euro Debt Market for Latest AI Megabond Deal](https://finance.yahoo.com/search?p=Alphabet+Returns+to+Euro+Debt+Market+for+Latest+AI+Megabond+Deal)（Yahoo / 2026-05-05）
- [Why Alphabet Stock Soared 34% in April -- One Catalyst Is Its Move to Challenge Data Center AI Chip Leader Nvidia](https://finance.yahoo.com/search?p=Why+Alphabet+Stock+Soared+34%25+in+April+--+One+Catalyst+Is+Its+Move+to+Challenge+Data+Center+AI+Chip+Leader+Nvidia)（Yahoo / 2026-05-05）
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q20 `quick_brief`: quick brief exceeded 60000ms latency budget
