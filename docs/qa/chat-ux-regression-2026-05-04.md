# Chat UX Regression - 2026-05-04

## Scope

This QA note records the Phase 1-7 chat UX repair:

- default chat is conversational (`output_mode=chat`)
- the UI exposes one `报告` toggle instead of `简报 / 深度`
- structured templates are reserved for report mode
- normal chat must not leak planner/tool/trace wording
- report follow-up works in normal chat via `last_report` memory context
- chat progress/status is scoped per session to avoid stuck cross-session loading

## Query Matrix

| ID | Query | Expected mode | Must not contain | Expected behavior |
| --- | --- | --- | --- | --- |
| Q1 | `英伟达（NVDA）今天多少钱` | chat | `问题：`, `后续关注：`, `get_stock_price`, `Suggested ladder` | Natural price answer with ticker, quote value if available, and short interpretation. |
| Q2 | `特斯拉最新关键新闻（24小时）及对股价影响的解读` | chat | `本轮问题包含`, `分析对象`, `get_company_news` | Natural news + impact answer with clean citations. |
| Q3 | `英伟达（NVDA）技术面分析：RSI、MACD、关键支撑阻力位` | chat | `暂无技术指标` | If indicators are unavailable, explain the data gap naturally and say what would be checked. |
| Q4 | `请做 Apple 深度投资报告` | investment_report | N/A | Structured report mode remains available through explicit report wording or the `报告` toggle. |
| Q5 | `刚才那份报告里最大的风险是什么？` | chat | report template boilerplate | Uses `memory_context.last_report` and answers about the previous report without requiring report mode. |

## Automated Evidence

```text
pytest -q backend/tests/test_chat_response_contract.py backend/tests/test_graph_store_memory.py backend/tests/test_understand_request.py
28 passed

npm run test:unit --prefix frontend -- useStore.conversation.test.ts
8 passed

npm run build --prefix frontend
passed

npx playwright test report-button.spec.ts -g "report toggle"
2 passed

npm run test:e2e --prefix frontend -- request-understanding-chat.spec.ts
4 passed
```

## Notes

- `report-button.spec.ts` still contains older route/workbench tests that are not part of this change; after fixing the welcome gate setup, six of those old tests passed and five unrelated navigation/context-panel expectations still need a separate cleanup pass.
- Browserlist data warning appeared during frontend build/e2e and is not caused by this change.
