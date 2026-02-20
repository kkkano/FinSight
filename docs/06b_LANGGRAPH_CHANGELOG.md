# FinSight LangGraph 变更记录（Changelog / Patch Notes / Worklog）

> 本文件记录 LangGraph 重构过程中的所有变更条目、补丁说明和实施日志。
> 设计规范见 `06a_LANGGRAPH_DESIGN_SPEC.md`，TODO/路线图见 `AGENTIC_SPRINT_TODOLIST.md`。

---

## 10. 变更记录（按日追踪）

| 日期 | 类型 | 内容 | 影响范围 |
|---|---|---|---|
| 2026-02-15 | 文档同步 | 在 `05_RAG_ARCHITECTURE.md` 新增「4.3 数据分层与字段归属（Memory/Portfolio/RAG/Live）」；补充字段级归属、生命周期与三条硬规则；在 `06a_LANGGRAPH_DESIGN_SPEC.md` 新增 `4.4 数据分层约束` 与路由原则，统一开发语义边界。 | Docs（RAG 架构 + LangGraph 设计规范） |
| 2026-02-02 | 研报入口 | 使用 **按钮触发专用**，区分发送按钮和 | FE/BE 接口增加 `options.output_mode` |
| 2026-02-02 | selection 宽松 | `strict_selection=false` 默认宽松，让 Planner 可以适度获取 selection | Planner/PolicyGate |
| 2026-02-02 | 排布决策 | 采用 **Planner-Executor**（LLM 做结构化计划 PlanIR | BE LangGraph |
| 2026-02-02 | 模板决策 | 按 `subject_type` 提供不同模板；新闻研报不再套公司研报 | Template/Render |
| 2026-02-02 | selection.type 清理 | selection.type 只允许 **内容来源类型**：`news | filing | doc`，已经废弃 `report` 改为统一 `doc`（ 旧版本过渡） | FE/BE selection + ResolveSubject |
| 2026-02-02 | PolicyGate | PolicyGate 负责提供 `budget + allowlist + schema`（tool/agent），让 Planner 在 allowlist 内部计划 | BE LangGraph（policy_gate / planner） |
| 2026-02-02 | Operation 规范 | Operation 规则「先关键字获取，成熟后实现真正的 constrained LLM」，输入必须保留简单规则兜底 | BE LangGraph（parse_operation） |
| 2026-02-02 | Planner 约束 | 关键约束：selection 先读/必须总结、研报模式不允许研报全发散（）、 PlanIR 可读可验 | BE LangGraph（planner / tests） |
| 2026-02-02 | ExecutePlan 默认模式 | ExecutePlan 默认 dry_run（不调用实际工具），验证可查/可控，通过 env 切换 live tools | BE LangGraph（executor） |
| 2026-02-02 | 模板管理 | 模板在 `backend/graph/templates/*.md` 维护，Render 按 `subject_type+output_mode` 选择注入变量 | BE LangGraph（render/templates） |
| 2026-02-02 | Evidence 展示策略 | 已推迟到 2026-02-05，默认关闭，通过 `LANGGRAPH_SHOW_EVIDENCE=true` 显示（links-only） | BE LangGraph（render） |
| 2026-02-03 | Subject 优先级（active_symbol vs query） | 当 query 包含显 ticker/公司名时应该覆盖可能过期的 active_symbol，解决「问 NVDA 却用 GOOGL」 | BE LangGraph（resolve_subject） |
| 2026-02-03 | Trace 可观测性 | `/chat/supervisor/stream` 改为实时推送各 node/step 执行进度；trace 对应只在结束后附加 | BE SSE + LangGraph trace |
| 2026-02-05 | 研报默认 Agent（LLM Planner） | LLM Planner 在 `output_mode=investment_report` 强制补充默认 agent steps（含 `macro_agent`），并修复 agent/tool inputs（query/ticker/selection_ids） | BE LangGraph（planner）、 tests |
| 2026-02-05 | Trace 可读性（Executor/SSE） | executor_step_start 的 `result.inputs` 改为结构化对象（不再是 JSON 字符串），`agent_start/agent_done` SSE 事件字段让前端读取并携带 step_id/inputs | BE executor + FE stream |
| 2026-02-05 | 研报证据展示 | 综合研报体的不再包含「证据池附加链接」，而是证据链接只在 Sources/证据池卡片展示，不在 markdown 中展示，但 `LANGGRAPH_SHOW_EVIDENCE=true` | BE report_builder/render + FE ReportView |
| 2026-02-05 | 字数统计口径 | BE/FE 字数统计函数忽略 raw URL，避免「链接占了好大面积」。综合研报对标保证 >=2000 字的正文内容（不计链接） | BE report_builder + FE ReportView |
| 2026-02-06 | API 启动时去遗化 | `backend/api/main.py` 不再初始化 `ConversationAgent`；全部路由使用 LangGraph + Orchestrator，`agent` 变量仅保留兼容性测试钩子 | BE API 层 |
| 2026-02-06 | 会话 ID 修复 | `/chat/supervisor*` 缺失 session_id 时生成 UUID，禁止固定 `"new_session"` | FE/BE 会话链路 |
| 2026-02-06 | 上下文容器会话隔离 | 上下文容器迁移到 session-scoped `ContextManager` 映射，按 thread_id 隔离 | BE API 层 |
| 2026-02-06 | 前端会话透传 | `sendMessageStream` 透传 `session_id`；主 Chat 和 MiniChat 使用同一 session state（localStorage 持久化） | FE API/client + store |
| 2026-02-06 | 前端路由收口部署 | 使用 `react-router-dom` 正式路由（`/chat`、`/dashboard/:symbol`）；移除 `pushState/popstate` 手工状态机 | FE App 架构 |
| 2026-02-06 | 快捷兼容入口 | 保留 `/?symbol=XXX` 入口，自动重定向到 `/dashboard/:symbol`，兼容历史书签和分享链接 | FE Router |
| 2026-02-06 | 输出模式显式化 | 在 Chat 和 MiniChat 中加可见的「深度 研报」模式切换按钮；不再作为隐藏设置，而是正式功能按钮 | FE ChatInput/MiniChat |

---

## 11.12.6 Patch Note (2026-02-07)
- Planner escalation hardening:
  - Required / `__force_run=true` high-cost agents are now protected from budget-pruning.
  - Filing/report scenarios will keep required `deep_search_agent` instead of dropping it during latency budget trimming.
- Validation:
  - `pytest -q backend/tests/test_deep_research.py backend/tests/test_executor.py backend/tests/test_planner_node.py backend/tests/test_templates_render.py backend/tests/test_report_builder_synthesis_report.py tests/retrieval_eval/test_retrieval_eval_runner.py` -> `40 passed`
  - `python tests/retrieval_eval/run_retrieval_eval.py --gate --drift-gate --report-prefix local` -> `PASS` (Recall@K=1.0000, nDCG@K=1.0000, Citation Coverage=1.0000, Latency P95=0.06ms)

