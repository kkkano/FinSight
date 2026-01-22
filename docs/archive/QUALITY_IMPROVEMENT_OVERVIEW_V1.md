# QUALITY_IMPROVEMENT_OVERVIEW

> 角色：Quality Assurance Architect
> 范围：后端核心 Agent（News/Macro/DeepSearch）、编排与报告流水线、前端报告展示可信度
> 参考：`docs/Thinking/*`，`docs/01_ARCHITECTURE.md`，`docs/02_PHASE0_COMPLETION.md`，`docs/03_PHASE1_IMPLEMENTATION.md`，`docs/04_PHASE2_DEEP_RESEARCH.md`，`docs/05_RAG_ARCHITECTURE.md`，`docs/05_PHASE3_ACTIVE_SERVICE.md`，`docs/ROADMAP.md`，`docs/PROJECT_STATUS.md`，`docs/REPORT_CHART_SPEC.md`

## 更新摘要（2026-01-22）

- 论坛冲突检测 + 反思补检链路落地（ForumHost + BaseFinancialAgent）
- SSRF 防护扩展到 DeepSearch 与 `fetch_url_content`
- 工具层统一连接池 + Retry，缓存抖动/负缓存补齐
- CircuitBreaker 分源阈值、Trace 规范化与 `/metrics` 入口
- pytest 路径统一（`backend/tests` + `test/`）

## 0. 执行摘要（Executive Summary）
结合 `docs/Thinking` 中对“证据链不足、数据源单薄、Macro/DeepSearch 深度不够”的诊断，以及 01-05 阶段文档的当前架构与 Roadmap，本次代码审阅的关键结论如下：

1) **可信度与可复核性仍是主瓶颈**。后端多个关键路径仍以“文本拼接 + 正则解析”传递数据（尤其是新闻与回退搜索），导致 Evidence 与 ReportIR 的结构化链路不稳定，前端的可信度呈现仅基于数量与单一分数，缺少“来源权重 + 证据质量”解释。用户能看见报告，但难以“复核”。
2) **异步边界混用存在运行时风险**。SSE 流式回退路径直接调用同步 `agent.chat()`，而该路径内部仍有 `asyncio.run()`；在事件循环中易触发 RuntimeError 或长时间阻塞，属于 P0 级可靠性风险。
3) **数据源覆盖面与回退路径仍偏“通用检索”**。MacroAgent 目前核心数据只依赖 FRED API，一旦失败回退为普通搜索文本，难以满足“经济日历/预期差/全球宏观”的分析质量目标；NewsAgent 的数据源结构化不足，去重与权重逻辑分散在多层，导致信息质量波动。
4) **可维护性与可观测性还不够**。`backend/tools.py` 超 3k 行、职责混杂；关键异常被 `pass` 吞掉，错误无法回溯；缓存没有容量边界，长期运行有内存漂移风险。

下面给出证据、重构对比与可执行行动计划（优先使用免费层 API），并补充前端可信度增强策略。

## 1. 核心流程分析（Mermaid Visualization）

### Current Workflow（当前现状）
```mermaid
flowchart TD
    U[User Query] --> API[/chat or /chat/stream]
    API --> CA[ConversationAgent]
    CA --> R[ConversationRouter]

    R -->|REPORT| RH[ReportHandler]
    R -->|CHAT| CH[ChatHandler]

    RH --> ORC[ToolOrchestrator]
    ORC --> TOOLS[backend/tools.py]
    TOOLS --> NEWS[News: yfinance/finnhub/alpha_vantage/search]
    TOOLS --> MACRO[Macro: FRED or search]

    RH --> DS[DeepSearchAgent]
    DS --> WEB[Search -> Fetch URL -> Parse]

    RH --> IR[ReportIR]
    IR --> FE[ReportView]

    CH --> FE
```

### Optimized Workflow（优化后建议）
```mermaid
flowchart TD
    U[User Query] --> API[/chat or /chat/stream]
    API --> CA[ConversationAgent (async-safe)]
    CA --> R[Intent Router]

    R -->|REPORT| RH[ReportHandler Async]
    RH --> PIPE[Structured Data Pipeline]
    PIPE --> SRC[Source Registry & Free-tier APIs]
    PIPE --> NORM[Schema Normalizer/DTO]
    PIPE --> SCORE[Evidence Scorer & Source Weight]
    PIPE --> RAG[RAG/Doc Store for DeepSearch]

    PIPE --> IR[ReportIR + Evidence Map]
    IR --> FE[ReportView: Credibility UI]

    R -->|CHAT| CH[ChatHandler]
    CH --> FE
```

