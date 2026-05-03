# Agent 体验、可观测性、RAG 三层与报告质量最终开工 Spec

状态：Final Spec / Ready for implementation
日期：2026-05-02
目标：以用户体验、架构清晰度、执行速度和回答质量为中心，统一规划前后端改造。

## 1. 北极星体验

FinSight 的长任务体验要接近 ChatGPT 的可观察生成过程：用户能实时看到系统正在规划什么、调用了哪些 agent、搜索了什么、抓取了哪些来源、哪些任务并行、哪个 agent 慢、为什么降级、还能随时停止或开启新对话。

核心原则：

- 用户不傻等：超过 5-10 秒的操作必须有可读事件。
- 总进度和每个 agent 进度同时存在。
- 后端是进度、ETA、取消和 trace 的事实源，前端只做展示和降级。
- 深度报告先回答用户 query，再展开研报结构。
- RAG 数据必须分层：对话记忆、本次 working set、长期 KB 不能混成一个桶。
- 普通用户看摘要，专家看 timeline，开发者看 raw trace。

## 2. 当前事实与问题

### 2.1 已有基础

- `backend/graph/executor.py` 已按 `parallel_group` 对步骤做局部并发。
- `backend/services/execution_service.py` 已统一 `/chat/supervisor/stream` 和 `/api/execute` 的 SSE 输出，并注入 `run_id/session_id`。
- `frontend/src/api/client.ts` 已有共享 SSE parser，并支持 `AbortSignal`。
- `frontend/src/store/executionStore.ts` 已有 execution run、timeline、cancelExecution 和 AbortController。
- `backend/rag/layering.py` 已引入 `memory/ws/kb` 三层 collection 命名与 metadata enrich。
- `frontend/src/pages/RagInspectorPage.tsx` 已开始展示 RAG layer、collection_kind、entity 和 DB Browser layer filter。

### 2.2 必须纠正的问题

- 并行只是调度层局部并行；agent 内部同步 I/O 仍会拖慢整体。
- DeepSearch 搜索、反思、抓取、fallback 缺少用户可读进度和有界并发。
- 总进度和 ETA 主要由前端估算，容易出现“100 秒突然变 1 秒”。
- agent 卡片只有状态和耗时，没有连续进度、当前工具、心跳和卡住提示。
- 没有产品级“新建对话 / 清空当前上下文 / 删除记忆”三种语义区分。
- 停止生成主要是前端 abort fetch；后端缺少可查询、可恢复、可审计的 cancel contract。
- 用户态看不到“搜了什么 / 调用了什么工具 / 正在抓取哪个来源”的安全摘要。
- 报告链缺少 `answer_targets`，固定研报模板可能掩盖未回答 query。
- 前端 Inspector 自己推断 collection 语义，和后端 `layering.py` 存在重复。
- 自动晋升长期 KB 有污染风险，必须有晋升门槛、审计和回滚。
- `.omx/`、审计截图、换行符归一化不应混入功能提交。

### 2.3 本轮补充审查发现

这些问题不是“体验优化项”，而是会直接影响可信度、可维护性和用户心智模型的架构红线：

- RAG 观测存在双轨写入风险：`execute_plan_stub` 自己写 `QueryRunRecord/SourceDocRecord/ChunkRecord/RetrievalHitRecord/RerankHitRecord`，同时 `install_rag_observability_hooks()` 又包装 `HybridRAGService.hybrid_search_many()` 自动写 run。必须统一成一个事实源，否则同一次业务请求会出现两类 run。
- `ws` 与 `kb` 生命周期已经有塌陷风险：filing/research_doc 或“高置信 + 高可靠来源”的材料会被标成 `persistent` 并自动写入 `kb_collection`。这不是一次性缓存，而是隐式长期写入。
- `hybrid_search_many()` 当前仍是按 collection 顺序调用，不是 bounded parallel。三层检索一旦扩展到 memory/ws/kb + 多 ticker，会被最慢 collection 拖住。
- `query_text_redacted` 当前等于原始 query，RAG Inspector 又能展示 `content_raw/chunk_text/payload_json`。这不是脱敏，而是给敏感数据换了个字段名。
- soft-delete 只删除 observability 视图，不保证向量检索层同步排除。结果可能出现“Inspector 里删了，RAG 仍命中”的用户信任事故。
- memory scope 混乱：用户级偏好、watchlist、last_focus 被 materialize 到 thread memory collection 时，语义上既像 user memory 又像 thread memory。New Chat / Clear Context / Delete Memory 会因此无法定义清楚。
- 同步 chat 响应仍可能返回完整 `trace`，而 stream 路径已有 raw trace gating。sync/stream 两条路径必须共享同一权限和脱敏策略。
- Stop 当前主要是前端 `AbortController.abort()` 和本地状态变化；没有后端 cancel registry、cancel token、最终状态查询和审计闭环。
- Chat 流链路还没接上 `AbortSignal`，Stop 对普通聊天 SSE 可能是假停止；execution 流和 chat 流目前不是同一套取消语义。
- New Chat / Clear Context 当前更像“换 session id / 清 selection pill”，没有统一清除 ticker、selection、status、progress、Agent logs、raw events、active run。
- `report_id` 深链存在首屏恢复后被 `replaceState` 抹掉的风险，分享、刷新、回退无法稳定复现同一视图。
- Inspector 已经能看三层命中，但仍是高密度诊断台；用户态、专家态、开发态没有固定信息边界，普通用户会被 DB row、payload、metadata 淹没。
- `execute_plan_stub` 中出现重复 `return` 这类低级坏味道，说明新增 RAG 三层逻辑已经膨胀到需要拆分职责，而不是继续堆在执行节点里。
- `/diagnostics/rag/db-browser/*?layer=` 对 `rag_source_docs/rag_chunks` 有静默失效风险：底层表没有物理 `collection` 列，collection/layer 主要在 `metadata_json`。
- legacy `session:deepsearch:*` collection 仍存在，新的 `mem/ws/kb` 只是兼容解释，不是唯一生命周期事实源。