## 11.12.7 Patch Note (2026-02-07)
- `macro_agent` source priority + conflict merge:
  - Added source priority ordering: `fred > market_sentiment > economic_events > search_cross_check`.
  - Added indicator-level merge + conflict detection with threshold-based checks.
  - Added structured `evidence_quality` and richer `raw_data` (`source_health/used_sources/conflicts/merge`).
  - Fixed status behavior: when FRED is unavailable but fallback data exists, status is `fallback` (not `success`).
- `fundamental_agent` filing metric standardization:
  - Added normalized metric pipeline (`revenue/net_income/operating_income/operating_cash_flow/total_assets/total_liabilities`).
  - Unified `YoY/QoQ` calculation across quarterly/annual paths with explicit period metadata.
  - Exposed standardized growth metadata in evidence and agent-level `evidence_quality`.
- Frontend transparency update (Agent cards):
  - `ReportIR.agent_status` now carries `evidence_quality`, `skipped_reason`, and `escalation_not_needed`.
  - Agent card now explicitly displays `EQ xx%` / `EQ N/A`.
  - Agent card now explicitly displays escalation skip state (`Escalation skipped`) and skip reason.
- Validation:
  - `pytest -q backend/tests/test_deep_research.py backend/tests/test_technical_fundamental_agents.py backend/tests/test_report_builder_synthesis_report.py` -> `15 passed`
  - `npm run build --prefix frontend` -> `success`

---

## 13. Worklog（实施日志，每完成一个小步在此标记）

