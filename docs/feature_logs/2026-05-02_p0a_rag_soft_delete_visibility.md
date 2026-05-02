# 2026-05-02 P0-A RAG Soft-delete 诊断可见性

状态：已完成后端小批次

## 本批范围

- `/diagnostics/rag/runs` 新增 `include_deleted`，默认隐藏软删除 run，需要审计时可显式回看。
- `/diagnostics/rag/runs/{run_id}/events` 新增 `include_deleted`，软删除 run 后仍可按需查看事件轨迹。
- `list_hits()` 默认隐藏已删除 hit、已删除 chunk、已删除 rerank 行，避免 source doc 被删除后检索命中继续泄漏。
- `soft_delete_source_doc()` 级联标记：
  - `rag_source_docs`
  - `rag_chunks`
  - `rag_retrieval_hits`
  - `rag_rerank_hits`
- 测试 fake engine 改为共享响应队列，能准确模拟连续 SQL 调用和事务后读取。

## 验证

```powershell
python -m pytest backend\tests\test_rag_observability_store.py::test_list_runs_and_events_default_hide_deleted_but_can_include_them backend\tests\test_rag_observability_store.py::test_soft_delete_source_doc_cascades_to_hits_and_rerank_hits backend\tests\test_rag_observability_store.py::test_list_hits_hides_deleted_hits_chunks_and_rerank_rows_by_default -q
python -m pytest backend\tests\test_rag_observability_system_router.py::test_rag_runs_endpoint_returns_items_and_passes_filters backend\tests\test_rag_observability_system_router.py::test_rag_run_events_endpoint_passes_include_deleted -q
python -m pytest backend\tests\test_rag_observability_store.py backend\tests\test_rag_observability_system_router.py backend\tests\test_rag_observability_auth.py -q
```

结果：

```text
21 passed in 95.77s
```

## 后续仍需处理

- 前端 Inspector 可在后续批次暴露 run/events 的 `include_deleted` 开关。
- Chat 主链路仍需 New Chat / Clear Context、Stop/AbortSignal 和 AgentProgressList。