证据索引：

- `backend/graph/nodes/execute_plan_stub.py:292` 和 `:293` 有重复 `return`；同文件 `:1059` 开始创建 `QueryRunRecord`，`:1511` 追加 source docs。
- `backend/rag/observability_store.py:721`、`:740`、`:907` 到 `:953` 包装 `hybrid_search_many()` 并自动写 run。
- `backend/rag/observability_store.py:375`、`:727` 把 `query_text_redacted` 直接赋值为 query。
- `backend/rag/hybrid_service.py:477`、`:876`、`:1055` 的 `hybrid_search_many()` 是 collection 顺序 fanout。
- `frontend/src/store/executionStore.ts:1265` 到 `:1278` 的 cancel 主要是 abort controller 和本地状态。
- `frontend/src/components/ChatInput.tsx:372` 和 `frontend/src/api/client.ts:939` 的聊天 SSE 链路没有接 `AbortSignal`。
- `frontend/src/store/useStore.ts:407` 的 `setSessionId` 主要切换 session/messages，未统一清理 ticker、selection、execution 和日志状态。
- `frontend/src/components/layout/ChatWorkspace.tsx:85` 到 `:97` 读取 `report_id` 后会改写 URL。
- `frontend/src/pages/RagInspectorPage.tsx:77` 到 `:79` 把 `query_text/content_raw/chunk_text` 放入 DB Browser 优先列；`:1078`、`:1107` 展开原文和 chunk。
- `backend/api/chat_router.py:118` 到 `:134` 的 sync chat 响应 metadata 仍包含 `trace`。
- `backend/agents/deep_search_agent.py:1215` 到 `:1219` 仍有 legacy `session:deepsearch:*` 命名。
- `backend/rag/observability_store.py:617` 到 `:628` 的 layer filter 需要覆盖 metadata-only collection 字段。

## 3. 目标范围

### 3.1 In scope

- Chat/Workbench/MiniChat 的对话生命周期、停止生成和上下文清理体验。
- Agent/Tool/DeepSearch 的实时可观测事件。
- 后端 `progress_update`、`agent_step`、`agent_heartbeat`、cancel API。
- 前端总进度 + per-agent 进度 + activity rail。
- RAG 三层检索、晋升治理、Inspector 展示。
- 深度报告 query contract、coverage validator 和 UI 展示。
- 相关单元、集成、前端 reducer、E2E、可观测性测试。

### 3.2 Out of scope

- 不重写整个 LangGraph Pipeline。
- 不新增新的金融 agent 类型。
- 不默认向普通用户暴露 raw trace JSON。
- 不把所有历史文档恢复为当前事实源。
- 不在本轮做自动交易、组合下单或高风险投资决策闭环。

## 4. 产品需求

### 4.1 对话生命周期

必须区分三个动作：

1. 新建对话
   - 生成新的 `session_id/thread_id`。
   - 清空当前 UI messages、currentStep、executionProgress、active run。
   - 保留用户级偏好和 portfolio，不继承当前线程临时上下文。
   - 新线程第一条消息不能引用旧线程的“它 / 这家公司 / 上一份报告”。

2. 清空当前上下文
   - 保持当前 `session_id/thread_id`，但清除该线程的 transient context、pending selection、execution state、checkpoint transient fields。
   - 不删除长期 KB，不删除用户级偏好。
   - 清空后要发一条系统事件：`context_cleared`。

3. 删除当前对话记忆
   - 明确删除当前 thread memory 和本地消息历史。
   - 需要二次确认。
   - 删除行为写入 audit event。

后端建议：

- `POST /api/sessions/new`
- `POST /api/sessions/{thread_id}/clear-context`
- `DELETE /api/sessions/{thread_id}/memory`

前端建议：

- 顶部或输入框附近提供 `New Chat`、`Clear Context`、`Stop` 三个明确动作。
- New Chat 使用加号图标；Clear Context 使用清扫/重置图标；Stop 使用停止方块图标。
- 不用长文本按钮堆满界面，图标必须有 tooltip。

### 4.2 停止生成与取消任务

目标：用户点击 Stop 后，前端立即停止渲染，后端尽快停止可取消任务，并明确告诉用户“已停止，已保留部分结果”。

后端要求：

- 增加 `POST /api/executions/{run_id}/cancel`。
- `run_graph_pipeline`、executor、DeepSearch、tool adapter 周期性检查 cancel token。
- 对不可中断的外部 HTTP/LLM 请求，结束后丢弃后续事件并标记 `cancelled_after_inflight`。
- cancel 事件必须包含 `run_id`、`stage`、`agent_id?`、`reason`、`partial_artifacts_available`。

前端要求：

