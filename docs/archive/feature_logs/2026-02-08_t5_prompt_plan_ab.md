# 2026-02-08 — T5-3 Prompt/Plan A/B + Metrics 闭环

## 背景
- 按 `11.16` backlog 执行 T5-3：为 Planner 增加可控 A/B 试验能力，建立最小可观测指标回收闭环。

## 变更范围

### 1) Planner A/B 变体分配（后端）
- 文件：`backend/graph/nodes/planner.py`
- 新增环境变量：
  - `LANGGRAPH_PLANNER_AB_ENABLED`（默认 false）
  - `LANGGRAPH_PLANNER_AB_SPLIT`（默认 50）
  - `LANGGRAPH_PLANNER_AB_SALT`（默认 `planner-ab-v1`）
- 实现逻辑：
  - 以 `thread_id/session_id` + `salt` 进行稳定哈希分桶，保证同一会话稳定落在 A 或 B。
  - 无论 `stub` 或 `llm`，都写入 `trace.planner_runtime.variant`。

### 2) Prompt 变体（A/B）
- 文件：`backend/graph/planner_prompt.py`
- `build_planner_prompt` 升级为 `build_planner_prompt(state, variant="A")`。
- Prompt 内显式注入 `<planner_variant>` 标签，并加入 A/B 差异化规划指导语。

### 3) 指标与诊断
- 文件：`backend/graph/nodes/planner.py`
- 新增进程内聚合计数：
  - per-variant `requests` / `fallbacks` / `retry_attempts` / `avg_steps`
- 文件：`backend/api/system_router.py`
- 新增诊断接口：
  - `GET /diagnostics/planner-ab`
  - `GET /diagnostics/planner_ab`（兼容别名）

### 4) 接线与文档
- 文件：`backend/api/main.py`
  - 注入 `get_planner_ab_metrics` 到 `SystemRouterDeps`。
- 文件：`.env.example`
  - 增加 Planner A/B 三个变量样例。
- 文件：`readme.md`
  - Runtime Flags 增加 Planner A/B 说明。
  - API 列表新增 planner-ab 诊断接口。
- 文件：`docs/11_PRODUCTION_RUNBOOK.md`
  - 生产环境变量示例加入 Planner A/B。
  - 可观测性接口列表加入 planner-ab。

## 去黑盒架构说明（本轮新增）

### 1) 端到端执行链路（保持不变）
- 本次未改变主链路顺序：
  - `BuildInitialState -> NormalizeUIContext -> DecideOutputMode -> ResolveSubject -> Clarify -> ParseOperation -> PolicyGate -> Planner -> ExecutePlan -> Synthesize -> Render`
- 变更点仅位于 `Planner` 节点内部：新增 A/B 分流与观测，不改外部接口契约。

### 2) Planner A/B 决策步骤（新增）
1. 读取会话键（优先 `thread_id`，兜底 `session_id`）。
2. 组合 `LANGGRAPH_PLANNER_AB_SALT + thread/session` 计算稳定哈希。
3. 根据 `LANGGRAPH_PLANNER_AB_SPLIT` 决定落入 A 或 B。
4. 将结果写入 `trace.planner_runtime.variant`。
5. 使用对应 prompt 变体生成 PlanIR（A/B 仅影响“规划倾向”，不影响安全边界）。

### 3) 安全边界与 Agent 流程不变量（关键）
- 不变量 1：`PolicyGate` 仍是唯一 allowlist/budget 权威来源。
- 不变量 2：`planner._enforce_policy(...)` 继续强制：
  - `output_mode` 以 state 为准（防模型自升级）
  - `budget` 以 policy 为准（防模型自扩预算）
  - `steps` 仅允许授权 tool/agent（防越权调用）
- 不变量 3：回退路径（`planner_stub`）仍保留，并且带完整 runtime 字段。

### 4) 可观测性契约（新增字段）
- 运行时：`trace.planner_runtime.variant`
- 诊断面：`/diagnostics/planner-ab`（别名 `/diagnostics/planner_ab`）
  - per-variant：`requests` / `fallbacks` / `fallback_rate` / `retry_attempts` / `avg_steps`
  - totals：聚合视图，便于 A/B 收敛决策

### 5) 运维读取建议
- 看稳定性：优先看 `fallback_rate`（A 与 B 对比）
- 看复杂度：看 `avg_steps` 与 `retry_attempts`
- 看质量收敛：结合 retrieval gate（Recall/nDCG/Coverage/P95）联合判断是否推进默认变体

## 测试补充
- `backend/tests/test_planner_prompt.py`
  - 校验 A/B prompt marker 与内容差异。
- `backend/tests/test_planner_node.py`
  - 校验 A/B 分配稳定性。
  - 校验 LLM fallback 路径仍带 variant。
- `backend/tests/test_langgraph_api_stub.py`
  - 校验 API 响应 trace 中 planner runtime 的 variant 字段。
- `backend/tests/test_system_planner_ab_diagnostics.py`
  - 校验 planner-ab 诊断接口与别名可用。
- `backend/tests/test_trace_v2_observability.py`
  - 校验 planner runtime variant 在 trace span 透出。

## 风险与说明
- 指标采用进程内内存聚合，重启后清零（适合作为实时诊断，不替代长期统计）。
- A/B 仅影响 Planner prompt 指导语，不改变外部 API 契约。

## 验收命令（已执行）
- `pytest -q backend/tests/test_planner_prompt.py backend/tests/test_planner_node.py backend/tests/test_langgraph_api_stub.py backend/tests/test_system_planner_ab_diagnostics.py backend/tests/test_trace_v2_observability.py`
- `pytest -q backend/tests`
- `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`
- `python tests/retrieval_eval/run_retrieval_eval.py --gate`
- `npm run lint --prefix frontend`
- `npm run build --prefix frontend`
- `npm run test:e2e --prefix frontend`

## 验收结果
- `pytest -q backend/tests/test_planner_prompt.py backend/tests/test_planner_node.py backend/tests/test_langgraph_api_stub.py backend/tests/test_system_planner_ab_diagnostics.py backend/tests/test_trace_v2_observability.py` -> `28 passed`
- `pytest -q backend/tests` -> `368 passed, 8 skipped`
- `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py` -> `7 passed`
- `python tests/retrieval_eval/run_retrieval_eval.py --gate` -> `PASS`（`citation coverage=1.0`）
- `npm run lint --prefix frontend` -> pass
- `npm run build --prefix frontend` -> pass
- `npm run test:e2e --prefix frontend` -> `7 passed`
