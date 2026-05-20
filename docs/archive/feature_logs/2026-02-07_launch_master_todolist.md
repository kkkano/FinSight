# 2026-02-07｜上线冲刺 Master TODOLIST 同步

## 背景

用户要求把当前讨论的核心方向统一沉淀为可执行 TODOLIST，覆盖：

- LangGraph Trace 可观测性与可解释性增强；
- 工作台 / 市场快讯 / 研报库的信息架构落地；
- RAG 边界与数据库引入节奏；
- 会话记忆隔离与生产发布闭环；
- 前后端一体化上线 Gate（测试、构建、回滚、运维）。

## 本次文档变更

1. 更新 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`
   - 在 `13. Worklog` 新增“11.14 上线冲刺总清单（Master TODOLIST）”记录；
   - 新增 `11.14` 章节，按 `P0/P1/P2` 拆解从当前状态到生产上线的完整任务清单；
   - 明确工程口径：目标 99.99% 可用性，不承诺零缺陷；
   - 明确 Go/No-Go 阻塞 Gate（测试/可观测/会话隔离/安全/回滚）。

2. 与当前共识对齐
   - 保持 `docs/06` 作为 SSOT；
   - 保持“先 TODOLIST、后开发、完成补证据+devlog”流程；
   - 将“可观测性解释优先”纳入上线阻塞项（P0）。

## 验收方式

- 人工核对新增章节与条目存在：
  - `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`（`11.14` 章节）
  - `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`（`13. Worklog` 新增行）
  - `docs/feature_logs/2026-02-07_launch_master_todolist.md`

## 备注

- 本次为“计划与文档收口”，不涉及运行时代码逻辑变更；
- 后续开发必须按 `11.14` 条目逐条推进并回写证据。
