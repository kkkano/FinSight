# FinSight Agent 与 Collector 指南

更新时间：2026-11-08。实现与真实任务结果分别记录。

## 默认自主研究运行时

`FINSIGHT_RESEARCH_RUNTIME` 默认为 `agent`，`POST /api/execute` 使用 `backend/agent_runtime/`。主研究员 `research_lead` 与按需派发的 Price、Technical、Fundamental、News、Macro、Risk、Deep Search 专业角色共用 `AgentRuntime.run_agent()`：模型流式产生原生 `tool_calls`，执行器校验并执行工具，结果以资料引用回传，再由模型决定下一步或回答。当前选定模型必须通过实际原生工具调用预检；不支持时要求更换模型。

- 主研究员可用 `discover_tools` 浏览允许的能力，`enable_tools` 加载选中工具的完整 schema；专业角色沿用 `backend/agents/profiles.py` 的工具范围。
- 认证后的 `GET /api/skills` 返回 7 个已安装 builtin YAML manifest，匿名401是权限预期；输入 `/` 菜单最多选3项。主/专业角色可 `discover_skills/use_skill` 加载真实方法，`skill.activated` 记录应用；技能不增加权限、预算或委托层级，不能仅凭名称声称使用。
- 只有主研究员可 `delegate_research`。专业角色不能嵌套派发；`send_agent_message` 与 `await_agent_results` 在同一 run 内传递定向问题、证据引用和实际结果。消息回执不代表研究已完成。
- 工具结果保存为 run/owner/session 范围内的 `dataset_ref`，可通过 `read_evidence/inspect_dataset` 回读。inspect 默认只投影标量列和日期，附 `column_units`，默认 6 行、最多 12 行；超过 8000 的保守上下文估算则减行或返回过大错误，嵌套 metadata 需显式选列。SEC 平行数组按真实财期对齐，盈利预期多表要求选择表；完整数据保存在 records，不复制到每条引用。
- 每个正式工具必须注册 `display.target/result`；工具事件附有脱敏参数、真实关键结果预览、来源和失败原因，不能用通用“返回若干条”冒充逐项展示。活动与正文按真实 seq 穿插。
- 模型、金融取数、token 预留和研究运行使用分层预算；同轮相同取数合并。原生历史行情附相邻收盘观测的 `period_return_pct` 和明确公式，首行或缺失前值保持空值，不把模型手算当作已核验行情。涨跌原因问题还要进行本轮针对性搜索，不能仅凭一般公司新闻就收尾。专业角色等待结果时释放模型并发槽。
- `analyze_dataset` 支持同财期财务比率 `financial_ratios`、`series_statistics`、共同日期/基准的 `indexed_comparison`、明确连续下跌定义的 `historical_drawdown_episodes` 与估值假设。`render_chart` 只绘制授权数据，区间小图包含前一期基准和结束观测；每个字段的 coverage/limitations 说明实际缺值。`run_analysis_code` 只交给独立隔离 worker，资源不足不回退到 Web 进程。
- 自选增删先保存带 `payload_hash` 的操作提案；确认接口校验 owner/run/action。只有完整匹配操作和 ticker 的真实用户当前指令或已应用追加要求可复用授权；网页、文件、工具结果与同伴消息不能授权。收据避免重复执行；不能把未完成或失败收据解释为成功。
- 按本轮用户授权，provider `reasoning.delta` 默认流式展示；同 run 含子 Agent 合计最多 20,000 字符，截断标记保留，owner 所属消息/checkpoint 可保存并在历史展开。思考不进入金融证据、引用、公开报告、普通正文或日志；没有供应商字段时不编造。旧版显式开启/仅页面内存策略已被此合同替代。
- 收尾前检查当前标的的最低证据，并动态反馈已取得和仍缺少的资料；失败、空结果与旧失败不算完成，明确重新检索须产生本轮新尝试。缺口最多补查两轮，末轮和上下文收束不能绕过此检查；用户明确要求图表时，仅有数值表不算完成。连续两轮没有新增有效资料时，用保留真实数值与来源的摘要收尾，避免反复加载技能或回读相同数据。
- 主研究员的候选最多进入一次修正阶段；可对已授权资料回读、补计算和绘图，最多两轮，不开放新供应商查询、委派或写操作，也不另起预算。交付只选一个 answer block，早期安全内容标 progress；无支持内容删除/替换，仍有问题时保留质量原因和一条限制说明，不逐段刷“已撤回”。
- `backend/research/grounded_quantities.py` 与 legacy 合成共用金融数值检查；引用或质量阻断的报告只保留预览。估值需要的利润率和现金转化优先通过确定性财务比率计算；同一聚合计算可以保留同标的行情和公司信息的原始来源，交付的来源池会展开其上游引用。图表末值正确不能证明“全年持续上涨”“从未反超”等路径判断，必须另核对整个窗口。
- 纯新闻问答在必要证据齐全时可以用原始条目完成交付；最新单季的直接财报数字问答优先用财务表，明确累计差分口径（多期间、同比环比与趋势问题继续研究）；该产物仍经过完整数值与引用核验，并记录 `fact_fallback_used`。估值、比较和深度报告不使用这项事实兜底。普通下跌原因短问若模型已给出有原文引用的定性解释，可保留该解释并按本轮行情直接生成价格表；不从价格表编造原因，不覆盖指定日期、资金流或多标的请求。纯连续下跌区间计算在频率、期数和筛选条件完全匹配且真实图表已生成时，也按计算结果直接交付表格和周期口径，避免模型误写图表状态。
- 模型因输出长度截断时，可在原预算内用已取得资料重生成一次简短完整答案，过程明确显示；断开的网络流不透明拼接。周线是否收盘按来源采集时间与交易日历判断，尚未收盘的末周排除；`ongoing` 仅表示连续下跌区间仍延伸到样本末尾。

