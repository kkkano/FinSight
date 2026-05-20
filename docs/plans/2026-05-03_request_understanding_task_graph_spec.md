# FinSight Request Understanding Task Graph Spec

状态：执行 spec；核心聊天体验闭环已完成，剩余工作收敛到 planner/executor/synthesize 的全量多任务原生化和长期存储演进
创建日期：2026-05-03
最近校准：2026-05-11
适用范围：`/chat/supervisor`、`/chat/supervisor/stream`、Workbench 复用的 LangGraph 主链路
当前代码入口：`backend/graph/runner.py`、`backend/graph/state.py`、`backend/services/execution_service.py`

实现进度（2026-05-06）：

- 已完成：`prepare_context` 主链路合并、纯社交 `chat_respond`、`understand_request` 内 LLM conversation router、`GraphState` 新增理解层字段、URL/网页/文章 planner 工具 `fetch_url_content`、`trace/visibility=user`、前端 trace 消费、policy task 工具并集、planner stub 多任务消费、executor `task_results` 归集、多任务 conversational fallback、100-query 聊天 UX 完整验收、后端 conversation API、服务端 conversation snapshot store、会话标题/messages/PATCH、删除会话时清理 session context/report index/thread RAG collections/RAG observability runs、前后端停止生成闭环、executor/agent cooperative cancellation token。
- 保留兼容：旧 `resolve_subject / clarify / parse_operation` 仍注册，用于兼容测试和少数回退逻辑；`chat_respond` 仍在主路径上，但只处理纯社交快速通道。
- 待完成：planner/executor/synthesize 的全量多任务 PlanIR 原生化硬化、长耗时同步外部工具的更细粒度 cooperative cancel 支持、多设备/多用户级 conversation store 迁移。
- 验收证据：`docs/qa/chat-router-100-final100-current-state.md` / `.json` 记录 `tests/eval/chat_router_100.json` 的最终 current-state 运行，100 条、18 类、95 个 hard 红线用例全部通过（100 PASS / 0 REVIEW / 0 FAIL）。旧 40-query 回归证据保留在 `docs/qa/chat-ux-40-query-final40-post-context-binding.md`（39 PASS / 1 REVIEW / 0 FAIL）和 `docs/archive/qa/chat-ux-40-query-targeted-q10-render-marker-fix.md`。剩余风险为上游 LLM/工具延迟、额度、403 或不可读 URL；这些失败只能进入 diagnostics，不能作为 evidence 渲染。

## 1. 背景

当前 LangGraph 主链路已经收敛到单入口，旧 `ConversationRouter` / `SchemaToolRouter` 不再参与 `/chat/supervisor` 主路径。这一点是正确的。

真正的问题在图的前半段：用户请求理解被拆成了多个顺序节点：

```text
decide_output_mode -> chat_respond -> resolve_subject -> clarify -> parse_operation
```

这五个节点都在回答同一个问题：“用户到底想让系统做什么”。拆散之后出现了几个结构性问题：

- 闲聊、泛聊天、金融任务没有统一语义边界。
- `macro`、公司、ticker、持仓、文档 selection 的判断分散在不同文件。
- `clarify` 只看单个 `subject_type`，无法理解“部分任务可执行、部分任务缺信息”。
- `GraphState` 只有单个 `subject` 和单个 `operation`，处理不了复合请求。
- 前端无法稳定展示“系统识别了什么”，只能看到节点阶段名。
- 旧测试把节点顺序钉死，导致体验优化会变成维护流水线，而不是维护业务语义。

典型失败输入：

```text
今天天气不错，你帮我看看谷歌今天咋样，
然后美联储降息没，今天有什么大新闻会影响我的持仓吗
```

这不是一个 intent，而是一个 turn 内的多个任务：

- 社交前缀：不触发研究，只影响自然回复语气。
- 公司任务：`GOOGL` 今日表现。
- 宏观任务：美联储是否降息，需要官方/权威来源。
- 持仓任务：新闻对用户持仓影响；如果没有持仓，只澄清这一项，不能阻塞前两项。

## 2. 设计目标

### 2.1 必须实现

1. 将请求理解收敛为单一决策层，替代前半段五个意图节点。
2. 从 single intent 升级为 multi-task decision。
3. 纯社交可以规则快速短路；其余普通 chat/brief 优先交给 LLM conversation router 判断是否需要计划、直接回复或澄清。
4. LLM 不直接选工具、不直接调用 agent，只输出受 schema 约束的理解结果。
5. `policy_gate`、`planner`、`confirmation_gate`、`execute_plan`、`synthesize`、`render` 继续作为稳定执行边界。
6. `clarify` 不再是全局卡死点；只卡住缺信息的 task。
7. SSE/trace 暴露可读的 understanding 结果，前端可展示任务识别过程。
8. 前端不维护公司/ticker 字典；ticker/company/macro/portfolio 识别归后端。

### 2.2 不做

- 不把 planner/executor/RAG 一起推倒重写。
- 不让 LLM 直接生成工具 allowlist 或 agent allowlist。
- 不在前端复制后端别名词典。
- 不为每个新 operation 加一个新 graph 节点。

## 3. 最终主图

目标图约 11 个节点：

```text
START
-> build_initial_state
-> reset_turn_state
-> prepare_context
-> chat_respond (pure social only)
-> understand_request
   -> END
   -> alert_extractor -> alert_action -> END
   -> policy_gate -> planner -> confirmation_gate -> execute_plan -> synthesize -> render -> END
```

### 3.1 旧节点到新节点映射

| 当前节点 | 处理方式 | 目标职责 |
|---|---|---|
| `build_initial_state` | 保留 | 初始化 request、thread、messages、memory_context、trace |
| `reset_turn_state` | 保留 | 清理每轮临时状态 |
| `trim_history` | 合并 | 进入 `prepare_context` |
| `summarize_history` | 合并 | 进入 `prepare_context` |
| `normalize_ui_context` | 合并 | 进入 `prepare_context` |
| `decide_output_mode` | 替换 | 进入 `understand_request` |
| `chat_respond` | 替换 | 进入 `understand_request` 的 `direct` route |
| `resolve_subject` | 替换 | 进入 `understand_request.tasks[]` |
| `clarify` | 替换 | 进入 `understand_request.blocked_tasks[]` 和 route 决策 |
| `parse_operation` | 替换 | 进入 `understand_request.tasks[].operation` |
| `alert_extractor` | 保留 | 只处理 `alert_set` task 的参数抽取 |
| `alert_action` | 保留 | 保存和调度提醒 |
| `policy_gate` | 保留 | 工具/agent/budget/safety allowlist |
| `planner` | 保留并升级 | 第一阶段消费兼容投影，第二阶段消费 `tasks[]` |
| `confirmation_gate` | 保留 | HITL 执行确认 |
| `execute_plan` | 保留 | 执行 PlanIR |
| `synthesize` | 保留并升级 | 多任务结果合成 |
| `render` | 保留 | 最终 markdown/report 渲染 |

