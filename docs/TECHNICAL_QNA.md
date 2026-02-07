# FinSight 技术实现深度问答 (Technical Q&A)

> 📅 **创建日期**: 2026-01-09
> 📅 **更新日期**: 2026-01-13
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
    A["Yahoo Finance"] -->|失败/限流| B["Google Finance (Scraper)"]
    B -->|失败| C["Stooq API"]
    C -->|失败| D["CNBC/Finnhub"]
    D -->|全部失败| E["抛出异常/返回空"]
```

**设计要点**:
1.  **优先级**: 优先使用官方 API (Yahoo/Finnhub)，其次是稳定的 HTML 解析 (Google)，最后是备用源。
2.  **熔断器 (Circuit Breaker)**: 如果某个源连续失败（如 Yahoo 接口变动），`CircuitBreaker` 会自动“跳闸”，暂时屏蔽该源，直接请求下一个备用源，避免浪费时间在无效请求上。

---

## 🔮 架构演进篇

### Q5: RAG (检索增强生成) 是如何实现的？

**A**: RAG 基础设施已在 2026-01-12 完成，采用 **ChromaDB + Sentence Transformers** 方案：

**1. 向量存储层 (`backend/knowledge/vector_store.py`)**:
```python
class VectorStore:
    """ChromaDB 单例封装"""
    # 延迟加载，避免启动时阻塞
    def _get_embedding_fn(self):
        # 使用多语言模型，支持中英文
        self._embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

    def add_documents(self, collection_name, documents, metadatas, ids):
        # 向量化并存入 ChromaDB
        embeddings = self._embed_texts(documents)
        collection.add(documents=documents, embeddings=embeddings, ...)

    def query(self, collection_name, query_text, n_results=5):
        # 相似度检索，返回 Top-K 结果
        return collection.query(query_embeddings=query_embedding, n_results=n_results)
```

**2. RAG 引擎层 (`backend/knowledge/rag_engine.py`)**:
```python
class RAGEngine:
    def chunk_text(self, text, chunk_size=512, chunk_overlap=50):
        # 智能切片：句子边界检测 + 重叠窗口
        # 支持中英文句子结束符（。！？.）

    def ingest_document(self, collection_name, content, metadata):
        # 切片 -> 向量化 -> 入库

    def query_with_context(self, collection_name, query, top_k=5):
        # 检索 -> 格式化为 LLM 可用的上下文字符串
```

**3. 应用场景**:
- **DeepSearch 临时工作台**: 长文研报切片入库，任务结束后销毁
- **用户长期记忆**: 持久化存储用户偏好（计划中）

---

### Q6: 意图识别 (Intent Classification) 是如何工作的？

**A**: FinSight 采用 **Supervisor Agent 架构**，实现了业界标准的"三层混合"意图分类机制。

**架构流程**:
```
用户输入
    ↓
┌─────────────────────────────────────┐
│ 第一层：规则匹配（快速通道）          │
│ - "你好/帮助/退出" → 直接处理         │
│ - 多 ticker → 自动识别为对比         │
└─────────────────────────────────────┘
    ↓ 没匹配到
┌─────────────────────────────────────┐
│ 第二层：Embedding相似度 + 关键词加权  │
│ - 计算与各意图例句的相似度            │
│ - 关键词命中 → 加权 +0.12           │
│ - 相似度 >= 0.75 → 直接分类          │
└─────────────────────────────────────┘
    ↓ 置信度不够
┌─────────────────────────────────────┐
│ 第三层：LLM Router（兜底）           │
│ - 把候选意图告诉LLM                  │
│ - LLM做最终决策                      │
└─────────────────────────────────────┘
```

**关键设计原则**：关键词不是用来"匹配"的，而是用来**加权/提升置信度**：

```python
def _embedding_classify(self, query, query_lower, tickers):
    # 1. 先用 embedding 算语义相似度
    scores = self._embedding_classifier.compute_similarity(query)

    # 2. 关键词命中则加分（不是直接决定）
    for intent, keywords in KEYWORD_BOOST.items():
        if any(kw in query_lower for kw in keywords):
            scores[intent] += 0.12  # 加权，不是直接选择

    # 3. 选最高分，置信度不够则调用 LLM
    ...