## 2. 问题诊断与证据（Diagnosis & Evidence）

### 2.1 异步/同步边界混用导致潜在崩溃与阻塞（P0）
- **位置**：`backend/handlers/report_handler.py:67-83`，`backend/api/main.py:731-737`，`backend/conversation/agent.py:596-615`
- **问题描述**：在异步 SSE 路径内调用同步 `agent.chat()`，而 `agent.chat()` 的报告分支仍会触发 `asyncio.run()`。在已有事件循环中执行 `asyncio.run()` 会抛 RuntimeError 或阻塞主 loop。该问题会在高并发或长报告场景下被放大。
- **证据**：
```python
# backend/handlers/report_handler.py:67-83
result = asyncio.run(agent.research(query, ticker))
```
```python
# backend/api/main.py:731-737
result = agent.chat(resolved_query, capture_thinking=True)
```
```python
# backend/conversation/agent.py:596-615
try:
    return asyncio.run(self._handle_report_async(query, metadata))
except Exception as e:
    print(f"[Agent] Supervisor 调用失败: {e}")
```
- **影响**：SSE 回退路径会阻塞事件循环，导致 token 延迟、连接断开或 API 500；并且该错误只在运行期暴露，难以提前发现。

### 2.2 新闻链路“字符串格式 + 正则解析”导致结构化脆弱（P0）
- **位置**：`backend/tools.py:1913-1995`，`backend/agents/news_agent.py:22-107`
- **问题描述**：`get_company_news()` 输出的是格式化文本字符串，NewsAgent 再用正则解析为结构化数据。此链路一旦格式变更或源文本噪声增加，解析会失败，证据条目缺失。
- **证据**：
```python
# backend/tools.py:1913-1995
return f"Latest News ({ticker}):\n" + "\n".join(news_list)
```
```python
# backend/agents/news_agent.py:68-107
lines = news_text.split('\n')
url_match = re.search(r'\[([^\]]+)\]\(([^)]+)\)', line)
```
- **影响**：Evidence 与 ReportIR 的结构化稳定性下降，导致前端可信度展示（引用、来源）不完整，且 Debug 难度增加。

### 2.3 MacroAgent 数据覆盖面窄，回退为非结构化搜索（P1）
- **位置**：`backend/agents/macro_agent.py:20-48`
- **问题描述**：MacroAgent 仅依赖 FRED；失败时回退为搜索文本。缺少经济日历、预期值、全球宏观与行业宏观数据，难以实现“预期差”分析。
- **证据**：
```python
# backend/agents/macro_agent.py:31-48
fred_data = self.tools.get_fred_data()
...
search_result = self.tools.search("current US CPI inflation rate federal funds rate unemployment")
```
- **影响**：宏观分析可信度与覆盖面不足，与 docs/Thinking 中“宏观日历/全球宏观”目标存在差距。

### 2.4 异常被吞导致可观测性断裂（P1）
- **位置**：`backend/handlers/chat_handler.py:1163-1169`，`backend/handlers/followup_handler.py:258-286`，`backend/conversation/context.py:305-309`
- **问题描述**：关键路径存在 `except: pass` 或空处理，导致错误根因无法定位，后续只能看到“缺数据/回退”。
- **证据**：
```python
# backend/handlers/chat_handler.py:1163-1169
except:
    pass  # 忽略获取价格时的异常
```
```python
# backend/handlers/followup_handler.py:258-286
except Exception:
    pass
```
- **影响**：生产问题不可追踪、数据质量波动无迹可查，回退路径被动触发。

### 2.5 ToolOrchestrator 阻塞式节流与串行调用（P1）
- **位置**：`backend/orchestration/orchestrator.py:331`
- **问题描述**：在 fetch 循环中使用 `time.sleep(0.3)` 进行节流，若在同步路径执行，会阻塞请求线程；缺少异步限流器与并发控制策略。
- **证据**：
```python
# backend/orchestration/orchestrator.py:331
time.sleep(0.3)
```
- **影响**：高并发时吞吐受限，且 SSE 流式路径更容易出现卡顿。

