# LangGraph Pipeline 深入说明

更新时间：2026-07-16

本文补充 [`LANGGRAPH_FLOW.md`](LANGGRAPH_FLOW.md)。节点和边仍以 `backend/graph/runner.py` 为准。

## 1. 上下文准备

`prepare_context` 组合 `build_initial_state`、本轮状态清理、历史裁剪/摘要和 UI context 规范化。生产 checkpointer 恢复当前 thread 的消息；前端历史只在 checkpoint 没有消息时作为输入补充，不能覆盖或重复服务端历史。

同一 thread 的已验证 ticker 焦点与报告上下文保存在 `memory_context` checkpoint 字段。该字段不会跨 thread 查询，也不读写 JSON Memory。

## 2. 请求路由

`route_request` 全程使用确定性规则，产出：

- `understanding.route`：`direct`、`research` 或 `clarify`；
- request frame 与 operation；
- ready/blocked tasks；
- 固定的 `request_frame_id`、`render_group_id`、`render_kind`、priority 和 order。

封闭金融术语可以走 `direct`。需要实时数据、比较、分析或报告的请求进入 `research`；缺少必要标的或范围时进入 `clarify`。下游不得重新解析 query 来改写这些决定。

## 3. 策略、计划与采集

`collect_evidence` 对非 `research` lane 立即跳过，保证零外部 I/O。研究 lane 依次执行：

```text
policy_gate
  -> rule_based_planner
  -> execute_plan_node / DAG executor
  -> collector or tool
  -> evidence gate
```

planner 是确定性规则实现，运行时 trace 明确记录 `llm_calls=0`。PlanIR 必须经过能力、依赖和 policy 约束，不能发明工具。

Price、Technical、Fundamental、News、Macro、Risk 和 Deep Search collector 以 `llm=None` 构造，只做工具采集和结构化封装。raw result 通过 evidence gate 后才进入 evidence pool；error、timeout、empty、rejected 和 fallback 进入 diagnostics。

## 4. 分析

`analyze` 根据结构化 operation 决定分析方式：

- 事实型 research：调用 `_stub_render_vars` 构造确定性结果，业务 LLM 调用为 0；
- `analysis`、`earnings_impact`、`investment_opinion`、`news_impact`、`qa`：最多一次 `ResearchAnalyst`；
- `investment_report`：一次分析，并允许报告 verifier 检查不受支持的 Claim。

Prediction 不在该节点产生。`POST /api/predictions/generate` 进入独立服务，由 PredictionAnalyst 使用可信行情生成结构化 Prediction。

## 5. 验证与渲染

`validate` 记录 evidence ledger、引用数量、有效/拒绝 Claim、future-claim scrub 和 quality block。每个原始 task 必须有 `answered`、`partial`、`unavailable` 或 `blocked` 结果。

`render` 只消费已验证 artifacts。它不能调用工具、重新路由或把 diagnostics 当证据；渲染完成后仅把当前 thread 的必要上下文写回 checkpoint。质量被阻断的报告不可分享。

## 6. 持久化

- LangGraph：PostgreSQL checkpointer；测试可使用 `MemorySaver`。
- 核心业务：PostgreSQL conversation、watchlist、reports、Prediction、Outcome、Monitor 和 usage 表。
- RAG：PostgreSQL/pgvector；memory 来源仅限当前 thread 的可信上下文。
- Schema：Alembic 管理；应用启动只验证 revision，不执行核心 DDL。

## 7. 可观测性

每个节点写 trace；collector 发送 start/done/error 事件；ResearchAnalyst 发送明确的角色事件。每个逻辑 LLM 调用记录 stage、role、layer、endpoint、latency、token 和 failure code，供应商未返回 token 时保存 `null`。

SSE 的状态、降级、取消和终态遵循 [`execution-event-contract.md`](execution-event-contract.md)。前端必须按稳定错误码区分认证、行情、LLM、配额、校验和存储失败。

## 8. 修改检查

- 图变化同步 runner、GraphState、流程文档和 skeleton 测试。
- 新 capability 同步 profile、policy、planner、adapter 和 evidence gate。
- 新事件同步 SSE 合同、前端类型、store 和消费测试。
- 新回答形态通过 analysis/validate/render 扩展，不绕过证据边界。
- 不恢复旧节点、第二套执行器、reflection、debate 或跨 thread 用户画像。
