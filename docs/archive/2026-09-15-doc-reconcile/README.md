# 2026-09-15 文档对账归档

本批次保存已被当前六节点 LangGraph、统一 evidence contract 和 2026-09 重构方案取代的早期规划材料。归档文件仅用于理解历史决策，不是当前架构、接口或产品路线的事实源。

| 原路径 | 归档路径 | 原因 |
|---|---|---|
| `docs/Thinking/2026-01-29_schema_router_followup.txt` | `legacy-thinking/2026-01-29_schema_router_followup.txt` | 描述已移除的 Schema Router/Supervisor 接线 |
| `docs/Thinking/issue1.txt` | `legacy-thinking/issue1.txt` | 早期 Agent 数据源与 P0-P2 路线草案，能力边界和实现路径已被替代 |
| `docs/Thinking/issue2.txt` | `legacy-thinking/issue2.txt` | 基于旧多 Agent/Forum 架构的优化路线草案 |
| `docs/Thinking/issue3.txt` | `legacy-thinking/issue3.txt` | 与 `issue1/issue2` 重复的旧 Agent 演进路线 |
| `docs/Thinking/overview.txt` | `legacy-thinking/overview.txt` | 旧 Supervisor/Forum 质量改进计划，不符合当前六节点边界 |
| `docs/Thinking/subagent.txt` | `legacy-thinking/subagent.txt` | 旧子 Agent 方案与当前 Collector/ResearchAnalyst 合同冲突 |
| `docs/Thinking/unified_supervisor_proposal.py` | `legacy-thinking/unified_supervisor_proposal.py` | 未进入生产的 UnifiedSupervisor 提案，当前执行入口为 `/api/execute` 和六节点 Graph |

当前事实源：

- 架构：`../../01_ARCHITECTURE.md`
- Graph：`../../LANGGRAPH_FLOW.md`、`../../06a_LANGGRAPH_DESIGN_SPEC.md`
- 产品目标：`../../../DESIGN.md`
- 生产：`../../11_PRODUCTION_RUNBOOK.md`
