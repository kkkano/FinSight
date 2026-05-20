
# 2026-03-08 增量架构说明（RAG 三层）

- `backend/rag/layering.py`：三层 collection 解析与元数据归一化入口，负责 `memory / ws / kb`、`collection_kind`、`entity_scope`、`entity_key` 语义。
- `backend/graph/nodes/execute_plan_stub.py`：普通执行链的 Working Set / 长期 KB 写入与联合检索编排。
- `backend/agents/deep_search_agent.py`：DeepSearch 的 `ws:deepsearch:*` working set 与 `kb:stock:*` 晋升/补查入口。
- `backend/rag/hybrid_service.py`：RAG 文档模型补充 layer / entity / ingest / promotion / fingerprint 字段，并支持多 collection 联检。
- `backend/rag/observability_store.py`、`backend/rag/observability_runtime.py`：把 layer / collection path / hit 元数据落进 observability，供 Inspector 和 DB Browser 回放。
- `frontend/src/pages/RagInspectorPage.tsx`：Inspector 首屏、run 详情、collection 浏览、DB Browser 直接展示三层语义。

# 2026-05-18 增量架构说明（单 Agent 质量合同）

- `backend/research/agent_quality_contract.py`：单 Agent 质量合同入口，负责给 evidence 分配稳定 `agent_source:*`、构造 claim、计算 `agent_quality` 指标。
- `backend/agents/base_agent.py`：标准 `research()` 流程会自动挂载 `evidence_quality.agent_quality`；覆盖 `research()` 的 Agent 需要手动调用合同。
- `backend/agents/fundamental_agent.py`：原生输出 growth_quality / cash_flow_quality / eps_revision / balance_sheet_risk claims。
- `backend/agents/news_agent.py`：原生输出 catalyst_candidate / noise_or_secondary_signal / event_calendar claims。
- `backend/agents/risk_agent.py`：原生输出 risk_score / factor_exposure / stress_test claims。
- `scripts/agent_quality_eval.py` + `tests/eval/agent_quality_cases.json`：确定性 fixture eval gate，用于保存 before/after 结果并审计单 Agent 质量变化。

# 2026-05-20 增量架构说明（后端 Agent 能力诊断强化）

- `backend/graph/nodes/planner.py`：Planner 输出 `agent_selection` 诊断，`plan_ready` / `decision_note` 事件携带跳过原因、预算优先级、deepsearch 意图。PlanIR Schema 容错增强（`PlannerSchemaShapeError` + retry prompt）。
- `backend/graph/nodes/conversation_router.py`：新增内幕/非公开信息安全边界（`_query_requests_illicit_nonpublic_info`），多轮对话历史 ticker 补全主题提示。
- `backend/graph/nodes/chat_renderer.py`：新闻引用兜底——当 plan 无新闻源时直接抓取文章，确保回复契约有可引用 URL。
- `backend/research/debate.py`：新增 `build_read_only_adjudications`，输出 Bull/Bear/Judge 只读裁决产物。
- `backend/research/agent_quality_contract.py`：增强 low_source_quality / recovery action 诊断。

## 当前推荐心智模型

- `memory`：线程级轻记忆，不存大原文。
- `ws`：本次任务 working set，可短期复用，可过期。
- `kb`：长期稳定知识库，按股票/主题/宏观 scope 组织。

## 当前目录依赖

- `backend/rag/layering.py` -> 被 `hybrid_service.py` / `observability_store.py` / 编排节点调用。
- `backend/research/agent_quality_contract.py` -> 被 `base_agent.py`、Fundamental / News / Risk Agent 和 `scripts/agent_quality_eval.py` 调用。
- `frontend/src/pages/RagInspectorPage.tsx` -> 依赖 `frontend/src/api/client.ts` 的 diagnostics API。
- `docs/plans/2026-03-08_rag_three_layer_architecture_todolist.md` -> 作为后续持续开发与验收清单。