- ChatInput、ExecutionPanel、StreamingResultPanel 都能触发同一个 stop action。
- Stop 后消息气泡显示“已停止”，保留已流出的 token 和 activity timeline。
- 用户可以对 stopped run 继续追问、重新生成或另开新对话。
- Chat SSE 与 execution SSE 必须共用同一 `AbortSignal` / cancel store 契约；`sendMessageStream` 必须支持 `signal`。
- Stop 对聊天流的验收不是“按钮变灰”，而是请求被 abort、token 不再追加、active run 进入 stopped/cancelled 终态。

### 4.3 实时可观测 Activity Rail

用户态要像 ChatGPT 一样实时展示“系统在做什么”，但不暴露 raw JSON 和敏感 query payload。

新增用户态事件摘要：

- `planning_started`：正在拆解任务
- `agent_started`：某 agent 开始
- `search_query_started`：正在搜索某主题
- `search_results_found`：找到 N 条来源
- `document_fetch_started`：正在读取来源
- `document_fetch_done`：来源读取完成
- `tool_call_started`：调用工具
- `tool_call_done`：工具完成
- `agent_heartbeat`：仍在工作，当前阶段
- `fallback_used`：使用降级来源
- `quality_check_started/done`：质量检查
- `query_coverage_done`：用户问题覆盖情况

展示规则：

- 用户态显示短句：例如“DeepSearch 正在搜索 AI capex 风险，已找到 6 个来源”。
- 专家态显示 agent、tool、parallel_group、duration、source count。
- 开发态显示 raw event、metadata、JSON。
- event row 要可折叠，默认只展开当前活跃事件。

### 4.4 总进度 + Agent 独立进度

后端新增事实源：

```json
{
  "type": "progress_update",
  "run_id": "run_123",
  "stage": "executing",
  "progress_percent": 42,
  "eta_seconds": 75,
  "completed_weight": 18,
  "total_weight": 43,
  "active_agents": ["deep_search_agent"],
  "critical_path": ["deep_search_agent", "synthesize"]
}
```

agent 级事件：

```json
{
  "type": "agent_step",
  "run_id": "run_123",
  "agent_id": "deep_search_agent",
  "span_id": "span_deep_1",
  "step_id": "s4",
  "parallel_group": "report_agents",
  "progress_percent": 35,
  "current_step": "抓取第 2/4 篇文档",
  "tool": "search",
  "heartbeat": false
}
```

前端要求：

- 保留一条总进度。
- 增加 `AgentProgressList`：每个 agent 一行，显示状态、进度、当前动作、耗时、卡住标记、错误/跳过原因。
- 如果 15 秒无事件但 run 未结束，显示“仍在执行，等待后端事件”，不要假装卡死或完成。
- ETA 优先取后端；没有后端 ETA 时才本地估算，并明确标记为估算。

### 4.5 高影响 UX 断点清单

这些断点必须进入 P0/P1，而不是留到“以后美化”：

- 新对话：必须有显式 New Chat。它创建新 `thread_id`，清空当前 UI 和 pending run，但保留用户级设置。
- 清上下文：必须有显式 Clear Context。它只清 transient context，不删长期 KB，不删 user profile。
- 删除记忆：必须有 Delete Memory。它删除当前 thread memory 和本地消息，二次确认，写 audit。
- 停止生成：Stop 后 300ms 内 UI 状态变为 stopped，后端最终状态可查询，旧 run 不能继续推新 token。
- 重新生成：stopped/failed run 必须支持 regenerate，且 regenerate 会生成新 run_id 并继承原 query contract。
- 继续追问：对 stopped/partial report 的追问必须显式带上 partial artifact 引用，避免模型假装完整。
- 心跳：DeepSearch、抓取、rerank、报告生成任一阶段超过 10 秒必须发 `agent_heartbeat` 或 `tool_heartbeat`。
- 卡住态：15 秒无事件显示“等待后端事件”；30 秒无 heartbeat 显示 stalled；60 秒无 heartbeat 建议用户停止或重试。
- 搜索可见：用户态能看到“搜了什么主题、找到多少来源、正在读哪个来源域名”，但不能看到完整 prompt。
- 工具可见：用户态能看到工具名、动作和结果摘要；专家态能看到参数摘要；开发态才看 raw payload。
- 来源可信：报告旁必须有 evidence ledger 入口，显示主要来源、时间、层级、是否 fallback。
- 未回答警告：如果 `query_contract.unanswered_targets` 非空，报告第一屏必须显示 warning。
- 选择生命周期：用户选中的 ticker、report、source 进入 query contract；New Chat 后不能残留旧选择。
- 空态/错态：RAG Inspector、Activity Rail、Agent Progress、Report Panel 都要有明确空态、失败态、降级态。
- 深链恢复：刷新页面后 `run_id/thread_id/collection/layer/mode` 能恢复；恢复失败要显示原因。
- 移动端：Stop/New Chat/Clear Context 不得被输入框挤出；Activity Rail 默认折叠为最近 3 条。
- 重置会话必须通过单一 `resetConversationContext`：清空 messages、draft、current ticker、active selections、executionProgress、status text、Agent logs、raw events、active run 和 pending report view。
- 深链是 canonical state，不能首屏恢复后悄悄抹掉；如果 URL 要清理，必须把 `report_id/run_id/thread_id/mode` 写入可分享的新 canonical URL。

## 5. 后端架构要求

### 5.1 执行器并发

