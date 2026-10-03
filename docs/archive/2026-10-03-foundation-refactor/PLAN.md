# FinSight 研究基座重构与发布计划

日期：2026-10-03
状态：执行中
授权：用户要求生成计划、执行本次重构、更新文档、提交、push 和部署。
实现工作区：`E:/FinSight/.omx/worktrees/prediction-release`
分支：`release/models-us20-20261002`
起始发布版本：`1e03fa717d02969cb2352757e9cef58cd94a9c3a`

## 目标与范围

保留现有六节点 LangGraph 主图，重构请求、计划、证据、研究结果、质量裁决和运行持久化之间的合同，使真实投资问题不再因跨层重新解释而漏标的、漏维度、丢答案或发布错误事实。

完成条件：以下 M1–M8 全部取得验收证据；代码、测试与当前文档一致；新版本已提交、推送、部署，公开服务就绪并可确认版本；真实调用记录明确区分完整回答、证据不足、供应商故障与发布阻断。

纳入上一轮未提交的消息持久化、报价元数据、意图维度、证据投影、技术渲染和报告追问修复。保留原工作区用户改动，不重置原 `E:/FinSight`。本计划不修改 US20 冻结评估口径，不启用 `PREDICTION_ENABLED`，不恢复用户已关闭的全局生成并发上限，不发送额外测试邮件，不降低已授权的模型推理输出预算。

## 事实依据

- 当前主图：`backend/graph/runner.py:22`；研究取数入口直接执行 policy → rule planner → DAG，见 `backend/graph/nodes/collect_evidence.py:22`。
- 质量覆盖与枚举漂移：`backend/graph/report_builder.py:1329`、`backend/report/evidence_policy.py:79`；两个无网络 fixture 均复现 validator block 被后续变成可发布。
- 金融事实错误：`backend/tools/sec.py:172` 未核对单季区间；`backend/agents/fundamental_agent.py:542,586` 混用同比/环比并模糊匹配会计行；`backend/tools/local_disclosure.py:201` 仅校验域名/市场，无发行人核验。
- 语义和覆盖失配：`backend/graph/nodes/route_request.py:48` 启发式关联 frame；`backend/graph/planning/rule_planner.py:246` frame 分支可跳过未覆盖任务；`backend/graph/coverage_validator.py:56` 只检查全计划工具名字。
- 计划与依赖：`backend/graph/plan_ir.py:33` 接受任意 inputs；`backend/graph/planning/steps.py:54` 由排列推导依赖；`:126` 去重包括 parallel group。
- 竞争结果与冲突：`backend/graph/nodes/synthesize.py:240` 与通用合成可重复运行；`backend/graph/renderers/registry.py:136` 由分支优先级决定答案；`backend/graph/synthesis/research_synthesis.py:305` 按 stance 两两判冲突。
- 完成与保存：`backend/services/conversation_store.py:154` 整份消息覆盖；`backend/api/stream_replay.py:19` 和 `backend/api/execution_router.py:29` 的运行状态为进程内对象。
- RAG：`backend/rag/embedder.py:279` 失败后回退同维 hash；`backend/rag/hybrid_service.py:720` 主要验证维数；`backend/api/app_factory.py:205` 长期缓存健康成功状态。
- 13 类真实基线已完成：问候、报价、INTC 四维研究、催化追问、技术、财报影响、双股比较、宏观、港股、A 股、新闻、单股深度报告、对比报告。原始记录保存在受限 QA 目录；包含真实模型与行情，但使用隔离 RAG，不等于生产语义检索或浏览器登录验收。

## 目标合同

```mermaid
flowchart LR
    A[问题与会话上下文] --> B[统一请求与任务合同]
    B --> C[类型校验与逐任务覆盖后的 DAG]
    C --> D[主体 财期 单位 来源明确的证据]
    D --> E[唯一研究结果 事实 判断 引用 缺口]
    E --> F[单调合并的质量裁决]
    F --> G[后端保存运行与助手消息]
    G --> H[聊天和报告视图]
```

核心不变量：

