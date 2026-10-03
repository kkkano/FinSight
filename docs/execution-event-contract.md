# Execution Event Contract

更新时间：2026-10-03

## 完成与交付状态

`pipeline_stage(stage=done)` 只说明研究流程已结束，不能把前端运行提前设为 100%。最终 `done` 到达且答案已经应用后，前端才切换完成；等待期间最多 99%，显示“正在保存并交付回答”。SSE 收到最终 `done/error` 后立即结束读取，不等待 HTTP EOF。

若流程已结束但流未收尾，前端只读同一 `run_id` 的持久终态，校验 session/user message 身份后恢复服务器正文，不发起第二次研究。恢复后关闭网络流不代表用户取消，不调用业务取消接口。聊天回复占位丢失时，仅当对应问题、owner、run、控制器和运行状态仍一致才允许恢复正文；删除、清空、换账号或新的运行接管后不能复活旧回复。

旧客户端未发送消息 ID 时，服务器可能在本地问题快照后补建带 run 的问题/回答。历史恢复以本地问题 ID 精确定位，允许其末尾紧邻一组或多组同文且绑定一致的完整 canonical 问答；只在本地呈现合并最前面的 legacy 副本，保留所有真实运行记录。不同问题、缺失绑定、未完成尾部、换账号或新消息均禁止覆盖，不依赖客户端时钟。

本契约约束后端执行事件、SSE 序列化和前端消费。事件是可观测事实，不是前端模拟动画。

## 阶段

