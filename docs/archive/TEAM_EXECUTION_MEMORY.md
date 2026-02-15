# FinSight 执行记忆锚点（会话丢失恢复）

> 状态：Active  
> 最后更新：2026-02-07  
> 目的：当 AI 会话丢失时，快速恢复“必须遵守的开发流程与当前共识”。

## 1) 核心原则（必须遵守）

- `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 是 LangGraph 重构与实施的 **SSOT**。
- 所有开发任务都要走：**先登记 TODOLIST -> 执行 -> 完成勾选+证据 -> 写 devlog**。
- 历史阶段文档（`docs/02~05_PHASE*.md`）仅参考，不作为当前实现依据。

## 2) 标准执行流程（每次任务）

1. 在 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 的 `11.x TODOLIST` 新增或细化条目（含 DoD）。
2. 开始执行时将状态更新为 `DOING`（或在条目中体现进行中）。
3. 完成后更新为 `DONE`，并补充验收证据：
   - 后端：`pytest` 相关用例
   - 前端：`npm run build --prefix frontend`
   - 如涉及交互：`npm run test:e2e --prefix frontend`
4. 在 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 的 `13. Worklog` 追加一行记录（日期/小节/完成内容/测试证据/备注）。
5. 在 `docs/feature_logs/` 新增对应 devlog（文件名建议：`YYYY-MM-DD_<topic>.md`）。

## 3) 会话丢失后的恢复顺序（必读）

1. 先读本文件：`docs/TEAM_EXECUTION_MEMORY.md`
2. 再读文档索引：`docs/DOCS_INDEX.md`
3. 再读 SSOT：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`
4. 再看运行与发布约束：`docs/11_PRODUCTION_RUNBOOK.md`
5. 最后结合当前代码状态：`git status` / `git diff` / `git log --oneline -n 40`

## 4) 当前共识（2026-02-07）

- 主链路：`/chat/supervisor*` 的 LangGraph 单入口。
- 会话记忆：依赖 `session_id(thread_id)` + checkpointer；生产要求持久化。
- 文档治理：任何新增决策和路线，优先写入 `docs/06`，再同步入口文档。
- 后续方向：在不破坏现有架构前提下推进基金域能力（11.13 路线）。

## 5) 约束声明

- AI 自身跨会话记忆不可靠；本文件是仓库内可追溯“外部记忆”。
- 若本文件与代码冲突：以代码 + `docs/06` 最新记录为准，并立即回写修正文档。

