# Feature Log - 统一元字段 & 诊断面板（P1）
- 时间：2025-12-07 22:52:47
- 负责人：Codex

## 实施内容
1) Orchestrator 元字段统一  
   - `FetchResult` 增加 `as_of`，所有返回路径（缓存/多源成功/失败/直连工具）均带回 `as_of`、`fallback_used`、`tried_sources`、`trace`。  
   - Orchestrator 统计增加按源计数（calls/success/fail），便于健康面板聚合。  
2) API 诊断面板  
   - 新增 `/diagnostics/orchestrator`：返回总请求、缓存命中、回退次数、源级统计。  
   - `/diagnostics/langgraph` 仍用于 LangGraph DAG/自检。  
3) 前端可用的数据来源提示  
   - ChatHandler 价格查询返回包含 `data_origin`、`fallback_used`、`tried_sources`、`trace`、`as_of`，前端可直接展示数据来源/兜底提示。  
4) 思考过程时长  
   - ConversationAgent 在结果中增加 `thinking_elapsed_seconds`（包含错误路径），前端可显示“已思考 X 秒”。  

## 测试
- 命令：  
  `python -m pytest backend/tests/test_langgraph_selfcheck.py test/test_financial_graph_agent.py backend/tests/test_orchestrator_metadata.py backend/tests/test_orchestrator.py::test_fetch_with_fallback backend/tests/test_orchestrator.py::test_fetch_all_fail backend/tests/test_orchestrator.py::test_cache_integration`
- 结果：6 通过，0 失败（已有 PytestReturnNotNoneWarning 和 datetime.utcnow DeprecationWarning，源于历史测试/标准库提示，未改动逻辑）。

## 后续建议
- 前端流水线面板：调用 `/diagnostics/langgraph` + `/diagnostics/orchestrator`，展示节点/边、数据来源、回退比例、源健康度。  
- 可以在健康面板中对 `trace.duration_ms` 做分位数聚合；如需消除 DeprecationWarning，可统一使用 `datetime.now(timezone.utc).isoformat()`.  
