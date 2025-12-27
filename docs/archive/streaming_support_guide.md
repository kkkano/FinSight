# 流式支持模块说明文档

## 📋 问题原因分析

### 1. **为什么 streaming_support 有问题？**

#### 原因 A: 文件位置错误
- **Archive 版本**位于 `archive/old_langchain_versions/streaming_support.py`
- **Main.py 尝试导入**但文件不在主目录，导致 `ModuleNotFoundError`

#### 原因 B: API 不兼容
- Archive 版本需要 `agent.analyze_async()` 异步方法
- 当前 `langchain_agent.py` 只提供 `agent.analyze()` 同步方法
- LangGraph 架构变化导致回调处理方式不同

#### 原因 C: 导入依赖问题
- Archive 版本导入了 `from langchain.agents import AgentAction, AgentFinish`
- LangChain 1.0+ 中这些类的位置和用法都改变了
- 导入 `FINANCIAL_TOOLS` 的路径可能不对

---

## ✅ 解决方案

### 方案 1: 创建新的兼容版本（已实施）

我创建了一个**全新的** `streaming_support.py`，具有以下特点:

1. **兼容 LangChain 1.0+ 和 LangGraph**
   - 使用 `on_chain_start/end` 代替 `on_agent_start/finish`
   - 适配新的回调机制
   
2. **只依赖同步 API**
   - 不需要 `analyze_async` 方法
   - 直接使用当前的 `analyze()` 方法

3. **优雅降级**
   - 优先使用流式输出
   - 出错时自动降级到基础模式
   - 不会因为streaming失败而中断主流程

4. **修复了已知bug**
   - 修复了 `on_tool_end` 中 `len(output)` 的 TypeError
   - 添加了异常处理

---

## 🚀 使用方法

### 基础使用

```python
from langchain_agent import create_financial_agent
from streaming_support import AsyncFinancialStreamer

# 创建 agent
agent = create_financial_agent()

# 创建流式输出器
streamer = AsyncFinancialStreamer(
    show_progress=True,    # 显示进度信息
    show_details=True      # 显示详细步骤
)

# 执行流式分析
result = streamer.stream_analysis(agent, "分析 AAPL 股票")
print(result["output"])
```

### 进度条使用

```python
from streaming_support import ProgressIndicator

progress = ProgressIndicator(total_steps=5)
progress.start("开始分析")

for i, step in enumerate(["加载", "处理", "分析", "生成", "完成"]):
    progress.update(step)
    # ... 执行任务 ...

progress.finish(success=True)
```

### 仪表板使用

```python
from streaming_support import FinancialDashboard

dashboard = FinancialDashboard()

# 记录分析
dashboard.record_analysis(
    query="分析 AAPL",
    success=True,
    duration=12.5,
    tool_calls=6
)

# 显示统计
dashboard.display_dashboard()

# 获取指标
metrics = dashboard.get_metrics()
print(f"成功率: {metrics['success_rate']:.1f}%")
```

---

## 🎯 与 main.py 的集成

### main.py 中的容错处理

```python
# 导入时的容错
try:
    from streaming_support import AsyncFinancialStreamer, FinancialDashboard
except ImportError:
    print("警告: streaming_support 模块未找到，将使用基础模式")
    AsyncFinancialStreamer = None
    FinancialDashboard = None

# 使用时的检查
if AsyncFinancialStreamer is not None:
    streamer = AsyncFinancialStreamer(show_progress=True, show_details=True)
    result = streamer.stream_analysis(agent, query)
else:
    # 降级到基础模式
    print("\n[开始分析]")
    result = agent.analyze(query)
    print("[分析完成]\n")
```

---

## 🔧 主要组件说明

### 1. FinancialStreamingCallbackHandler

**功能**: 拦截 LangChain 执行过程中的各种事件，实时显示进度

**支持的回调**:
- `on_chain_start`: Agent 开始执行
- `on_tool_start`: 工具开始调用
- `on_tool_end`: 工具执行完成
- `on_llm_start`: LLM 开始思考
- `on_llm_end`: LLM 完成思考
- `on_chain_end`: Agent 执行完成
- `on_chain_error`: 执行出错

### 2. AsyncFinancialStreamer

**功能**: 流式输出控制器

**方法**:
- `stream_analysis(agent, query)`: 执行流式分析（主方法）
- `sync_stream_analysis(agent, query)`: 同步版本（返回字符串）

**特点**:
- 自动替换 agent 的 callback
- 完成后恢复原始 callback
- 完整的异常处理

### 3. ProgressIndicator

**功能**: 进度条显示

**方法**:
- `start(message)`: 开始显示
- `update(step_name)`: 更新进度
- `finish(success)`: 完成显示

### 4. FinancialDashboard

**功能**: 分析统计仪表板

**方法**:
- `record_analysis()`: 记录分析会话
- `display_dashboard()`: 显示统计信息
- `get_metrics()`: 获取指标数据

---

## ⚠️ 注意事项

### LangGraph 递归限制

如果遇到 `GraphRecursionError: Recursion limit of 25 reached`:

```python
# 在创建 agent 时增加递归限制
result = agent.agent.invoke(
    {"messages": [HumanMessage(content=query)]},
    config={
        "callbacks": [callback],
        "recursion_limit": 50  # 增加限制
    }
)
```

### API 速率限制

测试中遇到了 yfinance 的速率限制:
```
Too Many Requests. Rate limited. Try after a while.
```

**解决方案**:
1. 使用多个 API 密钥轮换
2. 添加请求延迟
3. 启用缓存机制

---

## 📊 测试结果

```bash
python test_streaming.py
```

**测试项目**:
1. ✅ 流式输出显示
2. ✅ 进度条功能
3. ✅ 仪表板统计
4. ⚠️  工具调用跟踪（有小bug已修复）

**性能**:
- 能够实时显示每个工具调用
- 显示 AI 思考过程
- 统计工具使用次数
- 计算总耗时

---

## 🎨 输出示例

```
======================================================================
📈 FinSight 流式分析 - LangChain 1.0+
======================================================================
🎯 查询: 获取 AAPL 的当前股价...
📅 开始时间: 2025-10-27 00:37:22
──────────────────────────────────────────────────────────────────────

🤔 AI 思考中... (第 1 轮)
✓ 完成思考

[Step 1] get_current_datetime
   Input: {}
   Result: 2025-10-27 00:37:24

🤔 AI 思考中... (第 2 轮)
✓ 完成思考

[Step 2] get_stock_price
   Input: {'ticker': 'AAPL'}
   Result: AAPL Current Price: $262.82 | Change: $3.24 (+1.25%)

[Step 3] get_company_info
   Input: {'ticker': 'AAPL'}
   Result: Company Profile (AAPL)...

======================================================================
✅ 分析完成!
⏱️  总耗时: 25.34秒
🔧 工具调用: 8次
======================================================================
```

---

## 🔄 后续改进方向

1. **添加流式 Token 输出**
   - 实现 `on_llm_new_token` 显示 AI 生成过程
   
2. **可视化进度条**
   - 更美观的进度显示
   - 彩色输出支持

3. **性能监控**
   - 每个工具的耗时统计
   - 内存使用监控

4. **Web UI 支持**
   - WebSocket 实时推送
   - 浏览器端显示进度

---

**创建时间**: 2025-10-27  
**版本**: 1.0.0  
**兼容性**: LangChain 1.0+, LangGraph
