# Frontend Status UI update
- 时间：2025-12-07 23:01:57
- 负责人：Codex

## 内容
- Chat loader 改为动态状态：显示当前动作文案 + 实时秒数计时，避免“FinSight 正在分析...”假死感。
- 引入全局状态 `statusMessage/statusSince`，发送消息时提示“Analyzing…”，完成后提示耗时并短暂展示。
- ChatHandler 价格返回 now 包含 as_of/fallback/trace，可供前端展示来源。
- ConversationAgent 返回 `thinking_elapsed_seconds`，用于前端耗时展示。

## 代码点
- frontend/src/store/useStore.ts
- frontend/src/components/ChatInput.tsx
- frontend/src/components/ChatList.tsx
- backend/conversation/agent.py
- backend/handlers/chat_handler.py
- backend/orchestration/orchestrator.py

## 测试
- 前端未提供 npm test 脚本：`npm test -- --runInBand` 提示 Missing script "test"（未运行）。
- 需人工在浏览器验证加载器状态/计时显示。