- `parallel_group` 继续作为 planner 显式并行语义。
- executor 增加有界并发：全局、每 provider、每 tool、每 agent 均可限流。
- Python 版本允许时优先使用 `asyncio.TaskGroup`；否则保留 `gather` + structured cancellation。
- agent 内部同步 I/O 迁移到 async client 或 `asyncio.to_thread`。
- 每个并发任务必须有 `span_id` 和 parent-child 关系。

### 5.2 DeepSearch 速度与质量

- initial search、targeted gap search、document fetch 改为 bounded parallel。
- 每轮 reflection 发事件：`reflection_started`、`gap_identified`、`targeted_search_started`、`summary_updated`。
- 抓取 fallback 顺序必须可见：direct -> Jina -> Wayback。
- 每个外部来源要记录 timeout、retry、status、content_length、fallback_reason。
- DeepSearch 结果必须输出 evidence ledger，供 synthesize 和 report validator 使用。

### 5.3 Trace / Span 模型

统一事件字段：

- `schema_version`
- `run_id`
- `event_id`
- `parent_id`
- `span_id`
- `thread_id`
- `stage`
- `step_id`
- `parallel_group`
- `agent_id`
- `tool`
- `status`
- `started_at`
- `ended_at`
- `duration_ms`
- `progress_percent`
- `message`
- `user_message`
- `metadata`
- `error`

架构要求：

- 废除无法区分请求的全局广播 listener，或源头强制带 `run_id` 并按 `run_id` 过滤。
- executor、agent adapter、base agent 不能重复发同一个 lifecycle；统一一个 owner。
- SSE 支持 `id:`，便于断线续传。
- 提供 `/api/executions/{run_id}/events` 回放。

### 5.4 RAG 三层治理

三层定义：

- `memory`：线程摘要、用户偏好、最近上下文、指代消解；不存长原文。
- `ws`：本次任务材料、agent evidence、网页片段、短期缓存；必须 TTL。
- `kb`：财报、公告、电话会、研究文档、人工上传；长期保留。

改造要求：

- 后端 `backend/rag/layering.py` 是 collection 语义唯一事实源。
- 前端不再长期手写 collection parser；API 返回 `layer/collection_kind/entity_scope/entity_key`。
- 普通 Chat 默认不自动写长期 KB。
- DeepSearch/研报/财报解读只把高质量材料标记为 candidate；自动晋升必须满足规则。
- 晋升必须有 `promotion_status`、`doc_fingerprint`、`parent_collection`、`parent_run_id`。
- Inspector 提供晋升、拒绝、软删除、恢复的审计入口。

### 5.5 报告 Query Contract

新增数据结构：

```json
{
  "query_contract": {
    "original_query": "...",
    "resolved_query": "...",
    "answer_targets": [
      {"id": "t1", "question": "AI capex 是否压制利润率", "required": true}
    ],
    "answered_targets": ["t1"],
    "unanswered_targets": [],
    "coverage_status": "passed"
  }
}
```

要求：

- planner 先从 query 中抽取 `answer_targets`。
- 检索 query 必须由 ticker + answer target 共同生成，禁止只用 `{ticker} earnings outlook`。
- 报告第一节必须叫“直接回答”，逐条回答 `answer_targets`。
- 固定研报章节只作为证据展开，不能替代直接回答。
- validator 对 required target 做 coverage gate。
- 未回答必须显式说明原因：缺数据、来源冲突、实时工具失败或超预算。

### 5.6 RAG 不是一次性缓存

结论：DeepSearch 用完即废不合理。合理设计是“短期材料可过期，证据链可回放，高质量材料可晋升，低质量材料可丢弃”。

生命周期分层：

- `ephemeral`：单个 tool call 的临时结果，只在内存中流转，不进入向量库；失败抓取、低质量片段、重复噪音默认在这里结束。
- `ws`：本次任务或当前 thread 的 working set。DeepSearch 抓到并被使用的来源、报告 evidence、agent 摘要进入这里；有 TTL，可被同一线程后续追问复用。
- `memory`：用户偏好、线程摘要、最近关注对象和指代消解材料。只存摘要和结构化事实，不存长网页原文。
- `kb`：人工上传、财报、公告、电话会、可信研究材料，长期保留。自动晋升必须通过来源质量、内容完整性、去重和人工/规则门槛。

硬合同：

- DeepSearch 的有效来源必须进入 `ws`，并写入 `parent_run_id/doc_fingerprint/source_doc_id/chunk_id`，否则报告无法回放证据。
- `ws` 默认 TTL 建议 7-30 天，可按 `thread_id`、`ticker`、`run_id` pin 住，报告被收藏或导出时自动延长。
- `kb` 只能由 `promotion_status=approved` 的材料进入；`candidate/rejected/deleted` 不能被长期检索默认命中。
- `ws` 不允许 `scope=persistent`。如果材料要长期保留，只能先进入 `promotion_status=candidate`，再由 promotion gate 转入 `kb`。
- 普通 chat、普通 DeepSearch、普通网页抓取不得自动写 `kb`；filing/research_doc 也必须先过 gate，不允许靠 doc_type 直接长期化。
- 同一来源再次出现时必须按 `doc_fingerprint` 去重，更新 metadata 和引用计数，而不是重复写多个 chunk。
- RAG hit 必须返回 `layer/collection/source_doc_id/chunk_id/doc_fingerprint/parent_collection/parent_run_id/promotion_status`。
- 用完即废只适用于明确标记为 `ephemeral` 或 `rejected` 的材料，不能适用于支撑最终回答的证据。
- legacy `session:deepsearch:*` 必须迁移到 `ws:deepsearch:*` 或明确标记为只读历史兼容；新写入路径不能继续生成 legacy collection。

