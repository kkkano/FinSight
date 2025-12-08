# Feature Log - LangGraph 诊断接口与工具 trace 暴露
- 时间：2025-12-07 22:40:27
- 负责人：Codex

## 实施内容
1) API 诊断  
   - 新增 `/diagnostics/langgraph`（FastAPI），调用 `ConversationAgent.describe_report_agent()` 返回 LangGraph DAG 概览、自检状态、模型/提供商信息，前端可直接用于流水线面板。
2) ConversationAgent  
   - 新增 `describe_report_agent()`，优先使用 `self_check()`，回退 `get_agent_info()`，无外部 LLM 调用。
3) 工具 trace 暴露  
   - `FetchResult` 已包含 `fallback_used`/`tried_sources`/`trace`，现于 ChatHandler 价格查询返回时附带 `data_origin`、`fallback_used`、`tried_sources`、`trace`，便于前端显示数据来源/兜底提示。

## 测试
- 命令：  
  `python -m pytest backend/tests/test_langgraph_selfcheck.py test/test_financial_graph_agent.py backend/tests/test_orchestrator_metadata.py backend/tests/test_orchestrator.py::test_fetch_with_fallback backend/tests/test_orchestrator.py::test_fetch_all_fail backend/tests/test_orchestrator.py::test_cache_integration`
- 结果：6 通过，0 失败（遗留 PytestReturnNotNoneWarning，源于旧测试用例返回 True，未改动行为）。

## 备注 / 下一步
- 可在前端“执行流程”面板调用 `/diagnostics/langgraph`，显示节点/边、模型、可用性。  
- 后续可在 API 响应统一字段名（`data_origin`/`fallback_used`/`as_of`），并在日志中聚合来源/耗时做健康面板。  
