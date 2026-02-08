# 2026-02-08 T0 对齐 + T1/T2/T3 增量执行记录

## 背景

按执行要求，先做 `T0` 文档对齐，再推进 `T1/T2/T3` 的可落地增量，确保 `11.14` 主清单与代码现实一致，避免“假待办/文档漂移”。

## 本批完成内容

### 1) T0 文档对齐
- 在 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 的 Worklog 追加本批执行记录。
- 新增 `11.16 11.14 状态对齐与真实 Backlog`，明确：
  - 已完成项按 `11.14.13` + `11.15` 回填 DONE 基线。
  - 未完成项收敛到可执行 backlog（T1~T5）。

### 2) T1 可观测性闭环（增量）
- `backend/graph/trace.py`
  - 为关键节点补齐 trace.v2 结构字段：
    - `decision_type`
    - `summary`
    - `fallback_reason`
  - planner step 预览新增 `parallel_group`。
  - execute step 摘要新增 `duration_ms`、`status_reason`、`parallel_group`。
- `backend/graph/executor.py`
  - `artifacts.step_results` 增强：
    - `duration_ms`
    - `status_reason`
    - `parallel_group`
- `frontend/src/components/ThinkingProcess.tsx`
  - Decision Summary 视图补充 `decision_type/summary` 展示。
- `frontend/src/components/AgentLogPanel.tsx`
  - 摘要优先读取 `summary/decision_type/fallback_reason`，减少“空洞 reason/result”。

### 3) T2 RAG 与证据链硬化（增量）
- `backend/services/report_index.py`
  - 新增 `list_citations(...)`，支持按 `report_id/source_id/query/date` 过滤。
- `backend/api/report_router.py`
  - 新增 API：`GET /api/reports/citations`。
- `backend/tests/test_report_index_api.py`
  - 增加 citation 检索过滤测试（query/source_id）。

### 4) T3 数据库与会话隔离（增量）
- `backend/graph/checkpointer.py`
  - `LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK` 默认值从 `true` 收紧为 `false`。
- `.env.example`
  - 增加 checkpointer 相关配置示例（sqlite/postgres + fallback 开关）。

## 验证结果

- `pytest -q backend/tests/test_report_index_api.py backend/tests/test_graph_checkpointer.py backend/tests/test_trace_and_session_security.py backend/tests/test_trace_v2_observability.py backend/tests/test_executor.py`
  - `28 passed`
- `npm run lint --prefix frontend`
  - 通过
- `npm run build --prefix frontend`
  - success

## 当前剩余（下一批）

- T1：前端三层视图显式切换与 fallback 路径可视化。
- T2：检索门禁指标与发布门禁绑定（Recall@K/nDCG/Coverage/P95）。
- T3：Postgres checkpointer 实际切换演练 + 回滚证据归档。
- T4：`11.14.6~11.14.9` 全量回归与证据归档。


## T4 全量收口回归（同日追加）

### 执行命令
- `pytest -q backend/tests`
- `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`
- `python tests/retrieval_eval/run_retrieval_eval.py --gate`
- `npm run test:e2e --prefix frontend`

### 结果
- 后端全量：`351 passed, 8 skipped`
- retrieval 单测：`6 passed`
- retrieval gate：`PASS`（Recall@K=1.0, nDCG@K=1.0, Citation Coverage=1.0, P95=0.23ms）
- 前端 e2e：`13 passed`

### 结论
- `11.16` 中 T4（稳定性与安全收口）已达成 DONE。
- 当前剩余主项集中在：T1（三层视图切换）、T2（门禁指标绑定）、T3（Postgres 演练）、T5（P1 增强）。
