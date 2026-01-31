# Developer Console & TraceEmitter 开发日志

> **版本**: v0.6.9
> **日期**: 2026-02-01
> **开发者**: Claude (Anthropic) + Human Developer

---

## 概述

本次更新实现了完整的 **Developer Console（开发者控制台）** 功能，提供实时 SSE 事件流查看器，支持 26 种事件类型的追踪和展示。核心改进包括 TraceEmitter 全局单例、事件管道架构修复、前端 AgentLogPanel 组件等。

---

## 1. TraceEmitter 全局事件发射器

### 1.1 架构设计

```
emit_*() → TraceEmitter._emit() → async_queue → drain loops → SSE yield → Frontend
```

**文件**: `backend/orchestration/trace_emitter.py`

### 1.2 核心类

```python
class TraceEmitter:
    """
    全局追踪事件发射器（单例模式）

    使用方式:
        emitter = get_trace_emitter()
        emitter.emit_tool_start("search", {"query": "TSLA"})
        # ... 执行工具 ...
        emitter.emit_tool_end("search", result, duration_ms=150)
    """
```

### 1.3 支持的 26 种事件类型

| 类别 | 事件类型 | 说明 |
|------|----------|------|
| **Token** | `token` | Token 流式输出 |
| **Thinking** | `thinking` | 思考步骤 |
| **Tool** | `tool_start`, `tool_end`, `tool_call` | 工具调用生命周期 |
| **LLM** | `llm_start`, `llm_end`, `llm_call` | LLM 调用生命周期 |
| **Cache** | `cache_hit`, `cache_miss`, `cache_set` | 缓存操作 |
| **Data** | `data_source`, `api_call` | 数据源和 API 调用 |
| **Agent** | `agent_start`, `agent_done`, `agent_step`, `agent_error` | Agent 执行生命周期 |
| **Supervisor** | `supervisor_start`, `supervisor_done` | Supervisor 执行生命周期 |
| **Forum** | `forum_start`, `forum_done` | Forum 综合生命周期 |
| **System** | `system`, `done`, `error`, `unknown` | 系统事件 |

### 1.4 TraceEvent 数据结构

```python
@dataclass
class TraceEvent:
    event_type: str                    # 事件类型
    category: TraceCategory            # 事件类别
    message: str                       # 人类可读消息
    timestamp: str                     # ISO 时间戳
    level: TraceLevel                  # DEBUG/INFO/WARN/ERROR
    duration_ms: Optional[int]         # 持续时间(毫秒)
    agent: Optional[str]               # 关联的 Agent
    metadata: Dict[str, Any]           # 额外元数据
```

---

## 2. Supervisor 事件管道修复

### 2.1 问题描述

之前的实现中，TraceEmitter 发射的事件无法传递到前端 SSE 流，导致 Developer Console 无法显示实时事件。

### 2.2 修复方案

**文件**: `backend/orchestration/supervisor_agent.py`

1. **创建 async_queue 并连接 TraceEmitter**:
```python
# 连接 TraceEmitter 的 async_queue
trace_queue = asyncio.Queue()
trace_emitter.set_async_queue(trace_queue)
```

2. **添加 drain loops 排空队列**:
```python
# 每轮都排空 trace_queue，将 TraceEmitter 事件转为 SSE
try:
    while True:
        trace_evt = trace_queue.get_nowait()
        yield json.dumps(trace_evt.to_sse_dict(), ensure_ascii=False)
except asyncio.QueueEmpty:
    pass
```

3. **添加 Supervisor 生命周期事件**:
```python
# 发射 Supervisor 开始事件
trace_emitter.emit_supervisor_start(query=query, tickers=tickers)

# ... 处理流程 ...

# 发射 Supervisor 完成事件
trace_emitter.emit_supervisor_done(
    query=query,
    intent=result.intent.value,
    success=result.success,
    duration_ms=total_duration_ms
)
```

4. **清理机制防止跨请求泄漏**:
```python
finally:
    # 清理 TraceEmitter async_queue
    trace_emitter.clear_async_queue()
```

