# Feature Log - 诊断面板按钮位置调整
- 时间：2025-12-07 23:35:33
- 负责人：Codex

## 内容
- 将健康面板按钮移至头部主题切换左侧，默认收起；面板以悬浮卡片形式展开。
- DiagnosticsPanel 支持传入 className 以定位/样式，默认保持收起状态。

## 文件
- frontend/src/components/DiagnosticsPanel.tsx（新增 className，收起逻辑保留）
- frontend/src/App.tsx（按钮放在头部，移除底部展示）

## 测试
- 后端快速集回归：`python -m pytest backend/tests/test_orchestrator_metadata.py backend/tests/test_langgraph_selfcheck.py test/test_financial_graph_agent.py`（3 通过）。
- 前端未自动化测试，需浏览器手验悬浮按钮与展开效果。
