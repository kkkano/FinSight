# LangGraph Pipeline 深入说明

更新时间：2026-10-04

本文补充 [`LANGGRAPH_FLOW.md`](LANGGRAPH_FLOW.md)。节点和边仍以 `backend/graph/runner.py` 为准。

## 1. 上下文准备

`prepare_context` 组合 `build_initial_state`、本轮状态清理、历史裁剪/摘要和 UI context 规范化。生产 checkpointer 恢复当前 thread 的消息；前端历史只在 checkpoint 没有消息时作为输入补充，不能覆盖或重复服务端历史。

同一 thread 的已验证 ticker 焦点与报告上下文保存在 `memory_context` checkpoint 字段。该字段不会跨 thread 查询，也不读写 JSON Memory。

## 2. 请求路由

`route_request` 用确定性规则理解问题、绑定主体，再由 `request_compiler.finalize_request_contract` 统一产出：

- `understanding.route`：`direct`、`research` 或 `clarify`；
- `request_frames`、逐 frame 的 `intent_contracts` 与兼容 operation 投影；
- ready/blocked tasks；
- 固定的 `request_frame_id`、`render_group_id`、`render_kind`、priority 和 order。
- 每个 task 的主体、分句 `request_text`、显式 `required_evidence` 与可解释的 blocked 原因。
- `request_constraints.py` 保留排除维度及明确的小时/天窗口；`render_contract.answer_requirements` 与 `task.answer_requirements` 冻结逐项回答义务，不因取数失败删除。

封闭金融术语可以走 `direct`。需要实时数据、比较、分析或报告的请求进入 `research`；缺少必要标的或范围时进入 `clarify`。frame ID 与真实 task ID 是明确关联，不靠后续字符串相似度匹配；下游消费合同，不能各自重新解析 query 改写主体或维度。原 INTC 多维研究、催化追问及 `AAPL price, MSFT news, NVDA fundamentals` 是回归样本。

“公司名（明确交易代码）”按用户给出的上市地绑定，例如腾讯控股（0700.HK）只产生港股任务，名称默认的 TCEHY 不会被额外加入。用户明确要求比较两种代码时仍保留双方；上海证券 `.SH` 输入统一为供应商使用的 `.SS`。

明确的单字母代码、大写 COST 等证券代码不被普通英文词表丢弃；公司名称后直接给出的代码同样绑定上市地，中文别名按最长不重叠匹配。加密交易对归一为 BTC-USD 等标准代码，作为 crypto 主体，不附加公司财务或默认股票期权任务。已有公司历史的省略追问仍绑定历史，用户明确要求虚构示例或不查实时资料时可直接解释。

## 3. 策略、计划与采集

`collect_evidence` 对非 `research` lane 立即跳过，保证零外部 I/O。研究 lane 依次执行：

```text
policy_gate
  -> rule_based_planner
  -> validate_executable_plan / validate_plan_coverage_for_frames
  -> execute_plan_node / DAG executor
  -> collector or tool
  -> evidence gate
```

planner 是确定性规则实现，运行时 trace 明确记录 `llm_calls=0`。`planning/validation.py` 使用实际注册工具的 `args_schema` 校验 inputs，并验证唯一 step/task ID、任务引用、`depends_on`/`data_dependencies` 引用和无环性；错误 SEC 参数必须在外部 I/O 前失败。

`coverage_validator.py` 按 `(task_id, subject, evidence_kind)` 检查匹配市场的有效生产者；工具名相同但任务或 ticker 不同不能冒领覆盖。这是计划能力检查，执行后的真实数据缺口仍需由证据与结果质量检查记录。用户点名的维度不能被轻量成本 profile 删除；可减少可选补充研究，不能把必需步骤静默变成可选。

依赖分两种：`depends_on` 必须成功，其失败会跳过控制依赖闭包；`data_dependencies` 等待成功或失败结束，随后 Agent 可以处理来源缺失。两种依赖都参与无环校验。`parallel_group` 是展示分组，独立节点就绪即执行。

`request_data_scope` 为单次 DAG 建立 `RequestData`。tool adapter 与 collector 的 `SharedToolView` 通过同一工具名、绑定默认值后的参数和时间范围复用一个 Future；等待者取得结果副本。成功和失败都在本轮共享，不跨用户/运行缓存，也不因改变展示分组再次取数。替代生产者的名称或参数不同，仍可独立执行。

Price、Technical、Fundamental、News、Macro、Risk 和 Deep Search collector 以 `llm=None` 构造，只做工具采集和结构化封装。raw result 通过 evidence gate 后才进入 evidence pool；error、timeout、empty、rejected 和 fallback 进入 diagnostics。

金融适配层先核验主体、指标定义、单位和实际财期，再生成证据：SEC 单季按 start/end duration 区分累计/年度；财务行用明确别名；同比与环比按真实日期对齐；本地公告验证发行人，新闻格式头与 CPI 单位均不能冒充有效事实。

业务/竞争任务会请求 `get_sec_filings(include_content=True)` 读取最新年报和季报的相关正文。`content_read` 与非空 `content_sections` 才表示已读材料；目录 URL 或请求参数本身不能冒充正文。报价若源于日线 K 线，保留 `market_session=regular_close`、日期精度和币种，并明确不是盘后价格或精确成交时刻。