## 4. `prepare_context`

`prepare_context` 是纯确定性节点，不调用 LLM。

职责：

- 修剪历史消息。
- 必要时压缩历史。
- 规范化 UI context。
- 去重 selections。
- 规范化 legacy selection type，例如 `report -> doc`。
- 提供给 `understand_request` 的上下文摘要。

该节点不做 subject/operation 判断。

## 5. `understand_request`

`understand_request` 是新的请求理解节点，是前半段语义的唯一写入点。

### 5.0 状态契约必须先落地

实现顺序上必须先改状态契约，再改图节点。否则新节点只能继续把复合语义塞回旧的 `subject` / `operation`，问题不会真正消失。

`backend/graph/state.py` 需要新增或校准：

- `SubjectType` 增加 `macro`、`index`、`commodity`、`theme`。
- `OperationName` 使用受控枚举，至少覆盖本 spec 的 operation 列表。
- `UnderstandingTask`：单个可执行或待澄清任务。
- `BlockedTask`：缺上下文、缺权限、缺持仓、缺 selection 等不能执行的局部任务。
- `Understanding`：本轮请求理解的单一事实源。
- `ContextRef`：来源于 `thread`、`ui_selection`、`active_symbol`、`portfolio`、`document`、`explicit_user_input` 的上下文引用。
- `TimeScope`：`today`、`yesterday`、`latest`、`last_7_days`、`this_week`、`explicit_range`、`unknown`，并保存解析依据。

推荐最小结构：

```python
class Understanding(TypedDict, total=False):
    conversation_intent: Literal["casual", "general_chat", "financial_task", "mixed"]
    route: Literal["direct", "clarify", "research", "alert", "mixed"]
    social_prefix: str | None
    direct_response: str | None
    output_mode: OutputMode
    tasks: list[UnderstandingTask]
    blocked_tasks: list[BlockedTask]
    primary_task_id: str | None
    requires_planner: bool
    route_reason: list[str]
    assumptions: list[str]
    context_refs: list[ContextRef]
    request_time: str
    timezone: str
```

`reset_turn_state` 必须把 `understanding`、`tasks`、`blocked_tasks`、`context_refs`、`route`、`cancelled` 等本轮临时字段清掉；长期 conversation memory 不能在这里清理。

当前代码有一个需要先修的契约漂移：`resolve_subject.py` 已可能写入 `subject_type="macro"`，但 `GraphState.SubjectType` 还没有 `macro`。这是 Phase 1 的硬前置，不应拖到 planner 阶段。

### 5.1 三层策略

第一层：硬规则

- 空输入。
- 纯寒暄：`你好`、`hello`、`谢谢`。
- UI 显式 `output_mode`。
- UI selections。
- 后端 ticker/company/index/commodity 映射。
- 明确 alert 格式中的价格阈值。

第二层：结构化 LLM

仅在规则无法完整解释时调用，典型场景：

- 复合请求。
- 泛聊天与金融任务混合。
- 宏观传导问题。
- 指代问题，例如“它为什么跌了”。
- “帮我看看这个”这类依赖 selection / active context 的句子。

第三层：代码校验

- 校验枚举值。
- ticker 去重和标准化。
- 禁止 LLM 输出未知工具名。
- 校准低置信度 task。
- 将可执行任务和 blocked task 分开。

### 5.2 输出 schema

```json
{
  "conversation_intent": "casual | general_chat | financial_task | mixed",
  "route": "direct | clarify | research | alert | mixed",
  "social_prefix": "string | null",
  "direct_response": "string | null",
  "output_mode": "chat | brief | investment_report",
  "tasks": [
    {
      "task_id": "t1",
      "question": "string",
      "subject_type": "company | macro | portfolio | news_item | news_set | filing | research_doc | index | commodity | unknown",
      "tickers": ["GOOGL"],
      "entity_name": "Google",
      "operation": "qa | daily_brief | price | technical | fetch | summarize | analyze_impact | fact_check | news_impact | compare | alert_set | morning_brief | rebalance_check",
      "time_scope": "today | latest | historical | explicit_range | unknown",
      "needs_clarification": false,
      "clarify_question": null,
      "confidence": 0.92,
      "source": "rule | llm | mixed",
      "reason": ["matched company alias", "operation inferred from query"]
    }
  ],
  "blocked_tasks": [
    {
      "task_id": "t3",
      "question": "今天有什么大新闻会影响我的持仓吗",
      "reason": "missing_portfolio_holdings",
      "clarify_question": "我还没有你的持仓列表。要按当前关注标的筛选，还是先提供持仓？"
    }
  ],
  "primary_task_id": "t1",
  "requires_planner": true,
  "reason": ["multi-task financial request"]
}
```

### 5.3 兼容投影

第一阶段为了降低风险，`understand_request` 同时写入旧字段：

- `state["understanding"]`
- `state["tasks"]`
- `state["subject"]`
- `state["operation"]`
- `state["output_mode"]`
- `state["clarify"]`
- `state["artifacts"]["draft_markdown"]`，仅 direct/clarify route 使用

`subject` / `operation` 从 `primary_task_id` 投影而来，保证旧 `policy_gate` / `planner` 可继续工作。

第二阶段再让 `planner` 原生消费 `tasks[]`。

兼容投影规则：

- 只从 `primary_task_id` 对应的可执行 task 投影。
- 如果只有 `blocked_tasks`，不得伪造 `subject` / `operation`；走 `clarify`。
- 如果 route 为 `mixed`，可执行 task 正常投影，blocked task 保留到 `understanding.blocked_tasks`，最终 synthesis 负责提示。
- 如果 task 是 `macro` 且没有 ticker，不能投影成 `unknown company`。
- 如果用户显式给出本轮 holdings，例如“我持有 AAPL、GOOGL”，该上下文优先级高于已保存 portfolio。
- 如果用户给出 fallback，例如“不知道就按苹果处理”，不能进入全局 clarify。

