# Chat UX 40-Query Acceptance Eval (2026-05-05)

- Started at: `2026-05-05T14:27:01`
- Entry point: `POST /chat/supervisor` via FastAPI `TestClient`
- Stream spot checks: Q35-Q38 call `/chat/supervisor/stream` in isolated sessions
- Result: `2` PASS, `0` REVIEW, `0` FAIL
- Elapsed: `152.9s`

## Acceptance Rules

- Normal chat should feel conversational and keep context.
- Only explicit report mode should use report-style structure.
- User-facing text must not leak internal tool names, trace labels, or mechanical templates.
- News answers should include links; if upstream items lack URLs, renderer should provide search links.
- Switching sessions must preserve the right context and not leave the user-facing answer empty.

## Summary Table

| ID | Type | Verdict | Mode | Route | ms | Issues |
|---|---|---|---|---|---:|---|
| Q27 | compound_alert_news | PASS | chat | alert | 50884 | - |
| Q35 | history_switch_a | PASS | chat | research | 44359 | - |

## Full Answers

### Q27 - compound_alert_news

**Query:** TSLA 跌破 180 提醒我，顺便说说最近新闻。

**Expected:** 能处理提醒和新闻混合需求。

**Session:** `eval-alert-news`

**Eval Session:** `eval-alert-news-20260505142701-3ddbe9`

**Context:**

```json
{
  "user_email": "eval@example.com"
}
```

**Observed:** mode=`chat`, route=`alert`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "TSLA"
    ],
    "operation": "alert_set"
  }
]
```

**Conversation Router:**

```json
{
  "execution_route": "alert",
  "context_binding": {
    "source": "none",
    "confidence": 0.0,
    "reason": "current user turn contains explicit subject(s), so implicit history was ignored",
    "subject_hint": "TSLA"
  },
  "relation": "new_topic",
  "domain_intent": "alert",
  "confidence": 0.8,
  "needs_tools": true,
  "reason": "用户明确要求设置价格提醒并获取最新新闻，两者均需工具支持（预警设置和新闻查询）。",
  "reply_guidance": "首先确认将设置TSLA跌破180的提醒，然后提供TSLA最近新闻的摘要，如监管动态、业务进展等。"
}
```

**Full Answer:**

---
已为 `TSLA` 创建到价提醒：下跌到 `180.0` 时提醒。
- 订阅类型：price_change
- 说明：系统已保留你原有订阅类型，并追加价格提醒。

另外你还问到“说说最近新闻”。提醒已经设好；这部分需要实时研究链路，我会保留这个上下文，下一句可以直接让我继续查。
---

### Q35 - history_switch_a

**Query:** AAPL 最近新闻怎么看？

**Expected:** 会话 A 建立 AAPL 上下文。

**Session:** `eval-switch-A`

**Eval Session:** `eval-switch-A-20260505142701-3ddbe9`

**Observed:** mode=`chat`, route=`research`, verdict=`PASS`

**Tasks:**

```json
[
  {
    "subject_type": "company",
    "tickers": [
      "AAPL"
    ],
    "operation": "fetch"
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
    "subject_hint": "AAPL"
  },
  "relation": "new_topic",
  "domain_intent": "news",
  "confidence": 0.9,
  "needs_tools": true,
  "reason": "用户需要AAPL的最新新闻数据，这需要实时工具获取和验证。",
  "reply_guidance": "使用工具获取AAPL最新新闻后，提供新闻摘要、关键事件和简要分析。"
}
```

**Stream Spot Check:**

```json
{
  "present": true,
  "status_code": null,
  "output_mode": "chat",
  "response_len": 1718,
  "token_len": 1718,
  "event_count": 87,
  "body_preview": null
}
```

**Full Answer:**

---
AAPL 我找到几条比较相关的消息：
- [Bank of America resets Apple stock price target after earnings](https://finance.yahoo.com/search?p=Bank+of+America+resets+Apple+stock+price+target+after+earnings)（Yahoo / 2026-05-05）
- [Apple holds talks with Intel, Samsung for US chipmaking, Bloomberg News reports](https://finance.yahoo.com/search?p=Apple+holds+talks+with+Intel%2C+Samsung+for+US+chipmaking%2C+Bloomberg+News+reports)（Yahoo / 2026-05-05）
- [Is Apple Stock a Buy as iPhone Revenue Soars?](https://finance.yahoo.com/search?p=Is+Apple+Stock+a+Buy+as+iPhone+Revenue+Soars%3F)（Yahoo / 2026-05-05）

- 美银将目标价上调至$330并维持买入评级，Q2财报数据强劲是核心驱动，这为股价提供了估值锚点和情绪支撑
- 苹果正与Intel、Samsung洽谈美国本土芯片制造，目的是降低对台积电的单一依赖，但公司内部对非台积电技术的可靠性和产能规模仍有顾虑，短期内不太可能大规模切换
- 据报道苹果正在考虑一笔重大AI收购，这与其一贯保守的并购风格不同，背景是Tim Cook即将把CEO职位交给John Ternus，市场对苹果AI布局的质疑仍在
- Tim Cook提到AI推动的内存成本上升（所谓'RAMmageddon'）将推高设备售价，这对硬件毛利率是潜在压力，但苹果的品牌溢价能力可能部分对冲

来源：
- [Bank of America resets Apple stock price target after earnings](https://finance.yahoo.com/search?p=Bank+of+America+resets+Apple+stock+price+target+after+earnings)（Yahoo / 2026-05-05）
- [Apple holds talks with Intel, Samsung for US chipmaking, Bloomberg News reports](https://finance.yahoo.com/search?p=Apple+holds+talks+with+Intel%2C+Samsung+for+US+chipmaking%2C+Bloomberg+News+reports)（Yahoo / 2026-05-05）
- [Is Apple Stock a Buy as iPhone Revenue Soars?](https://finance.yahoo.com/search?p=Is+Apple+Stock+a+Buy+as+iPhone+Revenue+Soars%3F)（Yahoo / 2026-05-05）
- [Apple Weighs Major AI Deal As Investors Reassess Growth And Valuation](https://finance.yahoo.com/search?p=Apple+Weighs+Major+AI+Deal+As+Investors+Reassess+Growth+And+Valuation)（Yahoo / 2026-05-04）
- [Apple's Tim Cook says AI-fueled 'RAMmageddon' will make your next laptop and phone a lot pricier](https://finance.yahoo.com/search?p=Apple%27s+Tim+Cook+says+AI-fueled+%27RAMmageddon%27+will+make+your+next+laptop+and+phone+a+lot+pricier)（Yahoo / 2026-05-04）
---

## Follow-Up Analysis

All deterministic checks passed. Manual review should still read the full answers above for tone and usefulness.
