# 流式输出实现指南

> 📅 创建日期: 2025-12-27
> ✅ 实现完成: 2025-12-27
> 🎯 目标: 实现 LLM 逐字流式输出，提升用户体验

---

## 一、实现状态

| 任务 | 状态 | 文件 |
|------|------|------|
| 后端 SSE 流式输出 | ✅ 完成 | `backend/langchain_agent.py` |
| 后端 API 端点 | ✅ 完成 | `backend/api/main.py` |
| 前端流式接收 | ✅ 完成 | `frontend/src/api/client.ts` |
| 前端逐字显示 | ✅ 完成 | `frontend/src/components/ChatInput.tsx` |
| 测试脚本 | ✅ 完成 | `backend/tests/test_streaming.py` |

---

## 二、技术方案

### 2.1 后端：SSE (Server-Sent Events)
- 使用 FastAPI 的 `StreamingResponse`
- LangGraph 的 `astream_events` 获取逐字输出

### 2.2 前端：fetch + ReadableStream
- 使用 `fetch` API 接收 SSE
- 逐字更新消息内容

---

## 三、核心代码

### 3.1 后端 - analyze_stream 方法

```python
# backend/langchain_agent.py
async def analyze_stream(self, query: str, thread_id: Optional[str] = None):
    """Stream LLM output token by token."""
    async for event in self.graph.astream_events(initial_state, config=config, version="v2"):
        kind = event.get("event", "")
        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                yield json.dumps({"type": "token", "content": chunk.content})
```

### 3.2 后端 - API 端点

```python
# backend/api/main.py
@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    async def generate():
        async for chunk in report_agent.analyze_stream(request.query):
            yield f"data: {chunk}\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

### 3.3 前端 - 流式接收

```typescript
// frontend/src/api/client.ts
async sendMessageStream(query, onToken, onToolStart, onToolEnd, onDone, onError) {
    const response = await fetch(`${API_BASE_URL}/chat/stream`, {...});
    const reader = response.body?.getReader();
    // 逐行解析 SSE 数据
}
```

---

## 四、SSE 数据格式

```
data: {"type": "token", "content": "你"}
data: {"type": "token", "content": "好"}
data: {"type": "tool_start", "name": "get_stock_price"}
data: {"type": "tool_end"}
data: {"type": "done"}
```

---

## 五、测试方法

```bash
# 启动后端
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload

# 运行测试
python -m backend.tests.test_streaming
```

---

## 六、验收标准

- [x] 后端 `/chat/stream` 返回逐字 SSE
- [x] 前端能接收并逐字显示
- [x] 工具调用事件正确传递
- [x] 错误处理正常
- [x] TypeScript 编译无错误