兼容模式的目标不是一次性多任务全跑完，而是先保证旧 planner 不崩、旧能力不回退、新理解结果可观测。

## 6. 路由语义

| route | 条件 | 行为 |
|---|---|---|
| `direct` | 纯寒暄或普通非金融聊天 | 写 `draft_markdown`，END |
| `clarify` | 没有任何可执行任务，且缺关键信息 | 写澄清问题，END |
| `research` | 至少一个可执行研究任务 | 进入 `policy_gate` |
| `alert` | 单一或主任务是提醒设置 | 进入 `alert_extractor` |
| `mixed` | 有可执行任务，也有 blocked task | 先执行可执行任务，最终合成时提示 blocked task |

原则：**澄清不能阻塞整个 turn，只能阻塞缺信息的 task。**

## 7. Planner 升级

### 7.1 第一阶段：兼容模式

`planner` 继续读旧字段：

- `subject`
- `operation`
- `output_mode`
- `policy`

但 trace 中要记录：

- `understanding.primary_task_id`
- `understanding.task_count`
- `understanding.blocked_task_count`

### 7.2 第二阶段：多任务 PlanIR

PlanIR 增加 `tasks`：

```json
{
  "goal": "multi-task financial brief",
  "tasks": [
    {
      "task_id": "t1",
      "steps": [
        {
          "id": "t1_s1",
          "kind": "tool",
          "name": "get_stock_price",
          "inputs": {"ticker": "GOOGL"},
          "parallel_group": "g1"
        }
      ]
    }
  ],
  "synthesis": {
    "style": "structured",
    "sections": ["谷歌今日表现", "美联储事实核查", "持仓影响待确认"]
  }
}
```

## 8. Policy Gate 边界

`policy_gate` 不理解自然语言。

输入应改为：

- `understanding.tasks[]`
- `output_mode`
- `ui_context`
- 用户权限 / budget / agent preferences

输出仍是：

- `allowed_tools`
- `allowed_agents`
- `budget`
- `agent_selection`
- `tool_schemas`
- `agent_schemas`

LLM 不能越过 policy gate 选择工具。

## 8.1 RAG 与记忆边界

RAG 不能继续被当成 deep search 的一次性缓存来理解。系统需要四层明确边界：

| 层 | 生命周期 | 写入来源 | 读取场景 | 删除/过期 |
|---|---|---|---|---|
| `run_cache` | 单次 run | 工具、搜索、agent 中间结果 | 同一次回答内去重和合成 | run 结束后可丢弃或短 TTL |
| `conversation_memory` | 单个会话 | 用户明确表达、系统对话摘要、已确认上下文 | 指代解析、连续追问、上一轮风险点 | 删除会话时删除或标记不可用 |
| `workspace_kb` | 工作区/文档级 | 上传 PDF、报告、用户保存的研究材料 | 文档问答、跨会话材料复用 | 用户删除文档时删除 |
| `user_profile/portfolio` | 用户级 | 用户保存的持仓、偏好、风险约束 | 组合影响、调仓建议、默认偏好 | 用户显式编辑或删除 |

执行约束：

- deep search 产生的网页证据默认只进入 `run_cache`，不能自动污染长期 memory。
- 只有用户明确保存、系统高置信摘要并通过策略允许、或文档上传索引，才可进入长期层。
- RAG 命中必须带 `layer`、`collection`、`source_id`、`score`、`freshness`、`permission_scope`。
- synthesis 引用 RAG 时要区分“本轮检索证据”和“历史记忆”，避免把旧结论当新事实。
- 删除会话时，必须清理或隔离对应 `conversation_memory`，不能让旧 ticker/风险点泄露到新会话。

首阶段 MVP：

- 保留现有 deep search 缓存作为 `run_cache`。
- 为 conversation/thread 增加最小 memory scope 标记。
- trace 中展示 RAG 命中层级和数量。
- 不做复杂向量库迁移，避免把请求理解重构和 RAG 存储重构绑死。

## 9. 前端契约

前端只做交互状态，不做金融语义识别。

前端允许做：

- 空输入禁用。
- 正在流式输出时禁用提交或显示停止按钮。
- 根据用户选择传 `output_mode`。
- 传 `session_id`、`active_symbol`、`selections`、`portfolio context`。
- 展示 `understanding.tasks[]`。

前端禁止做：

- 维护公司名到 ticker 的字典。
- 判断 macro/company/portfolio。
- 根据关键词决定后端工具或 agent。

### 9.0 会话体验契约

会话体验要接近 ChatGPT 的基本模型：新建、切换、删除、保留历史、上下文隔离。

MVP 允许前端 localStorage 保存会话列表和消息；后端会话 API 已落地最小生命周期：

- `GET /api/conversations`：列出后端已触达的 session context 摘要。
- `POST /api/conversations`：新建/触达会话并返回 `session_id/thread_id`。
- `GET /api/conversations/{id}`：加载会话摘要和当前后端 context。
- `DELETE /api/conversations/{id}`：删除会话，并清理 session context、report index、thread RAG collection 和 RAG observability runs。
- `PATCH /api/conversations/{id}`：改标题、置顶、归档，以及服务端 messages snapshot 更新。

当前边界：前端 localStorage 仍是当前浏览器运行态的消息真相源；后端 `conversation_store` 保存轻量 messages/title/pinned/archive snapshot，用于 list/get/patch/delete 和后端会话恢复。下一步若要支持多设备实时同步，需要把该 JSON store 迁移到数据库并补用户权限隔离。

行为要求：

- 新建会话必须生成新的 `session_id/thread_id`，清空当前 active context、pending trace、agent 状态和未完成流。
- 切换旧会话必须恢复该会话消息和会话级上下文，但不能恢复上一会话的临时 run 状态。
- 删除当前会话后要进入最近一个会话；没有剩余会话时创建空白会话。
- 删除非当前会话不能影响当前流式 run。
- 正在生成时切换/删除会话，前端必须先取消当前 run 或明确提示状态；不能让 token 写入错误会话。
- 会话标题优先用首条用户消息生成摘要，不能永远显示固定“新对话”。

