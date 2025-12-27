# 阶段0 补完指南

> 📅 更新日期: 2025-12-27
> 🎯 目标: 完成阶段0剩余 10%（节点级 tracing）

---

## 一、当前完成状态

| 任务 | 状态 | 文件 |
|------|------|------|
| KV 缓存 | ✅ | `backend/orchestration/cache.py` |
| 熔断器 | ✅ | `backend/services/circuit_breaker.py` |
| 工具编排器 | ✅ | `backend/orchestration/orchestrator.py` |
| FetchResult 标准化 | ✅ | `orchestrator.py:41-69` |
| 前端诊断面板 | ✅ | `frontend/src/components/DiagnosticsPanel.tsx` |
| 测试覆盖 | ✅ | `test_circuit_breaker.py`, `test_cache.py` |
| **节点级 tracing** | ⚠️ | 仅有工具级，缺节点级 |

---

## 二、待完成：节点级 Tracing

### 2.1 当前实现分析

`langchain_agent.py` 已有 `FinancialAnalysisCallback`，记录：
- `tool_start` / `tool_end` 事件
- 工具名称、耗时、输入输出预览

**缺失**：
- 节点级别的 span（agent 节点、tools 节点）
- LangSmith 集成的 metadata

### 2.2 增强方案

在 `langchain_agent.py` 中添加节点级 tracing：

```python
# 在 _build_graph 方法中增强

from langchain_core.tracers import LangChainTracer

def _build_graph(self):
    # ... 现有代码 ...

    # 包装 agent_node 添加 tracing
    async def traced_agent_node(state: MessagesState) -> dict:
        with trace_span("agent_node") as span:
            span.set_attribute("messages_count", len(state.get("messages", [])))
            result = await agent_node(state)
            span.set_attribute("has_tool_calls", bool(result.get("tool_calls")))
            return result

    workflow.add_node("agent", traced_agent_node)
    # ...
```

### 2.3 简化实现（推荐）

直接在 callback 中增强，无需修改图结构：

```python
# langchain_agent.py - FinancialAnalysisCallback 增强

def on_chain_start(self, serialized, inputs, **kwargs):
    self._run_start = time.time()
    node_name = serialized.get("name", "chain")
    self._record({
        "event": "node_start",
        "node": node_name,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "input_keys": list(inputs.keys()) if isinstance(inputs, dict) else None,
    })

def on_chain_end(self, outputs, **kwargs):
    duration = (time.time() - self._run_start) * 1000 if self._run_start else None
    self._record({
        "event": "node_end",
        "duration_ms": duration,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "output_keys": list(outputs.keys()) if isinstance(outputs, dict) else None,
    })
```

---

## 三、验收标准

### 3.1 功能验收

```python
# 测试代码
agent = create_financial_agent()
result = agent.analyze("分析 AAPL")

# 验证 trace 包含节点级事件
trace = result.get("trace", [])
node_events = [e for e in trace if e.get("event") in ("node_start", "node_end")]
assert len(node_events) >= 2, "应该有节点开始和结束事件"
```

### 3.2 诊断面板验收

前端 `DiagnosticsPanel` 应能显示：
- 节点执行顺序
- 每个节点耗时
- 工具调用详情

---

## 四、阶段0 完成后的状态

```
阶段0（基座强化）: ██████████ 100%

✅ 工具失败不再500，返回结构化错误
✅ 缓存命中率可观测（日志可见 cache_hit）
✅ 熔断状态可见（diagnostics 显示跳过原因）
✅ 搜索兜底可用（Tavily 限时返回）
✅ LangSmith 可见完整调用链（节点级 + 工具级）
✅ 前端 Diagnostics 面板可用
```

---

## 五、下一步

阶段0 完成后，立即启动阶段1：

1. 创建 `backend/agents/` 目录
2. 实现 `base.py`（AgentOutput + BaseFinancialAgent）
3. 实现 `price_agent.py`（复用 orchestrator）

详见 [03_PHASE1_IMPLEMENTATION.md](./03_PHASE1_IMPLEMENTATION.md)
