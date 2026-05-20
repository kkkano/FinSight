# 2026-05-02 前端 Chat 上下文控制与停止生成

状态：已完成前端小批次

## 本批范围

- `useStore` 新增会话级动作：
  - `clearConversationContext()`：保留当前 session，清空消息、草稿、ticker、执行状态、agent logs、raw events 和 request metrics。
  - `startNewChat()`：创建新 session，并以干净欢迎消息启动新对话。
  - `cancelChatStream()`：中止当前 chat SSE 请求并清理运行态。
- `ChatInput` 为每次流式请求创建 `AbortController`，并把 signal 传到 `sendMessageStream()`。
- 运行中发送按钮切换为 Stop 按钮，用户可中途停止当前响应。
- `sendMessageStream()` 支持 `AbortSignal`，中止后不再把缺少 `done` 事件误报为 stream error。
- `ChatWorkspace` 顶部新增“新对话”和“清空上下文”入口。
- `/chat?report_id=...` 回放后不再强制 `replaceState('/chat')`，避免深链参数被首屏抹掉。
- API client 同步支持 RAG diagnostics 的 `include_deleted` 参数，便于后续 Inspector 接上软删除回看。

## 验证

```powershell
npm run test:unit -- src/store/useStore.conversation.test.ts
npx vitest run src
npm run build
```

结果：

```text
src/store/useStore.conversation.test.ts: 2 passed
npx vitest run src: 8 passed
npm run build: passed
```

说明：`npm run test:unit` 当前会收集 `frontend/e2e/*.spec.ts`，这些文件使用 Playwright `test()` DSL，需用 `npm run test:e2e` 执行，不能直接交给 Vitest。

## 后续仍需处理

- `AgentProgressList` 独立组件和 agent 级进度展示。
- RAG Inspector 暴露 `include_deleted` 开关并整理 layer 深链改动。
- 前端整体 E2E/截图验收。