需要后端配合的边界：

- `thread_id` 是图 checkpoint、conversation memory、trace run 的共同会话键。
- `run_id` 是单次执行键，不能代替 `thread_id`。
- 新会话默认不继承旧会话 ticker/selection，除非用户显式选择全局 portfolio/profile。

### 9.1 用户可见思考过程设计

前端需要展示更具体的“可观测推理过程”，但不要展示模型隐藏思维链。用户应该看到系统基于哪些可验证信号做了什么决定，而不是看到一组写死的“正在分析、正在搜索、正在生成”假步骤。

核心原则：

- 后端事件驱动：所有步骤来自 SSE/trace 事件，前端只负责渲染，不伪造进度。
- 可折叠：默认展示 1 行当前动作，用户展开后看到结构化详情。
- 可解释：每个关键步骤都回答“识别了什么、为什么这么走、下一步查什么、哪些信息缺失”。
- 可验证：搜索、工具、agent、RAG 命中都显示真实 query/source/count/status。
- 可控：流式期间提供停止按钮；停止后保留已完成步骤和取消原因。
- 不泄露隐藏 chain-of-thought：展示的是 `reason_summary`、`route_reason`、`evidence_summary`，不是原始模型逐 token 推理。

建议 UI 结构：

```text
Assistant Message
├─ Process Strip（默认折叠）
│  ├─ 理解：识别 4 个任务，1 个待补充
│  ├─ 计划：准备查询价格、新闻、宏观事件、组合影响
│  ├─ 检索：3 个搜索 / 5 个工具 / 2 个 RAG 命中
│  ├─ Agent：Price、News、Macro、Risk 已完成
│  └─ 合成：发现 1 个冲突，已在回答中标注
└─ Final Answer
```

展开详情用分组 timeline，不做营销式大卡片：

| 组 | 展示内容 | 示例 |
|---|---|---|
| `understanding` | task decomposition、route、blocked task、assumptions | “谷歌=GOOGL；微软=MSFT；持仓影响需要持仓数据” |
| `planning` | plan groups、预算、禁用项、output mode | “brief 模式：跳过 deep_search，优先价格+新闻” |
| `retrieval` | search query、provider、live/cache、result_count | `search: GOOGL news yesterday` |
| `tool` | tool name、args 摘要、status、latency | `get_stock_price(GOOGL)` |
| `agent` | agent name、目标、evidence_count、confidence | “Macro agent 查找 FOMC/Fed 官方信息” |
| `synthesis` | evidence merge、conflicts、caveats | “新闻情绪与盘中涨跌不一致，标注为短期冲突” |

禁止：

- 前端写死固定 5 步进度，不管后端是否真的执行。
- 显示假百分比。
- 把所有 trace dump 给用户，造成噪音。
- 用“AI 正在深度思考”这种不可验证文案替代真实事件。
- 在 brief 模式下展示和 deep search 一样重的过程 UI。

### 9.2 Deep / Brief 控件契约

Deep / Brief 的可点击状态不能依赖前端金融词典。

前端只根据以下条件启用：

- 输入非空，或存在可提交的 selection / active context。
- 当前没有进行中的提交，或当前 UI 显示的是“停止”。
- 用户权限允许该 output mode。

后端负责判断：

- “谷歌 / 微软 / 苹果”映射成什么 ticker。
- 没有 ticker 的 macro 问题是否可执行。
- deep search 是否必要、是否被用户禁用、是否因 brief 模式跳过。
- 多任务请求中哪些 task 可以执行、哪些需要澄清。

如果后端判定 brief/deep 不适合，应返回 user-visible trace 或 answer caveat，而不是让前端提前禁用。

## 10. SSE 与可观测性

新增用户可见事件：

```json
{
  "type": "thinking",
  "stage": "langgraph_understand_request_done",
  "userMessage": "已识别 3 个任务，其中 1 个需要补充信息",
  "data": {
    "route": "mixed",
    "task_count": 3,
    "blocked_task_count": 1,
    "tasks": [
      {"task_id": "t1", "subject_type": "company", "operation": "daily_brief", "tickers": ["GOOGL"]},
      {"task_id": "t2", "subject_type": "macro", "operation": "fact_check"},
      {"task_id": "t3", "subject_type": "portfolio", "operation": "news_impact", "blocked": true}
    ]
  }
}
```

前端展示建议：

- ThinkingBubble 显示简短语义结果。
- Agent log 显示完整 task 列表和 route reason。
- 用户可以看到“系统不是忘了持仓，而是缺持仓数据”。

### 10.1 用户可见 Trace Event

新增统一事件载荷，供 `ThinkingBubble`、执行 timeline、agent log 共用：

```json
{
  "type": "trace",
  "visibility": "user",
  "stage": "understanding | planning | retrieval | tool | agent | synthesis",
  "status": "started | completed | skipped | blocked | failed | cancelled",
  "title": "识别请求",
  "summary": "识别 4 个任务，其中持仓影响需要补充持仓数据",
  "data": {
    "task_ids": ["t1", "t2", "t3", "t4"],
    "route_reason": ["matched company aliases", "portfolio data missing"],
    "assumptions": ["昨天按交易日解析"],
    "source_kind": "rule | llm | tool | rag | cache | web",
    "latency_ms": 124
  }
}
```

各阶段最低字段：

| stage | 必须字段 |
|---|---|
| `understanding` | `tasks[]`、`blocked_tasks[]`、`route_reason[]`、`assumptions[]` |
| `planning` | `plan_groups[]`、`allowed_tools[]`、`skipped_tools[]`、`budget` |
| `retrieval` | `query`、`provider`、`result_count`、`cache_status` |
| `tool` | `tool_name`、`args_summary`、`status`、`latency_ms` |
| `agent` | `agent_name`、`goal`、`evidence_count`、`confidence` |
| `synthesis` | `sections[]`、`conflicts[]`、`caveats[]` |

前端渲染规则：

- compact view 只显示 `title + summary + status icon`。
- detail view 显示分组 timeline 和关键字段。
- 同一个 `run_id + stage + task_id` 的事件应合并更新，避免刷屏。
- `visibility != "user"` 的内部 debug 事件只进入开发面板，不进入普通用户视图。
- cancelled 事件必须显示“用户已停止”或“后端已取消”，不能伪装成失败。

