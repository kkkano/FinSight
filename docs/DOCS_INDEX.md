# 文档导航与状态（2026-02）

本页用于标记当前有效文档、历史文档与归档位置，避免继续在过期文档上开发。

## 1. 当前有效（生产与开发以这些为准）

- `docs/06a_LANGGRAPH_DESIGN_SPEC.md`：**LangGraph 设计 SSOT（唯一开发标准）**
- `docs/06b_LANGGRAPH_CHANGELOG.md`：LangGraph 变更日志（配合 06a 使用）
- `docs/11_PRODUCTION_RUNBOOK.md`：生产部署/回滚/排障 Runbook
- `docs/01_ARCHITECTURE.md`：当前生产架构与模块边界
- `docs/05_RAG_ARCHITECTURE.md`：RAG v2 当前架构与检索策略
- `docs/LANGGRAPH_FLOW.md`：LangGraph 15 节点完整数据流文档（含 Mermaid 图）
- `docs/LANGGRAPH_PIPELINE_DEEP_DIVE.md`：LangGraph 全流程深度拆解（12 张 Mermaid 图 + 详细表格 + 端到端数据流）
- `docs/AGENTS_GUIDE.md`：6 个子 Agent 详细文档（数据源/输出/容错/熔断器/选择逻辑）
- `docs/PROMPT_OPTIMIZATION_CHANGELOG.md`：全项目 18 个 LLM 提示词优化前后对比报告
- `docs/Thinking/ADR-2026-02-07-agent-routing.md`：Agent 评分选路决策
- `docs/Thinking/ADR-2026-02-07-rag-data-boundary.md`：RAG 数据边界决策
- `docs/Thinking/ADR-2026-02-07-deepsearch-evolution.md`：DeepSearch 演进决策
- `README.md`：项目入口说明（版本/架构/评分口径/API/工具）
- `tests/retrieval_eval/*`：检索质量评测基线（dataset/thresholds/baseline/CI gate）

## 2. 次级参考文档

- `docs/PROJECT_STRUCTURE.md`
- `docs/ROUTING_ARCHITECTURE_STANDARD.md`
- `docs/DASHBOARD_DEVELOPMENT_GUIDE.md`
- `docs/REPORT_CHART_SPEC.md`

## 3. 已归档（2026-02 大扫除）

以下文件已迁移到 `docs/archive/`：

**阶段文档（历史参考）：**
- `02_PHASE0_COMPLETION.md`
- `03_PHASE1_IMPLEMENTATION.md`
- `04_PHASE2_DEEP_RESEARCH.md`
- `05_PHASE3_ACTIVE_SERVICE.md`
- `06_LANGGRAPH_REFACTOR_GUIDE.md`（**DEPRECATED** — 已由 06a + 06b 取代）

**执行记录 & 路线图（已完成）：**
- `AGENTIC_SPRINT_TODOLIST.md`
- `EXECUTION_PLAN_DETAILED.md`
- `SPRINT2_DEVLOG.md`
- `V1_RELEASE_SUMMARY.md`
- `WORKBENCH_ROADMAP.md`
- `ROADMAP.md`
- `TEAM_EXECUTION_MEMORY.md`

**问题追踪 & 技术问答（已关闭）：**
- `ISSUE_TRACKER.md`
- `TECHNICAL_QNA.md`
- `QUERY_MATRIX_REPORT.md`
- `AGENT_ARCHITECTURE_DESIGN.md`

**设计预览（已实现）：**
- `dashboard_v2_preview.html`
- `design_concept_v2.html`

**旧一批归档（2026-02 早期清理）：**
- `PROJECT_ANALYSIS_V1.md`、`PROJECT_STATUS.md`、`fix_summary_2026-01-24.md` 等
- 完整列表见 `docs/archive/2026-02-doc-cleanup/`

## 4. 文档治理规则

- 新增核心设计/规则，先写入 `docs/06a_LANGGRAPH_DESIGN_SPEC.md`（SSOT）。
- 与代码冲突时，以代码与 06a 为准，并同步更新 01/README。
- 历史文档允许保留，但必须在首屏标注 `Archived` 或 `Superseded`。
- `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 已废弃并归档，不再作为开发依据。