| 日期 | 小步 | 做了什么 | 验证/证据 | 备注 |
|---|---|---|---|---|
| 2026-02-02 | 11.1.1 目录骨架与基础设施 | 创建 `backend/graph`（State + Nodes + Runner），完成 Phase 1 stub graph | `pytest -q backend/tests/test_langgraph_skeleton.py`（passed） | 使用 `MemorySaver` 作为临时 checkpointer；持久化将在后续 Phase 1/2 |
| 2026-02-02 | 11.1.2 核心 Graph + API 兼容 | `/chat/supervisor` 和 `/chat/supervisor/stream` 接入 LangGraph stub 路由；flag 控制 | `pytest -q backend/tests/test_langgraph_api_stub.py`（passed） | 目前默认不启用，不影响现有功能。后续阶段会逐步成为默认路由并移除分叉路 |
| 2026-02-02 | 11.1.3 Phase 1 验收 | Graph 节点 trace spans 回放，添加 stub SSE 事件（ thinking 事件回放） | `pytest -q backend/tests/test_langgraph_skeleton.py backend/tests/test_langgraph_api_stub.py`（passed） | 当前为回执行回放。后续将会改为实时 astream_events |
| 2026-02-02 | 11.2.1 API 契约 | 添加 `options.output_mode/strict_selection/locale` ，接入 LangGraph stub runner | `pytest -q backend/tests/test_langgraph_api_stub.py`（所有测试通过） | 目前只 LangGraph 路由解析 options，旧路由后续会被移除 |
| 2026-02-02 | 11.2.2 前端按钮 | 在 Chat / MiniChat 添加「生成投资报告」按钮，传入 `options.output_mode=investment_report` | `npm run build --prefix frontend`（成功） | E2E 尚未覆盖（后续按 Playwright 覆盖按钮触发路由验证） |
| 2026-02-02 | 11.2.2 前端按钮（E2E） | Playwright E2E 覆盖「生成投资报告」按钮及 options.output_mode | `npm run test:e2e --prefix frontend`（passed） | Playwright install 问题（`C:\\Users\\Administrator\\AppData\\Local\\ms-playwright\\__dirlock`），已解决重试 chromium |
| 2026-02-02 | 11.2.4 Phase 2 验收 | LangGraph stub 路由验证 output_mode 默认及 UI override，含 trace 可读性 | `pytest -q backend/tests/test_langgraph_api_stub.py`（passed） | Phase 2 只验证契约可测；更高确认性将在 Phase 3/4 中替换 stub |
| 2026-02-02 | 11.2.3 selection.type 清理 | selection.type 改为 `news|filing|doc`；测试旧 `report` 改为统一映射（即doc）；LangGraph ResolveSubject 识别 filing/doc | `pytest -q backend/tests/test_langgraph_skeleton.py`（passed）+ `npm run build --prefix frontend`（成功） | Legacy Supervisor 仍将 news selection 视为 report-like，Phase 5 移除旧路由后不再要求 |
| 2026-02-02 | 11.3.1 PlanIR Schema | 创建 PlanIR Pydantic schema + 校验；Planner（stub）写入并验证 plan_ir，失败则 fallback 并记录 trace | `pytest -q backend/tests/test_plan_ir_validation.py`（passed） | Phase 3 后续将用 Planner 替换为 LLM 约束输出，输出须符合本 schema |
| 2026-02-02 | 11.3.1 PolicyGate | 创建 `policy_gate` 节点提供 budget + allowlist + schema；加入主图校验，decide_output_mode 和 policy_gate 和 planner | `pytest -q backend/tests/test_policy_gate.py backend/tests/test_langgraph_skeleton.py`（passed） | allowlist 目前为最小集合，后续会按 subject_type/operation 更细粒度加入安全限制策略 |
| 2026-02-03 | 11.3.2 ParseOperation | 创建 `parse_operation` 节点（关键字优先）识别 operation（fetch/summarize/analyze_impact/price/technical/compare/extract_metrics/qa | `pytest -q backend/tests/test_parse_operation.py backend/tests/test_langgraph_skeleton.py`（passed） | 将来更高级「上下文相关」操作识别为 fetch news，将在切换到 constrained LLM 时须保留简单规则兜底可查 |
| 2026-02-02 | 11.3.2 Planner 约束 | Planner（stub）初始化核心 steps，并附加常量关键约束：selection 先读/必须总结；非研报模式不允许研报全发散 | `pytest -q backend/tests/test_planner_constraints.py`（passed） | 尚未接 LLM Planner Prompt。后续切换到 LLM 时须保留这些约束 |
| 2026-02-02 | 11.3.2 Planner Prompt | 创建可查阅 Planner Prompt builder（输入：subject/operation/output_mode/budget/allowlist/schema） | `pytest -q backend/tests/test_planner_prompt.py`（passed） | 目前仅是 prompt，下一步接入 LLM 后需验证并查看 PlanIR 校验+fallback |
| 2026-02-02 | 11.3.3 Executor | 创建可查阅 executor（parallel_group 并行 + step cache + optional failure）；接入 `ExecutePlan` 节点（默认 dry_run） | `pytest -q backend/tests/test_executor.py`（passed） | 目前默认 `LANGGRAPH_EXECUTE_LIVE_TOOLS=false`，后续真实调用 agent 时需补充完整测试 |
| 2026-02-02 | 11.3.4 Phase 3 验收 | 验证：选中新闻分析不触发「默认的全桶」；研报模式可扩展并在每步包含 why | `pytest -q backend/tests/test_phase3_acceptance.py`（passed） | Phase 3 目前均为 dry_run，Phase 4/5 将接入模板并删除旧路由 |
| 2026-02-02 | 11.4.1 模板与渲染层 | 创建 templates 按 subject_type+output_mode 渲染（news/company/filing），含模板缺失回退处理 | `pytest -q backend/tests/test_templates_render.py`（passed） | 模板内容目前为占位符，Phase 4.2 将接入 evidence_pool 来扩展 |
| 2026-02-02 | 11.4.2 证据链接层 | 执行结果与 selection 统一到 evidence_pool；Render 支持展示或通过 env 关闭 | `pytest -q backend/tests/test_evidence_pool.py backend/tests/test_templates_render.py`（passed） | 后续当搜索/agent 输出也要统一 evidence_pool（须增加区分标注 |
| 2026-02-02 | 11.6 Docs 同步 | README/01-05 增加 SSOT 标注及 LangGraph 迁移说明，更新文档间导航索引 | 人工检查：`README.md`、`readme_cn.md`、`docs/01_ARCHITECTURE.md`、`docs/02..05*` | 后续须去冲突同步，更细粒度的内容更新将以 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` 为准 |
| 2026-02-03 | 11.3.2b Planner（真正 LLM + 回退） | 创建 `planner` Node（stub/llm + policy enforce + fallback），接入 Graph 替换 `planner_stub` | `pytest -q backend/tests/test_planner_node.py backend/tests/test_langgraph_skeleton.py`（passed） | 使用假 fake LLM，无 key 默认 fallback。后续须补充集成性能测试 |
| 2026-02-03 | 11.4.4 Synthesize（移除占位符） | 创建 `synthesize` 节点提供 `artifacts.render_vars`；Render 改为注入；默认不再包含「未实现」 | `pytest -q backend/tests/test_synthesize_node.py backend/tests/test_langgraph_api_stub.py backend/tests/test_langgraph_skeleton.py`（11 passed） | LLM synth 受 env 控制，无 key 自动 stub。后续须补充集成性能测试 |
| 2026-02-04 | 11.4.4 Synthesize（compare 修复） | 修复 compare（AAPL vs MSFT）在 LLM synthesize 中的字段缺失、prompt schema 增加 `comparison_*` keys；LLM 省略 key 时用 stub defaults，避免模板出现占位符 | `pytest -q backend/tests/test_synthesize_node.py` + `pytest -q backend/tests`（91 passed, 8 skipped） | 发现：compare 场景下「对比结论」无效/证据为空——已修复 output_format 及 compare keys |
| 2026-02-04 | 11.3.1/11.3.3/11.4.4 Compare（AAPL vs MSFT）稳定化 | 修复 live tools 后的 compare 功能出现 agent step 执行失败、证据缺失；PolicyGate brief/chat 默认禁止 agent；Executor 支持 `kind=agent`；ExecutePlan 和 agent 输出统一归 evidence_pool；Synthesize LLM 模式保护 `comparison_*` 免受篡改与 hallucination | `pytest -q backend/tests/test_policy_gate.py backend/tests/test_executor.py backend/tests/test_live_tools_evidence.py backend/tests/test_synthesize_node.py`（7 passed）+ `pytest -q backend/tests`（91 passed, 8 skipped） | 研报模式可以加 agents，但测试可以看到 trace/占位符。后续可改善，reload 后的未完成下次代码 |
| 2026-02-04 | 11.4.1/11.4.2/11.4.4 Compare 净化去噪 | brief 场景不再展示非核心「关键指标/风险提示」，不再展示 raw tool output / 数据 dump；evidence 默认禁用，研报模式展示 links-only；LLM synthesize 为 compare 场景加入清洗避免 dump；metrics 保护避免 hallucination | `pytest -q backend/tests/test_synthesize_node.py backend/tests/test_templates_render.py`（2 passed）+ `pytest -q backend/tests`（91 passed, 8 skipped） | 测试可以看到的 raw dump/占位符已经去除，reload 后的未完成下次代码）。后续高频范围 `used fallback price history`（这个性能测试不实时投喂（还有指标分析提示） |
| 2026-02-04 | 11.4.1/11.4.4 Company fetch（新闻列表）修复 | 「最近有什么最新新闻」默认走 company_news 模板并展示 links-only 新闻列表；Synthesize stub 格式化 news_summary；LLM synthesize 修复 `risks` 类型不一致的导致验证失败；内部错误信息不外泄（不直接暴露给用户） | `pytest -q backend/tests/test_synthesize_node.py backend/tests/test_templates_render.py`（2 passed）+ `pytest -q backend/tests`（91 passed, 8 skipped） | 测试可以看到新模板和 trace。后续可改善，reload 后的未完成下次代码）。实时新闻须开启 live tools |
| 2026-02-04 | 11.4.4 风险提示格式（JSON与Markdown） | 修复 LLM synthesize 将 `risks` 作为 dict/list 时会被字符串化后直接展示为 JSON；改为格式化为 bullet；合并后再清理数据（保持无关数据不泄漏） | `pytest -q backend/tests/test_synthesize_node.py backend/tests/test_templates_render.py`（2 passed）+ `pytest -q backend/tests`（91 passed, 8 skipped） | 发现：风险提示显示为 `{\"AAPL\":...}`——已修复。LLM 返回 dict 后 dump 为字符串；现在统一渲染为 `AAPL：../MSFT：..` |
| 2026-02-04 | 11.4.5 ReportIR（卡片研报） | LangGraph 研报模式输出 ReportIR（含 `synthesis_report`、估值、`agent_status`、`citations`），前端恢复 `ReportView` 卡片渲染。Planner stub 研报模式默认加载 6 Agent steps（用于卡片填充），selection 条件携带 ticker 到各模板。以及 LLM 429 错误处理 | `pytest -q backend/tests/test_langgraph_api_stub.py`（passed）+ `pytest -q backend/tests`（91 passed, 8 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 后续未展示卡片。后续可改善，live tools 下的 Agent 是否真正能够产出完整证据池 |
| 2026-02-03 | 11.3.3b Executor（live tools + evidence） | dry_run 也执行 selection summary；live tools 执行结果统一归 evidence_pool（selection + tools） | `pytest -q backend/tests/test_executor.py backend/tests/test_live_tools_evidence.py`（passed） | live tools 当前使用 stub invoker，不调用真实 API |
| 2026-02-03 | 11.5 Phase 5（默认 LangGraph） | `/chat/supervisor*` 默认走 LangGraph（不再 env 分叉）；所有应答 classification.method=langgraph | `pytest -q backend/tests/test_langgraph_api_stub.py`（passed） | legacy 遗留仅在文件级别保留作为回退渠道，下一步清理并统一 clarify |
| 2026-02-03 | 11.6 Docs 同步（更新） | README/readme_cn 移除 `LANGGRAPH_ENABLED` 分叉，增加 Planner/Synthesize/live-tools 开关；stream 端的迁移 resolve_reference 说明 | `pytest -q backend/tests`（69 passed）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 旧环境目前在 API 层兼容（旧 agent 函数仍通过 agent.context.resolve_reference），后续迁移到 LangGraph memory |
| 2026-02-03 | 11.5 Phase 5（清理删除 + 依赖更新） | 清理删除 `backend/api/main.py` 中 legacy Supervisor/Router 直接支持；更新 LangChain/LangGraph 到最新分支稳定版并锁定依赖 | `python -m pip install -r requirements.txt --upgrade`（成功） + `pytest -q backend/tests`（76 passed, 1 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 安装 `sentence-transformers` 修复了 legacy IntentClassifier 的 embedding 需求，`_model=False`（禁用了 boost_weight 对比测试不受影响） |
| 2026-02-03 | 11.5 Phase 5（clarify 收口 + deprecate） | 清理 legacy `selection_override`；接入 LangGraph `Clarify` Node（唯一的补充入口）；修复 `ResolveSubject` 从 query 提取 ticker；legacy Router/Supervisor 标记 deprecated 提示 | `pytest -q backend/tests`（78 passed, 1 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | Clarify 暂且影响有限；主要通过 query ticker 匹配（如「分析苹果」则 AAPL），后续进一步 |
| 2026-02-03 | 11.5 Phase 5（去重路由 trace） | trace 含有 `routing_chain=["langgraph"]`，回归测试确认 `/chat/supervisor*` 不再走 legacy Router/SchemaRouter | `pytest -q backend/tests`（79 passed, 1 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 通过 monkeypatch 让boom（测试反向回归）；trace 作为可观测证据（后续可扩展为 routing_chain += "fallback" 等） |
| 2026-02-03 | 11.1.2/UX 修复（subject 优先 + 去噪） | 修复 query 显式 ticker/company 应覆盖 active_symbol，解决「问 NVDA 却用 GOOGL」；Render 不再附带 executor.step_results 产出的 debug 文本 | `pytest -q backend/tests`（80 passed, 1 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 测试可以看结果，后续可改善，reload 后的未完成代码。live tools 开启正式调用（见 11.3.3b/11.4.4 中有详细说明） |
| 2026-02-03 | 11.5/可观测性（实时 trace + 不再覆盖） | `/chat/supervisor/stream` 改为实时推送各 node/step 事件（不再覆盖执行后回放）。加入 `get_technical_snapshot` 的映射（operation=price/technical）。让「最新股价→上下文相关」可查阅 | `pytest -q backend/tests`（76 passed, 8 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 新增 `backend/graph/event_bus.py`，trace spans 携带 data 摘要，executor/LLM 节点发送 tool/llm 事件 |
| 2026-02-05 | 11.4.5 研报体的修复与补充（Trace/字数/证据） | 修复 LLM Planner 研报遗漏默认 agents（含宏观），修复 executor/agent SSE trace 可读性（inputs 结构化 + 事件类型让前端读取）；综合研报去重和证据池附带链接，不重复「分析」行；字数统计忽略 URL；MacroAgent 默认补丰 | `pytest -q backend/tests`（95 passed, 8 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 回归 query：`详细分析苹果公司，生成投资报告` 不再出现「宏观未查到/数据重复/链接超出」等问题；trace 的 inputs 不再是 `{\"...\"}` 字符串 |
| 2026-02-05 | 11.3.2b Planner（step_id 唯一 + 预算保留 agents） | 修复 `_next_step_id` 未占用到新补充 steps id 冲突（step_results 覆盖。前端 Agent 卡片会有重复）；investment_report 裁剪 max_tools 时优先保留 baseline agents（macro/deep_search），必要时替换低优先级补充 | `pytest -q backend/tests`（96 passed, 8 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 发现：TSLA 请求确切产出「新闻」研报中多个 Agent 输出相同内容 macro/deep_search 未出场；已确认 step_id 冲突 + 裁剪退出点断，已修复 |
| 2026-02-06 | 11.7.1 小步 A（会话链路收口） | API 启动路去遗（移除 `ConversationAgent` 初始化），改为 LangGraph + Global Orchestrator；`/chat/supervisor*` 缺失 session 生成 UUID；上下文容器改为 session-scoped ContextManager；前端 stream 透传/持久化 session_id（主 Chat 和 MiniChat 共享） | `pytest -q backend/tests/test_langgraph_api_stub.py backend/tests/test_phase5_no_double_routing.py backend/tests/test_health_and_validation.py backend/tests/test_streaming_reference_resolution.py`（6 passed）+ `npm run build --prefix frontend`（成功）+ `npm run test:e2e --prefix frontend`（passed） | 消除 `"new_session"` 的会话共享；API 与 legacy 启动时混合；下一步进入 11.7.2：前端路由与消息架构收口 |
| 2026-02-06 | 11.7.2 小步 B（前端路由收口） | 前端改为路由驱动架构。采用 `react-router-dom`，`/` 重定向到 `/chat`，Dashboard 改为 `/dashboard/:symbol`；移除 `pushState/popstate` 手工 URL 状态机；兼容 `/?symbol=XXX` 快捷跳转。同步更新 e2e 路由 | `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed）+ `pytest -q backend/tests/test_langgraph_api_stub.py backend/tests/test_phase5_no_double_routing.py backend/tests/test_health_and_validation.py backend/tests/test_streaming_reference_resolution.py`（6 passed） | 「router 乱飞」问题收口到单一路由机制；下一步进 11.7.2 的输入/输出模式清理 |
| 2026-02-06 | 11.7.2 小步 B（输出模式显式化） | 在 Chat / MiniChat 中把输出模式从「深度 研报」正式切换按钮；发送按钮跟随当前模式提交（不再靠隐藏设置）；正式功能按钮样式；联动「生成投资报告」内容按钮在合适条件下可见 | `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 完成基本输出收口；后续可增加更多输出格式或更多可视化分层 |
| 2026-02-06 | 11.7.2 小步 B（布局/层叠/移动端 + e2e 收尾） | 完成布局分层级拆分（消息区 / Context Panel / Trace Panel）；`RightPanel` 不再混合各种功能；MiniChat、`AgentLogPanel` 独立分层展示。移动端断点为单列布局；更新 e2e（路由切换、session 持续性、selection 持续一致性） | `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 11.7.2 全面收口完成；下一步进入 11.7.3：持久化 checkpointer、Adapter 统一层、CI 质量门禁 |
| 2026-02-06 | 11.7.3 小步 C（LangChain/LangGraph 基础设施收口） | 依赖统一、持久化 checkpointer、Adapter 统一层、失败测试标准化、契约版本管理、CI 门禁；修复 `AsyncSqliteSaver` 在多事件循环/多 TestClient reload 下的 `no active connection`（重建 checkpointer 和 runner 的 event loop 检测与缓冲；loop 自动重建） | `pytest -q backend/tests/test_graph_checkpointer.py backend/tests/test_live_tools_evidence.py backend/tests/test_planner_node.py backend/tests/test_synthesize_node.py backend/tests/test_langgraph_api_stub.py backend/tests/test_phase5_no_double_routing.py backend/tests/test_health_and_validation.py backend/tests/test_streaming_reference_resolution.py`（12 passed）+ `npm run build --prefix frontend`（成功）+ `npm run test:e2e --prefix frontend`（passed） | 11.7.3 收口完成；后续可扩展 Postgres 兼容测试层。保持同一契约版本的 checkpointer 可观测字段不会破坏产物 |
| 2026-02-06 | 11.8 小步 D（生产就绪 Runbook + 架构清理扫描 + 文档） | 创建生产就绪文档 Runbook（全面替代 README/SSOT/CI 成为唯一操作手册）。删除确认不再使用的过时或长期弃用的归档模块（`backend/_archive/legacy_streaming_support.py`、`backend/_archive/smart_dispatcher.py`、`backend/_archive/smart_router.py`、`backend/_archive/tools_legacy.py`、`backend/orchestration/_archive/supervisor.py`、`backend/legacy/README.md`、`backend/legacy/__init__.py`），标记对仍可回归旧路由的 legacy router/supervisor 文件添加 deprecated | `pytest -q backend/tests`（100 passed, 8 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 先确保没有任何毛病，再执行扫描删除。后续要确认删除 legacy router/supervisor，需要替换对应的测试引用和调用后再逐步下一步 |
| 2026-02-06 | 11.8 二轮复查（第二遍） | 按照用户要求再次执行分析、门禁全流程，完成删除后的扫描步骤，确保过时模块已经不再被引用 | `pytest -q backend/tests`（100 passed, 8 skipped）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed）+ `rg` 引用检查 | 分阶段收口。运维操作请参考 `docs/11_PRODUCTION_RUNBOOK.md` 执行。历史文档中的旧路径引用经检查不影响运行 |
| 2026-02-06 | 11.9 小步 E（Warning 清理收口） | 修复 pytest return-not-none 等测试写法问题；修复 datetime timezone-aware 的过时警告；Vite vendor 分包消除构建 warning；移除 baseline-browser-mapping；修复 pytest warning baseline 配置 | `pytest -q backend/tests`（100 passed, 8 skipped，无 warnings）+ `npm run build --prefix frontend`（成功，无 warning）+ `npm run test:e2e --prefix frontend`（passed） | 11.9 完成后 CI 输出已从「警告丛生」变为纯净，注意力聚焦在实失败上。后续如有新警告按同标准及时处理 |
| 2026-02-06 | 11.10 小步 F（架构评审与技术建议） | 完成对当前后端设计/前端解构/ Agent 选路/RAG 选型的系统评审；形成三条建议：CapabilityRegistry + 评分选路、RAG 分层存储（持久库+临时库），混合检索（pgvector+tsvector+RRF），文档体系收口（README/01~05/Thinking ADR） | 文档证据：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`（11.10）+ 交叉查阅：`backend/graph/runner.py`、`backend/graph/nodes/policy_gate.py`、`backend/graph/adapters/agent_adapter.py`、`frontend/src/App.tsx`、`frontend/src/components/RightPanel.tsx`、`docs/05_RAG_ARCHITECTURE.md` | 此小步为架构工作变更记录，不涉及代码时间执行。11.11 按 11.10.6 Todo 执行并最终验证 |
| 2026-02-06 | 11.8 文档清理与归类（归档 + 索引） | 归档过期文档到 `docs/archive/2026-02-doc-cleanup/`（`PROJECT_STATUS.md`、`PROJECT_ANALYSIS_V1.md`、`QUALITY_IMPROVEMENT_OVERVIEW_V2/V3.md`、`PROMPT_*`、`PHASE2_DEMO_REPORT.md`、`fix_summary_2026-01-24.md`、`DASHBOARD_IMPLEMENTATION_PLAN.md`、`_utf8_test.txt`），更新 `docs/DOCS_INDEX.md` 和归档说明 `docs/archive/2026-02-doc-cleanup/README.md` | `rg -n "PROJECT_STATUS\\.md|PROJECT_ANALYSIS_V1\\.md|QUALITY_IMPROVEMENT_OVERVIEW_V[23]\\.md|PROMPT_OPTIMIZATION_PROPOSAL\\.md|PROMPT_REDESIGN_SYNTHESIS\\.md|PHASE2_DEMO_REPORT\\.md|fix_summary_2026-01-24\\.md|DASHBOARD_IMPLEMENTATION_PLAN\\.md|_utf8_test\\.txt" docs`（仅归档目录和索引文档命中） | 文档清理完成收口，后续新增文档须先更新 `docs/DOCS_INDEX.md` 标注状态。查旧路径是否影响老目录 |
| 2026-02-06 | 11.11.1 小步 G（CapabilityRegistry + Planner评分选路） | 创建 `backend/graph/capability_registry.py` 统一 Agent 能力模型与评分逻辑；`policy_gate` 在 investment_report 下按 subject/operation/query 选择 Agent 子集（不默认全量）；`planner` 和 `planner_stub` 同步接受评分选路注入/评分 Agent。不再固定全量加 6 Agent。完成回归测试确认默认公司研报及简单查询等场景正确 | `pytest -q backend/tests/test_capability_registry.py backend/tests/test_policy_gate.py backend/tests/test_planner_node.py`（15 passed）+ `pytest -q backend/tests`（105 passed, 8 skipped）+ `npm run build --prefix frontend`（成功）+ `npm run test:e2e --prefix frontend`（passed） | 11.10.6 首个 Todo 已完成；接下来进入 11.11.2（RAG 分层存储与混合检索层） |
| 2026-02-06 | 11.11.2 小步 G（RAG v2 最小可行栈） | 创建 `backend/rag/hybrid_service.py`（memory/postgres 双后端、RRF、TTL、upsert），`execute_plan_stub` 集成 `evidence_pool -> ingest -> hybrid_retrieve -> artifacts.rag_context`，`synthesize` 注入 `rag_context` 上下文；补充 `backend/tests/test_rag_v2_service.py` 和 execute_plan RAG 上下文测试 | `pytest -q backend/tests/test_rag_v2_service.py backend/tests/test_live_tools_evidence.py backend/tests/test_synthesize_node.py`（11 passed）+ `pytest -q backend/tests`（109 passed, 8 skipped）+ `npm run build --prefix frontend`（成功）+ `npm run test:e2e --prefix frontend`（passed） | 11.10.6 第二个 Todo 已完成；下一步进入 `App.tsx/RightPanel` 职责再拆解和文档收口 |
| 2026-02-06 | 11.11.3 小步 G（App/RightPanel 职责再层拆解） | 前端架构分层拆分：`App.tsx` 仅含路由入口，`WorkspaceShell` 中包含壳层与布局状态，`RightPanel` 改为组合层并拆分 `RightPanelAlertsTab`/`RightPanelPortfolioTab`/`RightPanelChartTab` + `useRightPanelData`；更新 Context Panel 折叠/展开和 Tab 切换 e2e | `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 完成 11.10.6 最后一个 Todo（App/RightPanel 分层拆解）；然后进一步完善平稳进入 SSOT 收口或基线完善 |
| 2026-02-07 | 11.10.6 文档收口（README/01~05/Thinking ADR） | 更新 README/README_CN、`docs/01~05`、`docs/Thinking/2026-01-31_*` 的 SSOT 收口；更新当前架构图/参数/fallback/tool/version；历史阶段文档标记 Archived；Thinking ADR 标为 Superseded；同步 `docs/DOCS_INDEX.md` | 人工审对：`README.md`、`readme_cn.md`、`docs/01_ARCHITECTURE.md`、`docs/02_PHASE0_COMPLETION.md`、`docs/03_PHASE1_IMPLEMENTATION.md`、`docs/04_PHASE2_DEEP_RESEARCH.md`、`docs/05_PHASE3_ACTIVE_SERVICE.md`、`docs/05_RAG_ARCHITECTURE.md`、`docs/Thinking/2026-01-31_architecture_refactor_guide.md`、`docs/Thinking/2026-01-31_routing_architecture_decision.md`、`docs/DOCS_INDEX.md` | 11.10.6 最后一个 Todo 已完成；下一步可进入基线完善与检索工具（Recall@K/nDCG/覆盖率） |
| 2026-02-07 | 11.11.4 检索质量评测工具 | 创建 `tests/retrieval_eval`（`dataset_v1.json`、`run_retrieval_eval.py`、`thresholds.json`、`baseline_results.json`，测试）；CI 增加 `retrieval-eval` 门禁并上传 artifact | `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`（passed）+ `python tests/retrieval_eval/run_retrieval_eval.py --gate --report-prefix local`（PASS，Recall@K=1.0000 / nDCG@K=1.0000 / Citation Coverage=1.0000 / Latency P95=0.08ms） | 11.10.6 最后一个 Todo 收口完成；后续可根据检索算法迭代更新 `baseline_results.json` 再调整阈值 |
| 2026-02-07 | 11.11.4 检索文档同步（README/README_CN/DOCS_INDEX） | 更新检索评测工具从「计划中」变为「已就绪」；更新基线门禁数据、文件入口说明；并声明下一步检索算法迭代为基线完善 + postgres nightly 基准线 | `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`（passed）+ `python tests/retrieval_eval/run_retrieval_eval.py --gate --report-prefix local`（PASS） | 禁止遗留文档错误引导；说明要与代码实际完成度一致（而非只存在「即将推出」，数据及时同步好再更新） |
| 2026-02-07 | 11.12 文档增强与融合补丁 + DeepSearch 路线 | `docs/01` 增加运行时序/节点 I-O/Agent 选路及执行流程图；`docs/05` 增加「研报边界」段；`docs/06` 增加 11.12 外部参考库与路线图；更新 3 份当前激活 Thinking ADR | 人工审对：`docs/01_ARCHITECTURE.md`、`docs/05_RAG_ARCHITECTURE.md`、`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`、`docs/Thinking/ADR-2026-02-07-agent-routing.md`、`docs/Thinking/ADR-2026-02-07-rag-data-boundary.md`、`docs/Thinking/ADR-2026-02-07-deepsearch-evolution.md` | 完成文档融合。注意，后续内容将从接口和头文件开始，固化为可执行的文档 |
| 2026-02-07 | 11.12 文档增强（最终补丁 Agent 内部流） | 增加 query->选 Agent->planner->executor->选 Agent（深层）路线追踪的文档；`docs/01` 增加选路示例（含 reason）；planner/executor 内部 mermaid；更新 Agent 列表和筛选/过滤说明；README/README_CN 同步增加说明 | 人工审对：`docs/01_ARCHITECTURE.md`、`readme.md`、`readme_cn.md` | 下一步就是融合的知识正式具备后的真正 Agent 增强代码 |
| 2026-02-07 | 11.0 文档维护（会话丢失恢复流程固化） | 创建 `docs/TEAM_EXECUTION_MEMORY.md` 作为「会话丢失恢复锚点」，明确开始前写 `11.x TODOLIST`，过程中更新 `TODO->DOING->DONE` 并附证据，同时写 `docs/feature_logs` devlog | 人工审对：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`、`docs/TEAM_EXECUTION_MEMORY.md`、`docs/feature_logs/2026-02-07_session_recovery_memory.md` | 以后会话丢失后先读取锚点文件再继续执行进度 |
| 2026-02-07 | 11.14 最终冲线清单（Master TODOLIST） | 梳理完从仪表台/研报/RAG/会话隔离/可观测/安全审计的一体化执行清单（含 P0(P阻塞)/P1(P优化)/P2(P增强) 分层并设置 Gate），明确目标 99.99% 可用性。找出缺陷、四工程缺口举例 | 人工审对：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`、`docs/feature_logs/2026-02-07_launch_master_todolist.md` | 现在从当前状态推进到可发布终态。解决「功能很多但缺乏执行」的现象漂移 |
| 2026-02-07 | 11.14 补充（LLM 多密钥切换 + Raw Trace 开关） | 精进最终冲线清单补充两个核心须知特性：OpenAI-compatible 多 endpoint/多 key 轮询+健康切换（含 Raw SSE/Trace 采集开关）；下一步（全量/默认不采集开关） — 首要任务 provider 命名去混乱（`openai_compatible` 为主，`gemini_proxy` 兼容保留） | 人工审对：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`、`docs/feature_logs/2026-02-07_llm_rotation_trace_switch_addendum.md` | 重点需要验证 Gemini 实际走「OpenAI 协议」的兼容性，以及 trace 采集与测试冲突问题 |
| 2026-02-07 | 11.14 细粒度拆解（默认 Trace ON） | 按用户要求做清单细化到 WBS 级别（11.14.13），其中将 Raw Trace 默认采集调整为 ON。每个 LLM 多 endpoint 分化及进入 Trace，同时回归测试策略、DoD 检查清单目录 | 人工审对：`docs/06_LANGGRAPH_REFACTOR_GUIDE.md`、`docs/feature_logs/2026-02-07_ultra_granular_todolist_trace_on.md` | 目标是「可直接执行」，每一步均可分配 owner 并验证 |
| 2026-02-07 | 11.14.13 A~G 实施收口 | 完成 Trace/raw 采集开关路径、多 endpoint 分化及进入 trace、Workbench 首发可行栈、研报存档和回放、会话隔离安全审计、 阶段 CI 门禁。后续在 G 停止了执行，H/I 未开始 | `pytest -q backend/tests`（127 passed, 8 skipped）+ `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`（passed）+ `python tests/retrieval_eval/run_retrieval_eval.py --gate`（PASS）+ `npm run build --prefix frontend`（成功） + `npm run test:e2e --prefix frontend`（passed） | 同步标记 11.14.13.A~G 的选中证据归档（devlog：`docs/feature_logs/2026-02-07_11.14.13_A_to_G_implementation.md`） |
| 2026-02-08 | 11.14.13 A~G follow-up stabilization | Fixed broken `test_llm_rotation.py` and completed failover/recovery/explainable-error coverage; added cross-session reference isolation + RAG collection naming tests; stabilized Workbench/Trace E2E selectors with event-count assertion; added report_index filter and source_id consistency test coverage. | `pytest -q backend/tests` (337 passed, 8 skipped) + `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py` (6 passed) + `python tests/retrieval_eval/run_retrieval_eval.py --gate` (PASS) + `npm run build --prefix frontend` (success) + `npm run test:e2e --prefix frontend` (10 passed) | Closed remaining A~G follow-up gaps; H/I still pending by scope. |
| 2026-02-08 | 11.14.13 A~G tail closure (B/C/E/F) | Completed concurrency distribution pressure test for endpoint rotation, added fallback-summary stability test, delivered report_index migration/rollback scripts, and added second-pass redaction before AgentLog export. | `pytest -q backend/tests` (340 passed, 8 skipped) + `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py` (6 passed) + `python tests/retrieval_eval/run_retrieval_eval.py --gate` (PASS) + `npm run build --prefix frontend` (success) + `npm run test:e2e --prefix frontend` (12 passed) | 11.14.13 A~G remaining operational TODOs are closed except B-UI multi-endpoint config panel (still pending by scope/effort). |
| 2026-02-08 | 11.14.13.B UI multi-endpoint panel closure | Added Settings visual editor for `llm_endpoints[]` (add/remove/edit enabled/weight/cooldown/model/base/key), persisted payload to `/api/config`, and aligned provider naming to `openai_compatible` + `gemini_proxy` alias. Added E2E save assertion for multi-endpoint payload and legacy-field backfill. | `npm run build --prefix frontend`（success）+ `npm run test:e2e --prefix frontend`（13 passed） | This closes the last pending B-item within A~G scope. |
| 2026-02-08 | 11.14.13 H/I release drill + DoD closure | Completed pre-release 24h/2h checks (freeze + smoke + DB snapshot), staged gray rollout rehearsal (10%→50%→100%), rollback threshold hardening, rollback drill evidence, multi-endpoint failover drill, security/session final verification, and 20-request explainable trace sampling. Checked off Gate A-E and DoD-1~DoD-6. | `pytest -q backend/tests`（144 passed, 8 skipped）+ `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py`（6 passed）+ `python tests/retrieval_eval/run_retrieval_eval.py --gate`（PASS）+ `npm run build --prefix frontend`（success）+ `npm run test:e2e --prefix frontend`（13 passed）+ `pytest -q backend/tests/test_security_gate_auth_rate_limit.py backend/tests/test_trace_and_session_security.py backend/tests/test_llm_rotation.py`（19 passed） | Evidence bundle: `docs/release_evidence/2026-02-08_go_live_drill/`; runbook thresholds solidified in `docs/11_PRODUCTION_RUNBOOK.md`. |
| 2026-02-08 | 11.15 稳定性与安全审计模式（P0） | 后端安全/会话审计（CORS env + public path 配置 + session TTL/LRU），前端 session 生成 UUID 持久化，API base 统一到 `VITE_API_BASE_URL`，CI 增加 lint 前置门禁，删除 `App.bak.tsx` 解决 lint error | `pytest -q backend/tests/test_security_gate_auth_rate_limit.py backend/tests/test_trace_and_session_security.py`（13 passed）+ `npm run lint --prefix frontend`（0 errors, 0 warnings）+ `npm run build --prefix frontend`（success） | devlog：`docs/feature_logs/2026-02-08_full_audit_and_todo_plan.md`；后续按执行稳定化的 + 安全硬化方向继续执行 |
| 2026-02-08 | 11.15 P0 closure follow-up (lint warnings cleared + full regression) | Cleared remaining frontend lint warnings (`ChatInput` parsing + `Sidebar/SubscribeModal` hook deps), and completed full regression re-run after fixes. | `npm run lint --prefix frontend` (0 errors, 0 warnings) + `pytest -q backend/tests` (346 passed, 8 skipped) + `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py` (6 passed) + `python tests/retrieval_eval/run_retrieval_eval.py --gate` (PASS) + `npm run build --prefix frontend` (success) + `npm run test:e2e --prefix frontend` (13 passed) | P0 quality gate is now fully green with no lint warnings; no new blocker found by subagent audit. |
| 2026-02-08 | 11.15 P1 execution (router split + dashboard concurrency + news ranking) | Completed P1 in required order: (1) split `backend/api/main.py` into modular routers (`chat/user/system/market/subscription/config/report`) and keep `main.py` as app assembly + middleware; (2) upgraded dashboard aggregation to `asyncio.to_thread + timeout + fallback_reasons`; (3) implemented market-news ranking (`time_decay + source_reliability + impact_score`) while preserving `market_raw/impact_raw` for raw stream switch; frontend adapted with ranked/raw toggle and light UI polish in `NewsFeed` and `Workbench`. | `pytest -q backend/tests/test_langgraph_api_stub.py backend/tests/test_streaming_datetime_serialization.py backend/tests/test_report_index_api.py backend/tests/test_security_gate_auth_rate_limit.py` (20 passed) + `pytest -q backend/tests` (346 passed, 8 skipped) + `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py` (6 passed) + `python tests/retrieval_eval/run_retrieval_eval.py --gate` (PASS) + `npm run lint --prefix frontend` (0 errors, 0 warnings) + `npm run build --prefix frontend` (success) + `npm run test:e2e --prefix frontend` (13 passed) | P1 core track is closed for this batch; compatible with existing routes and release gates remain green. |
| 2026-02-08 | 11.14 T0 alignment + T1/T2/T3 incremental execution | Ran T0 alignment and executed first incremental batch for T1/T2/T3: (1) dashboard fallback symbol policy fixed (`currentTicker -> position -> AAPL`), (2) trace.v2 fields extended (`decision_type/summary/fallback_reason` + plan `parallel_group` + execute `duration/status`), (3) citation index query endpoint `/api/reports/citations` added with `source_id/query/date` filters, (4) checkpointer memory fallback default hardened to `false`, and env sample updated. | `pytest -q backend/tests/test_report_index_api.py backend/tests/test_graph_checkpointer.py backend/tests/test_trace_and_session_security.py backend/tests/test_trace_v2_observability.py backend/tests/test_executor.py` (28 passed) + `npm run lint --prefix frontend` (pass) + `npm run build --prefix frontend` (success) | T0 completed for this batch; unresolved 11.14 items are now consolidated in 11.16 realistic backlog. |
| 2026-02-08 | 11.15 dashboard default-symbol fix | Root-caused `/dashboard/GOOGL` to Sidebar fallback using `watchlist[0]`; `default_user` persisted watchlist starts with `GOOGL`, so dashboard entry inherited it. Updated fallback strategy to deterministic priority: `currentTicker -> first portfolio symbol -> AAPL` (no longer `watchlist[0]`). | `npm run lint --prefix frontend` (pass) + `npm run build --prefix frontend` (success) | Dashboard no longer jumps to Google by default when watchlist head is `GOOGL`; behavior is now predictable and product-aligned. |
| 2026-02-08 | 11.16.6 T5-3 文档深度对齐（去黑盒） | Completed T5 summary backfill (mark T5-1/2/3 as DONE in 11.16 overview with evidence links to `11.16.4~11.16.6`), expanded T5-3 with black-box-removal architecture notes (planner AB decision path, prompt variant boundaries, policy/agent invariants, fallback + diagnostics observability), and synced Chinese entry docs with new runtime/diagnostics contract. | `docs/06_LANGGRAPH_REFACTOR_GUIDE.md` (11.16/T5 + 11.16.6.A) + `readme_cn.md` (runtime flags + diagnostics endpoints) + `docs/feature_logs/2026-02-08_t5_prompt_plan_ab.md` | Documentation state now matches code/runtime behavior; readers can trace T5-3 end-to-end without relying on code spelunking. |

## 2026-02-19 Phase J Evidence Quality Upgrade
- Activated SEC evidence wiring in investment report planning and executor evidence expansion.
- Added free enrichment tools: `backend/tools/jina_reader.py` and `backend/tools/authoritative_feeds.py`.
- DeepSearch now supports Jina fallback for short-content pages and authoritative RSS supplementation.
- Quality gate in `report_builder.py` is now report-type aware with graded confidence penalties.
- Fixed research snippet-focus UX race (`ResearchTab.tsx`, `ReferenceList.tsx`) and added E2E regression.
- Added hallucination regression tests (`backend/tests/test_synthesize_hallucination.py`) and expanded Phase J backend test coverage.
- Validation snapshot: `pytest backend/tests -x` => `832 passed, 8 skipped`; `npx tsc -b --noEmit` => pass; `npx playwright test e2e/research-tab.spec.ts` => `4 passed`.

## 2026-02-19 Phase J P0 Hotfix (post-smoke)
- Fixed CN dotted ticker parsing regression causing `600519.SS -> SS` truncation in query extraction path.
- Fixed `backend/tools/financial.py` fallback runtime error by importing `search`.
- Rotated local Exa/Tavily keys and revalidated provider connectivity.
- Verification:
  - `pytest backend/tests/test_ticker_mapping_cn_market_suffix.py backend/tests/test_resolve_subject.py -q` -> `10 passed`
  - `pytest backend/tests/test_policy_planner_query_regression.py backend/tests/test_router_regression_baseline.py -q` -> `70 passed`
  - Real smoke (`600519.SS`) confirms `subject.tickers=["600519.SS"]` and no `symbol: SS` delisted errors in logs.

## 2026-02-20 Phase J P0/P1 Completion
- Added free evidence tools and wiring:
  - `get_authoritative_media_news` (`backend/tools/authoritative_feeds.py`)
  - `get_earnings_call_transcripts` (`backend/tools/earnings_transcripts.py`)
  - `get_local_market_filings` (`backend/tools/local_disclosure.py`)
- Planner hardening:
  - `deep_financial` now force-includes authoritative media + transcript retrieval.
  - US uses SEC chain; CN/HK uses local disclosure chain.
  - Budget pruning now preserves required report tools.
- Execution/reporting:
  - Expanded new tool outputs into citation-grade evidence rows in `execute_plan_stub.py`.
  - Quality gate is now market-aware (`US: 10-K/10-Q`, `CN/HK: local filing`).
- Smoke verification (`LANGGRAPH_EXECUTE_LIVE_TOOLS=true`):
  - `AAPL`: citations=24, 10-K/10-Q/transcript/media/snippet checks all pass.
  - `600519.SS`: citations=24, local filing/transcript/media/snippet checks all pass.
  - details: `scripts/phase_j_smoke_before_after_2026-02-19.json`.
- Regression snapshot:
  - `pytest backend/tests -x` => `839 passed, 8 skipped`
  - `npx tsc -b --noEmit` => pass

## 2026-02-20 Phase J P2 Completion
- Added Wayback fallback utility (`backend/tools/wayback.py`) and integrated fallback order in `backend/agents/deep_search_agent.py` for hard-paywall scenarios.
- Upgraded transcript discovery (`backend/tools/earnings_transcripts.py`) with market-aware query expansion and CN/HK coverage improvements.
- Added official macro release tool (`backend/tools/macro_official.py`) for BLS/BEA/FED document-level references.
- Integrated official macro tool into:
  - `backend/agents/macro_agent.py`
  - `backend/langchain_tools.py`
  - `backend/tools/manifest.py`
  - `backend/tools/__init__.py`
- Added env controls in `.env.example` for Wayback and official macro retrieval limits/timeouts.
- Added regression tests:
  - `backend/tests/test_wayback_tool.py`
  - `backend/tests/test_earnings_transcripts_tool.py`
  - `backend/tests/test_macro_official_tool.py`
- Updated integration tests:
  - `backend/tests/test_deep_research.py`
  - `backend/tests/test_tool_manifest.py`
  - `backend/tests/test_tools_capabilities_api.py`
- Verification:
  - Targeted: `32 passed`
  - Full backend: `pytest backend/tests -x` -> `847 passed, 8 skipped`

## 2026-02-20 Phase J P3 Completion
- Added SEC quarterly XBRL fallback:
  - `backend/tools/sec.py`: `get_sec_company_facts_quarterly`
- Added CN/HK dedicated market source:
  - `backend/tools/cn_hk_market.py` (Eastmoney quote/kline/financials)
- Dashboard routing update:
  - `backend/dashboard/data_service.py`
    - CN/HK valuation/financials/technicals route to dedicated source
    - US financials fallback order now prefers SEC CompanyFacts before Finnhub
- Peer routing update:
  - `backend/dashboard/peer_service.py`
    - default peers split by market (`US/CN/HK`)
    - CN/HK peer metrics fallback wired to dedicated source
- Tests:
  - `backend/tests/test_sec_tools.py` (added CompanyFacts coverage)
  - `backend/tests/test_dashboard_finnhub_fallback.py` (added routing/fallback coverage)
- Validation:
  - `pytest -q backend/tests/test_sec_tools.py backend/tests/test_dashboard_finnhub_fallback.py` -> `14 passed`
  - `pytest backend/tests -x` -> `856 passed, 8 skipped`
