# 归档说明：Agent 可观测性审计后的文档清理

归档日期：2026-05-02

本批次归档目标是减少根目录和 `docs/plans/` 中过期路线图、完成态 todolist、临时报告对当前开发判断的干扰。归档不代表删除，只代表这些文档不再作为当前事实源。

## 归档文件

| 原路径 | 归档原因 |
|---|---|
| `docs/CLAUDE.md` | 旧执行记忆，职责已由仓库级 `AGENTS.md` 和 `docs/AGENTS.md` 覆盖。 |
| `docs/DASHBOARD_AGENT_TODOLIST.md` | Dashboard 旧阶段清单，大量条目已完成或被后续工作取代。 |
| `docs/DASHBOARD_HOTFIX_2026-02-17.md` | 已完成 hotfix 记录，保留作历史证据。 |
| `docs/DASHBOARD_P0_DATA_TRACE.md` | 已完成 P0 trace 草稿，当前事件契约以 `execution-event-contract.md` 为准。 |
| `docs/INTERVIEW_PREP.md` | 非当前产品/架构事实源。 |
| `docs/PHASE_1_4_TEST_REPORT.md` | 旧阶段测试报告，保留作历史证据。 |
| `docs/PROJECT_STRUCTURE.md` | 文件自身已标记 archived，且描述 v1 ConversationAgent 时代结构。 |
| `docs/PROMPT_OPTIMIZATION_CHANGELOG.md` | 旧提示词优化报告，后续改造以计划 spec 和代码测试为准。 |
| `docs/ROADMAP_PHASES_1_4_FINAL.md` | 旧阶段路线图，已被当前 LangGraph/RAG 计划取代。 |
| `docs/ROUTING_ARCHITECTURE_STANDARD.md` | 旧 `ConversationRouter` / `SchemaRouter` 标准，已被 LangGraph 单入口和 request understanding spec 取代。 |
| `docs/plans/FORUM_PROMPT_OPTIMIZATION.md` | Forum 旧 prompt 计划，已非当前执行主线。 |
| `docs/plans/FORUM_PROMPT_OPTIMIZATION_V2.md` | Forum 旧 prompt 计划迭代版，已非当前执行主线。 |
| `docs/plans/Future_Blueprint_Execution_Plan_CN.md` | 早期蓝图执行计划，已被后续架构文档和计划取代。 |

## 保留在当前区的文档

- LangGraph、RAG、事件契约、生产 runbook、Dashboard 开发指南继续保留在 `docs/` 根目录。
- 当前仍在推进的 RAG 计划继续保留在 `docs/plans/`。
- 探索性材料继续留在 `docs/Thinking/`，但不作为当前事实源。
