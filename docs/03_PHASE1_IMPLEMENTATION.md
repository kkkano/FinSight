# FinSight Phase 1 历史归档（专家 Agent 与协作）

> **状态**: Archived (Reference Only)  
> **最后更新**: 2026-02-07  
> **实现依据**: 请以 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 为准

---

## 1. 本阶段历史目标

Phase 1 的目标是从“单体问答”升级到“专家分工协作”：

- 引入价格/新闻/技术/基本面/宏观等专家能力
- 建立统一协调者与综合输出机制
- 打通基础上下文记忆

当前这些能力已经纳入 LangGraph 主链路中的 Planner/Executor/Adapter 体系。

---

## 2. 仍然有效的历史产出

| 能力 | 当前归属 |
|---|---|
| 专家能力实现 | `backend/orchestration/agents/*` |
| Agent 适配层 | `backend/graph/adapters/agent_adapter.py` |
| 任务执行入口 | `backend/graph/nodes/execute_plan_stub.py`（逐步收口到统一 executor） |
| 对话上下文基础 | API session-scoped context + graph state |

---

## 3. 已被替代或收口的内容

- 旧 Supervisor 主链路叙事已替换为 LangGraph 单入口。
- 旧路由分类与多处分支追问模型不再作为当前设计。
- 仅保留必要兼容层，不再以该阶段文档驱动开发。

---

## 4. 与当前文档的关系

- 当前架构：`docs/01_ARCHITECTURE.md`
- 重构 SSOT：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`
- 生产部署：`docs/11_PRODUCTION_RUNBOOK.md`

---

## 5. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-02-07 | 文档改为历史归档格式，清理旧计划态与旧路由描述 |
