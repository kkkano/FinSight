# FinSight Request Understanding Task Graph Spec

状态：目标架构 spec，尚未完全实现
创建日期：2026-05-03
适用范围：`/chat/supervisor`、`/chat/supervisor/stream`、Workbench 复用的 LangGraph 主链路
当前代码入口：`backend/graph/runner.py`、`backend/graph/state.py`、`backend/services/execution_service.py`

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
3. 规则优先处理确定事实，结构化 LLM 只处理语义复杂和复合请求。
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

## 12. 迁移计划

### Phase 0：文档与契约

- 新增本 spec。
- 更新 README / DOCS_INDEX / docs 协作规则。
- 标记旧 routing 文档为历史参考。

### Phase 1：类型与测试

- `GraphState` 增加 `understanding`、`tasks`。
- `SubjectType` 增加 `macro`、`index`、`commodity`。
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
- 展开详情能看到 search query、tool args 摘要、provider、result_count、agent evidence_count、blocked task reason。
- 普通用户视图只展示 `visibility=user` 事件，内部 debug trace 放开发面板。
- “停止生成”保留 AbortController，并补后端 run cancellation。
- Deep/Brief 按钮只传 `output_mode`，不判断 ticker。

### Phase 6：文档收口

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

## 13. 验收标准

后端：

- `python -m pytest backend/tests/test_understand_request.py -q`
- `python -m pytest backend/tests/test_langgraph_skeleton.py backend/tests/test_policy_gate.py backend/tests/test_tool_manifest.py -q`
- 复合请求不再被压成单一 subject。
- macro 无 ticker 请求不触发“先选定分析对象”。
- 泛聊天不触发金融 clarify。

前端：

- `npm run build`
- `npx vitest run src`
- Playwright 验证：
  - 新建/切换/删除会话。
  - Deep/Brief 按钮只受 actionable input 和 output mode 影响。
  - 复合请求能显示多个理解 task。
  - 展开 Process Strip 后能看到真实 trace：task decomposition、search query、tool/agent 状态、blocked task reason。
  - 过程 UI 来自 SSE 事件；模拟后端不发 retrieval/tool 事件时，前端不能显示对应假步骤。
  - 用户可停止流式输出。

文档：

- README 不再把旧 18 节点称为最终架构。
- DOCS_INDEX 明确当前事实源、目标 spec、历史文档边界。
- 所有被归档文档在 archive README 记录原路径和原因。
