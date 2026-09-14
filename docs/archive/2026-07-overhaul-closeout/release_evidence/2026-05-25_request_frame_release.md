# Request-Frame Architecture Release Evidence

Date: 2026-05-25
Branch: `feature/request-frame-architecture`

## Scope

This release makes `RequestFrame` + `IntentContract` the authoritative request-understanding path in production. The design boundary is evidence-first:

- `conversation_router` resolves subject/context/relation.
- `intent_contract` compiles facets into `required_evidence`, `render_intent`, and `budget_profile`.
- `operation` remains only as a compatibility projection for legacy planner/renderer surfaces.
- Planner coverage must satisfy frame evidence/results before a research/action frame is considered valid.

## Production Flags

Recommended production defaults:

```env
FINSIGHT_INTENT_CONTRACT_MODE=enforce
FINSIGHT_CONTEXT_ROUTER_ENABLED=true
FINSIGHT_FORCE_AGENT_RESEARCH_CONFIG=true
FINSIGHT_CHAT_MULTI_TICKER_RESEARCH_LIMIT=3
SEC_HOLDINGS_ENABLED=true
AGENT_LLM_ANALYZE_ENABLED=true
TECHNICAL_AGENT_LLM_SUMMARY_ENABLED=1
BASE_AGENT_MAX_REFLECTIONS=0
```

`BASE_AGENT_MAX_REFLECTIONS=0` keeps Agent LLM refinement available without multiplying calls through the reflection loop.

## Local Verification

Commands:

```bash
python -m compileall -q backend/graph backend/tests
python -m pytest backend/tests -q -p no:cacheprovider
```

Result after release hardening:

```text
1436 passed, 8 skipped
```

Focused semantic boundaries:

- `AAPL vs MSFT` -> research, `performance_comparison`, `get_performance_comparison`.
- `NVDA 和 AMD 哪个估值更合理` -> rank frame, per-ticker `price_snapshot/company_profile/earnings_estimates`.
- `研究一下特斯拉会不会被 SpaceX 影响` -> impact frame for TSLA, `price_snapshot/news_context/risk_profile`.
- `why do high valuation stocks dislike higher rates?` -> direct answer, no evidence, no plan steps.
- `How could this week's FOMC decision affect the Nasdaq?` -> research, `macro_context`, macro release/news/search steps.
- `Do not look up news; just explain why oil prices can affect airlines` -> direct answer, no price/news evidence.
- `Buffett latest 13F holdings in AAPL` -> holdings evidence; with `SEC_HOLDINGS_ENABLED=true`, planner emits insider/institutional holdings steps.
- Backtest requests -> action frame, `run_strategy_backtest`.
- Missing-subject weak deixis (`this stock...`, `这只票...`) -> clarify, not direct.

## Non-Goals

This release deliberately does not add query-specific route patches. New long-tail behavior should be represented by a bounded facet/evidence kind and covered at the contract/planner coverage layer.
