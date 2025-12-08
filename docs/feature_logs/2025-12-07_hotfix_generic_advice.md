# Hotfix - 泛化股票推荐与动态状态
- 时间：2025-12-07 23:14:10
- 负责人：Codex

## 内容
- 后端 ChatHandler：无 ticker 时增加 `_handle_generic_recommendation`（静态示例标的 + 风险提示 + 分批仓位建议），在闲聊/建议分支命中，避免“推荐几只股票”无法响应。
- 状态计时/来源字段：沿用上一轮改动，未变。

## 文件
- backend/handlers/chat_handler.py

## 测试
- 运行：`python -m pytest backend/tests/test_orchestrator_metadata.py backend/tests/test_langgraph_selfcheck.py test/test_financial_graph_agent.py`
- 结果：3 通过，0 失败（仍有 datetime.utcnow DeprecationWarning，未改动）。
