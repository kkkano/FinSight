# FinSight 技术实现深度问答 (Technical Q&A)

> 📅 **创建日期**: 2026-01-09
> 🎯 **用途**: 项目技术难点自查、架构设计面试题库、核心功能实现原理记录。

---

## 🚀 核心功能实现篇

### Q1: FinSight 的流式输出 (SSE) 是如何实现的？

**A**: SSE 的实现非常经典，是通过 **FastAPI + LangGraph + SSE 标准** 组合完成的。它构建了一条从 LLM 到前端浏览器的“即时通讯流水线”。

系统由 3 个核心代码段组成：

#### 1. 源头：LangChain 逐字生成 token
**原理**: 使用 LangGraph 的 `astream_events` 监听 LLM 的每一个 chunk。
**代码位置**: `backend/langchain_agent.py`

```python
# 监听 LLM 的每一个小动作
async for event in self.graph.astream_events(initial_state, ...):
    # 监听到 LLM 正在说话 (on_chat_model_stream)
    if kind == "on_chat_model_stream":
        chunk = event.get("data", {}).get("chunk")
        # 拿到一个字，立刻 yield 出去
        yield json.dumps({"type": "token", "content": chunk.content}) + "\n"
```

#### 2. 管道：SSE 格式封装
**原理**: 将底层的 raw token 包装成符合 **SSE 协议** 的格式（`data: ...\n\n`）。
**代码位置**: `backend/api/streaming.py`

```python
async for raw in report_agent.analyze_stream(query):
    # ... 解析 JSON ...
    if event_type == "token":
        # 包装成 SSE 格式：data: {...}\n\n
        # 这就好比把散装的货物装进标准的集装箱，浏览器才能认得
        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
```

#### 3. 出口：FastAPI 流式响应
**原理**: 使用 `StreamingResponse` 保持长连接，持续推送数据。
**代码位置**: `backend/api/main.py`

```python
return StreamingResponse(
    generate_report(), # 这个生成器会不断 yield 数据
    media_type="text/event-stream", # 告诉浏览器这是 SSE 流
    # headers 禁用缓存，确保实时性
    headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
)
```

---

### Q2: 为什么选择 LangGraph 而不是原生 LangChain Agent？

**A**: 虽然 LangChain Agent 适合线性任务，但在复杂的**多 Agent 协作**场景下，LangGraph 优势更明显：

1.  **循环能力 (Cyclic Graphs)**:
    *   **LangChain**: 主要是 DAG（有向无环图），很难实现“Agent A 做完 -> Agent B 检查 ->如果不合格 -> 退回给 Agent A”这样的循环。
    *   **LangGraph**: 原生支持循环由于 `StateGraph` 的设计，这对于实现 `NewsAgent` 的**反思循环 (Reflection Loop)** 至关重要。

2.  **状态管理 (State Management)**:
    *   LangGraph 显式定义了 `MessagesState`，让多个 Agent（如 Supervisor、PriceAgent、NewsAgent）可以共享同一个上下文历史，数据流转更清晰。

3.  **细粒度控制**:
    *   通过 `astream_events` 可以精确控制流式输出的每一个环节（如只输出 token，隐藏工具调用的中间步骤），提升用户体验。

---

### Q3: Supervisor 架构是如何解决 API 不兼容问题的？

**A**: 在 Phase 1 实现中，我们遇到了 FastAPI 的 `asyncio` 事件循环与 LangChain `asyncio.run()` 的冲突。

**问题背景**:
FastAPI 本身运行在一个 Event Loop 中。如果我们在请求处理函数中直接调用 `asyncio.run(supervisor.analyze())`，会抛出 *"RuntimeError: asyncio.run() cannot be called from a running event loop"*。

**解决方案**:
1.  **全链路异步化**: 彻底移除同步的 `asyncio.run()` 调用。
2.  **Await Rewrite**: 将所有阻塞调用改为 `await`。
    *   `Supervisor.analyze` -> `await Supervisor.analyze`
    *   `ReportHandler.handle` -> `await ReportHandler.handle`
3.  **流式重构**: 对于 `analyize_stream`，直接使用 `async for` 迭代生成器，利用 FastAPI 自身的异步特性进行流式传输，避免了创建新的 Event Loop。

---

### Q4: 系统的“多源数据回退”机制是如何设计的？

**A**: 为了保证金融数据的可靠性，我们在 `backend/tools.py` 中实现了严格的降级策略。

以 `get_stock_price` 为例，其调用链路如下：

```mermaid
flowchart LR
    A[Yahoo Finance] -->|失败/限流| B[Google Finance (Scraper)]
    B -->|失败| C[Stooq API]
    C -->|失败| D[CNBC/Finnhub]
    D -->|全部失败| E[抛出异常/返回空]
```

