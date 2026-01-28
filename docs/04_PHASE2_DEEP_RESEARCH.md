# FinSight 阶段2：深度研报与按需调用

> **计划周期**: Week 5 - Week 6
> **更新日期**: 2026-01-28
> **核心目标**: 生产"卖方分析师"级别的深度研报 (Deep Research)
>
> **近期同步**:
> - ReportIR citations 增加 confidence / freshness_hours 字段（P0-2）
> - News/Macro 回退结构化输出，避免 raw 文本进入报告（P0-3）
> - get_company_news 改为结构化列表，NewsAgent/SupervisorAgent 同步适配（P1-1）
> - SSRF 防护扩展至 DeepSearch + fetch_url_content（P1-2）
> - pytest 收集 backend/tests + test/（不再标记 legacy）
> - PlanIR + Executor 与 EvidencePolicy 落地（计划模板/执行 trace/引用校验）
> - DataContext 统一 as_of/currency/adjustment 并输出一致性告警（P0-27）
> - BudgetManager 限制工具调用/轮次/耗时预算，预算快照可追溯（P0-28）
> - SecurityGate：鉴权 + 限流 + 免责声明模板落地（P0-29）
> - Cache 抖动 + 负缓存，CircuitBreaker 支持分源阈值
> - Trace 规范化输出 + /metrics 可观测性入口

> - Split backend/tools.py into backend/tools/ (search/news/price/financial/macro/web); keep backend.tools compatibility
> - Config entry unified: backend/llm_config.py uses user_config.json > .env; llm_service uses same source
> - Core backend logging migrated from print to logging (API/Agents/Services/Orchestration)
> - SchemaToolRouter: one-shot LLM tool selection + schema validation + ClarifyTool templates (USE_SCHEMA_ROUTER)
---

## 0.1 Recent Updates (2026-01-28)

- Evidence pool exposed for chat/report to make research traceable
- News output adds short “overall summary” and relevance filtering
- Search fallback avoids Wikipedia for finance; RSS/Finnhub preferred
- Multi-ticker comparison auto-renders multiple charts
- NEWS intent fast-path reduces misclassification to generic search

## 0. 当前状态（2026-01-11）

- /chat/stream 全意图真实 token 流式输出已完成（含 REPORT done 事件 ReportIR）
- /chat 与 /chat/stream 已接入异步 Supervisor 与指代消解
- Phase 1 技术/基本面 Agent 已补齐，ReportIR Schema/Validator 已完成，DeepSearch 真实检索 + PDF + Self-RAG 已落地，重点转向 Macro 升级与前端结构化卡片优化

## 1. 核心任务拆解

### 1.1 中间表示层 (IR)
- [x] **ReportIR Schema**: 定义 `backend/report/ir.py`。
- [x] **IR Validator**: 确保生成的 JSON 结构完整，避免前端渲染报错。
- [x] **ReportIR Chart Option Spec**: 统一 chart 输出规范（见 `docs/REPORT_CHART_SPEC.md`，2026-01-11）。

### 1.2 按需 Agent (On-Demand Agents)
- [x] **DeepSearchAgent**:
    - **触发**: 当 NewsAgent 信息量不足 (<3 条) 或用户明确要求"深度分析"时。
    - **能力**: 真实检索 + PDF 解析，支持 Self-RAG 反思检索与二次补检。
- [x] **MacroAgent**: 已完成 (2026-01-12)
    - **触发**: 提问涉及"美联储"、"加息"、"通胀"等宏观词汇。
    - **能力**: 调用 FRED API 获取实时经济数据（CPI、联邦基金利率、GDP、失业率、10年期国债、收益率曲线）。
    - **特性**: 自动检测衰退预警信号（收益率倒挂）。

### 1.3 前端升级
- [x] **结构化渲染**: `ReportView.tsx` 已对齐 design_concept_v2.html，支持章节折叠、来源跳转。
- [x] **置信度可视化**: 置信度进度条已接入 ReportView，支持即时展示。
- [x] **交互细化**: 章节定位 + 滚动高亮 + 引用联动 + ECharts 图表渲染已接入。
- [x] **订阅邮箱接入**: Report 卡片订阅按钮使用 Settings 邮箱（避免 prompt）。

---

## 2. 深度搜索策略

### 2.1 "广撒网，精捕捞"
1.  **Broad Search**: `Tavily` 搜索 "AAPL investment thesis 2025"。
2.  **Freshness Gate**: 优先采用 Reuters/Bloomberg RSS + Finnhub 48h 的新鲜信号，过期条目触发补检。
3.  **Filter**: 这里的 URL 哪些是权威媒体（WSJ, Bloomberg）？哪些是水文？
4.  **Deep Read**: 对筛选出的前 3 篇文章进行全文抓取 (`Jina Reader` 或 `Firecrawl`)。
5.  **Synthesize**: 结合长上下文窗口生成深度观点。

### 2.2 宏观联动
- 如果 `MacroAgent` 发现最近处于"加息周期"，自动调低所有成长股的评级。
- 这是一个跨 Agent 的 Context 共享机制。

---

## 3. 验收标准

1.  **研报质量**: 生成的报告必须包含至少 2 个"非显而易见"的观点（Insight），不仅仅是新闻堆砌。
2.  **来源可溯**: 每一个论点（Point）必须附带至少 1 个可点击的引用链接（Citation）。
3.  **鲁棒性**: 即使 `DeepSearch` 失败，也能优雅降级为普通新闻摘要，不报错。

---

## 4. 补充更新（2026-01-12）

### 4.1 MacroAgent 升级 - FRED API 集成

**实现内容**：
- **tools.py**: 新增 `get_fred_data()` 函数，支持 FRED API 调用
- **macro_agent.py**: 重写为真实数据驱动，不再依赖模拟数据

**支持的经济指标**：
| 指标 | Series ID | 说明 |
|------|-----------|------|
| CPI 通胀率 | CPIAUCSL | 消费者价格指数 |
| 联邦基金利率 | FEDFUNDS | 美联储基准利率 |
| GDP 增长率 | GDP | 国内生产总值 |
| 失业率 | UNRATE | 劳动力市场指标 |
| 10年期国债 | GS10 | 长期利率基准 |
| 收益率曲线 | T10Y2Y | 10Y-2Y 利差（衰退预警） |

**特性**：
- 自动检测收益率倒挂（recession_warning）
- 结构化输出多条 evidence 项
- 支持 `FRED_API_KEY` 环境变量配置

### 4.2 Vector RAG 基础设施

**新增模块**: `backend/knowledge/`

```
backend/knowledge/
├── __init__.py          # 模块导出
├── vector_store.py      # ChromaDB 封装（单例模式）
└── rag_engine.py        # RAG 引擎（切片+检索）
```

**VectorStore 特性**：
- ChromaDB 持久化客户端（自动回退内存模式）
- Sentence Transformers 本地 Embedding（`paraphrase-multilingual-MiniLM-L12-v2`）
- 支持临时集合（DeepSearch 工作台）和持久化集合（用户记忆）

**RAGEngine 特性**：
- 智能文档切片（句子边界检测 + 重叠窗口）
- 批量入库与相似度检索
- `query_with_context()` 直接返回 LLM 可用的上下文字符串

**依赖**：
```
chromadb>=0.4.0
sentence-transformers>=2.2.0
```