### 5.7 RAG Observability 单一事实源

目标：一个业务请求只有一个顶层 RAG run，所有 search、ingest、rerank、promotion 都是它的 child span 或 child event。

合同：

- orchestrated graph 路径由 `execute_plan` 或统一 RAG coordinator 创建 `rag_query_run`。
- `HybridRAGService` 不在 orchestrated context 中新建独立 run，只发 `rag_search_span`、`rag_ingest_span`、`rag_rerank_span`。
- service hook 只允许用于离线脚本、诊断页面直接调用、测试工具这类没有上层 run 的场景；此时必须标记 `origin=service_hook`。
- 每条 observability 记录必须带 `business_run_id`、`rag_run_id`、`span_id`、`parent_span_id`、`thread_id`、`session_id`。
- 禁止出现同一 query 同时生成 `run_*` 与 `ragrun_*` 且互不关联的情况。
- `hybrid_search_many()` 的 observability 不能只记录 primary collection；必须记录完整 `search_collections` 和每个 collection 的 latency、hit_count、error。

### 5.8 Memory Scope 合同

当前最危险的问题是“记忆来自用户级 profile，但 collection 名称像 thread memory”。必须拆开：

- `mem:user:{tenant}:{user}`：用户长期偏好、watchlist、风险偏好、语言偏好。New Chat 和 Clear Context 不删除。
- `mem:thread:{tenant}:{user}:{thread}`：当前对话摘要、最近指代、当前任务偏好。Delete Memory 删除，Clear Context 清 transient 后可重建摘要。
- `mem:subject:{tenant}:{user}:{ticker}`：用户对某 ticker 的长期关注摘要，可由明确收藏或高质量报告更新。
- `ws:thread:{tenant}:{user}:{thread}`：当前线程 working set，受 TTL 和 run pin 管理。
- `kb:{subject_type}:{subject_key}`：长期知识库，默认不接受普通聊天写入。

写回规则：

- sync chat 和 stream chat 必须共享同一 memory persistence policy。
- quality hard-blocked 的报告不写 memory；soft-blocked 只允许写“用户问过什么”和“报告未通过质量门禁”，不能写结论。
- Clear Context 发 `context_cleared` 并清除 transient checkpoint；Delete Memory 发 `memory_deleted` 并删除 thread memory 与本地消息。
- 所有 memory 写入必须记录 `source_run_id/source_message_id/write_reason/ttl/policy_version`。

### 5.9 删除、脱敏、权限与保留

- `query_text_redacted` 必须是真脱敏字段，至少屏蔽账户、邮箱、token、长数字、用户私有备注和完整 prompt；原始 `query_text` 只对 dev/internal 可见。
- `content_raw/chunk_text/payload_json/metadata_json` 默认不进用户态；专家态只看 preview；开发态需权限开关和审计。
- diagnostics API 必须按角色返回字段：`user` 看摘要，`expert` 看可解释证据，`dev/internal` 才看 DB row 和 raw JSON。
- DB Browser 的 `layer` filter 必须对 `rag_documents_v2`、`rag_source_docs`、`rag_chunks`、`rag_query_runs` 全部有效；没有物理 `collection` 列的表必须从 `metadata_json.collection/layer` 过滤。
- soft-delete 必须定义 retrieval 语义：被 soft-delete 的 source/chunk 默认不可被检索命中；向量库要同步 tombstone 或物理删除。
- 删除需要 audit：`deleted_by/delete_reason/deleted_at/deletion_scope/retrieval_effect/vector_delete_status`。
- 恢复需要 audit，并重新打开 retrieval visibility。
- run/detail/db browser 分页必须使用稳定复合游标，例如 `(started_at, run_id)` 或 `(created_at, id)`，不能只靠时间字段。

### 5.10 Fanout、Provenance 与性能合同

- `hybrid_search_many()` 改为 bounded parallel，支持全局并发、每 collection 并发、每 backend timeout。
- 任一 collection 失败不应拖垮整次检索；结果中记录 partial failure 和 fallback。
- 返回结果必须保留每个命中来自哪个 collection，而不是合并后丢失来源。
- rerank 输入和输出都要记录 `input_rank/output_rank/score/selected_for_answer`。
- evidence ledger 是报告质量的事实源，synthesize 只能引用 ledger 中的证据，不能引用不可追溯的临时文本。

## 6. 前端体验与视觉要求

### 6.1 Chat 主界面

- 第一屏必须是可用工作界面，不做营销式 hero。
- 输入区要支持：New Chat、Stop、Clear Context、Trace Mode。
- loading 气泡旁展示 Activity Rail，而不是只显示一根进度条。
- 已停止、失败、降级、质量阻断必须有清晰状态，不混成普通错误。
- 新建对话后旧消息不应继续出现在当前线程。

### 6.2 Activity Rail 视觉

- 设计风格：专业金融工作台，低噪音、高信息密度、可扫描。
- 用户态只显示 3-6 条关键活动，更多内容折叠。
- 每条活动包含：图标、动作、主体、耗时或状态。
- search 事件展示搜索主题和来源数量，不展示敏感完整 prompt。
- tool 事件展示工具名和结果摘要，不展示原始参数 JSON。