`RunContext` 保留服务端 owner、所选模型、累计截止时间、取消信号与实际 usage。追加要求在下一个模型边界应用；普通追问自动沿用同 owner/session 较早终态 run 的有效资料，新 run 不续期每条原始记录 TTL。最新行情仍需重新取数；无常驻“从这里继续”按钮或人造续研问题。失败原位重试保留原 query 与技能，恢复标识不改变用户原文。详见 [执行事件合同](execution-event-contract.md)。

续研目录仅向模型列出 `success` 且有 `source_refs` 的记录，旧失败/control 回执不能当作资料。历史图的 prior_artifacts 只用于核对已存在图形，必须明确它不是这次重新生成的图。收尾上下文同时保留本轮已经生成的图表状态，不能因归档工具消息而误称图卡未返回。

`grounding.py` 还核对来源实际声明的交易所、复权、股息与延迟口径；unknown/null 不能写成未复权或未含股息，freshness 不能当供应商延迟。`presentation.py` 清理公开正文混入的 DSML 内部标记，绝不从文本标记解析或执行工具。

曲线交叉使用纯函数 `comparison_crossovers` 及统一 `comparison_stats.crossovers`，不把基准持平后的初次分离算作交叉；文字次数和日期必须同口径复核。两期已披露财报只证明一次期间变化，“连续两季增长”至少需要三期同口径数据，一次增长也不能保证下一期继续增长。

Python 环境预置 `datasets/pd/np/get_frame`。SEC 平行数组可用 `get_frame(ref, table="companyfacts")`，结果保留 `period_ends/periods` 并提供 `period_end/period` 别名和已有标量上下文列；原始 datasets 不变。其他具名多表仍需明确选择，不能猜表、财期或单位。

需要返回的值必须赋给 `result`，只 print 会得到 `analysis_result_missing`。JSON 编码支持 NumPy 标量和 `pd.Timestamp`，NaN/Infinity 仍拒绝；DataFrame/数组需转为可序列化 rows/列表。失败的 `logs/logs_truncated/code_error` 用于定位代码与有界重试，不是金融结果。推荐图表结果为 `{"rows": [...], "summary": "..."}`；资源与输出上限见[Runbook](11_PRODUCTION_RUNBOOK.md)。