### 10.2 SSE 过滤与兼容规则

当前 `execution_service` 存在 `trace_raw_enabled=false` 时过滤 raw trace 的逻辑。新增 `type="trace"` 事件后必须明确：

- `visibility="user"` 的 `trace` 事件永远不被 raw trace 过滤。
- `visibility="debug"` 或未声明 visibility 的内部事件，在 raw trace 关闭时进入过滤。
- 旧 `type="thinking"` 事件可以保留，但新 Process Strip 以 `type="trace"` 为主。
- 前端 `parseSSEStream` 必须显式支持 `type="trace"`，并按 `stage/status/task_id` 合并到 timeline。
- 同一 run 的事件必须带 `session_id` 和 `run_id`。
- 事件 payload 必须 JSON 可序列化，时间统一 ISO 8601。
- provider、query、tool args 只展示摘要，不能泄露密钥、完整认证头或用户隐私字段。

### 10.3 停止生成与取消链路

“停止”不是前端假停止，必须形成端到端取消语义。

要求：

- 前端点击停止后调用 `AbortController.abort()`，并把当前 run 标记为 `cancelling`。
- 后端 streaming generator 感知断开后取消 producer task。
- graph runner 设置 context-scoped cancellation token；executor 和 agent adapter 已检查 token 或处理 `asyncio.CancelledError`。同步外部工具若不能 cooperative cancel，按 best-effort 取消展示并等待超时收口。
- 被取消的 run 必须发出或记录 `trace/status=cancelled`，包含已完成阶段和取消时间。
- 已经产出的 token 和 trace 保留在当前会话，不回滚。
- 取消后用户可以继续追问；下一轮 `reset_turn_state` 不能继承上轮 cancelled 的临时状态。
- 若某个外部 API 无法中断，后端至少要停止继续合成，并在 trace 里记录 `best_effort_cancel`。

UI 文案：

- 普通停止：`已停止生成，保留已完成的结果。`
- 后端确认取消：`后端已取消本次运行。`
- 超时或工具不可中断：`已停止展示，部分后台调用可能已超时结束。`

## 11. 回归测试矩阵

| Query | 预期 |
|---|---|
| `你好` | `direct/casual` |
| `谢谢` | `direct/casual` |
| `今天心情不错` | `direct/general_chat` |
| `你好，我想问股票` | `clarify` 或 `research`，不能 casual 直出 |
| `苹果怎么样` | `company/AAPL/qa` |
| `Apple 怎么样` | `company/AAPL/qa` |
| `谷歌AI业务进展如何` | `company/GOOGL/qa` |
| `GOOGL AI业务进展如何` | `company/GOOGL/qa` |
| `美联储利率路径对大型科技股估值有什么影响` | `macro/analyze_impact` |
| `降息对纳指有什么影响` | `macro or index/analyze_impact` |
| `美联储今天降息了吗` | `macro/fact_check/today` |
| `比较微软和苹果` | `company/[MSFT,AAPL]/compare` |
| `帮我做特斯拉深度研究` | `company/TSLA/investment_report` |
| `它为什么跌了` + active `AAPL` | `company/AAPL/qa` |
| `它为什么跌了` + no active context | `clarify/followup_without_context` |
| `帮我看看这个` + news selection | `news_item/qa or summarize` |
| `帮我看看这个` + no selection | `clarify/missing_context` |
| `TSLA 跌破 200 提醒我` | `alert/alert_set` |
| `今天有什么大新闻影响我的持仓吗` + portfolio exists | `portfolio/news_impact` |
| `今天有什么大新闻影响我的持仓吗` + no portfolio | `blocked_task/missing_portfolio_holdings` |
| `今天天气不错，你帮我看看谷歌今天咋样，然后美联储降息没，今天有什么大新闻会影响我的持仓吗` | `mixed`，至少 company + macro 可执行，portfolio 可阻塞 |

### 11.1 复杂 Query Golden Set

这些 query 是后续 `backend/tests/test_understand_request.py` 的表驱动 golden cases。测试目标不是判断最终回答文案，而是判断请求理解层是否稳定拆任务、保留上下文、区分可执行任务与 blocked task。所有 `今天`、`昨天`、`最近` 必须基于请求时间解析，不能写死自然日。

