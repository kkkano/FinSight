# Feature Log - 前端数据来源 & 健康面板 + 建议兜底
- 时间：2025-12-07 23:14:10
- 负责人：Codex

## 内容
- 前端 Loader/状态：显示当前动作文案 + 实时秒数（避免假死）。
- 数据来源标签：助手消息可显示 data_origin / as_of / fallback_used / tried_sources。
- 健康面板：新增 DiagnosticsPanel 调用 /diagnostics/langgraph 与 /diagnostics/orchestrator 展示节点/模型与源健康。
- 泛化推荐入口：ChatInput 增加快捷按钮“推荐几只股票”等示例输入。
- UTC 警告修复：orchestrator 使用 timezone.utc 的时间戳。
- 前端测试脚本占位：package.json 增加 test 脚本占位，避免缺失脚本错误。

## 代码
- frontend/src/types/index.ts
- frontend/src/api/client.ts
- frontend/src/components/ChatInput.tsx
- frontend/src/components/ChatList.tsx
- frontend/src/components/DiagnosticsPanel.tsx (新增)
- frontend/src/App.tsx
- backend/orchestration/orchestrator.py
- package.json

## 测试
- 后端快速集：`python -m pytest backend/tests/test_orchestrator_metadata.py backend/tests/test_langgraph_selfcheck.py test/test_financial_graph_agent.py`（3 通过）。
- 前端：未跑自动化（脚本占位），需浏览器手验状态条、来源标签与健康面板。