当前文本 phase 由后端写入 blocks/checkpoint；前端“思考/思考过程”“参数/结果”只是展示文案，不改变类型与真实错误。progress 不参与正式复制、会话摘要或后续回答历史。旧图的 `prior_artifacts` 仅保留有有效原始数据支撑的投影，不自动重画。

当前主应用后端与前端为 `agent-20261108-365a20081c6b`，独立 compute 保持 `python-20261107-a0b8e1d70e82`。本次新闻、财报、估值与追问的实际结果见[研究恢复验收](reports/2026-11-08_research_recovery/LIVE_RESEARCH.md)；受保护HTTP/本人OAuth与容器内部验证分开记录。

`compact_result` 优先投影财务数值、财期与口径、新闻原文和日期、完整计算区间与比较统计；长行情用明确的采样标记，不能将预览省略解释成数据缺失。`inspect_dataset` 按数据顺序取最新财期，显式元数据列保留口径及差分输入的有界投影；原始申报链继续可回读。显式回读的游标只推进实际返回的字符数。修正反馈硬限 10000 UTF-8 字节，仍受整体上下文/时间/token 预算约束。展示隐藏内部资料编号，真实引用继续可查看来源详情。

## Legacy 与预测适用边界

下方请求编译、ResearchAnalyst 与确定性 Collector 流程适用于 `FINSIGHT_RESEARCH_RUNTIME=legacy`。独立 Prediction 和固定 US20 的 forecast 合同继续沿用原实现；原生研究的专业角色使用 profile 描述，不修改 `TechnicalAgent`、`RiskAgent` 的冻结预测算法和公开账本。

## 1. Legacy 业务调用用途

业务 LLM 调用按用途区分，均使用请求中全局选定的模型：

| 角色 | 输入 | 输出 | 调用预算 |
|---|---|---|---|
| `request_compiler` | 当前原文、已绑定主体、当前线程历史和真实输入引用 | 保留全部原始要求的语义合同；工具能力由代码投影 | 复杂请求一个逻辑调用，结构错误最多同上下文纠正一次，保留实际 usage |
| `PredictionAnalyst` | trusted Kline、服务端指标、新闻摘要、已有 Prediction | 严格 Prediction JSON | 一个逻辑任务，最多一次纠错 |
| `ResearchAnalyst` | 规范化 evidence、Claim、任务与缺口 | 唯一 `research_result`、报告 draft | 按任务、草稿、核验及允许重试记录实际 usage，不能按角色数推断调用数 |
| `direct_answer` | 明确不需实时资料的概念问题 | 概念解释及标注为虚构的示例 | 不采集外部行情，使用同一模型配置及预算；已有固定正文无需调用 |

PredictionAnalyst 的 anchor 由服务端覆盖，方向、概率、止损、目标和 RR 由服务端校验。ResearchAnalyst 不直接取数，也不能引用 evidence pool 外的确定性数字。

请求编译只做语义提取，不负责研究判断或选择外部工具。原始要求保存在 `understanding.semantic_contract`，下游不能以能力不足或计划裁剪删除分母。明确社交和简单即时报价不额外调用请求模型。

## 2. Legacy 内部 Collector 与独立 forecast

`backend/agents/profiles.py` 描述 Price、News、Fundamental、Technical、Macro、Risk 与 Deep Search 的工具归属和展示元数据。这些 profile 是内部 evidence collector，不是用户选择的独立人格，也不代表七次 LLM 调用。

`backend/graph/adapters/collector_adapter.py` 使用 `llm=None` 构造 collector；`BaseFinancialAgent` 仅为兼容既有构造签名接收该参数并立即丢弃。collector 的职责只有：

- 调用许可范围内的工具；
- 规范化来源、时间、质量和失败语义；
- 生成 `AgentOutput`、evidence 与候选 Claim；
- 把工具错误作为 diagnostics 返回。

计划通过 `required_evidence` 明确 Agent 的输入义务，先等待相关数据生产者终态，再分析本轮已取得的数据。`SharedToolView` 与 tool adapter 共用 `RequestData`，相同工具和绑定参数只取一次；返回结果副本，保留 provider、as-of 和失败状态。失败来源可以由其他有效生产者补充，不能把“等待数据”误当作上游必须成功的控制依赖。