| ID | Query | 预期拆解 | 失败判定 |
|---|---|---|---|
| C01 | `你好，今天天气不错，帮我看看谷歌昨天涨了多少，谷歌有什么新闻，然后微软呢？微软的新闻和涨幅如何？最近有没有发生什么大事影响我的几只股票？我的调仓要变动吗？` | `mixed`；`social_prefix` 保留；`GOOGL/price/yesterday` + `GOOGL/fetch/latest_news` + `MSFT/price/yesterday` + `MSFT/fetch/latest_news`；portfolio `news_impact` 和 `rebalance_check` 视持仓是否存在执行或进入 `blocked_tasks` | 只识别谷歌、忘记微软、把天气当天气查询、因缺持仓阻塞全部任务 |
| C02 | `早，昨天苹果为什么跌了？微软也是同样原因吗？如果不是，分别列出主要原因。` | `mixed/research`；`AAPL/price+news_impact/yesterday`；`MSFT/price+news_impact/yesterday`；第二句“同样原因”指向 AAPL 但必须生成 MSFT 独立任务 | 把“也是”误解成只回答 AAPL，或只做 compare 不查各自原因 |
| C03 | `美联储这周降息概率变了吗？这对QQQ、苹果、微软和我的科技股仓位有什么影响？` | `macro/fact_check/explicit_range(this_week)`；`index/QQQ/analyze_impact`；`company/[AAPL,MSFT]/analyze_impact`；portfolio impact 若无持仓则局部 blocked | 要求 ticker 后才能回答 macro，或把 QQQ 当公司 |
| C04 | `先别做长报告，30秒告诉我谷歌和微软今天谁更强，新闻、涨跌幅、风险点各一句。` | `output_mode=brief`；`compare/[GOOGL,MSFT]`；每个 ticker 有 price/news/risk 子需求；工具预算低 | 进入 investment_report，或只比较价格不处理新闻和风险 |
| C05 | `做深度研究：NVDA，但只看最近一周新闻、财报和竞争格局，最后给我买入/观望/卖出的理由。` | `output_mode=investment_report`；`company/NVDA`；time_scope explicit range `last_7_days`；constraints 包含 news/filing/competitive landscape；结论格式偏好保留 | 忽略“最近一周”，或当成普通聊天短答 |
| C06 | `我持有AAPL、GOOGL、MSFT，现在CPI超预期，对我的组合影响最大的是哪一个？需要怎么调仓？` | 显式 holdings 写入 task context；`macro/analyze_impact(CPI)`；`portfolio/news_impact or macro_impact`；`portfolio/rebalance_check` 可执行 | 因没有已保存 portfolio 而澄清全部，或丢掉用户本轮给出的持仓 |
| C07 | `看一下这条新闻会不会影响TSLA和我的组合，顺便如果TSLA跌破180提醒我。` + news selection | `news_item/analyze_impact`；`company/TSLA/news_impact`；portfolio impact 可执行或局部 blocked；`alert_set/TSLA/below/180` 走 alert path 或 mixed alert handling | 因 alert 把研究任务吞掉，或无 selection 时不澄清新闻上下文 |
| C08 | `我昨天问的那家公司今天有什么更新？如果你不知道我说的是谁，就按苹果处理。` | 有 thread subject 时解析为该 subject；无 thread subject 时 fallback `AAPL`；operation `fetch/latest_news` 或 `daily_brief/today` | 无上下文时直接澄清，忽略用户提供的 fallback |
| C09 | `这个PDF里的公司和谷歌相比怎么样？重点看收入增长和估值，不要泛泛而谈。` + doc selection | `research_doc/extract_metrics`；`company/GOOGL/extract_metrics`；`compare`；constraints 包含 revenue growth + valuation | 前端或后端要求用户再输入 PDF 公司名，或只总结 PDF 不比较谷歌 |
| C10 | `最近有什么大事影响半导体？NVDA、AMD、TSM分别怎么看，给表格，不要长篇。` | `theme/semiconductor/news_impact/latest`；`company/[NVDA,AMD,TSM]/daily_brief or analyze_impact`；format preference table + brief | 只识别第一个 ticker，或把 TSM 当美股以外 unsupported |
| C11 | `谷歌AI capex 会不会拖累利润率？微软和Meta有没有类似问题？顺便看一下最近市场怎么定价。` | `company/GOOGL/analyze_impact(capex -> margin)`；`company/[MSFT,META]/compare or analyze_impact`；market pricing 触发 price/news/valuation evidence | 只输出结构化摘要不回答问题，或把 Meta 漏掉 |
| C12 | `不用deep search，快速看下GOOGL和MSFT今天涨跌、新闻、有没有需要我马上注意的风险。` | `output_mode=brief`；planner constraint `no_deep_search`；`company/[GOOGL,MSFT]/price+news+risk`；可使用轻量工具 | 仍调用 deep search，或因为多 ticker 强制进入长报告 |
| C13 | `帮我看看苹果今天咋样，然后把刚才说的那个风险也考虑进去。` + prior risk in thread | `company/AAPL/daily_brief/today`；thread memory 中提取 prior risk 作为 constraint；无 prior risk 时只对该 constraint 局部降级，不阻塞 AAPL | 因“刚才那个风险”缺失而完全澄清，或忘记 AAPL |
| C14 | `如果今天纳指继续跌，AAPL、MSFT、NVDA哪个对我组合拖累最大？我没有组合的话就按等权假设。` | `index/NDX or QQQ/scenario`；`company/[AAPL,MSFT,NVDA]/analyze_impact`；portfolio impact，若无 holdings 使用 equal-weight assumption 而不是 blocked | 缺持仓时澄清，忽略用户给出的等权 fallback |
| C15 | `请先确认美联储今天有没有公告，再判断这会不会影响我的持仓；如果没持仓，就只讲对大型科技股估值的影响。` | `macro/fact_check/today` 必须先执行；portfolio impact 有持仓则执行；无持仓 fallback 为 `macro/analyze_impact(large_tech_valuation)` | 因无持仓直接结束，或跳过 fact_check 直接泛谈 |

### 11.2 测试与评估门槛

请求理解重构必须先有可重复评估，不能靠手感。

后端单元测试至少覆盖：

- pure casual 不触发金融任务。
- company alias、ticker、中文公司名都由后端解析。
- macro 无 ticker 也可形成可执行任务。
- selection / active_symbol / thread subject 的优先级。
- explicit holdings 和 fallback assumption。
- mixed route 中可执行 task 与 blocked task 分离。
- `reset_turn_state` 清理新字段，不污染下一轮。
- `SubjectType`、`OperationName`、`TimeScope` 枚举校验。

契约测试至少覆盖：

- `understand_request` 输出 JSON schema 校验。
- 兼容投影到旧 `subject` / `operation`。
- `trace/visibility=user` 在 raw trace 关闭时仍能到前端。
- `trace/visibility=debug` 在 raw trace 关闭时不进普通用户视图。
- cancellation 事件状态。

前端测试至少覆盖：

- `parseSSEStream` 识别 `type="trace"`。
- Process Strip 只展示收到的真实 stage。
- 没有 retrieval/tool 事件时不显示假检索/假工具步骤。
- 新建/切换/删除会话不会串消息。
- 停止生成后保留已收到 token 和 trace。
- 报告按钮启用逻辑不依赖 ticker 字典；普通发送不暴露 Deep/Brief 主切换。

Playwright 手测场景至少覆盖：

- C01、C03、C06、C09、C12、C15。
- 中文公司名输入：`谷歌`、`微软`、`苹果`。
- 无 ticker 宏观问题：`美联储利率路径对大型科技股估值有什么影响`。
- 混合闲聊 + 金融任务 + 持仓任务。
- 运行中停止、随后继续追问。
- 新建会话后旧 ticker 不泄露；切回旧会话后历史可用。

LLM-as-judge 可以作为辅助质量评估，但不能作为唯一 gate。合并前的硬 gate 是 schema、golden case、契约测试和 Playwright。

## 12. 执行前置清单

开工前必须确认以下内容已经写入 issue/task 或实现计划：

