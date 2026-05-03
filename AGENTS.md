
# 2026-03-08 增量架构说明（RAG 三层）

- `backend/rag/layering.py`：三层 collection 解析与元数据归一化入口，负责 `memory / ws / kb`、`collection_kind`、`entity_scope`、`entity_key` 语义。
- `backend/graph/nodes/execute_plan_stub.py`：普通执行链的 Working Set / 长期 KB 写入与联合检索编排。
- `backend/agents/deep_search_agent.py`：DeepSearch 的 `ws:deepsearch:*` working set 与 `kb:stock:*` 晋升/补查入口。
- `backend/rag/hybrid_service.py`：RAG 文档模型补充 layer / entity / ingest / promotion / fingerprint 字段，并支持多 collection 联检。
- `backend/rag/observability_store.py`、`backend/rag/observability_runtime.py`：把 layer / collection path / hit 元数据落进 observability，供 Inspector 和 DB Browser 回放。
- `frontend/src/pages/RagInspectorPage.tsx`：Inspector 首屏、run 详情、collection 浏览、DB Browser 直接展示三层语义。

## 当前推荐心智模型

- `memory`：线程级轻记忆，不存大原文。
- `ws`：本次任务 working set，可短期复用，可过期。
- `kb`：长期稳定知识库，按股票/主题/宏观 scope 组织。

## 当前目录依赖

- `backend/rag/layering.py` -> 被 `hybrid_service.py` / `observability_store.py` / 编排节点调用。
- `frontend/src/pages/RagInspectorPage.tsx` -> 依赖 `frontend/src/api/client.ts` 的 diagnostics API。
- `docs/plans/2026-03-08_rag_three_layer_architecture_todolist.md` -> 作为后续持续开发与验收清单。