```

**方案对比**:

| 方案 | 适用场景 | 准确率 | 成本 |
|------|---------|--------|------|
| 关键词匹配 | 快速通道、辅助加权 | 60-70% | 免费 |
| Embedding相似度 | 主力方案 | 80-90% | 低 |
| 微调分类模型 | 大规模生产 | 95%+ | 训练成本高 |
| LLM Router | 兜底、复杂场景 | 90%+ | 高 |

**FinSight 采用**: Embedding为主 + 关键词加权 + LLM兜底

**Embedding 模型**: `paraphrase-multilingual-MiniLM-L12-v2` (支持中英文，延迟加载)

**API 端点**:
- `/chat/supervisor` - 协调者模式对话
- `/chat/supervisor/stream` - 协调者模式流式对话

---

### Q7: NEWS 子意图分类 (Sub-intent Classification) 是如何实现的？

**A**: NEWS 意图采用 **子意图分类 (Sub-intent Classification)** 机制，区分"获取新闻"与"分析新闻影响"。

**背景问题**:
用户问"苹果新闻"和"分析苹果新闻影响"是两种不同需求：
- 前者只需返回新闻列表
- 后者需要 LLM 进行深度分析

**解决方案**:

**文件位置**: `backend/orchestration/supervisor_agent.py`

```python
def _classify_news_subintent(self, query: str) -> str:
    """
    NEWS 意图的子分类：区分"查询新闻"和"分析新闻"
    """
    query_lower = query.lower()

    # 分析类关键词（中英文）
    analyze_keywords = [
        # 中文分析词
        "分析", "影响", "解读", "意味", "评估", "看法", "观点",
        "走势", "预测", "解析", "深度", "详细", "怎么看", "会怎样",
        "带来", "导致", "造成", "引发", "说明", "反映", "表明",
        "利好", "利空", "机会", "风险", "趋势", "前景", "展望",
        # 英文分析词
        "analyze", "analysis", "impact", "effect", "implication",
        "interpret", "predict", "forecast", "outlook", "assess"
    ]

    # 检查是否包含分析类关键词
    for keyword in analyze_keywords:
        if keyword in query_lower:
            return "analyze"

    return "fetch"  # 默认返回查询类
```

**处理策略**:

| 子意图 | 处理方式 | 输出格式 |
|--------|---------|---------|
| `fetch` | `_handle_news()` - 返回原始新闻列表 | 新闻标题 + 链接 |
| `analyze` | `_handle_news_analysis()` - LLM 深度分析 | 新闻摘要 + 市场影响 + 投资启示 + 风险提示 |

**分析类输出结构** (`_handle_news_analysis()`):
```markdown
## 📰 相关新闻
[原始新闻列表]

---

## 🔍 深度分析

### 📰 新闻摘要
简要总结主要新闻事件

### 📊 市场影响分析
- **短期影响**：对股价/市场的即时影响预判
- **中长期影响**：潜在的持续性影响

### 🎯 投资启示
- 这些新闻对投资者意味着什么？

### ⚠️ 风险提示
- 新闻中隐含的风险因素
```

---

### Q8: ReportIR 构建与 Forum 分析解析是如何实现的？

**A**: ReportIR 构建采用 **优先解析 Forum 完整分析** 的策略，确保前端卡片能展示结构化的 8 节报告。

**核心方法**: `_build_report_ir()` 和 `_parse_forum_sections()`

**文件位置**: `backend/orchestration/supervisor_agent.py`

```python
def _parse_forum_sections(self, forum_text: str) -> list:
    """
    解析 Forum 的 8 节分析文本为结构化章节

    匹配模式: ### 1. 📊 执行摘要 或 ### 1. 执行摘要
    """
    section_pattern = r'###\s*(\d+)\.\s*([^\n]+)\n([\s\S]*?)(?=###\s*\d+\.|$)'
    matches = re.findall(section_pattern, forum_text)

    sections = []
    for match in matches:
        order, title, content = match
        # 清理标题中的 emoji
        clean_title = re.sub(r'[📊📈💰🌍⚠️🎯📐📅]\s*', '', title).strip()
        sections.append({"title": clean_title, "content": content.strip()})

    return sections


