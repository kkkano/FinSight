# 2026-05-02 P0-A RAG 可观测单事实源与脱敏

状态：已完成首批后端修复

## 本批范围

- 统一 `execute_plan_stub` 的 RAG 可观测写入入口，改为使用 `backend.rag.observability_store` 作为事实源。
- 新增 RAG service hook 抑制上下文，避免 orchestrated graph 已手工记录 RAG run 时，`HybridRAGService` hook 再创建孤儿 run。
- 为 RAG 查询记录新增真实脱敏，避免 `query_text_redacted` 等同原始 query。
- 在执行节点创建 `QueryRunRecord` 时写入 redacted query。
- 补充后端测试覆盖：
  - 敏感 query 脱敏。
  - hook 抑制后不写 service-side run。
  - execute_plan RAG 可观测仍正常写 run、event、source、chunk、hit。

## 验证

```powershell
python -m pytest backend\tests\test_rag_v2_service.py backend\tests\test_rag_observability_store.py backend\tests\test_rag_observability_system_router.py backend\tests\test_rag_observability_execute_plan.py backend\tests\test_trace_and_session_security.py backend\tests\test_live_tools_evidence.py backend\tests\test_langgraph_api_stub.py -q
```

结果：

```text
51 passed in 30.57s
```

## 仍需后续批次处理

- `hybrid_search_many()` 仍需真正 bounded parallel，而不是顺序 fanout。
- `ws` TTL 与 `kb` promotion gate 还要继续收紧，避免隐式长期化。
- diagnostics DB Browser 的 `layer` filter 需要补 metadata-only 表过滤测试。
- soft-delete 还未闭环到 retrieval visibility。
- 前端 Chat Stop、New Chat、Clear Context 和深链恢复仍待单独批次处理。