**设计要点**:
1.  **优先级**: 优先使用官方 API (Yahoo/Finnhub)，其次是稳定的 HTML 解析 (Google)，最后是备用源。
2.  **熔断器 (Circuit Breaker)**: 如果某个源连续失败（如 Yahoo 接口变动），`CircuitBreaker` 会自动“跳闸”，暂时屏蔽该源，直接请求下一个备用源，避免浪费时间在无效请求上。

---

## 🔮 架构演进篇

### Q5: 下一步 RAG (检索增强生成) 将如何落地？

**A**: 目前 DeepSearchAgent 仍使用模拟数据，RAG 计划分三步走：

1.  **Ingestion (入库)**:
    *   使用 `LlamaIndex` 解析 PDF 研报和长新闻。
    *   使用 `ChromaDB` (本地向量库) 存储 Embedding 向量。

2.  **Retrieval (检索)**:
    *   **Hybrid Search**: 结合关键词搜索（精确匹配股票代码）和语义搜索（匹配“增长潜力”、“风险因素”等概念）。
    *   **Self-RAG**: 检索后让 LLM 评估相关性，只有相关性高的片段才作为 Context 输入。

3.  **Generation (生成)**:
    *   将检索到的 Top-K 片段注入到 `ReportSystemPrompt` 中，生成带有精确引用来源的深度报告。

---

### Q6: 意图识别 (Intent Classification) 是如何工作的？

**A**: FinSight 采用 **"规则 + LLM" 混合路由机制**，在确保响应速度的同时兼顾灵活性。

**工作流程 (Router Pipeline)**:

1.  **元数据提取 (Metadata Extraction)**:
    *   **正则匹配**: 识别 `AAPL`, `^GSPC` 等标准代码。
    *   **字典映射**: 将“英伟达”映射为 `NVDA`，“纳指”映射为 `^IXIC` (支持中英文别名)。

2.  **快速通道 (Quick Match)**:
    *   **GREETING**: 匹配“你好”、“介绍自己”（且不含金融关键词）。
    *   **REPORT (深度分析)**: 强匹配关键词：`分析`, `报告`, `值得买吗`, `前景`, `outlook`。
    *   **ALERT (监控)**: 匹配 `提醒`, `监控`, `跌破`, `alert`。
    *   **FOLLOWUP (追问)**: 匹配 `为什么`, `展开说说`（需结合Context判断是否有上文）。
    *   **CHAT (快速问答)**: 匹配 `股价`, `多少钱`, `price`。

3.  **LLM 兜底 (LLM Fallback)**:
    *   如果规则未命中，调用 `GPT-4o/Gemini` 进行语义判断。
    *   **Prompt**: *"Analyze user intent: CHAT/REPORT/ALERT..."*

**当前局限与改进策略**:
*   **问题**: 强规则依赖死板的关键词。例如用户说“看看特斯拉”，可能因为没用到“分析”一词而被误判为普通 CHAT。
*   **改进**:
    *   **Few-Shot Prompting**: 优化 LLM Prompt，增加模糊查询的示例。
    *   **语义相似度**: 引入轻量级 Embedding 模型（如 `all-MiniLM-L6-v2`），计算 Query 与各意图描述的余弦相似度，替代硬编码关键词。

---

### Q7: 子 Agent (Sub-agents) 目前存在哪些缺陷？

**A**: 虽然架构设计了 6 大专家 Agent，但目前成熟度参差不齐：

| Agent | 状态 | 核心缺陷 | 改进计划 |
|-------|------|----------|----------|
| **PriceAgent** | ✅ 可用 | 仅支持基础行情，缺乏这种盘口/逐笔数据 | 接入 WebSocket 实时数据流 |
| **NewsAgent** | ✅ 可用 | 依赖外部搜索 API，去重逻辑简单 | 增加 Cross-Validation (多源交叉验证) |
| **DeepSearchAgent** | ⚠️ **Mock** | **当前是模拟实现** (返回假数据)，无真实长文阅读能力 | 接入 `Firecrawl` 抓取 + 向量化阅读 |
| **MacroAgent** | ⚠️ 简易 | 仅关键词搜索，未对接 FRED/WorldBank 等专业库 | 集成专业宏观数据库 API |
| **TechnicalAgent** | ❌ **缺位** | 代码框架未实现 | 引入 `TA-Lib` 计算 MA/RSI/MACD |
| **FundamentalAgent**| ❌ **缺位** | 代码框架未实现 | 引入 `yfinance.financials` 进行杜邦分析 |

**架构风险**:
*   **Supervisor 瓶颈**: 目前所有子 Agent 都通过 Supervisor 串行/并行调度，如果 Supervisor 逻辑出错 (如 JSON 解析失败)，整个分析链会断裂。
*   **Context 丢失**: 子 Agent 之间尚未实现高效的 Memory 共享（如 TechnicalAgent 应该能看到 MacroAgent 的通胀结论）。

---
*文档将持续更新，记录项目核心技术演进。*
