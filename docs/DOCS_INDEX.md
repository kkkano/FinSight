# 文档索引（2026-02-24）

本页用于区分“当前有效文档”与“历史归档文档”，避免继续引用过期方案。

## 1) 当前有效（开发与运维优先阅读）

- `readme.md`：项目入口、启动与关键链路摘要
- `readme_cn.md`：中文版架构与使用说明
- `docs/01_ARCHITECTURE.md`：当前系统架构与流程图（Mermaid）
- `docs/AGENTS_GUIDE.md`：Agent 与 Tool 链路矩阵（与代码对齐）
- `docs/DASHBOARD_DEVELOPMENT_GUIDE.md`：Dashboard 前后端开发指南
- `docs/DASHBOARD_AGENT_TODOLIST.md`：Dashboard/Workbench 迭代路线
- `docs/11_PRODUCTION_RUNBOOK.md`：生产运行与排障手册
- `docs/05_RAG_ARCHITECTURE.md`：RAG 体系结构说明
- `docs/LANGGRAPH_FLOW.md`：LangGraph 流程文档
- `docs/LANGGRAPH_PIPELINE_DEEP_DIVE.md`：LangGraph 深度拆解

## 2) 设计与计划文档（按需参考）

- `docs/plans/*`：规划类文档
- `docs/design/*`：视觉/方案设计稿
- `docs/prototype/*`：原型页面
- `docs/feature_logs/*`：阶段功能日志
- `docs/feature_logs/2026-02-19_phase_j_evidence_quality_upgrade.md`：Phase J 证据质量增强落地记录

## 3) 思考与决策记录（保留，不删除）

- `docs/Thinking/*`：思考过程、ADR、问题分析

> 规则：`docs/Thinking` 为保留区，不做清理删除。

## 4) 归档区

- `docs/archive/*`
- `docs/archive/2026-02-doc-cleanup/*`

历史方案、旧阶段报告、已完成临时文档统一进入归档目录。

## 5) 本轮清理记录

- 已将 `docs/workbench_v2_preview.html` 归档到 `docs/archive/2026-02-doc-cleanup/workbench_v2_preview.html`

## 6) 文档治理规则

- 任何架构链路变化，至少同步更新：
  - `readme.md`
  - `docs/01_ARCHITECTURE.md`
  - `docs/AGENTS_GUIDE.md`
- 新文档创建后，必须在本索引登记。
- 不确定是否废弃时，优先“归档 + 索引备注”，不直接删除。

## 2026-02-20 ����ͬ����Phase J P0/P1��
- ����/�����ص��ĵ���
  - `docs/feature_logs/2026-02-19_phase_j_evidence_quality_upgrade.md`��P0/P1 ��� + smoke �����
  - `docs/06b_LANGGRAPH_CHANGELOG.md`��Phase J P0/P1 completion��
  - `scripts/phase_j_smoke_before_after_2026-02-19.json`��AAPL/600519 before-after �Աȣ�
- �������ļ�һ���Ķ���������ԭ���ִӡ������ż�����ʧ�ܡ�������� API �������������á������·����

## 2026-02-20 Incremental Sync (Phase J P2)
- Updated docs:
  - `docs/feature_logs/2026-02-19_phase_j_evidence_quality_upgrade.md` (added P2 section)
  - `docs/06b_LANGGRAPH_CHANGELOG.md` (added Phase J P2 completion)
  - `docs/AGENTS_GUIDE.md` (added P2 tool matrix and routing notes)
  - `AGENTS.md` (added architecture sync block for P2)
- New/updated runtime evidence path summary:
  - DeepSearch fallback order now includes Wayback for hard paywalls.
  - Transcript retrieval expanded for CN/HK markets.
  - Macro agent now emits official-source release evidence (BLS/BEA/FED).

## 2026-02-20 Incremental Sync (Phase J P3)
- Updated docs:
  - `docs/feature_logs/2026-02-19_phase_j_evidence_quality_upgrade.md` (added P3 section)
  - `docs/06b_LANGGRAPH_CHANGELOG.md` (added Phase J P3 completion)
  - `docs/AGENTS_GUIDE.md` (added market-routing tool matrix)
  - `AGENTS.md` (added architecture sync block for P3)
- Runtime capability summary:
  - US quarterly financial fallback now includes SEC CompanyFacts (XBRL).
  - CN/HK valuation + financials + kline now have dedicated free source routing.
  - Peer defaults are now split by market to avoid US-basket fallback on CN/HK symbols.

## 2026-02-24 Pseudo-Comparison Bug Fix + Turn State Reset

- 更新文档：
  - `readme.md` / `readme_cn.md`：LangGraph 管线 15→16 节点，Mermaid 图加入 `reset_turn_state`
  - `docs/LANGGRAPH_FLOW.md`：13→16 节点，加入 reset_turn_state 节点文档
  - `docs/01_ARCHITECTURE.md`：流程图加入 reset_turn_state
  - `docs/06b_LANGGRAPH_CHANGELOG.md`：追加完整变更条目
- 新增模块：
  - `backend/graph/nodes/compare_gate.py`：compare evidence gate（3 个谓词函数）
  - `backend/graph/nodes/reset_turn_state.py`：per-turn 状态清除（12 字段 + 5 trace sub-keys）
- 新增测试：
  - `backend/tests/test_compare_gate.py`（24 tests）
  - `backend/tests/test_graph_node_order.py`（6 tests）
  - `backend/tests/test_p0_unit.py`（41 tests）
- 回归：964 passed, 15 skipped, 0 failed
