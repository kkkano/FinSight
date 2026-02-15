# FinSight Phase 2 历史归档（深度研究与研报能力）

> **状态**: Archived (Reference Only)  
> **最后更新**: 2026-02-07  
> **实现依据**: 请以 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 为准

---

## 1. 本阶段历史目标

Phase 2 的目标是将系统从“回答问题”提升到“可交付研究结论”：

- 深度检索能力引入
- 结构化研报输出（ReportIR）
- 证据链与可追溯性增强

当前这些目标已映射到 LangGraph 的 Planner/Execute/Synthesize 与 RAG v2 路径。

---

## 2. 仍然有效的历史产出

| 能力 | 当前归属 |
|---|---|
| 结构化研报渲染能力 | `backend/report/*` + 前端报告视图 |
| 证据池思路 | `evidence_pool` / `trace` / `rag_context` |
| 深度研究能力 | `deep_search_agent` + 执行层检索补充 |
| 宏观维度能力 | `macro_agent` + 事件/数据工具 |

---

## 3. 已被替代或收口的内容

- 旧的“阶段路线图式”任务状态标签不再维护。
- 早期仅以 Chroma 本地为中心的叙事已升级为 RAG v2 混合检索方向。
- 当前是否启用哪些链路，以 `docs/06` 11.x 清单和代码实况为准。

---

## 4. 与当前文档的关系

- 当前架构：`docs/01_ARCHITECTURE.md`
- 重构 SSOT：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`
- RAG 专项：`docs/05_RAG_ARCHITECTURE.md`
- 生产部署：`docs/11_PRODUCTION_RUNBOOK.md`

---

## 5. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-02-07 | 文档改为历史归档格式，去除过期阶段状态与旧实现假设 |
