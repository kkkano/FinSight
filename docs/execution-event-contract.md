# Execution Event Contract

## 目标
- 将执行追踪从“散点日志”统一为“阶段状态机 + 分组时间线 + 决策摘要”。
- 在 `trace_raw_enabled=false` 下仍保留用户可读的关键进度事件。

## 阶段枚举（与真实管线一致）
- `planning`
- `executing`
- `synthesizing`
- `rendering`
- `done`
- `cancelled`

## 关键事件（Raw OFF 仍保留）
- `token`
- `done`
- `error`
- `plan_ready`
- `pipeline_stage`
- `step_start`
- `step_done`
- `step_error`
- `agent_start`
- `agent_done`
- `agent_error`
- `trace`（仅 `visibility="user"`）
- `decision_note`

## Raw-only 事件（Raw OFF 会过滤）
- `llm_*`
- `tool_*`
- `cache_*`
- `data_source`
- `api_call`

## 事件 Payload

### `pipeline_stage`
```json
{
  "type": "pipeline_stage",
  "stage": "planning|executing|synthesizing|rendering|done|cancelled",
  "status": "start|running|done|error|resume|cancelled",
  "message": "human readable summary",
  "duration_ms": 1234,
  "error": "optional",
  "timestamp": "ISO-8601"
}
```

取消语义：

- 前端点击停止后使用 `AbortController.abort()` 断开当前 SSE。
- 后端 execution service 捕获 `asyncio.CancelledError` 后发出 `pipeline_stage.stage="cancelled"` 和用户可见 `trace.stage="cancelled"`。
- executor 和 agent adapter 读取 context-scoped cancellation token，阶段边界或 agent 返回前停止后续 step/agent 事件；同步外部 HTTP/LLM 调用可能只能在返回后丢弃后续输出。
- 取消不是错误；已经产出的 token、trace 和 report partial 保留在当前会话。

### `plan_ready`
```json
{
  "type": "plan_ready",
  "plan_steps": [
    {
      "id": "s1",
      "kind": "agent|tool|llm",
      "name": "news_agent",
      "parallel_group": "report_agents",
      "optional": false
    }
  ],
  "plan_steps_count": 1,
  "selected_agents": ["news_agent"],
  "skipped_agents": ["macro_agent"],
  "has_parallel": false,
  "reasoning_brief": "planner summary without chain-of-thought",
  "timestamp": "ISO-8601"
}
```

### `decision_note`
```json
{
  "type": "decision_note",
  "scope": "planner|synthesize|verifier",
  "title": "Planner selection summary",
  "reason": "why",
  "impact": "impact scope",
  "next_step": "optional",
  "timestamp": "ISO-8601"
}
```

### `trace`（用户可见）
```json
{
  "type": "trace",
  "visibility": "user",
  "stage": "understanding|planning|retrieval|tool|agent|synthesis|cancelled",
  "status": "start|running|done|error|cancelled",
  "title": "已理解请求",
  "summary": "识别 4 个任务，其中 1 个需要补充信息",
  "tasks": [
    {
      "id": "task_1",
      "subject_type": "company",
      "tickers": ["GOOGL"],
      "operation": "price",
      "time_scope": "today"
    }
  ],
  "blocked_tasks": [
    {"id": "blocked_1", "reason": "missing_portfolio_holdings"}
  ],
  "timestamp": "ISO-8601"
}
```

约束：

- `visibility="user"` 的 `trace` 在 `trace_raw_enabled=false` 时仍保留。
- `visibility="debug"` 或未声明 visibility 的内部 trace 不进入普通用户视图。
- 前端只渲染后端真实发出的 stage，不伪造 search/tool/agent 进度。
- payload 中的 query、provider、tool args 只能展示摘要，不得泄露密钥或隐私字段。

## 发射位置
- `planning:start/done/error`：`backend/graph/nodes/planner.py`
- `understanding:done`：`backend/graph/nodes/understand_request.py`
- `executing:start/done/error`：`backend/graph/executor.py`
- `synthesizing:start/done/error`：`backend/graph/nodes/synthesize.py`
- `rendering:start/done`（run + resume）：`backend/services/execution_service.py`
- `cancelled`（run + resume）：`backend/services/execution_service.py`
- `cancelled` cooperative token：`backend/graph/cancellation.py`、`backend/graph/executor.py`、`backend/graph/adapters/agent_adapter.py`
- `done`：`backend/services/execution_service.py`

## 前端消费与降级
- `pipelineReducer` 负责消费 `plan_ready` / `pipeline_stage` / `decision_note` / `agent_done` 扩展字段。
- 未发新字段时采用降级策略：
  - `selected_agents/skipped_agents` 为空数组
  - `decision_notes` 为空
  - `etaSeconds=null`
- `traceViewMode` 映射：
  - `user`：阶段条 + 当前步骤
  - `expert`：阶段条 + 分组时间线 + 统计 + 决策说明
  - `dev`：原始 `AgentLogPanel`

## 兼容策略
- 事件协议增量扩展，不移除旧字段。
- 旧前端可忽略新增事件；新前端可在旧事件流下正常降级。
- 不引入数据库迁移。