- 状态契约：新增 `Understanding`、`UnderstandingTask`、`BlockedTask`、`ContextRef`、`TimeScope`。
- 类型漂移：修复 `SubjectType` 缺 `macro/index/commodity/theme`。
- 测试先行：创建 `backend/tests/test_understand_request.py`，先录入 golden cases。
- 兼容投影：定义 `primary_task -> subject/operation` 的投影函数。
- 图接入：先接入 `understand_request`，不要先删除旧文件。
- Trace：新增 `type="trace"`、`visibility=user/debug`、stage/status 字段。
- 前端解析：`parseSSEStream` 支持 trace event，execution store 支持按 stage 合并。
- Process Strip：只渲染真实 trace，不渲染假进度。
- 会话：MVP localStorage 与后端 `/api/conversations` 生命周期 API 的边界已确认。
- RAG：确认 `run_cache/conversation_memory/workspace_kb/user_profile` 四层边界。
- 取消：确认前后端 cancellation 最小闭环。
- 文档：实现完成后同步 README、架构文档、事件契约和 docs index。

明确禁止的实现路径：

- 不先重写 planner/executor。
- 不在前端补 ticker/company 字典。
- 不把 deep search 缓存直接升级成长期记忆。
- 不展示隐藏 chain-of-thought。
- 不用节点顺序测试替代语义测试。
- 不为了支持 operation 增加更多前置 graph 节点。

## 13. 需要用户决策的事项

以下事项不是代码能自动替你决定的产品边界，需要你拍板。默认建议已给出：

| 决策项 | 推荐默认 | 影响 |
|---|---|---|
| 会话持久化 | 当前是前端 localStorage 运行态 + 后端 `conversation_store` messages/title/PATCH snapshot | MVP 已能新建/切换/删除并隔离上下文；多设备同步仍需迁移到数据库 |
| 删除会话是否删除 conversation memory | 删除或隔离该会话 memory | 更符合用户直觉，避免旧上下文泄露 |
| 报告模式触发 | 用户显式点击报告按钮或传 `investment_report` 才触发 | 避免普通聊天被套报告模板 |
| 普通 chat 是否允许短计划/工具 | 允许，由 LLM router 和 policy/planner 决定 | 保持对话感，同时不牺牲需要证据的问题 |
| RAG 长期记忆写入 | 默认只保存用户明确保存/上传/确认的信息 | 避免把临时网页结论污染长期记忆 |
| 用户可见 trace 详细度 | 默认 compact，一键展开详情 | 普通用户不被噪音淹没，高级用户可观测 |
| 停止生成后的结果 | 保留 partial answer 和 trace | 符合聊天产品直觉 |
| 宏观问题无 ticker | 允许执行 macro task | 解决“美联储利率路径...”这类问题 |
| 持仓缺失 | 局部 blocked，其他任务继续 | 避免因为 portfolio 缺失阻塞全部回答 |
| 投资建议措辞 | 输出分析与风险，不做确定性买卖承诺 | 降低合规和误导风险 |

如果你不特别改，后续实现就按“推荐默认”执行。

## 14. 迁移计划

### Phase 0：文档与契约

- 新增本 spec。
- 更新 README / DOCS_INDEX / docs 协作规则。
- 标记旧 routing 文档为历史参考。

### Phase 1：类型与测试

- `GraphState` 增加 `understanding`、`tasks`。
- `SubjectType` 增加 `macro`、`index`、`commodity`、`theme`。
- 增加 `Understanding`、`UnderstandingTask`、`BlockedTask`、`ContextRef`、`TimeScope`。
- 增加 `OperationName` 枚举或等价受控字面量。
- 新增 `backend/tests/test_understand_request.py`。
- 将复杂 Query Golden Set 转为表驱动测试，至少断言 route、task count、tickers、blocked_tasks、time_scope、output_mode、planner constraints。
- 将旧 `test_greeting_shortcircuit` 改成 route 断言，而不是节点顺序断言。

### Phase 2：兼容实现

- 新增 `backend/graph/nodes/understand_request.py`。
- 保留旧节点文件，但主图只接入 `understand_request`。
- `understand_request` 投影旧 `subject` / `operation`。
- 旧节点测试迁移到新节点测试。

### Phase 3：图收敛

- 移除主图中的：
  - `decide_output_mode`
  - `chat_respond`
  - `resolve_subject`
  - `clarify`
  - `parse_operation`
- 将 `trim_history/summarize_history/normalize_ui_context` 合并为 `prepare_context`。

### Phase 4：Planner 原生多任务

- `planner` 消费 `tasks[]`。
- `execute_plan` 按 task 归集 evidence。
- `synthesize` 输出多任务分节回答。

### Phase 5：前端可观测 UX

- 展示 task decomposition。
- 实现可折叠 Process Strip：理解 / 计划 / 检索 / Agent / 合成。
- 由 SSE `trace` 事件驱动前端过程展示，禁止前端写死假步骤或假百分比。
- `parseSSEStream` 支持 `type="trace"`，普通用户视图只消费 `visibility=user`。
- 展开详情能看到 search query、tool args 摘要、provider、result_count、agent evidence_count、blocked task reason。
- 普通用户视图只展示 `visibility=user` 事件，内部 debug trace 放开发面板。
- “停止生成”保留 AbortController，并补后端 run cancellation。
- 报告按钮只传 `output_mode=investment_report`，不判断 ticker；普通发送不注入“深度/简报”关键词。

### Phase 6：RAG、会话、取消闭环

- RAG 分层标记 `run_cache/conversation_memory/workspace_kb/user_profile`。
- 已完成 MVP：删除会话时清理 session context、report index、thread memory/working-set collections，并按 collection 批量软删除 RAG observability runs。
- 已完成 MVP：新建会话生成独立 `session_id/thread_id`，前端切换/删除不串消息。
- 已完成 MVP：停止生成形成前端 abort、后端 `CancelledError` trace/pipeline event、executor/agent cancellation token、前端 cancelled thinking step 的闭环。
- 已完成 MVP：服务端 conversation snapshot store 支持 messages/title/pinned/archive/PATCH。
- 待增强：同步外部工具的 cooperative cancel、数据库级 conversation store、多设备同步和用户权限隔离。

### Phase 7：文档收口

实现完成后必须同步：

- `README.md`
- `frontend/README.md`
- `docs/DOCS_INDEX.md`
- `docs/01_ARCHITECTURE.md`
- `docs/06a_LANGGRAPH_DESIGN_SPEC.md`
- `docs/06b_LANGGRAPH_CHANGELOG.md`
- `docs/LANGGRAPH_FLOW.md`
- `docs/LANGGRAPH_PIPELINE_DEEP_DIVE.md`
- `docs/execution-event-contract.md`
- `docs/AGENTS.md`

