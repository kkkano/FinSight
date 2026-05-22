
# 2026-03-08 增量架构说明（RAG 三层）

- `backend/rag/layering.py`：三层 collection 解析与元数据归一化入口，负责 `memory / ws / kb`、`collection_kind`、`entity_scope`、`entity_key` 语义。
- `backend/graph/nodes/execute_plan_stub.py`：普通执行链的 Working Set / 长期 KB 写入与联合检索编排。
- `backend/agents/deep_search_agent.py`：DeepSearch 的 `ws:deepsearch:*` working set 与 `kb:stock:*` 晋升/补查入口。
- `backend/rag/hybrid_service.py`：RAG 文档模型补充 layer / entity / ingest / promotion / fingerprint 字段，并支持多 collection 联检。
- `backend/rag/observability_store.py`、`backend/rag/observability_runtime.py`：把 layer / collection path / hit 元数据落进 observability，供 Inspector 和 DB Browser 回放。
- `frontend/src/pages/RagInspectorPage.tsx`：Inspector 首屏、run 详情、collection 浏览、DB Browser 直接展示三层语义。

# 2026-05-18 增量架构说明（单 Agent 质量合同）

- `backend/research/agent_quality_contract.py`：单 Agent 质量合同入口，负责给 evidence 分配稳定 `agent_source:*`、构造 claim、计算 `agent_quality` 指标。
- `backend/agents/base_agent.py`：标准 `research()` 流程会自动挂载 `evidence_quality.agent_quality`；覆盖 `research()` 的 Agent 需要手动调用合同。
- `backend/agents/fundamental_agent.py`：原生输出 growth_quality / cash_flow_quality / eps_revision / balance_sheet_risk claims。
- `backend/agents/news_agent.py`：原生输出 catalyst_candidate / noise_or_secondary_signal / event_calendar claims。
- `backend/agents/risk_agent.py`：原生输出 risk_score / factor_exposure / stress_test claims。
- `scripts/agent_quality_eval.py` + `tests/eval/agent_quality_cases.json`：确定性 fixture eval gate，用于保存 before/after 结果并审计单 Agent 质量变化。

# 2026-05-20 增量架构说明（后端 Agent 能力诊断强化）

- `backend/graph/nodes/planner.py`：Planner 输出 `agent_selection` 诊断，`plan_ready` / `decision_note` 事件携带跳过原因、预算优先级、deepsearch 意图。PlanIR Schema 容错增强（`PlannerSchemaShapeError` + retry prompt）。
- `backend/graph/nodes/conversation_router.py`：新增内幕/非公开信息安全边界（`_query_requests_illicit_nonpublic_info`），多轮对话历史 ticker 补全主题提示。
- `backend/graph/nodes/chat_renderer.py`：新闻引用兜底——当 plan 无新闻源时直接抓取文章，确保回复契约有可引用 URL。
- `backend/research/debate.py`：新增 `build_read_only_adjudications`，输出 Bull/Bear/Judge 只读裁决产物。
- `backend/research/agent_quality_contract.py`：增强 low_source_quality / recovery action 诊断。

# 2026-05-21 增量架构说明（执行路由闭环与 TechnicalAgent 扩面）

- `backend/graph/nodes/conversation_router.py`：`task_hints` 执行判定改为结构化判断，区分当前轮可执行任务与历史追问残留 hint。
- `backend/graph/nodes/conversation_router.py`：显式 `investment_report` 与技术面请求进入 fast path，不再先等待会话路由 LLM，避免“是否启动研究”类绕圈和长时间无进展。
- `backend/graph/nodes/understand_request.py`：`direct_answer` 若携带可执行任务会被强制投射为 research；direct 回复清理“是否启动研究/进入研究链路”类绕圈 CTA。
- `backend/graph/nodes/decide_output_mode.py`：显式“深度投资报告 / deep report / filing document longform”等 query 可覆盖前端默认 `chat`，进入 `investment_report` 和 `report_generation` lane；否定报告请求仍保持 chat。
- `backend/graph/nodes/policy_gate.py`、`backend/graph/nodes/planner_stub.py`：显式技术面任务会开放并计划 `technical_agent`；request-understanding tasks 路径的研报也会补齐 SEC/CompanyFacts/8-K、权威媒体、电话会 transcript 与报告 agent 步骤。
- `backend/agents/base_agent.py`：Agent 内部 LLM 分析 / gap detection / summary update 增加硬超时，LLM 长尾时回退到确定性摘要，避免单 Agent 拖垮整轮报告。
- `backend/agents/technical_agent.py`：技术 Agent 从 K 线 + search 扩展为 K 线、当前报价、期权 IV/PCR/Skew、市场情绪和 search；确定性摘要补支撑/阻力、MA20 偏离和成交量相对均量，并把新增信号写入 evidence。
- `backend/graph/nodes/understand_request.py`：单公司深度报告中的竞品 ticker 只作为 `peer_tickers` 上下文，不再把“覆盖 NVIDIA/AMD/TSMC 竞争”误升级成四家公司 compare 报告；显式“比较/对比/谁更值得买”仍保持 compare。
- `backend/agents/deep_search_agent.py`：DeepSearch 财务研报查询会保留用户点名主题（如产品路线、分析师评级、竞品格局、估值、6-12 个月风险机会），同时默认限制 gap follow-up 为 1 轮 / 1 条查询，减少报告长尾空转。
- `backend/agents/technical_agent.py`：技术面摘要默认走确定性指标路径，不等待 Agent 内部 LLM；如需恢复技术 Agent 自身 LLM 精修，可显式设置 `TECHNICAL_AGENT_LLM_SUMMARY_ENABLED=1`。