### 6.3 Agent Progress List

- 每个 agent 使用固定高度行，避免进度更新导致布局跳动。
- 行内字段：agent 名称、状态、当前步骤、独立进度、耗时、来源数、错误/跳过原因。
- agent 运行超过 30 秒无 heartbeat，显示 stalled badge。
- 支持按 parallel_group 分组展示，让用户看出“这些在并行”。

### 6.4 RAG Inspector

- 首页先展示三层概览：memory / ws / kb 的 collection 数、文档数、命中数。
- Run detail 展示 search path：查了哪些 collection、命中哪些 layer。
- DB Browser 默认隐藏长文本，点击展开。
- collection 深链必须稳定：`?collection=...&layer=...`。
- “晋升到 KB / 拒绝 / 软删除 / 恢复”使用明确按钮和确认态。

### 6.5 视觉质量红线

- 不嵌套卡片套卡片。
- 不使用大面积渐变、装饰性光斑、无意义 hero。
- 金融工具应保持密度和秩序，避免松散的大卡片堆叠。
- 按钮优先图标 + tooltip；只有关键命令保留文字。
- 所有进度条、agent 行、工具行必须固定尺寸，防止跳动。
- 移动端不允许文字挤出按钮或遮挡内容。

### 6.6 用户态 / 专家态 / 开发态视图合同

`traceViewMode` 不是样式开关，而是信息边界：

- `user` 默认视图：直接回答、当前活动摘要、总进度、可读来源摘要、未回答警告、Stop/New Chat/Clear Context。不得默认展示 raw JSON、DB row、完整 chunk、完整 prompt。
- `expert` 视图：agent timeline、parallel group、layer hit breakdown、fallback、query contract、coverage、source preview、rerank 摘要。可以解释为什么慢、为什么降级、为什么没回答。
- `dev` 视图：raw SSE、span/tree、event payload、DB row、collection deep link、request id、run id、schema version。必须有权限门槛和“正在查看敏感调试信息”的状态提示。

切换规则：

- mode 切换不得丢失当前 `run_id/collection/layer/selected source`。
- 页面刷新后恢复 mode，但如果权限不足，自动降级到 `user` 并提示原因。
- 用户态 Activity Rail 最多展示 6 条关键事件；expert/dev 可以展开完整 timeline。

### 6.7 Inspector 信息架构整改

RAG Inspector 现在能看很多数据，但还不是好用的工具。整改目标是“先解释，再下钻”：

- 第一屏：三层总览、最近 runs、当前 run 的 search path、主要问题 badge。
- 第二层：命中与证据，按 layer/source/quality 分组，而不是按数据库表顺序堆叠。
- 第三层：DB Browser 和 raw payload，只给 dev/internal。
- 每个 collection/layer badge 要有 tooltip，说明 `memory/ws/kb` 的生命周期和删除影响。
- 删除、恢复、晋升、拒绝必须使用独立操作区，避免和只读筛选混在一起。
- 长文本 preview 默认 200-360 字；展开 raw text 前显示数据敏感提示。

## 7. API 合同

新增或固化：

- `POST /api/sessions/new`
- `POST /api/sessions/{thread_id}/clear-context`
- `DELETE /api/sessions/{thread_id}/memory`
- `POST /api/executions/{run_id}/cancel`
- `GET /api/executions/{run_id}`
- `GET /api/executions/{run_id}/events`
- `GET /diagnostics/rag/db/{table}?layer=...`
- `POST /diagnostics/rag/promotions`
- `POST /diagnostics/rag/documents/{source_doc_id}/restore`
- `DELETE /diagnostics/rag/documents/{source_doc_id}/retrieval-visibility`

所有响应必须包含：

- `status`
- `schema_version`
- `request_id` 或 `run_id`
- `timestamp`
- `error` 或 `data`

事件 contract：

- SSE 必须带 `id:`，event id 可用于断线续传。
- 所有事件必须带 `run_id/event_id/schema_version/timestamp`。
- raw event 和 user event 分离：同一后端事件可以生成 raw payload 和 redacted summary。
- `progress_update` 必须声明 `confidence=authoritative|estimated`。
- cancel API 返回最终态前可为 `cancelling`，但必须可轮询到 `cancelled/completed/failed`。

## 8. 实施顺序

### P0-A：架构红线先止血

- 统一 RAG observability 单一事实源，禁止同一业务请求双 run。
- `query_text_redacted` 改为真实脱敏，用户态不返回 raw query/raw chunk/raw payload。
- `hybrid_search_many()` 改为 bounded parallel，并记录每个 collection 的耗时和失败。
- Stop 接入后端 cancel contract，而不是只 abort 前端 fetch。
- 报告第一屏强制 `query_contract` 和未回答警告。

验收：

- 单次 DeepSearch 只产生一个顶层 RAG run，child span 可追溯。
- 普通用户接口和用户态 UI 看不到 raw JSON、完整 chunk、完整 query。
- 多 collection 检索中某一层失败时，其他层仍返回，并在 Activity Rail 显示 partial fallback。
- Stop 后后端 run 最终状态可查询为 `cancelled` 或 `cancelled_after_inflight`。

### P0-B：停止傻等

- 增加 `progress_update`、`agent_step`、`agent_heartbeat`。
- 前端实现 Activity Rail、AgentProgressList、Stop。
- DeepSearch 发搜索/抓取/反思事件。
- 报告增加“直接回答”章节和最小 query coverage。

