# WP4 Task 1 env helper 迁移地图

## 公共语义

`backend/utils/env.py` 统一提供 `env_str`、`env_int`、`env_float`、`env_bool`、`env_csv`。普通变体均保留旧调用名，通过 import alias 回接；空字符串、解析失败和 bool 真值集合的行为以原 `planner.py` 实现为准。

## 已迁移定义

- `backend/llm_config.py`
- `backend/api/security_gate.py`
- `backend/api/concurrency.py`（仅普通整数解析）
- `backend/graph/checkpointer.py`
- `backend/graph/adapters/agent_adapter.py`
- `backend/graph/intent/router.py`
- `backend/graph/nodes/planner.py`
- `backend/graph/planning/policy_enforcement.py`
- `backend/graph/policy/runtime.py`（仅普通布尔解析）
- `backend/graph/report_builder.py`
- `backend/graph/synthesis/normalization.py`
- `backend/rag/hybrid_service.py`（仅普通布尔解析）
- `backend/report/evidence_policy.py`
- `backend/report/quality_engine.py`
- `backend/services/langfuse_tracer.py`
- `backend/services/llm_retry.py`
- `backend/services/rate_limiter.py`
- `backend/services/report_cache.py`

合计删除 27 个重复的普通 `_env_*` 定义。

## 保留的特殊变体

- `backend/api/concurrency.py::_env_enabled_unless_disabled`：除 `false/0/off` 外均视为启用，不能改成严格真值表。
- `backend/rag/observability_runtime.py::_bounded_env_int`：整数解析后钳制到 `1..3650`。
- `backend/rag/hybrid_service.py::_bounded_env_int`：整数解析后按调用点钳制 worker 数。
- `backend/rag/execution_support.py::_bounded_env_int`：整数解析后按调用点钳制 RAG 参数。
- `backend/graph/policy/runtime.py::_bounded_env_int`：整数解析后钳制 agent 反思轮数与超时。

这些函数只改为表达特殊语义的名称，函数体、默认值和消费端行为不变。`def _env_int` / `def _env_bool` 守护因此可以准确拦截后续新增的普通重复实现。
