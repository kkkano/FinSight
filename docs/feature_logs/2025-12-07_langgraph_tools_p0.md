# Feature Log - LangGraph 自检 & 工具元数据（P0）
- 时间：2025-12-07 22:30:28
- 负责人：Codex

## 背景 / 范围
- 按优先级先处理 LangGraph 接线自检、工具层可观测性与回退标记，避免“黑箱”问题。

## 实施内容
1) LangGraph agent  
   - 新增 `describe_graph()`，输出 DAG 概览（节点、边、max_iterations、工具列表）。  
   - 新增 `self_check()`，在不触发外部 LLM 的情况下返回 ready 状态、模型/提供商与 DAG 信息。  
2) 工具层可观测性  
   - `FetchResult` 增加 `fallback_used`、`tried_sources`、`trace` 字段，所有返回路径（成功/缓存/失败/直接调用）均覆盖。  
3) 测试覆盖  
   - 新增 `backend/tests/test_langgraph_selfcheck.py`（Dummy LLM，验证自检接口）。  
   - 新增 `backend/tests/test_orchestrator_metadata.py`（验证回退时的元数据与 trace 一致性）。  
   - 复跑现有关键 Orchestrator 测试用例，确保未回归。

## 测试
- 命令：  
  `python -m pytest backend/tests/test_langgraph_selfcheck.py test/test_financial_graph_agent.py backend/tests/test_orchestrator_metadata.py backend/tests/test_orchestrator.py::test_fetch_with_fallback backend/tests/test_orchestrator.py::test_fetch_all_fail backend/tests/test_orchestrator.py::test_cache_integration`
- 结果：6 通过，0 失败；现有测试文件内的 return 产生 PytestReturnNotNoneWarning（既有遗留，未修改断言结构）。

## 结论 / 下一步
- LangGraph 自检与工具 trace 已落地，可用于前端/健康检查展示。  
- 后续可在 API 层暴露自检结果（如 `/diagnostics/langgraph`）并在前端流水线面板显示节点/trace。  
