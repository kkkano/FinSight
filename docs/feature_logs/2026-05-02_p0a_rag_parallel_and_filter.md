# 2026-05-02 P0-A RAG 多集合检索并发与 Layer 过滤

状态：已完成后端小批次

## 本批范围

- 为 `hybrid_search_many()` 增加有界并发 fan-out，避免多 collection 搜索按顺序串行拖慢 deep research。
- 通过 `RAG_SEARCH_MANY_MAX_WORKERS` 控制最大 worker 数，默认保守并发，避免把数据库或 embedding/search 后端打爆。
- fan-out 提交线程任务时复制当前 `contextvars`，保证 `suppress_rag_observability_hooks()` 等请求级上下文不会在线程边界丢失。
- DB Browser 的 `layer` 过滤补齐 metadata-only 表场景：当表没有 `collection` 列但有 `metadata_json` 时，直接按 `metadata_json ->> 'layer'` 过滤。
- 补充测试覆盖：
  - 多 collection 搜索会并发，但最大并发受上限约束。
  - observability hook suppression 在线程 fan-out 后仍然生效，不产生 service-side 双写 run。
  - metadata-only 表的 DB Browser `layer` 参数会真正进入 SQL WHERE 条件。

## 验证

```powershell
python -m pytest backend\tests\test_rag_v2_service.py::test_hybrid_search_many_uses_bounded_parallel -q
python -m pytest backend\tests\test_rag_observability_store.py::test_browse_db_table_filters_layer_from_metadata_json_without_collection_column -q
python -m pytest backend\tests\test_rag_observability_store.py::test_suppress_rag_observability_hooks_skips_service_side_runs -q
python -m pytest backend\tests\test_rag_v2_service.py backend\tests\test_rag_observability_store.py backend\tests\test_rag_observability_system_router.py backend\tests\test_rag_observability_execute_plan.py -q
```

结果：

```text
25 passed in 7.51s
```

## 后续仍需处理

- soft-delete retrieval visibility 还需要单独批次闭环。
- 前端 Chat 的 New Chat / Clear Context、Stop/AbortSignal、AgentProgressList 和深链恢复仍需单独批次处理。