新闻经 `news_event_quality` 标记时间、主体、来源和报道角色，网关与执行层保留该合同及原始行。当前归因报道仍为 `headline_only`；旧闻、观点、传闻和搜索摘要为 raw，明确错误主体的材料排除。日历搜索只进入 `discovery_candidates`。按 URL、事件身份和发布时间去重，保留同话题后续；报道覆盖和来源计数不表示独立核实。搜索宏观数值也不能冒充 FRED 官方读数，失败文本仅进入来源诊断。

## 4. 分析

`analyze` 进入统一合成入口，默认结构化模式按已编译任务处理：

- 事实型 research：调用 `_stub_render_vars` 构造确定性结果，业务 LLM 调用为 0；
- 研究任务：规范化 evidence/claim 和 TaskOutcome，生成 `artifacts.research_result`；结果就绪后直接返回，不再生成会被渲染器丢弃的第二份通用正文；
- `investment_report`：产生受证据约束的结构化 draft，Markdown 所有权属于 renderer；配置允许时可运行报告核验。

`research_result` 汇总 `task_results`、evidence/claim 索引、引用、限制和缺口。模型调用可能包含多个任务、草稿、核验及允许的重试，实际数量记录在 `analysis.business_llm_calls` 和 usage attribution；角色数和节点数都不能代表调用数。

是否需要解释按每个 task 的 `answer_requirements.requires_analysis` 判定，不再只看顶层或第一个 operation。模型收到任务内 E/C 编号，服务端映射回真实 evidence/claim ID；无效引用局部隔离，可在原有预算内做一次带错误原因的修正，不放宽事实校验。每项 `requirement_results` 保留 answered/partial/missing、引用及缺口原因，非空文本或高引用数量不能代替完整性。

通用概念题通过 `direct_answer_request` 进入同一全局选定模型的直接回答模式，要求示例明确虚构且算术自洽，不执行行情或研究工具。问候、固定术语和澄清已有确定性正文时无需模型；direct lane 的“零外部取数”不表示所有直接回复都零模型调用。

chat/brief 使用 `content_selection` 按请求维度选择当前财期、关键指标、事件和解释；完整证据仍保存在同一 `research_result`。比较先给横向摘要，单股明细展示一次；业务、竞争与风险解释按维度归属，renderer 不修改研究产物。

Prediction 不在该节点产生。`POST /api/predictions/generate` 进入独立服务，由 PredictionAnalyst 使用可信行情生成结构化 Prediction。

## 5. 验证与渲染

`validate` 记录 evidence ledger、引用数量、有效/拒绝 Claim、future-claim scrub 和质量裁决。每个原始 task 必须有 `answered`、`partial`、`unavailable` 或 `blocked` 结果。Claim 区分事实/观点/风险并保留主体、指标、期限和情景；不同维度或期限的多空观点不自动判冲突。

`report/quality_engine.evaluate_result_quality` 合并验证器、结构化结果和报告质量，状态只能按 `pass < warn < block` 升级。完整研究报告没有规范化受支持论据则阻断，事实仍可作为预览展示；聊天 `report=None` 不能擦掉已有阻断。`answer_status`、`has_supported_content` 和缺失义务进入最终事件。

`render` 只消费已验证 artifacts，不调用工具或重新判断用户意图。技术、新闻、宏观、财报、比较与追问按编译维度展示；内部冲突 ID 不作为用户正文。渲染完成后仅把当前 thread 的必要上下文写回 checkpoint。

## 6. 持久化

- LangGraph：PostgreSQL checkpointer；测试可使用 `MemorySaver`。
- 核心业务：PostgreSQL conversation、research_runs、conversation_messages、watchlist、reports、Prediction、Outcome、Monitor 和 usage 表。
- RAG：PostgreSQL/pgvector；memory 来源仅限当前 thread 的可信上下文。
- Schema：Alembic 管理；应用启动只验证 revision，不执行核心 DDL。

`execution_router` 在图执行前保存问题和助手占位，`execution_service` 在最终事件交付前调用终态保存回调。终态事务先锁会话再锁运行，幂等更新助手消息、会话版本及 final payload；旧快照合并时服务器正文优先。明确重新生成使用新 run/assistant ID，复用 user message ID，界面按 `reply_to` 的最新 run sequence 展示回复。

SSE 事件缓冲仍在内存，但 `/api/execute/runs/{run_id}` 和回放的终态兜底来自数据库。25 秒心跳、90 秒租约；失联记录被读取时转为 `interrupted`。保存失败保留临时预览并明确 `persistence_status=failed`，不承诺数据库完全不可写时仍能跨进程恢复。

RAG 推理通过私网 worker 执行。`embedding_identity` 必须与查询实际模型/版本/维数匹配；worker 失败时使用持久词法检索，向量可为 NULL，不能以同维 hash 代替 BGE。

## 7. 可观测性

每个节点写 trace；collector 发送 start/done/error 事件；ResearchAnalyst 发送明确的角色事件。每个逻辑 LLM 调用记录 stage、role、layer、endpoint、latency、token 和 failure code，供应商未返回 token 时保存 `null`。

SSE 的状态、降级、取消和终态遵循 [`execution-event-contract.md`](execution-event-contract.md)。前端必须按稳定错误码区分认证、行情、LLM、配额、校验和存储失败。

## 8. 修改检查

- 图变化同步 runner、GraphState、流程文档和 skeleton 测试。
- 新 capability 同步 profile、policy、planner、adapter 和 evidence gate。
- 新事件同步 SSE 合同、前端类型、store 和消费测试。
- 新回答形态通过 analysis/validate/render 扩展，不绕过证据边界。
- 不恢复旧节点、第二套执行器、reflection、debate 或跨 thread 用户画像。
