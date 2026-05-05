# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T17:24:40`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `0` PASS, `1` REVIEW, `0` FAIL
- Elapsed: `170.2s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q20 | quick_brief | REVIEW | brief | research | 167998 | quick brief exceeded 60000ms latency budget |

## Full Answers

### Q20 - quick_brief

**Query:** 先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。

**Expected:** 快速回答可用 brief，但仍应自然，不输出奇怪模板。

**Session:** `eval-quick-brief`

**Eval Session:** `eval-quick-brief-20260505172440-50c351`

**Observed:** mode=`brief`, route=`research`, verdict=`REVIEW`

**Tasks:**

```json
[
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
  "reason": "用户需要实时新闻、涨跌幅和风险点数据来比较 GOOGL 和 MSFT",
  "reply_guidance": "获取 GOOGL 和 MSFT 的最新新闻、今日涨跌幅和关键风险点，然后简洁比较谁更强，各用一句话总结。",
  "task_hints": [
    {
      "subject_type": "company",
      "subject_label": "GOOGL",
      "tickers": [
        "GOOGL"
      ],
      "operation": "analyze_impact",
      "params": {
        "time_frame": "today"
      },
      "reason": "获取 GOOGL 今日新闻、涨跌幅和风险点"
    },
    {
      "subject_type": "company",
      "subject_label": "MSFT",
      "tickers": [
        "MSFT"
      ],
      "operation": "analyze_impact",
      "params": {
        "time_frame": "today"
      },
      "reason": "获取 MSFT 今日新闻、涨跌幅和风险点"
    }
  ]
}
```

**Issues:**
- quick brief exceeded 60000ms latency budget

**Full Answer:**

---
GOOGL 我找到几条比较相关的消息：
- [Will Ulta’s (ULTA) Gemini-Powered “Ulta AI” and NielsenIQ Tie-Up Change Its Digital Narrative?](https://finance.yahoo.com/search?p=Will+Ulta%E2%80%99s+%28ULTA%29+Gemini-Powered+%E2%80%9CUlta+AI%E2%80%9D+and+NielsenIQ+Tie-Up+Change+Its+Digital+Narrative%3F)（Yahoo / 2026-05-05）
- [Alphabet Returns to Euro Debt Market for Latest AI Megabond Deal](https://finance.yahoo.com/search?p=Alphabet+Returns+to+Euro+Debt+Market+for+Latest+AI+Megabond+Deal)（Yahoo / 2026-05-05）
- [Why Alphabet Stock Soared 34% in April -- One Catalyst Is Its Move to Challenge Data Center AI Chip Leader Nvidia](https://finance.yahoo.com/search?p=Why+Alphabet+Stock+Soared+34%25+in+April+--+One+Catalyst+Is+Its+Move+to+Challenge+Data+Center+AI+Chip+Leader+Nvidia)（Yahoo / 2026-05-05）
- GOOGL 最新价格约为 383.25 USD，变动 -2.44 / -0.63%。

MSFT 我找到几条比较相关的消息：
- [Microsoft: The Market Is Pricing AI Costs, Not AI Returns](https://www.google.com/search?q=Microsoft%3A+The+Market+Is+Pricing+AI+Costs%2C+Not+AI+Returns)（SeekingAlpha / 2026-05-05）
- [Microsoft: Continued AI And Software Concerns](https://www.google.com/search?q=Microsoft%3A+Continued+AI+And+Software+Concerns)（SeekingAlpha / 2026-05-04）
- [Adeia Announces First Quarter 2026 Financial Results](https://finance.yahoo.com/search?p=Adeia+Announces+First+Quarter+2026+Financial+Results)（Yahoo / 2026-05-04）
- MSFT 最新价格约为 413.62 USD，变动 -0.57 / -0.14%。
- 关注下一财报季的营收指引和利润率变化
- 跟踪行业政策和竞争格局变化

来源：
- [Will Ulta’s (ULTA) Gemini-Powered “Ulta AI” and NielsenIQ Tie-Up Change Its Digital Narrative?](https://finance.yahoo.com/search?p=Will+Ulta%E2%80%99s+%28ULTA%29+Gemini-Powered+%E2%80%9CUlta+AI%E2%80%9D+and+NielsenIQ+Tie-Up+Change+Its+Digital+Narrative%3F)（Yahoo / 2026-05-05）
- [Alphabet Returns to Euro Debt Market for Latest AI Megabond Deal](https://finance.yahoo.com/search?p=Alphabet+Returns+to+Euro+Debt+Market+for+Latest+AI+Megabond+Deal)（Yahoo / 2026-05-05）
- [Why Alphabet Stock Soared 34% in April -- One Catalyst Is Its Move to Challenge Data Center AI Chip Leader Nvidia](https://finance.yahoo.com/search?p=Why+Alphabet+Stock+Soared+34%25+in+April+--+One+Catalyst+Is+Its+Move+to+Challenge+Data+Center+AI+Chip+Leader+Nvidia)（Yahoo / 2026-05-05）
- [Top Stock Reports for Alphabet, Walmart & Micron](https://finance.yahoo.com/search?p=Top+Stock+Reports+for+Alphabet%2C+Walmart+%26+Micron)（Yahoo / 2026-05-04）
- [Here is Why Alphabet (GOOGL) Is Among the Most Promising AI Stocks to Invest In](https://finance.yahoo.com/search?p=Here+is+Why+Alphabet+%28GOOGL%29+Is+Among+the+Most+Promising+AI+Stocks+to+Invest+In)（Yahoo / 2026-05-04）
---

## Follow-Up Analysis

These cases need manual review or another fix pass before deployment:

- Q20 `quick_brief`: quick brief exceeded 60000ms latency budget