# 2026-05-22 增量架构说明（报告链路长尾收敛）

- `backend/agents/base_agent.py`：Agent 内部 LLM 精修默认 opt-in；生产默认依赖工具与确定性摘要，避免 Price/Macro/Fundamental/News 的 LLM 长尾阻塞整轮报告。
- `backend/agents/deep_search_agent.py`：DeepSearch gap follow-up 将 LLM 产出的长缺口改写为短 ticker/topic 查询；竞品仅作为研究上下文，不扩大主标的。
- `backend/rag/embedder.py`：bge-m3 运行时不可用时，hash fallback 仍保持 1024 维，与既有 pgvector schema 对齐。
- `backend/graph/nodes/synthesize.py`：investment report 合成默认预算收敛到 180s / 1 attempt / 60s acquire，并有代码层硬上限 120s / 1 attempt / 45s acquire；报告合成关闭 SDK 内部重试，超时后回退模板报告，优先保证报告返回。
- `backend/graph/nodes/synthesize.py`：deep report verifier 收敛到 45s 单次核查，避免主报告已生成后继续被事实核查 LLM 长尾卡住。
- `backend/llm_config.py`：`create_llm` 支持按调用点覆盖 `max_retries`，报告链路可显式禁用 SDK 内部重试。
- `backend/graph/nodes/synthesize.py`：chat/brief 下纯报价或技术面任务走短任务图渲染，跳过 synthesis LLM，避免工具结果齐备后继续等待长尾合成。
- `backend/graph/nodes/chat_renderer.py`：技术面 chat 短答输出“技术面结论 + 可执行结论”，并清理内部 Suggested ladder 报价梯度残留。
- `backend/graph/templates/company_report.md`：公司研报不再回显完整用户 query，避免控制语句进入正文。

# 2026-05-22 增量架构说明（投资观点 chat 质量合同）

- `backend/graph/investment_intent.py`：集中识别投资观点类 query，避免在多个节点堆叠散乱短语判断。
- `backend/graph/nodes/conversation_router.py`、`backend/graph/nodes/understand_request.py`、`backend/graph/nodes/parse_operation.py`：将“走势怎么看 / 值得买吗 / bullish or bearish view”等显式观点请求投射为 `investment_opinion` research task。
- `backend/graph/nodes/policy_gate.py`、`backend/graph/nodes/planner_stub.py`：`investment_opinion` 必须打开价格、技术面、新闻、基本面、EPS 修正和风险证据，并规划 Technical / Fundamental / Risk / News agent。
- `backend/graph/nodes/chat_renderer.py`：投资观点 chat 输出固定质量章节：结论、价格/趋势、技术面、消息/催化、基本面/估值、风险；缺失维度必须显式标注 `[数据缺失]`。
- `backend/agents/price_agent.py`、`backend/agents/risk_agent.py`、`backend/agents/base_agent.py`：补齐 Price / Risk Agent 的报价、回撤、因子暴露和压力测试工具入口。
- `backend/tests/test_investment_intent.py`、`backend/tests/test_policy_planner_query_regression.py`、`backend/tests/test_chat_response_contract.py`、`backend/tests/test_agent_capability_audit.py`：保存 query -> route -> policy -> plan -> answer 的回归覆盖。

# 2026-05-22 增量架构说明（复合财报意图与软 Agent 召回）

- `backend/graph/earnings_intent.py`：新增财报表现与“财报 -> 股价影响”语义 facet，避免“财报/股价/影响”被单标签压成纯 price。
- `backend/graph/nodes/understand_request.py`、`backend/graph/nodes/conversation_router.py`：显式财报表现进入 `earnings_performance`，显式财报影响股价进入 `earnings_impact`；深度研报里的“覆盖财报”不再把报告主链误降级为短答财报链。
- `backend/graph/nodes/policy_gate.py`、`backend/graph/capability_registry.py`：chat/brief 的 rich research agent 选择改为 capability score + required floor；operation/facet 只影响召回权重、预算和 required 底线，不再由单个 if/elif 直接硬编码完整 agent 列表。
- `backend/graph/nodes/planner_stub.py`：`earnings_performance` 会拉取公司信息、季度事实、盈利预期、EPS 修正、财报新闻/电话会和 Fundamental/News agent；`earnings_impact` 额外拉取当前价格、历史回撤和 Risk agent。即使上游误判为 price，只要 query facet 指向财报影响股价，也会补齐复合工具链。
- `backend/graph/nodes/chat_renderer.py`：新增财报表现与财报影响股价短答渲染合同，回答必须包含财务表现、EPS 修正、消息/指引和风险；财报新闻引用只保留可绑定到当前 ticker/公司名的项目，避免旁支新闻混入。

## 当前推荐心智模型

- `memory`：线程级轻记忆，不存大原文。
- `ws`：本次任务 working set，可短期复用，可过期。
- `kb`：长期稳定知识库，按股票/主题/宏观 scope 组织。

## 当前目录依赖

- `backend/rag/layering.py` -> 被 `hybrid_service.py` / `observability_store.py` / 编排节点调用。
- `backend/research/agent_quality_contract.py` -> 被 `base_agent.py`、Fundamental / News / Risk Agent 和 `scripts/agent_quality_eval.py` 调用。
- `frontend/src/pages/RagInspectorPage.tsx` -> 依赖 `frontend/src/api/client.ts` 的 diagnostics API。
- `docs/plans/2026-03-08_rag_three_layer_architecture_todolist.md` -> 作为后续持续开发与验收清单。