### 2.6 DataCache 无容量上限与定期清理（P1）
- **位置**：`backend/orchestration/cache.py:46-103`
- **问题描述**：缓存采用 dict 持续增长，缺少 max_size 与定期清理调度，长期运行有内存增长风险。
- **证据**：
```python
# backend/orchestration/cache.py:46-103
self._cache: Dict[str, CacheEntry] = {}
...
self._cache[key] = CacheEntry(...)
```
- **影响**：内存不可控，服务运行时间越长越不稳定。

### 2.7 DeepSearch 对外部 URL 无校验（SSRF 风险）（P1）
- **位置**：`backend/agents/deep_search_agent.py:362-371`
- **问题描述**：DeepSearch 直接对搜索结果 URL 发起请求，未做私网/本地地址过滤与 allowlist，存在 SSRF 风险。
- **证据**：
```python
# backend/agents/deep_search_agent.py:362-371
response = requests.get(url, headers=headers, timeout=15)
response.raise_for_status()
```
- **影响**：若被恶意 URL 引导，可能访问内网资源或 metadata 服务。

### 2.8 前端可信度展示仅基于数量与单一分数（P1）
- **位置**：`frontend/src/components/ReportView.tsx:14-29`，`frontend/src/components/ReportView.tsx:99-108`
- **问题描述**：前端主要展示“confidence percent”与“来源域名数量统计”，未解释来源权重、证据质量、冲突点或时效性。
- **证据**：
```tsx
// frontend/src/components/ReportView.tsx:14-29
const confidencePercent = Math.round(confidence * 100);
```
```tsx
// frontend/src/components/ReportView.tsx:99-108
citations.forEach((citation) => {
  const domain = extractDomain(citation.url);
  counts.set(domain, (counts.get(domain) || 0) + 1);
});
```
- **影响**：用户无法判断“可信度为何高/低”，与 docs/Thinking 中“证据链说服力不足”的结论一致。

### 2.9 置信度硬编码缺少证据权重（P1）
- **位置**：`backend/agents/news_agent.py:176-184`
- **问题描述**：NewsAgent 仅凭“有无证据”直接给出固定 confidence。未区分来源可信度、时间新鲜度、重复度等质量因子。
- **证据**：
```python
# backend/agents/news_agent.py:176-184
confidence=0.8 if evidence else 0.1
```
- **影响**：可信度数值难以解释，前端展示很难增强用户信任。

## 3. 改进方案对比（Before & After）

### 3.1 异步边界修复：统一 Async API
**Before**（ReportHandler 中直接 `asyncio.run`）：
```python
# backend/handlers/report_handler.py:67-83
result = asyncio.run(agent.research(query, ticker))
```

**After**（统一 Async Handler + sync wrapper，仅在 CLI 使用）：
```python
class ReportHandler:
    async def handle_async(self, query, metadata, context):
        ...
        deepsearch_output = await self._run_deepsearch_async(query, ticker)
        ...

    async def _run_deepsearch_async(self, query, ticker):
        agent = DeepSearchAgent(self.llm, cache, self.tools_module, circuit_breaker)
        return await agent.research(query, ticker)

    def handle(self, query, metadata, context):
        # 同步环境才允许 asyncio.run
        return asyncio.run(self.handle_async(query, metadata, context))
```
**Rationale**：将“事件循环边界”集中到顶层，避免 `asyncio.run()` 在 loop 内调用；采用 **Async Boundary** 模式减少阻塞。

### 3.2 新闻结构化改造：DTO + Adapter
**Before**（文本格式化 + 正则解析）：
```python
# backend/tools.py:1913-1995
return f"Latest News ({ticker}):\n" + "\n".join(news_list)
```

**After**（统一 NewsItem 数据结构）：
```python
@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_at: str
    snippet: str = ""

# tools.py
def get_company_news(ticker: str) -> List[NewsItem]:
    ...
    return items

# news_agent.py
items = self.tools.get_company_news(ticker)
results.extend([item.__dict__ for item in items])
```
**Rationale**：使用 **DTO/Adapter** 模式统一数据结构，消除格式化文本解析的不确定性；便于后续打分、去重与可视化。

### 3.3 异常处理与可观测性：显式记录与追踪
**Before**（异常被吞）：
```python
# backend/handlers/chat_handler.py:1163-1169
except:
    pass
```