---

## 3. 前端 AgentLogPanel 组件

### 3.1 组件位置

**文件**: `frontend/src/components/AgentLogPanel.tsx`

### 3.2 功能特性

- **实时事件流**: 显示所有 SSE 事件
- **事件过滤**: 按事件类型筛选
- **搜索功能**: 全文搜索事件内容
- **时间戳显示**: 精确到毫秒的时间戳
- **JSON 展开**: 查看原始 JSON 数据
- **自动滚动**: 新事件自动滚动到底部
- **清除功能**: 一键清除事件历史

### 3.3 RawEventType TypeScript 定义

**文件**: `frontend/src/types/index.ts`

```typescript
export type RawEventType =
  | 'token'
  | 'thinking'
  | 'tool_start' | 'tool_end' | 'tool_call'
  | 'llm_call' | 'llm_start' | 'llm_end'
  | 'cache_hit' | 'cache_miss' | 'cache_set'
  | 'data_source' | 'api_call'
  | 'agent_start' | 'agent_done' | 'agent_step' | 'agent_error'
  | 'supervisor_start' | 'supervisor_done'
  | 'forum_start' | 'forum_done'
  | 'system' | 'done' | 'error' | 'unknown';
```

---

## 4. SSE 事件处理改进

### 4.1 前端 API Client 更新

**文件**: `frontend/src/api/client.ts`

- 支持所有 26 种事件类型的解析
- 原始事件转发到 Developer Console
- 错误事件的优雅处理

### 4.2 事件流架构

```
Backend                              Frontend
────────                             ────────
TraceEmitter.emit_*()
    ↓
async_queue.put_nowait()
    ↓
drain loop in process_stream()
    ↓
yield json.dumps(event.to_sse_dict())
    ↓
──────────── SSE Stream ────────────→ EventSource
                                          ↓
                                     onmessage handler
                                          ↓
                                     Store.addRawEvent()
                                          ↓
                                     AgentLogPanel render
```

---

## 5. 文件变更清单

### 5.1 新增文件

| 文件 | 说明 |
|------|------|
| `backend/orchestration/trace_emitter.py` | TraceEmitter 全局单例 |
| `frontend/src/components/AgentLogPanel.tsx` | Developer Console 组件 |
| `images/console.png` | Developer Console 截图 |

### 5.2 修改文件

| 文件 | 变更 |
|------|------|
| `backend/orchestration/supervisor_agent.py` | 添加 async_queue 连接和 drain loops |
| `frontend/src/types/index.ts` | 添加 RawEventType 完整定义 |
| `frontend/src/api/client.ts` | SSE 事件处理和转发 |
| `frontend/src/store/useStore.ts` | Console Panel 状态管理 |
| `frontend/src/components/RightPanel.tsx` | 集成 AgentLogPanel |
| `README.md` | 添加 Developer Console 文档 |
| `readme_cn.md` | 添加开发者控制台文档 |

---

## 6. 测试验证

### 6.1 功能测试

- [x] TraceEmitter 单例正确初始化
- [x] 所有 26 种事件类型正确发射
- [x] async_queue 正确连接和排空
- [x] SSE 流正确传输事件
- [x] 前端正确接收和显示事件
- [x] 跨请求无事件泄漏

### 6.2 性能测试

- [x] 高频事件发射无阻塞
- [x] 队列排空不影响主流程
- [x] 前端渲染性能良好

---

## 7. 后续优化建议

1. **事件持久化**: 支持导出事件日志
2. **事件统计**: 添加事件类型分布图表
3. **性能监控**: 添加事件延迟统计
4. **过滤增强**: 支持正则表达式过滤
5. **主题支持**: 添加事件类型颜色主题

---

## 8. 相关链接

- [架构文档](../01_ARCHITECTURE.md)
- [路由架构标准](../ROUTING_ARCHITECTURE_STANDARD.md)
- [README](../../README.md)
- [中文文档](../../readme_cn.md)
