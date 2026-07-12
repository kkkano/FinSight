# Execution Event Contract

更新时间：2026-07-12

本契约约束后端执行事件、SSE 序列化和前端消费。事件是可观测事实，不是前端模拟动画。

## 阶段

`planning`、`executing`、`synthesizing`、`rendering`、`done`、`cancelled`。

## 用户级事件

| type | 作用 |
|---|---|
| `pipeline_stage` | 阶段状态与耗时 |
| `plan_ready` | 已验证计划、选择/跳过的 Agent 和并行信息 |
| `step_start/done/error` | 计划步骤生命周期 |
| `agent_start/done/error` | Agent 生命周期 |
| `decision_note` | 不含 chain-of-thought 的决策摘要 |
| `trace` | `visibility=user` 的可解释进度 |
| `token` | 流式文本 token |
| `done/error` | 流结束或错误 |

`llm_*`、`tool_*`、`cache_*`、`data_source`、`api_call` 等细节只在 raw/dev 模式保留。

## 基础 payload

```json
{
  "type": "pipeline_stage",
  "stage": "executing",
  "status": "start|running|done|error|resume|cancelled",
  "message": "正在执行已确认计划",
  "duration_ms": 1234,
  "timestamp": "ISO-8601",
  "run_id": "...",
  "thread_id": "..."
}
```

事件新增字段应向后兼容；消费者必须忽略未知字段。不得在 payload 中放 API key、Authorization、Cookie、完整敏感工具参数或跨用户数据。

## `plan_ready`

```json
{
  "type": "plan_ready",
  "plan_steps": [
    {"id": "s1", "kind": "agent", "name": "news_agent", "parallel_group": "research", "optional": false}
  ],
  "selected_agents": ["news_agent"],
  "skipped_agents": [{"agent": "macro_agent", "reason": "not_needed"}],
  "has_parallel": false,
  "reasoning_brief": "选择新闻证据以回答事件问题",
  "timestamp": "ISO-8601"
}
```

`reasoning_brief` 只能是可披露决策摘要，不输出隐藏思维链。

## 取消与续传

- 前端停止时先中止 SSE，并调用后端取消作用域。
- execution service、图节点、executor 和 Agent adapter 共享 cancellation token。
- 取消不是普通错误；后端发出 `cancelled` 阶段并停止后续 step/agent 事件。
- 已产生的可见事件可保留；取消后到达的外部调用结果不得继续进入 evidence/synthesis。
- SSE 续传必须按 run/thread/user scope 校验，不能跨会话重放。

## 前端消费

- user：阶段和当前步骤。
- expert：阶段、分组时间线、Agent 选择和统计。
- dev：允许显示 raw 事件，但仍需脱敏。

事件生产主要位于 `backend/graph/event_bus.py`、`backend/graph/execution/`、`backend/graph/nodes/` 和 `backend/services/execution_service.py`；前端消费位于 execution store/adapter。修改事件必须同时更新两端类型和测试。
