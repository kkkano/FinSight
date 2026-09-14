# Request-Frame Architecture Readiness Evidence

Date: 2026-05-24
Branch: `feature/request-frame-architecture`
Head: `a12f128 Keep direct answers inside request-frame boundaries`
Base: `origin/main`

## Decision

The request-frame architecture branch is ready to merge into `main` from the
code and test perspective.

Deployment should use the normal canary/staged production path rather than an
unmonitored full cutover. The branch includes full backend, frontend, golden
query, and GraphRunner smoke evidence. Live external-tool smoke is still
provider-dependent; during manual probing, search quota and holdings latency
were the limiting factors, not the request-frame contract path.

## Architecture Contract Verified

The branch moves request understanding from operation-first routing to this
contract chain:

1. `conversation_router` resolves context and direct/research boundaries.
2. `RequestFrame` is the semantic frame source.
3. `EvidenceObligation` and `required_results` drive policy and planner.
4. `workflow_action` represents actions such as backtest.
5. `render_contract` drives compare/action/answer rendering.
6. Legacy `operation` remains only a compatibility projection.

## Query Evidence Matrix

The committed golden suite validates these representative user queries at the
contract, policy, planner, and coverage layers:

| Query | Expected proof |
| --- | --- |
| `NVDA and AMD which valuation is more reasonable` | `relation=rank`, `render=compare`, valuation evidence per ticker, no `get_performance_comparison` shortcut. |
| `Research whether TSLA could be affected by SpaceX` | External entity impact stays on `TSLA`, with price/news/risk evidence. |
| `backtest MACD strategy on AAPL` | `lane=action`, `workflow_action=backtest`, `required_results=backtest_result`, `run_strategy_backtest` planned. |
| `what is backtesting?` | Definition stays `lane=answer`, no backtest/tool steps. |
| `Check AAPL price, MSFT news, then explain Fed rate impact` | Three independent frames: price, news, macro. No frame evidence bleed. |
| `AAPL MACD technical analysis` | Technical analysis remains research, not backtest action. |
| `latest news links for MSFT` | News evidence and news/media steps are required. |
| `AAPL price now` | Price-only evidence and quote step only. |
| `How did NVDA earnings affect the stock price?` | Earnings impact includes profile, estimates, fundamental, news, calendar, transcript, filing, risk, and price evidence. |
| `How was MSFT earnings performance?` | Earnings performance excludes price/risk impact extras. |
| `Compare AAPL and MSFT risk` | Router direct cannot swallow compare/risk evidence; full graph reaches policy/planner. |
| `Research AAPL institutional holdings` | `holdings_ownership` plans public holdings/insider evidence without relying on legacy task routing. |
| `Do not look up news. Just tell me why semiconductors can sell off together.` | No-news mechanism question remains direct; no news tools/agents are planned. |

## GraphRunner Smoke Evidence

`backend/tests/test_request_frame_graph_smoke.py` verifies the full LangGraph
node flow with deterministic execution:

- A router `direct_answer` decision cannot bypass a request frame that requires
  compare/risk evidence.
- A no-news mechanism explanation terminates before `policy_gate` and planner.
- The test preserves `GraphRunner` routing, `understand_request`,
  `policy_gate`, `planner`, `execute_plan`, `synthesize`, and `render` node
  transitions while avoiding external provider quota as a source of flakiness.

## Verification Commands

All commands below were run on this branch after the final code changes.

```powershell
python -m pytest backend/tests/test_request_frame_graph_smoke.py backend/tests/test_request_frame_architecture.py backend/tests/test_request_frame_golden_queries.py backend/tests/test_policy_planner_query_regression.py backend/tests/test_understanding_v2_contract.py backend/tests/test_contextual_conversation_router.py::test_understand_request_no_news_mechanism_falls_back_to_direct_when_router_unavailable backend/tests/test_contextual_conversation_router.py::test_understand_request_uses_context_binding_for_direct_report_discussion backend/tests/test_reply_contract_lanes.py::test_do_not_generate_report_turn_builds_chat_contract backend/tests/test_reply_contract_lanes.py::test_price_word_in_mechanism_question_does_not_force_quote_tasks -q
```

Result: `73 passed`

```powershell
python -m pytest backend/tests -q
```

Result: `1427 passed, 8 skipped`

```powershell
python -m compileall -q backend/graph backend/tests
git diff --check
```

Result: passed

```powershell
npm run build
npm run test:unit
npm run lint
```

Frontend results:

- Build: passed
- Unit tests: `44 passed`
- Lint: `0 errors, 3 warnings`

The lint warnings are existing non-blocking warnings in:

- `frontend/src/components/agent-log/AgentLogPanel.tsx`
- `frontend/src/components/ui/ErrorBoundary.tsx`
- `frontend/src/pages/RagInspectorPage.tsx`

## Merge State

```powershell
git rev-list --left-right --count origin/main...HEAD
```

Result: `0 18`

```powershell
git merge-base --is-ancestor origin/main HEAD
```

Result: `origin/main is ancestor of HEAD`

This means the feature branch is ahead of `main` and not behind it.

## Deployment Recommendation

Merge recommendation: ready.

Deployment recommendation:

1. Merge `feature/request-frame-architecture` into `main`.
2. Deploy with the existing staged/canary process.
3. Enable monitoring for:
   - `trace.coverage_validator.status != ok`
   - request frames with evidence/results but `plan_ir.steps == []`
   - direct answers with `render_contract.shape=compare`
   - holdings live-tool latency
   - search provider quota fallback
4. Keep rollback simple: revert the feature branch merge or disable enforcement
   modes through existing environment gates where available.

## Non-Blocking Caveats

- Manual live-ish probing hit external search quota limits.
- Holdings live tool execution can exceed 90 seconds depending on provider
  behavior. The request-frame contract and planner path are covered by tests;
  provider latency should be monitored as an execution-layer concern.
- Existing untracked QA artifacts under `docs/qa/` were not included in this
  readiness package.
