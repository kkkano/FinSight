# WP4 Task 2 Settings 迁移地图

本表记录 typed Settings 的精确环境变量映射。默认值来自迁移前调用点；字段均使用
`validation_alias`，不依赖字段名或前缀推断。

| 域 | Settings 字段 | 环境变量 | 默认值 | 原调用位置 |
|---|---|---|---:|---|
| planner | `mode` | `LANGGRAPH_PLANNER_MODE` | `llm` | `graph/nodes/planner.py` |
| planner | `report_timeout_sec` / `report_max_tokens` / `report_max_attempts` / `report_acquire_timeout_sec` | `LANGGRAPH_PLANNER_REPORT_*` | `240 / 6000 / 3 / 180` | `graph/nodes/planner.py` |
| planner | `chat_timeout_sec` / `chat_max_tokens` / `chat_max_attempts` / `chat_acquire_timeout_sec` | `LANGGRAPH_PLANNER_CHAT_*` | `150 / 3000 / 2 / 120` | `graph/nodes/planner.py` |
| planner | `ab_enabled` / `ab_split` / `ab_salt` | `LANGGRAPH_PLANNER_AB_*` | `false / 50 / planner-ab-v1` | `graph/nodes/planner.py` |
| planner | `temperature` / `json_repair_attempts` | `LANGGRAPH_PLANNER_TEMPERATURE` / `LANGGRAPH_PLANNER_JSON_REPAIR_ATTEMPTS` | `0.2 / 2` | `graph/nodes/planner.py` |
| executor | `live_tools` | `LANGGRAPH_EXECUTE_LIVE_TOOLS` | `false` | `graph/execution/plan_pipeline.py` |
| executor | `progress_heartbeat_seconds` | `LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS` | `2.5` | `graph/executor.py` |
| executor | `dag_executor` / `evidence_bus` | `FINSIGHT_DAG_EXECUTOR` / `FINSIGHT_EVIDENCE_BUS` | `false / false` | `graph/execution/plan_pipeline.py` |
| executor | `research_ledger_enabled` / `jina_enrich_evidence` | `RESEARCH_LEDGER_ENABLED` / `JINA_ENRICH_EVIDENCE` | `true / true` | `graph/execution/*.py` |
| executor | `agent_invoker_timeout_seconds` / `deep_search_agent_timeout_seconds` / `agent_invoker_retry_attempts` | `LANGGRAPH_*AGENT*_TIMEOUT_SECONDS` / `LANGGRAPH_AGENT_INVOKER_RETRY_ATTEMPTS` | `180 / 继承 invoker / 2` | `graph/adapters/agent_adapter.py` |
| agent | `temperature` / `brief_enabled` | `LANGGRAPH_AGENT_TEMPERATURE` / `FINSIGHT_AGENT_BRIEF` | `0.2 / false` | `graph/adapters/agent_adapter.py` |
| agent | `llm_analyze_enabled` / `llm_analyze_timeout_seconds` / `llm_analyze_call_timeout_seconds` | `AGENT_LLM_ANALYZE_*` | `false / 8 / 8` | `agents/base_agent.py` |
| agent | `base_max_reflections` / `reflection_token_timeout_seconds` | `BASE_AGENT_MAX_REFLECTIONS` / `BASE_AGENT_REFLECTION_TOKEN_TIMEOUT_SECONDS` | `unset / 12` | `agents/base_agent.py` |
| security | `api_auth_enabled` / `api_auth_keys` / `api_auth_key` | `API_AUTH_*` | `false / empty / empty` | `api/security_gate.py` |
| security | `trust_proxy_headers` | `TRUST_PROXY_HEADERS` | `true` | `api/security_gate.py` |
| security | `rate_limit_*` | `RATE_LIMIT_*` | `true / 300 / 60` | `api/security_gate.py` |
| security | `concurrency_limit_enabled` / `generation_max_concurrent*` | `CONCURRENCY_LIMIT_ENABLED` / `GENERATION_MAX_CONCURRENT*` | `true / 10 / 2` | `api/concurrency.py` |
| security | `supabase_*` / `vite_supabase_*` | `SUPABASE_*` / `VITE_SUPABASE_*` | `empty` | `api/security_gate.py` |
| security | `rag_dev_*` / `rag_auth_cache_seconds` | `RAG_OBSERVABILITY_*` | `false / empty / local defaults / 60` | `api/security_gate.py` |

WP3 后的路径差异：旧 spec 所称 executor 配置目前分布于 `graph/executor.py`、
`graph/execution/plan_pipeline.py` 和 agent invoker 适配层；DAG 调度器本身没有独立 env 读取。
按当前 ownership 迁移，不恢复旧节点或 stub。

`BaseFinancialAgent` 的 `{AGENT_NAME}_LLM_ANALYZE_*` 是运行时动态键，无法用静态字段穷举；
这些 per-agent override 保留直接读取，未命中时的通用默认值已由 `AgentSettings` 提供。