collector 不执行 LLM analysis、reflection、debate 或隐式 Prediction。

固定 US20 公开账本另有显式 `forecast()` 模式：Technical 预测五日方向，Risk 预测五日收盘序列最大回撤是否达到 5%。两者只接收冻结快照，使用独立 token/次数预算，允许弃权且不回退为历史标签。该模式由定时采集器显式调用，不进入普通 Collector 执行链，也不与用户 PostgreSQL Prediction/Outcome 混合统计。口径、实际模型审计和基准见 [公开预测账本](PREDICTION_TRACK_RECORD.md)。

## 3. 公共合同

- 工具失败进入 diagnostics，不生成假 evidence。
- 每条 Claim 必须引用 evidence id。
- 模型使用任务内 E/C 引用编号，服务端映射真实 ID；错误引用局部隔离，合法解释保留，允许在原预算内纠错一次。
- 用户回答义务保存在 `answer_requirements`；逐项输出 `requirement_results`，不能仅凭引用块 coverage 或模型有返回就宣称完整。
- provider、`as_of`、freshness、quality 必须跨层保留。
- 财务事实先验证主体、会计定义、实际期间、频率、单位和来源。SEC 累计值不冒充单季，财务行不做 `revenue`/`Cost Of Revenue` 这类子串匹配；对应期间缺失时不把环比写成同比。
- 本地公告核验发行人；新闻标题头、搜索分隔线和不明单位的宏观数值不作为已验证事实。
- `backend/research/news_event_quality.py` 是新闻时效、主体与出处的统一合同。发布时间、首次观察时间、事件发生时间分别保存；未知发布时间不补成“最近”，缓存读取不刷新抓取时间。
- `reported_news` 仅表示有时效和主体关联的归因报道，仍为 `headline_only`，不能声称已核实原文。旧闻、观点、传闻、检索摘要只作 raw 线索；明确与个股无关的新闻不进入正文或 Claim。
- 新闻按规范 URL、发布时间和事件身份保守去重，同话题后续进展保留；来源数量不代表独立核实数。日程只有可追溯供应商日期才进入候选事件，未核实搜索结果进入 `discovery_candidates`，不预置虚假 CPI/FOMC/非农事件。
- `quality != trusted` 的 Kline 不能进入 Prediction 或 Outcome。
- legacy collector 只按 capability registry、policy 和 PlanIR 执行；原生专业角色按 runtime 工具白名单执行。
- 新 collector 必须复用公共 TaskOutcome、Claim、引用和错误合同，不得自建协议。
- 用户可见角色、collector 名称和 LLM usage attribution 必须区分，避免把工具采集误报成模型判断。
- Claim 区分 `assertion_type=fact/opinion/risk`，携带 `subject/metric/horizon/scenario`；只有可比命题的相反判断才是冲突，长期趋势与短期风险可共存。
- 风险规则分数只衡量已观测指标触发阈值的程度；没有触发阈值不能表述为整体投资风险低。输入不可验证时评分未知，不生成假 0 分。
- 证据及 Claim 身份在执行、合成和渲染中保持一致；legacy 的 `research_result` 是该路径最终研究产物，renderer 不重新选择意图或从另一路正文覆盖它。原生运行时以已核验 blocks 和终态正文交付。
- `evaluate_result_quality` 统一合并 `pass/warn/block`；已有阻断不可覆盖。完整研究报告必须有受支持论据，facts-only 结果保留为预览。

## 4. 修改检查

调整 collector 时至少同步：

1. `backend/agents/profiles.py` 的职责与工具集合；
2. capability registry、policy allowlist、证据生产者映射、规则 planner 和实际工具参数 schema；
3. collector adapter、RequestData、结构化输出与 evidence gate；
4. 定向单测和至少一个跨层执行测试；
5. 本指南及受影响的观测字段。

legacy 业务调用用途的扩展必须同步 usage 归因、评测、预算和生产门禁。原生研究增加专业角色时优先复用同一循环、profile、工具权限和资料合同，不能把角色数量当作实际模型调用次数。
