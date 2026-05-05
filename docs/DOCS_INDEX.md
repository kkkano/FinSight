# FinSight 文档索引

更新时间：2026-05-06
目标：把当前事实源、目标 spec、历史材料分开，避免继续引用过期路线图、临时报表和已完成 todolist。

## 当前必读

- `docs/01_ARCHITECTURE.md`：当前系统架构入口，描述主模块和数据流。
- `docs/06a_LANGGRAPH_DESIGN_SPEC.md`：LangGraph 主链路设计规范；当前代码以 `backend/graph/runner.py` 与 `understand_request` 测试为准。
- `docs/06b_LANGGRAPH_CHANGELOG.md`：LangGraph 相关变更日志。
- `docs/AGENTS_GUIDE.md`：Agent、Tool、Planner、Executor 链路说明。
- `docs/execution-event-contract.md`：执行事件、阶段、trace 展示契约。
- `docs/11_PRODUCTION_RUNBOOK.md`：生产运行和排障手册。
- `docs/DEPLOYMENT.md`：部署说明。
- `docs/AGENTS.md`：docs 目录协作规则和归档边界。

## 当前实现 Spec

- `docs/plans/2026-05-03_request_understanding_task_graph_spec.md`：请求理解层重构 spec。已接入 `prepare_context`、纯社交 `chat_respond`、`understand_request` 内 LLM conversation router、`tasks[]`、`blocked_tasks[]`、URL 工具 `fetch_url_content`、用户可见 trace、planner stub 多任务消费、executor `task_results`、后端 `/api/conversations` 生命周期 API、服务端 conversation snapshot store、会话标题/messages/PATCH 和停止生成 cancellation token 闭环；后续剩余项是 planner/executor/synthesize 全量多任务原生化硬化、多设备 conversation store 迁移和同步外部工具 cooperative cancel。
- `docs/plans/2026-05-02_agent_observability_report_quality_spec.md`：Agent 进度可观测、DeepSearch、报告质量和回答契约改造 spec。
- `docs/plans/2026-03-08_rag_three_layer_architecture_todolist.md`：三层 RAG 架构计划。
- `docs/plans/2026-03-07_rag_local_pg_observability_validation.md`：本地 PG 可观测验证计划。
- `docs/plans/2026-03-06_rag_observability_inspector_todolist.md`：RAG inspector 计划。

## 当前运行链路参考

- `docs/LANGGRAPH_FLOW.md`：当前运行时节点流参考。注意：它描述的是现状/历史快照，不是下一阶段目标架构。
- `docs/LANGGRAPH_PIPELINE_DEEP_DIVE.md`：Pipeline 深度拆解和排障入口。注意：节点数量和目标架构以最新 spec 与代码为准。

## 质量与报告

- `docs/reports/2026-05-03_request_understanding_query_results.md`：20 条复杂 query 的请求理解与规划矩阵输出。
- `docs/reports/2026-05-03_playwright_chat_smoke.md`：聊天 UX、会话切换/删除、Deep 模式启用、用户可见 trace 和停止生成的 Playwright 验证记录。
- `docs/qa/chat-ux-40-query-full-url-agent-2026-05-05.md`：当前聊天 UX 40-query 全量验收，保留完整 query 和答案；配套 JSON 为同名 `.json`。结果 39/40 PASS，达到 80-90% 发布线。
- `docs/qa/chat-ux-targeted-post-acceptance-polish-2026-05-06.md`：Q16/Q26/Q27/Q39 定向回归，验证 portfolio context、alert 文案、URL 失败文案和复合任务 polish；结果 4/4 PASS。
- `docs/qa/chat-ux-40-query-live-eval-2026-05-04.md` 与 `docs/qa/chat_regression_queries_2026_05_03.*` 是历史回归样本，保留作对比。
- `docs/HALLUCINATION_MITIGATION.md`：幻觉缓解与证据约束。
- `docs/REPORT_CHART_SPEC.md`：报告图表规范。
- `docs/rag-evaluation-guide.md`：RAG 评估方法。
- `docs/12_PRODUCTION_SSE_TUNNEL_POSTMORTEM.md`：SSE 隧道事故复盘，作为生产风险参考。

## RAG 体系

- `docs/05_RAG_ARCHITECTURE.md`：RAG v2 生产化架构说明。
- `docs/08_RAG_ARCHITECTURE.md`：pgvector + bge-m3 混合检索升级对比。

## 前端与 Dashboard

- `docs/DASHBOARD_DEVELOPMENT_GUIDE.md`：Dashboard/Workbench 开发指南。
- `docs/design/`：视觉方案与品牌资产。
- `docs/prototype/`：静态原型。
- `docs/ux/`：信息架构和交互提案。

## 历史与归档

- `docs/archive/`：过期方案、旧路线图、临时报表和被替代文档。
- `docs/archive/2026-05-agent-observability-cleanup/`：2026-05 文档清理归档批次。
- `docs/archive/2026-05-agent-observability-cleanup/ROUTING_ARCHITECTURE_STANDARD.md`：旧 `ConversationRouter` / `SchemaRouter` 标准，已被 LangGraph 单入口和 request understanding spec 取代。
- `docs/feature_logs/`：已完成工作的流水记录，只作追溯证据。
- `docs/Thinking/`：ADR、探索草稿和问题分析；默认不作为当前事实源。
- `docs/release_evidence/`：发布演练和运行证据。
- `docs/reports/`：生成报告和 trace 报告样本。

## 治理规则

- 根目录只放当前有效、需要长期引用的文档。
- 新计划放 `docs/plans/`，完成或过期后归档到 `docs/archive/<yyyy-mm-topic>/`。
- 不直接删除历史文档；归档时在批次 README 记录原路径和原因。
- 文档新增、移动或归档后，必须同步更新本索引。
- 如果文档与代码冲突，以代码、测试和运行日志为准，并在文档中标记需校准项。
