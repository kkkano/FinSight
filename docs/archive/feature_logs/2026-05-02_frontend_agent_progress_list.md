# 2026-05-02 前端 Agent 级进度列表

状态：已完成前端小批次

## 本批范围

- `executionStore` 将 `plan_ready` 的 selected agents 初始化为 `pending`，并保留计划步骤中的 `stepId` 与 `parallelGroup`。
- `executionStore` 新增 `agent_step` 事件归一化，持续写入单个 Agent 的 `progress`、`currentStep`、`lastEventAt`、`stepId` 和 `parallelGroup`。
- `agent_start`、`agent_done`、`agent_error` 同步维护 Agent 级进度，完成或异常时将对应 Agent 进度收敛到 `100`。
- 新增 `AgentProgressList`，在用户模式下展示每个 Agent 的实时步骤、状态、进度条、并行组和耗时。
- `ExecutionPanel` 用户模式从简略 Agent 卡片切换为更可观测的 Agent 进度列表，减少执行中“只知道系统在转圈”的黑箱感。
- `StreamingResultPanel` 运行态复用同一套 `AgentProgressList`，避免右侧执行结果面板继续维护第二套简略 Agent 状态 UI。

## 验证

```powershell
npx vitest run src/store/executionStore.reducer.test.ts
npx vitest run src
npm run build
```

结果：

```text
src/store/executionStore.reducer.test.ts: 5 passed
npx vitest run src: 9 passed
npm run build: passed
```

说明：本批只覆盖状态归一化和用户模式展示，不包含 RAG Inspector 的 layer 深链/过滤 UI 收口；那部分仍保持在后续批次处理。