**After**（结构化日志 + 轻量 trace）：
```python
except Exception as exc:
    logger.exception("price_fetch_failed", extra={"ticker": ticker1})
    trace.append({"stage": "price_fetch", "error": str(exc)})
```
**Rationale**：使用 **Structured Logging** 和可回溯 trace，降低“静默失败”风险，便于诊断和 SLA 统计。

## 4. 引用与权威背书（References）
- Python asyncio.run 文档：<https://docs.python.org/3/library/asyncio-task.html#asyncio.run>
- asyncio.to_thread 官方说明：<https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread>
- FastAPI 异步与阻塞调用建议：<https://fastapi.tiangolo.com/async/>
- HTTPX AsyncClient：<https://www.python-httpx.org/async/>
- Tenacity 重试策略：<https://tenacity.readthedocs.io/en/latest/>
- Circuit Breaker（Martin Fowler）：<https://martinfowler.com/bliki/CircuitBreaker.html>
- Cachetools TTLCache：<https://cachetools.readthedocs.io/en/latest/#cachetools.TTLCache>
- Python Logging 指南：<https://docs.python.org/3/library/logging.html>
- OWASP SSRF 防护清单：<https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html>
- ECharts Option 规范：<https://echarts.apache.org/en/option.html>

## 5. 执行计划（Action Plan）

### P0（0-2 周）：可靠性与证据链优先
- [ ] **异步边界统一**：将 ReportHandler/DeepSearch 迁移至 `handle_async`，SSE fallback 路径使用 `await agent.chat_async`，避免 `asyncio.run` 在 loop 内触发。
- [ ] **新闻结构化输出**：`get_company_news` 改为结构化 NewsItem 列表；NewsAgent/ReportHandler/ReportIR 使用统一 schema。
- [ ] **SSRF 风险控制**：对 DeepSearch 目标 URL 做私网与保留地址过滤，建立 allowlist（或 blocklist）策略。
- [ ] **异常记录与 trace**：移除 `except: pass`，为关键链路增加结构化日志与 trace 字段。

### P1（2-4 周）：覆盖面与可维护性
- [ ] **Macro 扩展（免费层优先）**：引入 Economic Calendar（TradingEconomics 免费层/公开日历抓取），补充 IMF/WorldBank 数据；并将“实际值 vs 预期值”纳入输出。
- [ ] **Source 权重体系**：为 Reuters/Bloomberg/FED/FOMC 等设置权重标签；ReportIR 增加 `evidence_quality` 与 `source_tier`。
- [ ] **tools.py 拆分与统一 HTTP 客户端**：将 `backend/tools.py` 拆为 `news.py`/`macro.py`/`price.py`，引入统一重试与超时策略。
- [ ] **缓存容量上限**：使用 TTL+LRU（cachetools）或加入 max_size 与定时清理。

### P2（4-8 周）：可解释性与体验强化
- [ ] **RAG 与报告一致性**：将 DeepSearch/RAG 的 evidence 统一映射到 ReportIR citations，确保前端引用可追溯。
- [ ] **前端可信度增强 UI**：新增“来源权重/时效性/证据数”的可视化条、冲突点列表、证据链引用（Evidence Map）。
- [ ] **质量评估基准**：建立 Golden Set（示例问题 + 期望结构化输出），进行回归与对比评估。

### 验证策略（单元/集成/回归）
- **单元测试**：
  - NewsItem schema + dedupe + source tier 评分（新增 `test_news_schema.py`）。
  - SSRF 过滤（构造内网/本地/保留 IP URL）。
- **集成测试**：
  - `/chat/stream` 报告路径验证：确保无 `RuntimeError: asyncio.run()`；SSE token 流不中断。
  - MacroAgent 输出验证：必须包含 `actual/forecast` 字段与来源标注。
- **回归测试**：
  - ReportIR 渲染稳定性（对照 `docs/REPORT_CHART_SPEC.md` 的 chart 输出）。
  - 前端可信度展示：确保来源权重与证据链可视化不回退为仅“计数”。

---

以上改进路径与 `docs/Thinking` 的优先级（先增强数据与证据，再做结构与交互）保持一致，同时与 `docs/ROADMAP.md` 的阶段性目标可无缝对齐。建议优先推进 P0，以稳定核心链路与可信度呈现。
