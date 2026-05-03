# Chat UX Playwright Smoke Report

生成日期：2026-05-03

本报告记录 request understanding、会话体验和用户可见 trace 的浏览器验证结果。测试入口为：

```bash
cd frontend
npx playwright test e2e/request-understanding-chat.spec.ts
```

## 覆盖场景

| ID | 场景 | 结果 |
|---|---|---|
| P01 | `GOOGL`、`Apple`、`谷歌`、`微软`、`苹果`、无 ticker 宏观问题均能启用 Deep 模式 | 通过 |
| P02 | 新建会话、切回旧会话、恢复旧消息、删除会话 | 通过 |
| P03 | 用户视图展开后展示后端 `trace` 事件携带的具体请求拆解摘要 | 通过 |
| P04 | 流式生成中出现停止按钮，点击后保留“已停止生成，保留已完成的结果。”，状态条显示“本次生成已停止（结果已保留）” | 通过 |

## 运行结果

```text
Running 4 tests using 1 worker

ok 1 e2e/request-understanding-chat.spec.ts › deep mode is enabled for aliases, ticker text, and macro questions without frontend alias dictionary
ok 2 e2e/request-understanding-chat.spec.ts › chat conversations can be created, restored, and deleted from the rail
ok 3 e2e/request-understanding-chat.spec.ts › user trace view shows concrete backend understanding summaries
ok 4 e2e/request-understanding-chat.spec.ts › running chat streams can be stopped from the input control

4 passed
```

## 同轮验证

```text
pytest -q backend/tests/test_understand_request.py backend/tests/test_langgraph_skeleton.py backend/tests/test_graph_node_order.py backend/tests/test_clarify_node.py backend/tests/test_p0_unit.py backend/tests/test_resolve_subject.py backend/tests/test_financial_intent.py backend/tests/test_langgraph_api_stub.py backend/tests/test_policy_gate.py backend/tests/test_policy_planner_query_regression.py backend/tests/test_planner_prompt.py backend/tests/test_planner_node.py
182 passed

npm run test:unit --prefix frontend -- --run src/api/client.sse.test.ts src/store/executionStore.reducer.test.ts src/store/useStore.conversation.test.ts
3 files / 15 tests passed

pytest -q backend/tests/test_conversation_router.py backend/tests/test_report_index_delete_session.py backend/tests/test_execution_cancel.py backend/tests/test_plan_ir_validation.py backend/tests/test_executor.py backend/tests/test_understand_request.py backend/tests/test_live_tools_evidence.py
37 passed

pytest -q backend/tests/test_rag_observability_store.py backend/tests/test_conversation_router.py backend/tests/test_execution_cancel.py backend/tests/test_report_index_delete_session.py
15 passed

npm run build --prefix frontend
build passed

python scripts/request_understanding_probe.py --output docs/reports/2026-05-03_request_understanding_query_results.md
20 query matrix regenerated
```

## 备注

- Playwright 配置使用 `webServer.port=4273`，避免 HTTP 可用性探测把 400 响应误判为已有服务。
- `Browserslist/caniuse-lite` 过期提示只影响依赖数据新鲜度，不影响本次构建和 E2E 结果。
