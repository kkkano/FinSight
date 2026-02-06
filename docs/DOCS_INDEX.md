# 文档导航与状态（2026-02）

本页用于标记当前有效文档、历史文档与归档位置，避免继续在过期文档上开发。

## 1. 当前有效（生产与开发以这些为准）

- `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`：LangGraph 重构 SSOT（唯一开发标准）
- `docs/11_PRODUCTION_RUNBOOK.md`：生产部署/回滚/排障 Runbook
- `docs/01_ARCHITECTURE.md`：架构说明（保留，冲突时以 06 为准）
- `docs/05_RAG_ARCHITECTURE.md`：RAG 设计说明（后续按 06/11.10 决议继续演进）
- `readme.md`、`readme_cn.md`：项目入口说明

## 2. 次级参考（仅供补充，不作为 SSOT）

- `docs/02_PHASE0_COMPLETION.md`
- `docs/03_PHASE1_IMPLEMENTATION.md`
- `docs/04_PHASE2_DEEP_RESEARCH.md`
- `docs/05_PHASE3_ACTIVE_SERVICE.md`
- `docs/PROJECT_STRUCTURE.md`
- `docs/ROUTING_ARCHITECTURE_STANDARD.md`
- `docs/ROADMAP.md`
- `docs/TECHNICAL_QNA.md`
- `docs/DASHBOARD_DEVELOPMENT_GUIDE.md`
- `docs/REPORT_CHART_SPEC.md`
- `docs/design_concept_v2.html`

## 3. 已归档（2026-02 清理）

已迁移到 `docs/archive/2026-02-doc-cleanup/`：

- `PROJECT_ANALYSIS_V1.md`
- `PROJECT_STATUS.md`
- `fix_summary_2026-01-24.md`
- `PHASE2_DEMO_REPORT.md`
- `QUALITY_IMPROVEMENT_OVERVIEW_V2.md`
- `QUALITY_IMPROVEMENT_OVERVIEW_V3.md`
- `PROMPT_OPTIMIZATION_PROPOSAL.md`
- `PROMPT_REDESIGN_SYNTHESIS.md`
- `DASHBOARD_IMPLEMENTATION_PLAN.md`
- `_utf8_test.txt`

## 4. 规则

- 新增核心设计或执行规则，先写入 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`。
- 文档与代码冲突时，先更新代码，再同步 06 和 11。
- 历史文档只允许归档，不允许继续作为“当前实现依据”。