def _extract_executive_summary(self, forum_text: str) -> str:
    """从 Forum 分析中提取执行摘要作为卡片摘要"""
    patterns = [
        r'###\s*1\.\s*[📊]?\s*执行摘要[^\n]*\n([\s\S]*?)(?=###\s*2\.|$)',
        r'\*\*投资评级\*\*[：:]\s*([^\n]+)',
        r'\*\*核心观点\*\*[：:]\s*([^\n]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, forum_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:500]
    return forum_text[:500]
```

**构建优先级**:
1. **优先**: 解析 Forum 的 8 节分析 (`_parse_forum_sections()`)
2. **Fallback**: 从各 Agent 输出构建章节 (当 Forum 解析失败时)

**ReportIR 数据结构**:
```json
{
  "report_id": "report_abc12345",
  "ticker": "AAPL",
  "title": "AAPL 深度分析报告",
  "summary": "执行摘要内容...",
  "sentiment": "bullish",
  "confidence_score": 0.85,
  "sections": [
    {
      "title": "执行摘要",
      "order": 1,
      "agent_name": "ForumHost",
      "confidence": 0.85,
      "contents": [{"type": "text", "content": "..."}]
    }
  ],
  "citations": [...],
  "risks": [...],
  "agent_status": {"price": {"status": "success"}, ...}
}
```

---

### Q9: 多轮对话上下文管理是如何实现的？

**A**: 系统实现了 **前端传递 + 后端提取** 的上下文管理机制。

**前端** (`ChatInput.tsx`):
```typescript
// 发送最近 6 条消息作为对话历史
const history = messages.slice(-6).map(msg => ({
  role: msg.type === 'user' ? 'user' : 'assistant',
  content: msg.content
}));

await sendMessageStream(input, { history });
```

**后端提取** (`SupervisorAgent._extract_context_info()`):
```python
def _extract_context_info(self, conversation_context: List[Dict]) -> tuple:
    """从对话历史中提取股票代码和摘要"""
    ticker_pattern = r'\b([A-Z]{1,5})\b'
    url_pattern = r'https?://[^\s\)\]<>"\']+'

    found_tickers = []
    context_parts = []

    for msg in conversation_context[-4:]:  # 最近 4 条
        content = msg.get("content", "")
        # 提取股票代码（过滤停用词）
        matches = re.findall(ticker_pattern, content)
        stopwords = {'A', 'I', 'AM', 'PM', 'AI', 'CEO', 'IPO', ...}
        found_tickers.extend([m for m in matches if m not in stopwords])
        # 构建摘要
        preview = content[:150] + "..." if len(content) > 150 else content
        context_parts.append(f"{role}: {preview}")

    return "\n".join(context_parts), found_tickers[-1] if found_tickers else None
```

**上下文感知特性**:
- **指代消解**: "它的新闻" → 从上下文提取之前讨论的股票
- **智能忽略**: REPORT 意图会检测上下文中的 ticker 是否与当前相关
- **LLM 增强**: 简单意图（如 PRICE）会结合上下文生成更相关的回复

---

### Q10: 子 Agent (Sub-agents) 目前存在哪些缺陷？

**A**: 架构设计了 6 大专家 Agent，目前大部分已实现：

| Agent | 状态 | 核心能力 | 改进计划 |
|-------|------|----------|----------|
| **PriceAgent** | ✅ 可用 | 多源回退行情查询 | 接入 WebSocket 实时数据流 |
| **NewsAgent** | ✅ 可用 | 反思循环 + RSS + Finnhub | 增加 Cross-Validation (多源交叉验证) |
| **TechnicalAgent** | ✅ 可用 | MA/RSI/MACD 技术指标 | 增加更多形态识别 |
| **FundamentalAgent** | ✅ 可用 | PE/PB/现金流/杠杆分析 | 增加 DCF 估值模型 |
| **DeepSearchAgent** | ✅ 可用 | 真实检索 + PDF + Self-RAG | 集成 RAGEngine 向量化 |
| **MacroAgent** | ✅ 可用 | FRED API 宏观经济数据 | 增加更多经济指标 |
| **RiskAgent** | ❌ **待实现** | VaR 计算、仓位诊断 | Phase 3 计划 |

**架构风险**:
*   **Supervisor 瓶颈**: 目前所有子 Agent 都通过 Supervisor 串行/并行调度，如果 Supervisor 逻辑出错 (如 JSON 解析失败)，整个分析链会断裂。
*   **Context 丢失**: 子 Agent 之间尚未实现高效的 Memory 共享（如 TechnicalAgent 应该能看到 MacroAgent 的通胀结论）。

---

### Q8: MacroAgent 如何获取宏观经济数据？

**A**: MacroAgent 在 2026-01-12 升级为真实 FRED API 数据驱动：

**数据源**: 美联储经济数据库 (FRED - Federal Reserve Economic Data)

**支持的指标**:
| 指标 | Series ID | 说明 |
|------|-----------|------|
| CPI 通胀率 | CPIAUCSL | 消费者价格指数 |
| 联邦基金利率 | FEDFUNDS | 美联储基准利率 |
| GDP 增长率 | GDP | 国内生产总值 |
| 失业率 | UNRATE | 劳动力市场指标 |
| 10年期国债 | GS10 | 长期利率基准 |
| 收益率曲线 | T10Y2Y | 10Y-2Y 利差 |

**特性**:
- 自动检测收益率倒挂（recession_warning）
- 结构化输出多条 evidence 项
- 支持 `FRED_API_KEY` 环境变量配置

```python
# backend/tools.py
def get_fred_data(series_id: str = None) -> Dict[str, Any]:
    """获取 FRED 宏观经济数据"""
    # 支持单指标或全量获取
    # 返回格式化数据 + recession_warning 标志
```
