# M9 旧执行界面证据

此目录保存删除前的 execution 组件、store、类型、快照和 AgentLogPanel 旧版本，不进入前端构建。

`manifest.json` 逐文件记录 SHA256 和处置。旧图固定阶段、预计百分比、旧 Agent 别名和瀑布布局断言只描述已退役实现，不复制到当前 UI。

现行协议继续由 `useChatStream.test.ts`、`researchStream.test.ts`、`TurnActivity.test.tsx` 运行。新 `agent-log/eventModel.test.ts` 与 `AgentLogPanel.test.tsx` 覆盖 v2 身份、重放去重、并行结束状态、筛选和脱敏 JSON；交付等待与会话恢复 E2E 保留业务断言，移除旧 store 百分比断言。

AgentLogPanel 保留开发者入口、搜索、类型与 Agent 多选、暂停、自动滚动、详情/复制、脱敏导出、最大化和清空。颜色与字号使用既有 `t-*` 语义令牌和 `text-2xs`。ChatList、核查组件、researchStream 及拆分后的 store 未改动。