1. 任务创建时确定 task/frame/subject 身份；下游不得重新解析原 query 改写它。
2. 覆盖单位为 `(task_id, subject, evidence_kind)`；同名工具不等于已满足义务。
3. 用户点名维度是必需义务；成本策略只能选择生产者，不能删除义务。
4. 工具输出先校验主体、指标定义、时间和单位，再进入证据；错误或未知不可冒充事实。
5. 证据身份跨执行、账本、合成、渲染保持一致；摘要和诊断不是新事实。
6. 判冲突必须指向同一对象、指标、期限和情景；多维观点允许共存。
7. 质量状态只能向更严重状态合并；执行完成、内容质量、持久化分别记录。
8. 最终助手消息由服务器幂等保存；SSE 和浏览器缓存只承载交付与显示。
9. 不同 embedding 模型/版本不得仅因维数相同进入同一语义空间。

## M1 金融事实入口与来源身份

- [x] `backend/tools/sec.py`：区分 duration/instant；按真实起止日期选择单季流量，保留实际 end/来源；累计、年度与季度不得混选，结果不依赖供应商数组顺序；EPS 不做累计差分伪补。
- [x] `backend/tools/financial.py`：每张报表保留实际频率、日期和来源；SEC 适配不把财政季度改写为日历季末。
- [x] `backend/agents/fundamental_agent.py`：明确指标别名与候选优先级；按真实日期对齐同比/环比；缺对应期间则缺失。
- [x] `backend/tools/local_disclosure.py`：标准化公司代码/别名，核验发行人；搜索结果为发现线索，身份未证实不得称该公司公告。
- [x] 新闻、宏观适配：拒绝搜索格式头/分隔线充当新闻；CPI 指数与通胀同比等数值保留语义单位。

验收：季度/累计、会计行名重排、非日历季度、少于五季、跨频率、错发行人、新闻格式噪声 fixture 全部通过；错误事实不进入 Agent claims。记录实际供应商缺数，不编造补齐。

## M2 唯一请求结构与逐任务覆盖

- [x] `intent/deterministic_engine.py`、`nodes/route_request.py`、`request_frame.py`：标的绑定后编译请求；从同一 frame 投射 task 与 legacy operation，取消出口启发式补身份。
- [x] 复合分句覆盖基本面、增长、催化、风险、财报及混合任务；每个有效任务有明确 frame，缺主语形成明确 blocked task。
- [x] `intent_contract.py`：成本 profile 不删除显式维度；兼容视图不得覆盖统一合同。
- [x] `coverage_validator.py`：按任务、标的、证据种类和有效生产者校验；缺任意主体或维度准确失败。

验收：原 INTC 四维、历史催化追问、技术指标题、`AAPL price, MSFT news, NVDA fundamentals`、双股增长/风险比较均规划完整；仅 AAPL 报价不能满足 MSFT 技术义务；语序或 facets 顺序变化不改变语义覆盖。

## M3 类型化计划与显式证据依赖

- [x] `plan_ir.py`、`planning/rule_planner.py`：返回前用实际工具注册 schema 验证 inputs、唯一 ID、任务引用、依赖引用与无环性。
- [x] `planning/steps.py`、`builders/`：先数据节点后消费 Agent；按实际输入依赖形成 DAG，独立分支并行。
- [x] 必需义务与可替代生产者、可选 enrichment 分离；任何配置无法满足义务时在执行前披露。
- [x] 共享取数按工具、标准化参数、请求时间范围去重；Agent 复用本轮已取得数据，保留供应商出处与失败状态。
- [x] budget 明确区分外部工具、Agent 和 LLM；不通过静默跳过必需步骤来“成功”。

验收：所有 builder 使用实际工具 schema 校验；错误 SEC 参数在外部 I/O 前拒绝；Agent 的必需证据引用非空；更改分组不增加相同数据调用；一个失败来源不能让无依赖分支被错误跳过。

## M4 唯一研究结果与单调质量门禁

