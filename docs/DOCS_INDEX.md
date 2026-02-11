# 文档导航与状态（2026-02）

本页用于标记当前有效文档、历史文档与归档位置，避免继续在过期文档上开发。

## 1. 当前有效（生产与开发以这些为准）

- `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`：LangGraph 重构 SSOT（唯一开发标准）
- `docs/06a_LANGGRAPH_DESIGN_SPEC.md`：LangGraph 设计规范（从 06 拆分）
- `docs/06b_LANGGRAPH_CHANGELOG.md`：LangGraph 变更日志（从 06 拆分）
- `docs/11_PRODUCTION_RUNBOOK.md`：生产部署/回滚/排障 Runbook
- `docs/TEAM_EXECUTION_MEMORY.md`：会话丢失后的执行恢复锚点（流程/证据/devlog 约束）
- `docs/01_ARCHITECTURE.md`：当前生产架构与模块边界
- `docs/05_RAG_ARCHITECTURE.md`：RAG v2 当前架构与检索策略
- `docs/LANGGRAPH_FLOW.md`：LangGraph 11 节点完整数据流文档（含 Mermaid 图）
- `docs/LANGGRAPH_PIPELINE_DEEP_DIVE.md`：LangGraph 全流程深度拆解（12 张 Mermaid 图 + 详细表格 + 端到端数据流）
- `docs/AGENTS_GUIDE.md`：6 个子 Agent 详细文档（数据源/输出/容错/熔断器/选择逻辑）
- `docs/WORKBENCH_ROADMAP.md`：工作台开发路线图（Sprint 1-4）
- `docs/ISSUE_TRACKER.md`：全量问题追踪清单（P0/P1/P2 checkbox）
- `docs/V1_RELEASE_SUMMARY.md`：v1.0.0 发布总结
- `docs/SPRINT2_DEVLOG.md`：Sprint 2 开发日志（v1.1.0 任务清单 + 变更记录）
- `docs/feature_logs/2026-02-10_sprint2_bugfix_batch.md`：Sprint 2 批量修复日志（13 项 bug 修复详情）
- `docs/Thinking/ADR-2026-02-07-agent-routing.md`：Agent 评分选路决策
- `docs/Thinking/ADR-2026-02-07-rag-data-boundary.md`：RAG 数据边界决策
- `docs/Thinking/ADR-2026-02-07-deepsearch-evolution.md`：DeepSearch 演进决策
- `README.md`、`readme_cn.md`：项目入口说明（版本/架构/fallback/tool）
- `tests/retrieval_eval/*`：检索质量评测基线（dataset/thresholds/baseline/CI gate）

## 2. 历史阶段文档（仅参考，不作为实现依据）

- `docs/02_PHASE0_COMPLETION.md`
- `docs/03_PHASE1_IMPLEMENTATION.md`
- `docs/04_PHASE2_DEEP_RESEARCH.md`
- `docs/05_PHASE3_ACTIVE_SERVICE.md`
- `docs/Thinking/2026-01-31_architecture_refactor_guide.md`（Superseded）
- `docs/Thinking/2026-01-31_routing_architecture_decision.md`（Superseded）

## 3. 次级参考文档

- `docs/PROJECT_STRUCTURE.md`
- `docs/ROUTING_ARCHITECTURE_STANDARD.md`
- `docs/ROADMAP.md`（历史路线图）
- `docs/TECHNICAL_QNA.md`
- `docs/DASHBOARD_DEVELOPMENT_GUIDE.md`
- `docs/REPORT_CHART_SPEC.md`
- `docs/design_concept_v2.html`

## 4. 已归档（2026-02 清理）

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

## 5. 文档治理规则

- 新增核心设计/规则，先写入 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`。
- 与代码冲突时，以代码与 06 为准，并同步更新 01/README。
- 历史文档允许保留，但必须在首屏标注 `Archived` 或 `Superseded`。
