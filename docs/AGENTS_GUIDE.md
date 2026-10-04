# FinSight AI 角色与 Collector 指南

更新时间：2026-10-04

## 1. 用户可感知角色

业务 LLM 调用按用途区分，均使用请求中全局选定的模型：

| 角色 | 输入 | 输出 | 调用预算 |
|---|---|---|---|
| `request_compiler` | 当前原文、已绑定主体、当前线程历史和真实输入引用 | 保留全部原始要求的语义合同；工具能力由代码投影 | 复杂请求一个逻辑调用，结构错误最多同上下文纠正一次，保留实际 usage |
| `PredictionAnalyst` | trusted Kline、服务端指标、新闻摘要、已有 Prediction | 严格 Prediction JSON | 一个逻辑任务，最多一次纠错 |
| `ResearchAnalyst` | 规范化 evidence、Claim、任务与缺口 | 唯一 `research_result`、报告 draft | 按任务、草稿、核验及允许重试记录实际 usage，不能按角色数推断调用数 |
| `direct_answer` | 明确不需实时资料的概念问题 | 概念解释及标注为虚构的示例 | 不采集外部行情，使用同一模型配置及预算；已有固定正文无需调用 |

PredictionAnalyst 的 anchor 由服务端覆盖，方向、概率、止损、目标和 RR 由服务端校验。ResearchAnalyst 不直接取数，也不能引用 evidence pool 外的确定性数字。

请求编译只做语义提取，不负责研究判断或选择外部工具。原始要求保存在 `understanding.semantic_contract`，下游不能以能力不足或计划裁剪删除分母。明确社交和简单即时报价不额外调用请求模型。

## 2. 内部 Collector

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
- collector 只按 capability registry、policy 和 PlanIR 执行。
- 新 collector 必须复用公共 TaskOutcome、Claim、引用和错误合同，不得自建协议。
- 用户可见角色、collector 名称和 LLM usage attribution 必须区分，避免把工具采集误报成模型判断。
- Claim 区分 `assertion_type=fact/opinion/risk`，携带 `subject/metric/horizon/scenario`；只有可比命题的相反判断才是冲突，长期趋势与短期风险可共存。
- 风险规则分数只衡量已观测指标触发阈值的程度；没有触发阈值不能表述为整体投资风险低。输入不可验证时评分未知，不生成假 0 分。
- 证据及 Claim 身份在执行、合成和渲染中保持一致；`research_result` 是最终研究产物，renderer 不重新选择意图或从另一路正文覆盖它。
- `evaluate_result_quality` 统一合并 `pass/warn/block`；已有阻断不可覆盖。完整研究报告必须有受支持论据，facts-only 结果保留为预览。

## 4. 修改检查

调整 collector 时至少同步：

1. `backend/agents/profiles.py` 的职责与工具集合；
2. capability registry、policy allowlist、证据生产者映射、规则 planner 和实际工具参数 schema；
3. collector adapter、RequestData、结构化输出与 evidence gate；
4. 定向单测和至少一个跨层执行测试；
5. 本指南及受影响的观测字段。

只有当输出合同、失败语义和调用预算无法由现有用途表达时，才讨论新增业务 LLM 角色。此类变更必须同步 usage 归因、评测、预算和生产门禁；概念直答不增加 Collector 或后台取数。