- [x] `report/evidence_policy.py`、`graph/report_builder.py`、`services/execution_service.py`：统一质量枚举/原因，保留 validator 最严重结果，聊天门禁进入最终 SSE。
- [x] `synthesis/contracts.py`、`research_synthesis.py`：统一证据投影、事实与判断；论据携带对象/维度/期限或可比命题，准确判冲突。
- [x] `nodes/synthesize.py`、`renderers/`：同一请求只有一个最终研究产物；删除无消费者的重复合成；渲染仅展示已确定事实、判断、引用和逐项缺口。
- [x] 技术、宏观、财报、比较和催化追问按请求维度给实质内容；诊断 ID 留在诊断数据，不堆进正文。
- [x] 无有效论据的完整研究报告不得发布归档；有支持的部分回答明确 partial，保留有效事实。

验收：两项质量覆盖 fixture 永不回归；chat/report 状态一致；长期趋势与短期风险可并存；输入不同实体/期间不形成假冲突；模型已生成内容被拒绝时记录具体原因；比较不能只有两个 ticker 和 PE；宏观回答必须回答事件或明确缺失。

## M4a 本轮新增：实时新闻与事件质量

2026-10-03 用户指定参考 [AIHOT](https://github.com/KKKKhazix/AIHOT)。参考固定提交 `cc66cceb1dc7a0bc147e942e49ff94c9cee418c6` 的实际机制，自行实现适合金融研究的合同；不移植品牌，也不把热度榜单当事实来源。

- [x] 新闻统一保留发布时间、抓取时间、事件发生时间及各自精度；未知时间不写成“最近”。
- [x] 来源可信度、主体关联、时效、报道/观点/传闻/历史线索分开记录；搜索摘要不升级为已确认事件。
- [x] 去重区分同一事件与同一话题；保留事件后续更新及原始来源，转载数不能冒充独立核实数。
- [x] tool → gateway → Agent → research_result 全链保留质量字段；低质量材料只进入线索和明确缺口。
- [x] 增加旧闻、未知日期、未来时间、错误标的、转载、同话题不同事件 fixture，归档参考依据和测试记录。

验收：真实 AAOI/CN 新闻记录回放不再把旧新闻或观点称为最新催化；保留可点击出处和归因；不得宣称算法能保证所有新闻真实。

## M5 后端最终消息与运行恢复

- [x] `services/conversation_store.py`：支持 message/run ID 幂等终态保存与版本冲突处理；旧整份快照不能抹掉服务器最终回答。
- [x] `services/execution_service.py`：生成终态持久化后再发送可交付完成事件；保存失败保留预览并明确失败状态。
- [x] `api/execution_router.py`、`api/stream_replay.py`：运行终态有持久化兜底，进程重启/内存回放过期可取最终结果，不静默重新收费执行。
- [x] `frontend/src/hooks/useChatStream.ts`、`store/useStore.ts`：消费服务器最终消息与保存状态，兼容现有用户历史和未完成请求；保留前轮认证刷新修复。
- [x] 如需数据库变更，仅新增表/字段/索引，通过 Alembic 迁移，部署前备份并在隔离库验证升级兼容；不改写历史用户消息。

验收：刷新、断线、重复 done、旧快照晚到、双标签页、换账号、保存失败、重启后恢复的关键路径通过；同一 run 最终助手消息只保存一次；owner 隔离不变。

## M6 RAG 推理隔离与向量身份

- [x] `rag/embedder.py`、`hybrid_service.py`：写入与查询校验实际模型/版本；禁止 hash 写入 BGE 语义空间；旧未知身份向量不假定可信。
- [x] 重型 embedding/reranker 从 API 进程移出，采用私网 worker 与明确资源预算；不在主 backend 中启动额外 ML 副本。
- [x] `api/app_factory.py`、部署配置：健康状态反映实际推理和降级；资源不足或 worker 失败时保留明确的词法检索降级，不能报告语义检索正常。
- [x] 保留已有向量与文档，不做破坏性清理或无依据的模型身份回填。

验收：不同模型同维向量被隔离；worker 不可用时 API 仍可响应并披露 RAG 状态；实测一次真实 worker 推理或准确记录硬件导致的显式降级；部署不再次耗尽主机资源。

## M7 文档与验收资产

- [x] 更新 `README.md`、`docs/01_ARCHITECTURE.md`、`LANGGRAPH_FLOW.md`、`LANGGRAPH_PIPELINE_DEEP_DIVE.md`、`06a_LANGGRAPH_DESIGN_SPEC.md`。
- [x] 更新 `AGENTS_GUIDE.md`、`HALLUCINATION_MITIGATION.md`、`execution-event-contract.md`、`REPORT_CHART_SPEC.md`。
- [x] 更新 `05_RAG_ARCHITECTURE.md`、`rag-evaluation-guide.md`、`11_PRODUCTION_RUNBOOK.md`、`DOCS_INDEX.md`。
- [x] 建立可重复的真实问题 fixture/验收记录；记录主体、期间、维度、引用、质量、持久化和耗时，非空/字数不代表通过。
- [x] 完成后将计划与脱敏验收摘要归档到 `docs/archive/2026-10-03-foundation-refactor/`，附 README。

## M8 提交、发布与线上确认

- [ ] 迭代运行定向测试；集成完成后运行一次必要广泛后端验证、前端 unit/类型检查/lint/build 和关键 Playwright 验收。
- [ ] 真实供应商调用串行或受资源约束；与生产用户/向量写入隔离，保留原问法与完整答案。禁止在主进程额外加载模型。
- [ ] 全部改动检查敏感信息与 diff；按逻辑边界提交并推送现有 release 分支。
- [ ] 部署前检查实际服务器 HEAD、磁盘/内存、数据库迁移和配置备份；使用 SHA 镜像与可验证回滚。
- [ ] 部署包含必要 worker 与 `--profile predictions` 的 watchdog；US20 collector 仍关闭。
- [ ] 检查公开就绪状态、前端版本、默认模型、报价/研究/报告/刷新恢复；核实 QA 临时进程均结束。

## 并行责任与顺序

默认仅两个独立子代理，不嵌套。第一轮：金融数据入口由 `multi_dimension_intent` 负责；质量/研究结果由 `conversation_repair_guard` 负责。主代理负责计划、请求/编排、集成与发布。随后复用空闲代理处理持久化与 RAG，明确非重叠文件；涉及共享接口先协调。

不采用默认“实现+规格审查+质量审查”代理链。所有代理保留同事改动，不提交或部署；主代理核对集成证据。

## 风险与回滚

- 合同迁移风险：保留薄适配输出，逐边界切换；新增字段采用兼容默认值，不恢复旧废弃主链。
- 数据正确性风险：优先拒绝不确定财期/主体；不以 LLM 解释替代确定性校验。
- 持久化风险：schema 仅向前兼容，升级验证后保留旧镜像；旧代码可读历史数据，回滚不删除新记录。
- 资源风险：推理独立 worker，限制其容器资源；发生内存压力停止本次 QA/worker，不清理其它业务容器。
- 外部供应商风险：按错误类型记录与披露；不将 5xx、缺数、质量阻断当成功，也不以一次供应商失败认定整个架构失败。
- 发布失败：恢复发布前配置/镜像，确认 `/readyz` 与前端版本；已提交的兼容数据库新增结构不强制回滚删除。

## 执行记录

- 2026-10-03：计划建立；上一轮修复保留；13 类基线已结束；本轮重构开始。

- 2026-10-03：M1/M2/M3/M5代码与定向验收完成；1929项后端回归通过、15项跳过，12项真实PostgreSQL验收另行通过；315项前端unit和5项浏览器测试通过。M4按实际回答继续校准可读性，M6已验证隔离/身份/降级合同，真实worker硬件验收待发布；M7当前文档已同步；M8真实API验收进行中。

- 2026-10-03：补齐 AIHOT 参考的新闻/事件合同及前端质量标签；修复显式港股代码被默认 ADR 扩面、跨标的来源 ID 冲突、无情绪样本被称中性、宏观失败字符串冒充事实。新闻专项202项、权威媒体/补充路径109项、宏观27项、前端新闻22项、近期跨层163项验证通过（范围有交集，不相加）。
- 2026-10-03：生产共宿主QA造成内存压力，停止命令未能通过SSH，用户重启主机后服务恢复；QA容器/隔离库/角色已清理，记录保留。剩余完整验收迁到本机；生产RAG资源降级和迁移仍待实际部署验证。