验收：

- 长任务 10 秒内必有用户可读事件。
- 用户能停止生成。
- 用户能看到哪些 agent 并行、哪个 agent 正在做什么。
- 深度报告第一节直接回答用户问题。

### P1：上下文和取消语义闭环

- 实现 New Chat、Clear Context、Delete Memory。
- 后端 cancel registry + executor/DeepSearch cancel token。
- trace span 去重和 request-scoped emitter。
- 前端停止后可重试、继续追问、另开新对话。

验收：

- 新对话不能引用旧线程。
- 清空上下文后当前线程不再解析旧指代。
- cancel 后后端不会继续向该 run 推事件。
- trace 不串到其他 session/run。

### P2：RAG 与质量治理

- 固化 RAG 三层 API 字段。
- Inspector 增加晋升/拒绝/软删除/恢复。
- 长期 KB 晋升门槛和 audit log。
- query_contract 接入 `PlanIR/ReportIR/ReportValidator`。

验收：

- 每个 RAG hit 都能解释来自哪一层、哪个 collection、为什么命中。
- 自动晋升不会把普通新闻碎片写入长期 KB。
- 报告 validator 能指出未覆盖的 answer target。

### P3：性能与稳定性

- DeepSearch bounded parallel 和 source-level timeout。
- provider/tool/agent rate limit。
- SSE reconnect + event replay。
- 前端 E2E 覆盖长任务、取消、恢复、切换会话。

验收：

- DeepSearch 同等质量下 p95 时长明显下降。
- 断线刷新后可恢复 run timeline。
- 并发两个用户请求 trace 不串扰。

## 9. 预期改动文件

后端：

- `backend/api/chat_router.py`
- `backend/api/execution_router.py`
- `backend/api/system_router.py`
- `backend/services/execution_service.py`
- `backend/graph/executor.py`
- `backend/graph/event_bus.py`
- `backend/graph/runner.py`
- `backend/graph/plan_ir.py`
- `backend/graph/nodes/planner.py`
- `backend/graph/nodes/planner_stub.py`
- `backend/graph/nodes/synthesize.py`
- `backend/graph/report_builder.py`
- `backend/report/ir.py`
- `backend/report/validator.py`
- `backend/agents/deep_search_agent.py`
- `backend/rag/layering.py`
- `backend/rag/hybrid_service.py`
- `backend/rag/observability_store.py`
- `backend/rag/observability_runtime.py`

前端：

- `frontend/src/api/client.ts`
- `frontend/src/store/useStore.ts`
- `frontend/src/store/executionStore.ts`
- `frontend/src/types/execution.ts`
- `frontend/src/components/ChatInput.tsx`
- `frontend/src/components/ChatList.tsx`
- `frontend/src/components/layout/ChatWorkspace.tsx`
- `frontend/src/components/execution/ExecutionPanel.tsx`
- `frontend/src/components/execution/StreamingResultPanel.tsx`
- `frontend/src/components/execution/AgentSummaryCards.tsx`
- `frontend/src/components/execution/AgentProgressList.tsx`
- `frontend/src/components/agent-log/AgentLogPanel.tsx`
- `frontend/src/components/thinking/*`
- `frontend/src/pages/RagInspectorPage.tsx`

测试：

- `backend/tests/test_executor.py`
- `backend/tests/test_execution_stage_events.py`
- `backend/tests/test_execution_cancel.py`
- `backend/tests/test_query_contract.py`
- `backend/tests/test_report_builder_synthesis_report.py`
- `backend/tests/test_synthesize_node.py`
- `backend/tests/test_rag_v2_service.py`
- `backend/tests/test_rag_observability_execute_plan.py`
- `frontend/src/store/executionStore.reducer.test.ts`
- `frontend/src/store/sessionLifecycle.test.ts`
- `frontend/src/components/execution/AgentProgressList.test.tsx`
- `frontend/e2e/execution-trace.spec.ts`

## 10. 验证命令

当前已有定向验证：

```powershell
python -m pytest backend\tests\test_rag_v2_service.py backend\tests\test_trace_and_session_security.py backend\tests\test_rag_observability_store.py backend\tests\test_rag_observability_system_router.py backend\tests\test_rag_observability_execute_plan.py backend\tests\test_live_tools_evidence.py -q
npm --prefix frontend run build
```

新增功能完成后必须补跑：

```powershell
python -m pytest backend\tests\test_execution_cancel.py backend\tests\test_query_contract.py backend\tests\test_execution_stage_events.py -q
npm --prefix frontend run test:unit -- src/store/executionStore.reducer.test.ts src/store/sessionLifecycle.test.ts src/components/execution/AgentProgressList.test.tsx
npm --prefix frontend run build
```

E2E：

```powershell
npm --prefix frontend run test:e2e -- execution-trace.spec.ts
```

新增验收测试必须覆盖：

