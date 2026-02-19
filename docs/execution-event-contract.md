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
  "stage": "planning|executing|synthesizing|rendering|done",
  "status": "start|running|done|error|resume",
  "message": "human readable summary",
  "duration_ms": 1234,
  "error": "optional",
  "timestamp": "ISO-8601"
}
```

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

## 发射位置
- `planning:start/done/error`：`backend/graph/nodes/planner.py`
- `executing:start/done/error`：`backend/graph/executor.py`
- `synthesizing:start/done/error`：`backend/graph/nodes/synthesize.py`
- `rendering:start/done`（run + resume）：`backend/services/execution_service.py`
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