`planning`、`executing`、`synthesizing`、`rendering`、`persistence`、`done`、`cancelled`。`done` 完成阶段与终态事件在持久化回调返回后交付；不能在浏览器仍未拿到可恢复答案时提前宣称已保存。

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
| `degraded` | LLM router、直接回复或合成不可用，本轮使用了明确披露的回退 |
| `quality_blocked` | 内容质量未通过，保留可展示预览及原因 |
| `done/error/cancelled` | 运行终态；内容质量和保存状态使用独立字段 |

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
  "session_id": "...",
  "seq": 12
}
```

事件新增字段应向后兼容；消费者必须忽略未知字段。不得在 payload 中放 API key、Authorization、Cookie、完整敏感工具参数或跨用户数据。

## `degraded` 与终态

```json
{
  "type": "degraded",
  "message": "LLM 暂时不可用，本轮已使用降级回答；结果可能不完整，请稍后重试。",
  "degradation": {
    "used": true,
    "stage": "routing|direct_reply|synthesis|runtime",
    "reason": "llm_unavailable|all_llm_attempts_failed"
  }
}
```

流式 `done` 返回 `degraded: boolean` 与 `degradation: object|null`。选定模型仍由请求上下文统一传入各 LLM 调用；允许的重试最终成功不等于整轮失败。若本轮所有 LLM 尝试均失败并使用规则、工具或模板结果，则以 `runtime/all_llm_attempts_failed` 披露。降级回答仍可展示，前端必须显示具体原因，不能伪装成正常模型成功。

终态的三个维度必须分开消费：

| 字段 | 语义 |
|---|---|
| `run_status` | `running/completed/failed/cancelled/interrupted/persistence_failed`；研究执行与交付生命周期 |
| `quality.state` | `pass/warn/block`，由统一裁决按最严重状态合并 |
| `answer_status` | `answered/partial/unavailable/blocked`，表示请求答复完整性；占位消息为 `running` |
| `has_supported_content` | 是否存在受支持的可展示内容 |
| `persistence_status` | `saved/failed/ephemeral`，分别表示服务器事务已提交、保存失败、无持久存储的匿名或开发运行 |
| `publishable`、`archived` | 内容可发布与报告已归档，两者不可混用 |

`done` 包含 `response`、`report` 或 `blocked_report`、质量原因和 metrics。质量阻断的报告仅为预览；完整报告需要规范化受支持 Claim。`report=None` 不能覆盖聊天已有质量状态。保存失败时正文预览仍在，`publishable=false`，错误码为 `conversation_persistence_failed` 或报告归档的 `report_persistence_failed`。

## 消息与运行身份

`POST /api/execute` 可携带以下字段：

```json
{
  "query": "英特尔的技术面、基本面、催化和风险分别如何？",
  "session_id": "public:USER_ID:THREAD_ID",
  "run_id": "CLIENT_RUN_ID",
  "client_user_message_id": "USER_MESSAGE_ID",
  "client_assistant_message_id": "ASSISTANT_MESSAGE_ID"
}
```

owner 只来自已验证身份。模型预检后，服务器先保存问题、运行和包含 `run_id/reply_to/isLoading=true` 的助手占位，再启动研究。终态事务更新权威助手消息、会话版本及运行 final payload，提交后返回：

```json
{
  "type": "done",
  "run_id": "CLIENT_RUN_ID",
  "session_id": "public:USER_ID:THREAD_ID",
  "run_status": "completed",
  "response": "已验证的完整正文",
  "persistence_status": "saved",
  "conversation_version": 2,
  "user_message_id": "USER_MESSAGE_ID",
  "assistant_message_id": "ASSISTANT_MESSAGE_ID",
  "assistant_message": {
    "id": "ASSISTANT_MESSAGE_ID",
    "role": "assistant",
    "content": "已验证的完整正文",
    "run_id": "CLIENT_RUN_ID",
    "reply_to": "USER_MESSAGE_ID",
    "run_sequence": 1,
    "isLoading": false,
    "answer_status": "answered"
  }
}
```

上例省略质量、时间、报告与 metrics 等字段。消息 `timestamp` 为毫秒时间戳；会话及运行 API 的 `created_at/updated_at/completed_at` 为秒时间戳。

相同 owner/run 再次 POST 只恢复原结果，在配额检查与模型预检之前返回；同 run 更换查询返回 409。用户主动重新生成必须新建 run 和 assistant ID，可复用 user message ID。历史运行审计保留，会话按 `reply_to` 最新 `run_sequence` 原位显示回复，迟到旧 run 不覆盖新结果。

会话快照写入采用事务合并，权威消息优先。客户端可提交 `expected_version`，过期时返回 HTTP 409 `conversation_version_conflict`，随后读取最新版本；不传版本的旧客户端也不能用旧快照抹去服务器回复。

## `plan_ready`

```json
{
  "type": "plan_ready",
  "plan_steps": [
    {"id": "s1", "kind": "agent", "name": "news_agent", "task_ids": ["task_1"], "parallel_group": "research", "optional": false, "depends_on": [], "data_dependencies": []}
  ],
  "selected_agents": ["news_agent"],
  "skipped_agents": [{"agent": "macro_agent", "reason": "not_needed"}],
  "has_parallel": false,
  "reasoning_brief": "选择新闻证据以回答事件问题",
  "timestamp": "ISO-8601"
}
```

`reasoning_brief` 只能是可披露决策摘要，不输出隐藏思维链。

计划必须已通过工具实际 schema、任务/依赖引用和无环校验。`depends_on` 要求上游成功，`data_dependencies` 只等待上游成功或失败结束；前端不得按展示分组推断真实依赖。

## 取消与续传

- 前端停止时先中止 SSE，并调用后端取消作用域。
- execution service、图节点、executor 和 Agent adapter 共享 cancellation token。
- 取消不是普通错误；后端发出 `cancelled` 阶段并停止后续 step/agent 事件。
- 已产生的可见事件可保留；取消后到达的外部调用结果不得继续进入 evidence/synthesis。
- SSE 续传必须按 run/thread/user scope 校验，不能跨会话重放。

`GET /api/execute/runs/{run_id}` 返回 `{run_id,session_id,status,user_message_id,assistant_message_id,created_at,updated_at,completed_at,result}`。`result` 在 running 时为 null，结束后为完整终态事件；不返回 worker ID 或私有请求上下文。

`GET /api/execute/runs/{run_id}/events?after_seq=N` 优先读取内存事件；缓冲过期或进程重启后，从 PostgreSQL 返回完整终态，标注 `recovered=true` 并给出大于 cursor 的 seq。恢复不重新执行研究。运行每 25 秒续期，90 秒租约失联且被读取后转为 `interrupted` 并保存可重试说明。

数据库完全不可写时，临时预览无法承诺跨进程恢复；前端提示保留当前内容，不能显示“已保存”。取消/中断时已流出的正文仍作为失败预览保存。执行 task 与取消路由仍在单个 backend 进程，终态持久化不代表已实现分布式任务调度。

## 前端消费

- user：阶段和当前步骤。
- expert：阶段、分组时间线、Agent 选择和统计。
- dev：允许显示 raw 事件，但仍需脱敏。
- 优先采用 `assistant_message.content` 或终态 `response` 校准流式正文；重复 done 根据消息/run ID 幂等合并。
- `persistence_status=saved` 时无需由浏览器再写最终正文；failed 保留预览并提示，ephemeral 不显示持久保存承诺。
- 刷新后遇到服务器占位，按 run ID 查询状态或续传，不再次 POST 新研究；同 owner 的 token 刷新不能切走当前会话。
- 前端附加图表标记是展示补充，不能通过迟到整份快照覆盖服务端权威正文；永久图表依赖服务器 artifact 或明确的 view metadata。

事件生产主要位于 `backend/graph/event_bus.py`、`backend/graph/execution/`、`backend/graph/nodes/` 和 `backend/services/execution_service.py`；前端消费位于 execution store/adapter。修改事件必须同时更新两端类型和测试。