旧文档处理：

- `docs/ROUTING_ARCHITECTURE_STANDARD.md` 已归档到 `docs/archive/2026-05-agent-observability-cleanup/`。
- 旧 `ConversationRouter` / `SchemaRouter` 相关说明进入 `docs/archive/<yyyy-mm-topic>/`。
- 已完成 todolist、临时报表、旧 roadmap 只保留在 archive。

## 15. 验收标准

后端：

- `python -m pytest backend/tests/test_understand_request.py -q`
- `python -m pytest backend/tests/test_langgraph_skeleton.py backend/tests/test_policy_gate.py backend/tests/test_tool_manifest.py -q`
- 复合请求不再被压成单一 subject。
- macro 无 ticker 请求不触发“先选定分析对象”。
- 泛聊天不触发金融 clarify。
- mixed route 中 blocked task 不阻塞可执行 task。
- `trace/visibility=user` 在 raw trace 关闭时仍能通过 SSE 到达前端。
- 停止生成后 run 状态为 cancelled 或 best_effort_cancelled。
- 删除会话后旧 conversation memory 不参与新会话理解。

前端：

- `npm run build`
- `npx vitest run src`
- Playwright 验证：
  - 新建/切换/删除会话。
  - 报告按钮只受 actionable input 和 output mode 影响。
  - 复合请求能显示多个理解 task。
  - 展开 Process Strip 后能看到真实 trace：task decomposition、search query、tool/agent 状态、blocked task reason。
  - 过程 UI 来自 SSE 事件；模拟后端不发 retrieval/tool 事件时，前端不能显示对应假步骤。
  - 用户可停止流式输出。
  - 新建会话后旧 ticker/selection 不泄露；切回旧会话后历史消息和上下文可恢复。
  - 输入 `谷歌`、`微软`、`苹果` 时报告按钮可提交，但前端没有公司字典。
  - 输入无 ticker 宏观问题时可提交，后端返回 macro task。

文档：

- README 不再把旧 18 节点称为最终架构。
- DOCS_INDEX 明确当前事实源、目标 spec、历史文档边界。
- 所有被归档文档在 archive README 记录原路径和原因。

## 16. 2026-05-03 验证记录

本轮实现完成后的硬 gate：

```text
pytest -q backend/tests/test_understand_request.py backend/tests/test_langgraph_skeleton.py backend/tests/test_graph_node_order.py backend/tests/test_clarify_node.py backend/tests/test_p0_unit.py backend/tests/test_resolve_subject.py backend/tests/test_financial_intent.py backend/tests/test_langgraph_api_stub.py backend/tests/test_policy_gate.py backend/tests/test_policy_planner_query_regression.py backend/tests/test_planner_prompt.py backend/tests/test_planner_node.py
182 passed

npm run test:unit --prefix frontend -- --run src/api/client.sse.test.ts src/store/executionStore.reducer.test.ts src/store/useStore.conversation.test.ts
3 files / 15 tests passed

pytest -q backend/tests/test_conversation_router.py backend/tests/test_report_index_delete_session.py backend/tests/test_execution_cancel.py backend/tests/test_plan_ir_validation.py backend/tests/test_executor.py backend/tests/test_understand_request.py backend/tests/test_live_tools_evidence.py
37 passed

pytest -q backend/tests/test_rag_observability_store.py backend/tests/test_conversation_router.py backend/tests/test_execution_cancel.py backend/tests/test_report_index_delete_session.py
15 passed

pytest -q backend/tests/test_conversation_router.py backend/tests/test_execution_cancel.py backend/tests/test_execution_stage_events.py backend/tests/test_executor.py
19 passed

pytest -q backend/tests/test_conversation_router.py
3 passed

npm run test:unit --prefix frontend -- --run src/store/useStore.conversation.test.ts src/api/client.sse.test.ts
2 files / 9 tests passed

npm run build --prefix frontend
build passed

cd frontend
npx playwright test e2e/request-understanding-chat.spec.ts
4 passed

python scripts/request_understanding_probe.py --output docs/reports/2026-05-03_request_understanding_query_results.md
20 query matrix regenerated
```

验证报告：

- `docs/reports/2026-05-03_request_understanding_query_results.md`
- `docs/reports/2026-05-03_playwright_chat_smoke.md`

## 17. 后续实施顺序

当前已经满足“像 ChatGPT 一样可新建/切换/删除会话、可停止、可看见真实思考/检索/执行过程、无 ticker 宏观问题可提交、前端不维护公司字典”的核心体验闭环。后续不应继续增加前置意图节点，而应在现有 task graph 上硬化。

建议执行顺序：

1. Planner 原生多任务硬化：LLM planner prompt/schema 直接消费 `tasks[]`、`blocked_tasks[]`、`context_refs[]`，并为每个 step 写入 `task_id/task_ids`；继续保留 stub fallback。
2. Executor/Synthesize 结果归因：所有 step result、evidence、RAG hit、agent summary 都按 `task_id` 回填；合成阶段优先按 task 分节，再做跨任务综合结论。
3. Trace 细化：retrieval/tool/agent 事件必须来自真实后端事件；前端 Process Strip 只负责折叠、分组、展示，不生成假搜索或假进度。
4. Conversation store 迁移：从 JSON snapshot 迁移到数据库，加入用户级权限、分页、全文搜索和多设备同步。
5. 外部工具 cancellation：对支持 async cancel 的 HTTP/LLM/tool wrapper 做 cooperative cancel；不支持的同步调用记录 `cancelled_after_inflight`，并丢弃取消后的后续事件。
6. RAG 晋升策略：DeepSearch working set 继续短期复用；只有用户明确保存、上传或系统通过规则确认的稳定资料才能晋升到长期 KB。

架构红线：

- 不再新增 `macro_router`、`company_router`、`chat_router` 这类前置分流节点。
- 不把别名/ticker 识别搬到前端。
- 不用长期 RAG 存储临时网页搜索结论。
- 不展示隐藏 chain-of-thought；用户可见思考过程只展示结构化任务、计划、真实工具/检索/agent 事件和可解释摘要。