- RAG 单一事实源：一次 orchestrated DeepSearch 只产生一个顶层 RAG run，service hook 不另建孤儿 run。
- 三层 provenance：每个 hit 都有 `layer/collection/source_doc_id/chunk_id/doc_fingerprint/parent_run_id`。
- memory scope：New Chat 不继承 thread memory；Clear Context 不删 user memory；Delete Memory 删除 thread memory。
- RAG 生命周期：`ws` 文档全部带 TTL；普通 chat 不自动写 `kb`；所有 `kb` 写入都有 promotion event 和 audit actor。
- legacy collection：新写入不再产生 `session:deepsearch:*`；历史 collection 只读兼容或迁移为 `ws:deepsearch:*`。
- soft-delete retrieval：被删除 source/chunk 不再被默认检索命中，恢复后可重新命中。
- layer filter：`rag_documents_v2/rag_source_docs/rag_chunks` 的 `layer` 过滤都正确，不因 collection 只存在 metadata 中而失效。
- redaction：普通用户接口不返回完整 `query_text/content_raw/chunk_text/payload_json`。
- raw trace gating：sync chat 和 stream chat 在相同权限下返回相同级别的 trace 信息。
- bounded parallel：三层 fanout 的总耗时不等于所有 collection 耗时相加，并有 per-collection timeout。
- cancel：Stop 后 200-300ms 内不再追加 token；后端最终态可查询，且不会继续推送该 run 的 token/event。
- reset：New Chat / Clear Context 后旧 ticker、selection、status、executionProgress、Agent logs、raw events 都不可见。
- deep link：`/chat?report_id=...`、RAG Inspector run/collection/layer 深链刷新、后退、分享后都能恢复同一视图。
- view mode：user/expert/dev 三种视图分别隐藏或展示正确字段，刷新后 deep link 可恢复。
- query coverage：required answer target 未回答时，报告第一屏和 API 都标记 warning。

## 11. 风险与缓解

- 风险：progress 权重设计过细，拖慢实现。
  缓解：先用阶段权重 + agent 权重，后续再调优。

- 风险：DeepSearch 并发过高触发外部限流。
  缓解：使用 bounded parallel、per-domain limit、timeout 和 fallback。

- 风险：长期 KB 被低质量网页污染。
  缓解：默认 candidate，只有可信来源和完整内容才能晋升。

- 风险：New Chat、Clear Context、Delete Memory 语义混淆。
  缓解：API、UI 文案和测试明确区分三者。

- 风险：用户态 trace 噪音过大。
  缓解：用户态只显示摘要，expert/dev 才展开细节。

- 风险：前端重复后端 collection 解析逻辑。
  缓解：后端 diagnostics API 直接返回规范字段，前端只兜底解析。

- 风险：RAG observability 双轨写入导致数据看起来“更多”，但实际不可解释。
  缓解：先做单一事实源和 parent-child span，再扩展 UI。

- 风险：soft-delete 只影响 Inspector，不影响向量检索。
  缓解：删除动作必须同步 retrieval visibility，并补回归测试。

- 风险：memory scope 不清导致新对话污染。
  缓解：把 user/thread/subject/ws/kb collection 命名和 API 语义固定下来。

- 风险：用户态看到过多诊断信息，降低信任。
  缓解：严格执行 user/expert/dev 信息边界，raw 只给 dev/internal。

- 风险：`ws` 证据被隐式长期化，污染 `kb`。
  缓解：禁止 `ws scope=persistent`，所有长期化都走 promotion gate。

- 风险：聊天 Stop 与 execution Stop 两套状态各停各的。
  缓解：统一 cancel store、`AbortSignal` 和后端 cancel API。

- 风险：深链被自动改写后无法复现问题。
  缓解：把 URL 作为 canonical state，禁止无痕抹掉关键参数。

## 12. 架构决策 ADR

Decision：采用“执行 run 为根、RAG span 为子、证据 ledger 可回放”的可观测架构；RAG 数据采用 `memory/ws/kb` 生命周期分层，DeepSearch 证据进入 working set，高质量材料再晋升 KB。

Drivers：

- 用户需要实时知道系统在做什么，而不是等待黑盒结果。
- 金融报告必须能追溯证据，不能只给模型生成文本。
- RAG 如果只是一次性缓存，就无法支持追问、复核、回放和长期知识沉淀；如果隐式长期化，又会污染 KB。
- raw trace 和原文材料有隐私风险，必须按视图和权限分层。

Alternatives considered：

- 继续让 `HybridRAGService` 自动记录所有观测：实现快，但会产生孤儿 run 和身份不一致。
- DeepSearch 结果只存内存：简单，但无法追问、回放、审计和晋升。
- 让高置信 DeepSearch 自动进 KB：短期命中率高，但会把未审核网页和报告中间态永久污染长期知识库。
- 前端继续本地估算进度：改动小，但用户会看到不可信 ETA。

Why chosen：

- 单一事实源减少解释成本，任何 UI drill-down 都能从 root run 走到 child span 和 evidence。
- working set 让“短期复用”和“长期治理”分离，避免 KB 污染。
- view mode 合同让普通用户得到清晰体验，同时保留专家和开发者排障能力。
- 显式 promotion gate 让“复用证据”和“长期记忆”成为两个动作，不靠隐式条件偷偷发生。

Consequences：

- P0 需要先改数据合同，短期会比直接堆 UI 慢。
- observability store、RAG service、execute_plan 之间必须明确 owner。
- 测试要覆盖权限、脱敏、删除、取消和 deep link，而不只是 happy path。

## 13. 开工 Definition of Ready

- 本 spec 已提交。
- 当前 RAG 三层改动的定向 pytest 通过。
- 前端 build 通过。
- `.omx/` 和临时截图不进入功能提交。
- 后续实现按 P0-A -> P0-B -> P1 -> P2 -> P3 推进，每阶段必须有测试和可回滚边界。
