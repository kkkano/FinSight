# 2026-02-07｜会话丢失恢复记忆机制落地

## 背景

用户明确要求：

- 任务前必须写入 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 的 TODOLIST；
- 任务完成必须更新 DONE 与证据；
- 必须补充 devlog；
- 需要一份“会话丢失后可恢复”的固定记忆锚点。

## 本次变更

1. 更新 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`
   - 在 `11.0 文档维护` 中新增“会话丢失恢复记忆固化”完成项；
   - 明确“每次实现后”除了验收证据，还需补 `docs/feature_logs` devlog；
   - 在 `13. Worklog` 追加本次记录。

2. 新增 `docs/TEAM_EXECUTION_MEMORY.md`
   - 固化执行原则（SSOT、流程、证据）；
   - 固化会话丢失恢复顺序（先读锚点 -> 索引 -> SSOT -> Runbook -> Git状态）；
   - 固化当前共识与冲突处理规则。

3. 更新 `docs/DOCS_INDEX.md`
   - 将 `docs/TEAM_EXECUTION_MEMORY.md` 纳入“当前有效”文档入口。

## 验收方式

- 人工核对文件存在与内容一致：
  - `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`
  - `docs/TEAM_EXECUTION_MEMORY.md`
  - `docs/DOCS_INDEX.md`
  - `docs/feature_logs/2026-02-07_session_recovery_memory.md`

## 备注

- 该机制不替代代码与测试，只解决“会话上下文丢失后的流程恢复”。
- 后续所有任务按此机制执行并持续更新。

