


<h1 align="center">FinSight AI</h1>

<p align="center">
  <strong>基于 LangGraph 的多智能体金融研究平台</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> |
  <a href="./readme_cn.md">中文</a> |
  <a href="./docs/DOCS_INDEX.md">文档索引</a>
</p>

---

**FinSight AI** 是一个生产级多智能体金融研究系统，基于 **LangGraph** 构建。它将对话式 AI 分析、6 标签页专业仪表盘、自主任务执行（工作台）和邮件主动预警统一在一个平台中。

> 7 个研究智能体（自主多工具）· 1 个 Synthesize 节点（冲突检测 + 幻觉防护 + compare_gate 证据校验）· 5 个仪表盘评分器（按标签页生成 AI 卡片）| 混合 RAG（bge-m3）| 实时 ECharts 图表 | LLM 驱动智能图表 | 8 组智能体交叉冲突检测 | 邮件订阅预警

---

## 目录

- [核心特性](#-核心特性)
- [平台预览](#-平台预览)
- [系统架构](#%EF%B8%8F-系统架构)
- [LangGraph 管线](#-langgraph-管线18-节点)
- [智能体生态](#-智能体生态)
- [仪表盘](#-仪表盘--6-个分析标签页)
- [RAG 引擎](#-rag-引擎--混合检索管线)
- [智能图表](#-智能图表--llm-驱动可视化)
- ["问这条"功能](#-问这条)
- [冲突检测](#%EF%B8%8F-冲突检测)
- [邮件预警与订阅](#-邮件预警与订阅)
- [Phase Labs（Phase 1–4）](#-phase-labsphase-14)
- [数据与存储架构](#-数据与存储架构)
- [缓存系统](#%EF%B8%8F-缓存系统)
- [记忆与用户档案](#-记忆与用户档案)
- [韧性与回退](#%EF%B8%8F-韧性与回退)
- [幻觉抑制](#-幻觉抑制)
- [技术栈](#-技术栈)
- [快速开始](#-快速开始)
- [项目结构](#-项目结构)

---

## ✨ 核心特性

| 类别 | 亮点 |
|------|------|
| **多智能体协作** | 7 个专业研究智能体（价格、新闻、基本面、技术面、宏观、风险、深度搜索）支持并行执行组 |
| **LangGraph 管线** | 18 节点有状态图，处理聊天、快速分析和深度投研报告，自适应路由 |
| **专业仪表盘** | 6 个分析标签页（总览、财务、技术、新闻、研究、同行）配 ECharts 可视化 |
| **AI 驱动洞察** | 5 个仪表盘评分器通过单次 LLM 调用 + 确定性规则回退，为每个标签页生成实时 AI 分析卡片（每个 1-3 秒） |
| **混合 RAG 引擎** | bge-m3（1024 维 Dense + Sparse）+ bge-reranker-v2-m3 交叉编码器精排 |
| **智能图表** | 双模式 LLM 图表：`<chart>`（内联数据）+ `<chart_ref>`（真实数据引用） |
| **冲突检测** | 自动跨智能体冲突分析，涵盖 8 组可比较维度 |
| **主动预警** | 3 个预警调度器（价格、新闻、风险），通过 SMTP 邮件通知 |
| **工作台** | 自主任务执行、投资组合再平衡（LLM 增强 + SSE 流式进度）、研报时间线、快速分析入口 |
| **"问这条"** | 上下文感知的后续提问——可对任意新闻、洞察或风险条目直接追问 |
| **思考气泡** | 三层执行展示：思考气泡（打字机效果）→ Agent 摘要卡片 → 详细时间线 |
| **一键晨报管线** | 持仓晨报接入 LangGraph Pipeline，确定性合成（零 LLM 成本），带 30 分钟缓存 |
| **调仓 LLM 增强** | Agent 数据 + LLM 优先级精调，为调仓建议提供增强理由与证据快照 |
| **幻觉防御** | 多层洗涤：正则模式匹配 + 证据交叉验证 LLM 输出 |
| **对话式价格提醒** | 聊天驱动设置提醒 —— 说"AAPL 跌破 180 提醒我" → 自动提取、落库、调度触发（Phase 1）|
| **智能选股** | 自然语言多条件选股筛选；含 CN/HK 覆盖边界 `capability_note` 提示（Phase 2）|
| **A 股市场数据** | 北向/南向资金流向、板块热力图、概念板块涨跌排行，覆盖 A 股 & 港股（Phase 3）|
| **策略回测** | SMA 双均线、MACD、RSI 策略；支持 T+1 结算、成本/滑点建模、前视偏差防护（Phase 4）|

---

## 📸 平台预览

<p align="center">
  <img src="images/cb70fece-c319-4964-91fc-d7be91211b91.png" alt="FinSight AI Dashboard" width="100%"/>
</p>


<p align="center">
  <img src="images/4dc0e95c-2963-4422-ba3e-d86a3788b4b1.png" alt="FinSight AI 仪表盘" width="100%"/>
</p>

<table>
<tr>
<td width="50%">

**总览标签** — AI 评分环、恐贪指数、智能体覆盖、风险指标


</td>
<td width="50%">

**财务标签** — 8 季度盈利图、EPS 惊喜、分析师目标价

<img src="images/12e7daa8071f4983b85e578bbca7a0e1.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**技术标签** — K 线蜡烛图、RSI、MACD、支撑/阻力位

<img src="images/7dd48dd6d1d3b1aa6e7b3d33e1dcc492.png" width="100%"/>
</td>
<td width="50%">

**新闻标签** — AI 新闻摘要、情绪条、标签筛选、富新闻卡片

<img src="images/48f1bedaef4381457d3ad98e5ae80201.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**同行标签** — PE/营收增长对比、详细指标表

<img src="images/060fdf7b3d8f93ebda65cb3daaaacf21.png" width="100%"/>
</td>
<td width="50%">

**研究标签** — 多智能体深度分析、冲突矩阵、引用追踪

<img src="images/3e47bb167c44c8f9cdcb23b20f905ada.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**思考过程 — 用户视图** — 折叠式推理节点（逻辑查图 / 规划策略 / 执行分析）

<img src="images/2b674275d75b4838f1e77de5d5980dfc.png" width="100%"/>
</td>
<td width="50%">

**执行时间线 + 分析师摘要卡片** — 逐 Agent 步骤追踪、11 智能体完成网格

<img src="images/78247136de4dd9db0d96c6ca5f574e3f.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**对话 + "问这条"** — 对话式 AI + 持仓面板

<img src="images/chat-report.png" width="100%"/>
</td>
<td width="50%">

**深度研究报告** — 智能体置信度、催化剂、风险提示

<img src="images/report1.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**工作台** — 任务执行、组合再平衡、研报时间线

<img src="images/workbench.png" width="100%"/>
</td>
</tr>
</table>

<details>
<summary>更多截图</summary>

| 对话内联图表 | 控制台 & SSE 事件 |
|:-:|:-:|
| ![对话报告](images/019a9f4cfab8326ea62828c13c4d6aca.png) | ![控制台](images/console.png) |

| 研究报告（完整版） | 大宗商品分析 |
|:-:|:-:|
| ![研究](images/a2970ffd1a178745f2c65b40a7d9f7b3.png) | ![黄金分析](images/ceb05773fea497b36b11f34ef68313a2.png) |

</details>

---

## 🏗️ 系统架构

```mermaid
graph TB
    subgraph "前端 (React + Vite)"
        UI[仪表盘 / 对话 / 工作台]
        STORE[Zustand 状态管理<br/>dashboardStore · executionStore · useStore]
        API_CLIENT[API 客户端<br/>SSE parseSSEStream]
    end

    subgraph "后端 (FastAPI)"
        ROUTER[API 路由<br/>chat · dashboard · execute · alerts]
        GRAPH[LangGraph 管线<br/>18 节点有状态图]
        AGENTS[智能体层<br/>7 研究智能体 + 5 洞察评分器]
        TOOLS[工具层<br/>32 个注册工具]
        SYNTH[合成节点<br/>冲突检测 · 幻觉洗涤]
    end

    subgraph "数据层"
        RAG[混合 RAG<br/>bge-m3 · 精排器]
        CACHE[仪表盘缓存<br/>16 类 TTL]
        MEMORY[记忆存储<br/>按用户 JSON]
        DB[(SQLite / PostgreSQL<br/>检查点 · 报告 · 持仓)]
    end

    subgraph "外部服务"
        YFINANCE[yfinance]
        FMP[FMP API]
        FINNHUB[Finnhub]
        TAVILY[Tavily / Exa / DDG]
        FRED[FRED API]
        SEC[SEC EDGAR]
        LLM_API[LLM 提供商<br/>OpenAI / Gemini / DeepSeek / Anthropic]
    end

    UI --> API_CLIENT --> ROUTER
    ROUTER --> GRAPH --> AGENTS --> TOOLS
    GRAPH --> SYNTH
    TOOLS --> YFINANCE & FMP & FINNHUB & TAVILY & FRED & SEC
    AGENTS --> LLM_API
    AGENTS --> RAG
    GRAPH --> CACHE & MEMORY & DB
```

---

## 🔄 LangGraph 管线（18 节点）

FinSight 的核心是一个 **18 节点 LangGraph 有状态图**，处理从日常对话到深度投资报告的所有场景。
仪表盘评分器通过 `/api/dashboard/insights` 独立提供，不属于这个 18 节点 LangGraph 主链路。

```mermaid
flowchart TD
    START((开始)) --> INIT["① build_initial_state<br/><i>解析输入，加载记忆</i>"]
    INIT --> RESET["② reset_turn_state<br/><i>清除临时字段 + trace 运行时</i>"]
    RESET --> CTX["③ normalize_ui_context<br/><i>合并 UI 提示，检测 ticker</i>"]
    CTX --> MODE{"④ chat_respond<br/><i>输出模式？</i>"}

    MODE -->|"闲聊 / 问答"| CHAT_END["直接 LLM 回复"]
    CHAT_END --> RENDER
    MODE -->|"需要分析"| SUBJ["⑤ resolve_subject<br/><i>Ticker 解析 + 去重</i>"]

    SUBJ --> CLARIFY{"⑥ clarify_gate<br/><i>有歧义？</i>"}
    CLARIFY -->|"有歧义"| ASK["请求用户澄清"]
    ASK --> RENDER
    CLARIFY -->|"明确"| PARSE["⑦ parse_operation<br/><i>14 级意图分类器</i>"]

    PARSE -->|"alert_set"| ALERT_EX["⑦a alert_extractor<br/><i>提取提醒参数</i>"]
    ALERT_EX -->|"有效"| ALERT_ACT["⑦b alert_action<br/><i>保存并调度</i>"]
    ALERT_EX -->|"无效"| RENDER
    ALERT_ACT --> RENDER
    PARSE -->|"其他操作"| POLICY["⑧ policy_gate<br/><i>能力评分 + 预算</i>"]
    POLICY --> PLAN["⑨ planner_node<br/><i>LLM 规划 或 Stub 回退</i>"]

    PLAN --> CONFIRM{"⑩ confirmation_gate<br/><i>人工审批？</i>"}
    CONFIRM -->|"拒绝"| RENDER
    CONFIRM -->|"批准"| EXEC["⑪ execute_plan<br/><i>并行智能体组</i>"]

    EXEC --> SYNTH["⑫ synthesize<br/><i>合并输出 + compare_gate + 冲突检查</i>"]
    SYNTH --> SCRUB["⑬ 幻觉洗涤<br/><i>正则 + 证据验证</i>"]
    SCRUB --> BUILD["⑭ report_builder<br/><i>构建 ReportIR 结构</i>"]
    BUILD --> RENDER["⑮ render_response<br/><i>格式化输出</i>"]
    RENDER --> SAVE["⑯ save_memory<br/><i>持久化记忆</i>"]
    SAVE --> END((结束))

    subgraph "执行引擎 (⑪)"
        direction LR
        EG1["组 1<br/>price · news"] --> EG2["组 2<br/>fundamental · technical"]
        EG2 --> EG3["组 3<br/>macro · risk · deep_search"]
    end

    EXEC -.-> EG1

    style RESET fill:#a855f7,color:#fff
    style SYNTH fill:#ff9800,color:#000
    style SCRUB fill:#f44336,color:#fff
    style POLICY fill:#2196f3,color:#fff
```

### 意图分类（`parse_operation`）

`parse_operation` 节点实现了一个**规则优先的意图分类器**，包含 14 种操作类型，按优先级从高到低排列：

| 优先级 | 操作类型 | 置信度 | 触发关键词 |
|:---:|---------|:---:|--------------|
| 1 | `compare` | 0.85 | vs, versus, 对比, 比较, 哪个更好 |
| 2 | `analyze_impact` | 0.75 | 影响, 冲击, 利好, 利空 |
| 3 | `backtest` | 0.86 | 回测, 策略回测, ma cross, macd strategy (Phase 4) |
| 4 | `alert_set` | 0.88 | 提醒, 预警, alert, notify, remind me (Phase 1) |
| 5 | `screen` | 0.86 | 筛选, 选股, screener (Phase 2) |
| 6 | `cn_market` | 0.84 | 资金流向, 北向, 龙虎榜, 概念股 (Phase 3) |
| 7 | `technical` | 0.85 | 技术面, macd, rsi, k线, 支撑阻力 |
| 8 | `price` | 0.80 | 股价, 现价, 报价, price, quote |
| 9 | `summarize` | 0.75 | 总结, 摘要, tl;dr |
| 10 | `extract_metrics` | 0.70 | 提取指标, eps, 营收, guidance |
| 11 | `fetch` | 0.65 | 获取, 新闻, latest news |
| 12 | `morning_brief` | 0.85 | 晨报, 早报, morning brief |
| 13 | (多标的默认) | 0.70 | 当 `len(tickers) >= 2` 且无护栏命中时自动触发 compare |
| 14 | `qa` | 0.40–0.55 | 兜底问答 |

**Guardrail-A 机制**：当检测到明确的单任务关键词（如 `price`）时，即使有多个股票代码也不会强制进入 `compare` 模式。

### GraphState 字段

管线通过丰富的状态对象（`GraphState`）在所有节点间维护状态：

| 字段 | 类型 | 说明 |
|------|------|------|
| `messages` | `Annotated[list, add_messages]` | 对话历史（LangGraph reducer 仅追加） |
| `subject` | `dict` | 解析后的实体 — `{type, ticker, name, market}` |
| `output_mode` | `str` | `"chat"` / `"quick_report"` / `"investment_report"` |
| `plan_ir` | `dict` | 执行计划（步骤、分组、依赖、成本估算） |
| `step_results` | `dict` | 各智能体/工具的原始输出 |
| `evidence_pool` | `list[dict]` | 收集的证据条目（带来源归因） |
| `rag_context` | `list[dict]` | 混合 RAG 检索结果 |
| `artifacts` | `dict` | 合成后的报告、引用、图表 |
| `trace` | `dict` | 可观测性：延迟、Token 数、失败 |
| `agent_preferences` | `dict` | UI 注入的智能体开关（开/关/深度） |
| `ui_context` | `dict` | 前端提示：active_tab、selection_context、news_mode |

### LangChain / LangGraph API 使用

| API | 用途 |
|-----|------|
| `langgraph.graph.MessagesState` | 带 `add_messages` reducer 的基础状态 |
| `langgraph.checkpoint.sqlite.SqliteSaver` | SQLite 持久化对话检查点 |
| `langgraph.checkpoint.postgres.PostgresSaver` | 可选 PostgreSQL 检查点后端 |
| `langgraph.types.interrupt()` | `confirmation_gate` 处人机协作暂停 |
| `langgraph.types.Command(resume=)` | 人工审批后恢复执行 |
| `langchain_core.messages.HumanMessage / SystemMessage / RemoveMessage` | 消息类型构造 |
| `langchain_core.messages.trim_messages` | 上下文窗口管理——裁剪旧消息 |
| `langfuse.decorators.langfuse_observe` | Langfuse 分布式追踪集成 |

---

## 🤖 智能体生态

### 研究智能体（7 个）

每个研究智能体继承自 `BaseFinancialAgent`，实现带反思循环、工具调用和证据收集的 `research()` 方法。

```mermaid
graph TB
    subgraph EXECUTOR["执行引擎"]
        direction TB
        POLICY["策略门<br/>能力评分"]
        PLANNER["规划节点<br/>LLM / Stub"]
        PARALLEL["并行分组"]
    end

    subgraph AGENTS["7 个研究智能体"]
        direction TB

        subgraph PA["🏷️ 价格智能体"]
            PA_T1["get_stock_price"]
            PA_T2["get_option_chain_metrics"]
            PA_T3["search (Tavily)"]
            PA_CASCADE["11 源价格级联<br/>yfinance → FMP → Finnhub → ..."]
        end

        subgraph NA["📰 新闻智能体"]
            NA_T1["get_company_news"]
            NA_T2["get_news_sentiment"]
            NA_T3["get_event_calendar"]
            NA_T4["score_news_source_reliability"]
            NA_T5["search (Tavily)"]
        end

        subgraph FA["📊 基本面智能体"]
            FA_T1["get_financial_statements"]
            FA_T2["get_company_info"]
            FA_T3["get_earnings_estimates"]
            FA_T4["get_eps_revisions"]
            FA_T5["search (Tavily)"]
        end

        subgraph TA["📈 技术面智能体"]
            TA_T1["get_stock_historical_data"]
            TA_T2["search (Tavily)"]
            TA_CALC["内部计算：RSI, MACD, BB<br/>MA, Stochastic, ADX, CCI"]
        end

        subgraph MA["🌍 宏观智能体"]
            MA_T1["get_fred_data"]
            MA_T2["get_market_sentiment"]
            MA_T3["get_economic_events"]
            MA_T4["search (Tavily)"]
        end

        subgraph RA["⚠️ 风险智能体"]
            RA_T1["evaluate_ticker_risk"]
            RA_T2["get_factor_exposure"]
            RA_T3["run_portfolio_stress_test"]
        end

        subgraph DS["🔍 深度搜索智能体"]
            DS_T1["Tavily → Exa → DDG<br/>多引擎回退"]
            DS_T2["文档抓取器<br/>SSRF 防护"]
            DS_T3["Self-RAG 循环<br/>SearchConvergence"]
        end
    end

    POLICY --> PLANNER --> PARALLEL
    PARALLEL --> PA & NA & FA & TA & MA & RA & DS
```

### 智能体详情

<details>
<summary><b>价格智能体 (PriceAgent)</b> — 实时与历史定价</summary>

- **工具**：`get_stock_price`、`get_option_chain_metrics`、`search`
- **特色**：11 源价格级联回退链：
  ```
  yfinance → FMP 报价 → FMP 历史 → Finnhub 报价 →
  Finnhub K 线 → Alpha Vantage → Polygon → Twelve Data →
  MarketStack → 网络搜索 → 硬编码回退
  ```
- **输出**：当前价格、涨跌幅、成交量、52 周范围、期权指标
- **反思**：最多 2 轮缺口分析

</details>

<details>
<summary><b>新闻智能体 (NewsAgent)</b> — 市场新闻与情绪</summary>

- **工具**：`get_company_news`、`get_news_sentiment`、`get_event_calendar`、`score_news_source_reliability`、`search`
- **数据源**：Finnhub 公司新闻、Finnhub 情绪、经济日历
- **特色**：信源可靠性评分（域名白名单 + 质量启发式）、突发新闻检测
- **输出**：分类新闻条目，含情绪评分、影响标签、信源可靠性评级

</details>

<details>
<summary><b>基本面智能体 (FundamentalAgent)</b> — 财务分析</summary>

- **工具**：`get_financial_statements`、`get_company_info`、`get_earnings_estimates`、`get_eps_revisions`、`search`
- **数据源**：yfinance（8 季度）、FMP（财务、公司概况）
- **特色**：营收/利润趋势分析、利润率分解、资产负债表健康度
- **输出**：季度财务数据、估值指标、盈利惊喜历史

</details>

<details>
<summary><b>技术面智能体 (TechnicalAgent)</b> — 技术指标与信号</summary>

- **工具**：`get_stock_historical_data`、`search`
- **内部计算**：RSI(14)、MACD(12,26,9)、布林带(20,2)、Stochastic %K/%D、ADX(14)、CCI(20)、Williams %R、8 条均线（MA5/10/20/50/100/200、EMA12/26）
- **输出**：支撑/阻力位、趋势信号（看多/看空/中性）、120 日指标时间序列

</details>

<details>
<summary><b>宏观智能体 (MacroAgent)</b> — 宏观经济背景</summary>

- **工具**：`get_fred_data`、`get_market_sentiment`、`get_economic_events`、`search`
- **数据源**：FRED（GDP、CPI、失业率、利率）、CNN 恐惧贪婪指数
- **特色**：宏观-微观联动分析（宏观趋势如何影响特定行业/个股）
- **输出**：经济指标、市场情绪评分、即将公布的经济事件

</details>

<details>
<summary><b>风险智能体 (RiskAgent)</b> — 风险评估</summary>

- **工具**：`evaluate_ticker_risk_lightweight`、`get_factor_exposure`、`run_portfolio_stress_test`
- **定制 research()**：不使用标准 `BaseFinancialAgent.research()` — 直接工具调用
- **计算**：Beta、VaR(95%)、最大回撤、夏普比率、行业暴露
- **输出**：风险评分、因子暴露、压力测试结果、风险警示

</details>

<details>
<summary><b>深度搜索智能体 (DeepSearchAgent)</b> — 网络情报</summary>

- **工具**：多引擎搜索（Tavily → Exa → DuckDuckGo）、文档抓取器
- **架构**：Self-RAG 循环 + `SearchConvergence` 追踪
  ```
  规划搜索 → 执行搜索 → 评分结果 →
  识别缺口 → 优化查询 → 重新搜索（最多 3 轮）
  ```
- **安全**：SSRF 防护（私有 IP 阻断）、持久化域名白名单
- **质量控制**：`_doc_quality_score()` = 信源分 * 0.5 + 新鲜度 * 0.25 + 深度 * 0.25
- **输出**：精选网络发现（含置信度评分），高质量结果（confidence ≥ 0.7）持久化到 RAG

</details>

### 仪表盘洞察评分器（5 个）

轻量级评分器（**非**自主智能体——无工具调用、无规划、无反思循环），为每个仪表盘标签页生成 AI 洞察卡片。它们接受已获取的 API 数据（零网络调用），通过**单次 LLM 调用**输出结构化 JSON，LLM 不可用时自动降级为确定性规则评分。这些评分器通过 `/api/dashboard/insights` 独立运行，不在 LangGraph 研究管线内。

| 评分器 | 标签页 | 输入数据 | 分析焦点 | 延迟 |
|-----------|--------|---------|---------|------|
| `OverviewDigest` | 总览 | 估值 + 技术 + 新闻 | 综合评分、关键洞察、整体风险 | 1-3s |
| `FinancialDigest` | 财务 | 财务 + 估值 | 盈利质量、财务健康、估值合理性 | 1-3s |
| `TechnicalDigest` | 技术 | 技术 + 指标序列 | 趋势判断、信号共振、关键价位 | 1-3s |
| `NewsDigest` | 新闻 | 市场新闻 + 影响新闻 | 主题提取、情绪分析、风险事件 | 1-3s |
| `PeersDigest` | 同行 | 同行 + 估值 | 竞争力评价、行业排名 | 1-3s |

每个评分器均有**确定性回退**（规则驱动），在 LLM 不可用时激活：

```
评分 = 基准(5) + RSI正常(+1) + 上升趋势(+2) + MACD顺向(+1) + 均线多头(+1) + 超买(-1)
```

---

## 📊 仪表盘 — 6 个分析标签页

### 总览标签
> AI 综合分析：评分环、恐贪指数、智能体覆盖矩阵、维度雷达、风险指标、亮点、分析师目标价。

![总览](images/2cae8333a4ce78d259c9734254e2f38d.png)

### 财务标签
> 8 季度财务表、ECharts 盈利组合图（营收柱 + 利润率线）、EPS 惊喜图、分析师目标价仪表、资产负债表摘要。

### 技术标签
> 真实 ECharts K 线蜡烛图（支撑/阻力标注线）、RSI(14) 时序图、MACD(12,26,9) 含柱状图、布林带位置、均线信号。

### 新闻标签
> 三子视图（个股 / 市场 7x24 / 重大事件）、7 组主题筛选 Chip、时间范围选择器、情绪统计条、带标签和影响徽章的富新闻卡片。

### 同行标签
> 同行评分网格、PE/PB 水平柱状图、营收增长发散柱状图、10+ 指标详细对比表。

### 研究标签
> 多智能体深度分析：按智能体分区（价格、新闻、技术、基本面、宏观、深度搜索）、冲突矩阵、引用追踪、置信度评分。

---

## 🔍 RAG 引擎 — 混合检索管线

FinSight 使用生产级混合检索管线，替代了旧版基于 SHA1 哈希的伪嵌入。

```mermaid
flowchart LR
    QUERY["用户查询"] --> ROUTER["RAG 路由器<br/><i>SKIP / SECONDARY / PRIMARY</i>"]

    ROUTER -->|PRIMARY| EMBED["bge-m3 编码<br/><i>1024 维 Dense + Sparse 词法</i>"]
    ROUTER -->|SKIP| LIVE["仅实时工具"]

    EMBED --> DENSE["稠密检索<br/><i>余弦相似度</i>"]
    EMBED --> SPARSE["稀疏检索<br/><i>词法权重匹配</i>"]

    DENSE --> RRF["RRF 融合<br/><i>+ Scope 加权</i>"]
    SPARSE --> RRF

    RRF --> RERANK["交叉编码器精排<br/><i>bge-reranker-v2-m3</i><br/>Top-30 → Top-8"]

    RERANK --> OUTPUT["rag_context<br/><i>注入合成节点 prompt</i>"]

    style EMBED fill:#4caf50,color:#fff
    style RERANK fill:#ff9800,color:#000
```

### 关键组件

| 组件 | 文件 | 模型 / 算法 |
|------|------|------------|
| **嵌入器** | `rag/embedder.py` | `BAAI/bge-m3` — 1024 维 Dense + Sparse（词法权重） |
| **混合检索** | `rag/hybrid_service.py` | RRF 融合 + scope 加权：persistent +0.15, medium_ttl +0.05 |
| **精排器** | `rag/reranker.py` | `BAAI/bge-reranker-v2-m3` 交叉编码器，Top-30 → Top-8 |
| **路由器** | `rag/rag_router.py` | 规则式：SKIP（实时行情）/ PRIMARY（历史分析）/ PARALLEL（深度研究） |
| **切片器** | `rag/chunker.py` | 按文档类型：新闻（不切）/ 财报（1000/200）/ 纪要（800/100） |
| **存储** | `rag/hybrid_service.py` | 内存 或 PostgreSQL（`pgvector` VECTOR(1024) + `tsvector`） |

### 文档生命周期

| 来源 | 作用域 | TTL | 触发方式 |
|------|--------|-----|---------|
| 智能体输出（证据） | `ephemeral` | 请求级 | 每次分析执行 |
| 新闻条目 | `medium_ttl` | 7 天 | NewsAgent 获取 |
| 深度搜索结果（confidence ≥ 0.7） | `persistent` | 永久 | 高质量自动持久化 |
| SEC 文件（未来） | `persistent` | 永久 | 定时 ETL |

### Prompt 注入（synthesize.py）

RAG 结果和实时证据以 XML 标签块注入：

```xml
<realtime_evidence>
  {当次执行收集的 evidence_pool}
</realtime_evidence>

<historical_knowledge>
  {混合检索的 rag_context}
</historical_knowledge>

<evidence_priority_rules>
  1. 实时数据与历史数据冲突时，以实时数据为准
  2. 引用历史数据时必须标注数据时间
  3. 无法确认时效性的数据需注明截至日期
</evidence_priority_rules>
```

### 质量基准 — RAG Quality V2

三层评估金字塔（`tests/rag_qualityV2/`），针对 12 个中文金融用例（财报、电话会、新闻）进行检索与生成质量的六维诊断：

| 层级 | 范围 | KC | KCR | CSR | UCR ↓ | CR ↓ | NCR | 门控 |
|------|------|----|-----|-----|-------|------|-----|------|
| **L1** Mock 上下文 | LLM 生成基线 | 0.8796 | 0.9479 | 0.9431 | 0.057 | **0.0** | 0.9896 | ✅ PASS |
| **L2** 真实检索 | 检索 + 生成协同 | 0.8960 | 0.9623 | **1.0000** | **0.000** | **0.0** | 0.9861 | ✅ PASS |
| **L3** 端到端 | 完整 LangGraph 流程 | **0.9072** | **0.9653** | 0.9924 | 0.008 | **0.0** | **1.0000** | ✅ PASS |

> **三层 CR = 0.0** — 零矛盾幻觉。 **L3 NCR = 1.0** — 端到端数值一致性完美。

指标说明：KC（关键点覆盖率）· KCR（关键点证据召回率）· CSR（陈述支持率）· UCR（无证据陈述率）· CR（矛盾率）· NCR（数值一致率）

---

## 📈 智能图表 — LLM 驱动可视化

FinSight 支持**双模式**内联图表，LLM 自主决定何时可视化有助于理解。

```mermaid
flowchart LR
    subgraph "模式 A：LLM 生成数据"
        LLM1["LLM 生成<br/>&lt;chart type='bar'&gt;<br/>{labels, values}"]
        LLM1 --> PARSE1["前端在 Markdown<br/>渲染前提取"]
        PARSE1 --> ECHART1["ECharts 渲染<br/>bar / line / pie / scatter / gauge"]
    end

    subgraph "模式 B：真实数据引用"
        LLM2["LLM 生成<br/>&lt;chart_ref source='peers'<br/>fields='trailing_pe'/&gt;"]
        LLM2 --> PARSE2["前端读取<br/>dashboardStore 数据"]
        PARSE2 --> ECHART2["ECharts 渲染<br/>真实 API 数值"]
    end
```

| 模式 | 标签 | 数据来源 | 适用场景 | 精度 |
|------|------|---------|---------|------|
| LLM 内联 | `<chart>` | LLM 填充 JSON 数据 | 趋势概览、定性对比 | 近似值 |
| API 引用 | `<chart_ref>` | 前端读取 `dashboardData` | 精确数值图表、历史序列 | 精确值 |

**处理流程**：图表标签在 Markdown 渲染**之前**从 LLM 输出中提取（与 `[CHART:TICKER:TYPE]` 相同模式），确保 `react-markdown` 永远不会看到原始 XML。

---

## 💬 "问这条"

上下文感知的后续提问功能，允许用户从仪表盘直接对任意新闻、AI 洞察或风险警示进行追问。

```mermaid
sequenceDiagram
    participant 用户
    participant 卡片 as NewsCard / AiInsightCard
    participant Store as dashboardStore
    participant 对话 as MiniChat
    participant API as 后端 SSE

    用户->>卡片: 点击"问这条"按钮
    卡片->>Store: setActiveSelection(SelectionItem)
    Store->>对话: MiniChat 读取 activeSelection
    对话->>对话: 自动填充上下文胶囊
    用户->>对话: 输入后续问题
    对话->>API: POST /api/chat（含 selection_context）
    API->>API: LangGraph 管线处理（带上下文）
    API-->>对话: SSE 流式响应
```

### SelectionItem 类型

| 类型 | 来源组件 | 发送到后端的上下文 |
|------|---------|------------------|
| `news` | NewsCard | `{title, summary, source, ts, sentiment}` |
| `filing` | 研究引用 | `{title, url, type}` |
| `doc` | 报告段落 | `{title, content_snippet}` |
| `insight` | AiInsightCard | `{tab, score, summary, key_points}` |
| `risk` | RiskMetricsCard | `{risk_type, description, severity}` |

---

## ⚔️ 冲突检测

当多个智能体分析同一标的时，结论可能产生矛盾。FinSight 自动检测并向用户披露这些分歧。

### 8 组可比较智能体对

| 智能体 A | 智能体 B | 比较维度 |
|---------|---------|---------|
| 技术面 | 基本面 | 方向判断（信号 vs 基本面） |
| 技术面 | 新闻 | 价格动能 vs 事件影响 |
| 技术面 | 价格 | 技术信号 vs 实际走势 |
| 基本面 | 新闻 | 基本面 vs 事件驱动叙事 |
| 基本面 | 宏观 | 个股基本面 vs 宏观环境 |
| 新闻 | 宏观 | 事件情绪 vs 宏观周期 |
| 价格 | 新闻 | 价格趋势 vs 新闻情绪 |
| 宏观 | 技术面 | 宏观趋势 vs 技术信号 |

### 触发公式

```
触发检测 = 深度研报 OR (成功智能体 ≥ 2 AND 可比较声明 ≥ 1)
```

冲突以**结构化 JSON**（用于矩阵可视化）和**内联文本**（用于报告可读性）两种形式呈现。

---

## 📧 邮件预警与订阅

<img src="images/ae7cbf42-a393-4ea8-bc75-ccf2d239e2c8.png" width="400" align="right"/>

FinSight 包含 3 个通过 APScheduler 运行的自动预警调度器：

| 调度器 | 触发条件 | 检查间隔 |
|--------|---------|---------|
| **PriceChangeScheduler** | 价格超出阈值（如 ±0.1%） | 15 分钟 |
| **NewsScheduler** | 关注列表标的的高影响新闻 | 30 分钟 |
| **RiskScheduler** | RSI 极端 / VaR 突破 / 回撤事件 | 60 分钟 |

### 邮件管线

```
调度器 → 规则引擎 → 创建预警 →
HTML 模板 (Jinja2) → SMTP 发送 →
递送追踪（暂时 vs 永久错误） →
3 次永久失败后自动停用
```

### 订阅管理

- `POST /api/subscriptions` — 创建订阅（邮箱 + 标的 + 预警类型）
- `GET /api/subscriptions/{email}` — 查看活跃订阅
- `DELETE /api/subscriptions/{id}` — 移除订阅
- 存储：`data/subscriptions.json`，按用户设置

<br clear="right"/>

---

## 💾 数据与存储架构

```mermaid
graph TB
    subgraph "SQLite（本地）"
        CP[(checkpoints.sqlite<br/><i>LangGraph 状态快照</i>)]
        RI[(report_index.sqlite<br/><i>报告元数据 + 引用</i>)]
        PF[(portfolio.sqlite<br/><i>持仓 + 交易</i>)]
    end

    subgraph "JSON 文件 (data/)"
        MEM["memory/{user_id}.json<br/><i>用户档案 + 关注列表</i>"]
        SUB["subscriptions.json<br/><i>邮件预警订阅</i>"]
        ALERTS["alerts/{user_id}.json<br/><i>预警推送历史</i>"]
    end

    subgraph "可选 PostgreSQL"
        PG_CP["langgraph_checkpoints<br/><i>可扩展检查点后端</i>"]
        PG_RAG["rag_documents_v2<br/><i>VECTOR(1024) + tsvector</i>"]
    end

    subgraph "内存"
        DCACHE["DashboardCache<br/><i>16 类 TTL</i>"]
        ICACHE["InsightsCache<br/><i>1h TTL + stale-while-revalidate</i>"]
        RAGMEM["RAG 内存存储<br/><i>无 PostgreSQL 时回退</i>"]
    end
```

### 数据库 Schema

<details>
<summary><b>报告索引 (SQLite)</b></summary>

```sql
CREATE TABLE report_index (
    report_id    TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    ticker       TEXT,
    title        TEXT,
    summary      TEXT,
    source_type  TEXT,          -- 'chat' | 'dashboard' | 'workbench'
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata     TEXT           -- JSON blob
);

CREATE TABLE report_citations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id    TEXT REFERENCES report_index(report_id),
    url          TEXT,
    title        TEXT,
    domain       TEXT,
    snippet      TEXT,
    accessed_at  TIMESTAMP
);
```

</details>

<details>
<summary><b>持仓 (SQLite)</b></summary>

```sql
CREATE TABLE holdings (
    user_id    TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    shares     REAL NOT NULL,
    avg_cost   REAL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, ticker)
);
```

</details>

<details>
<summary><b>RAG 文档 (PostgreSQL)</b></summary>

```sql
CREATE TABLE rag_documents_v2 (
    id          TEXT PRIMARY KEY,
    collection  TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   VECTOR(1024),       -- bge-m3 稠密向量
    ts_content  tsvector,           -- 中文全文搜索
    metadata    JSONB,
    scope       TEXT DEFAULT 'ephemeral',  -- ephemeral | medium_ttl | persistent
    created_at  TIMESTAMP DEFAULT NOW()
);
```

</details>

---

## 🗄️ 缓存系统

`DashboardCache` 管理 16 类不同 TTL：

| 类别 | TTL | 说明 |
|------|-----|------|
| `quote` | 30 秒 | 实时价格报价 |
| `technical_snapshot` | 60 秒 | 技术指标值 |
| `company_news` | 5 分钟 | 公司新闻 |
| `company_info` | 10 分钟 | 公司概况 |
| `sec_filings` | 15 分钟 | SEC 文件 |
| `market_chart` | 5 分钟 | OHLCV 价格数据 |
| `financials` | 10 分钟 | 季度财报 |
| `peers` | 10 分钟 | 同行对比 |
| `earnings_history` | 30 分钟 | EPS 历史 |
| `analyst_targets` | 30 分钟 | 分析师目标价 |
| `recommendations` | 30 分钟 | 买入/持有/卖出评级 |
| `indicator_series` | 5 分钟 | 技术指标时间序列 |
| `insights` | 1 小时 | AI 摘要洞察（stale-while-revalidate 最长 4h） |

### Stale-While-Revalidate 模式（洞察）

```
新鲜 (< 1h)    → 立即返回，cached=true
过期中 (1h-4h) → 返回过期数据 + 后台异步刷新
过期 (> 4h)    → 等待新结果生成
```

---

## 🧠 记忆与用户档案

按用户存储的 JSON 文件位于 `data/memory/{user_id}.json`：

```json
{
  "user_id": "abc123",
  "watchlist": ["AAPL", "GOOGL", "TSLA"],
  "preferences": {
    "language": "zh-CN",
    "risk_tolerance": "moderate",
    "default_depth": "report"
  },
  "interaction_history": [
    {"ticker": "AAPL", "action": "deep_research", "timestamp": "2026-02-18T10:30:00Z"}
  ]
}
```

记忆系统集成点：
- **关注列表 API**：`POST /api/user/watchlist/add` / `remove` — 持久化并被预警调度器使用
- **LangGraph 记忆**：在 `build_initial_state` 节点加载，在 `save_memory` 节点保存
- **仪表盘 Store**：前端 `dashboardStore` 初始化时通过 API 同步关注列表

---

## 🛡️ 韧性与回退

FinSight 为生产可靠性设计了多层回退机制：

| 组件 | 主要 | 回退 | 行为 |
|------|------|------|------|
| **规划器** | LLM 规划器（结构化输出） | `planner_stub`（关键词→工具映射） | LLM 超时(8s)自动切换 |
| **嵌入** | `BAAI/bge-m3`（1024 维） | SHA1 哈希嵌入（96 维） | 模型未加载时优雅降级 |
| **精排器** | `bge-reranker-v2-m3` | 跳过精排，直接用 RRF 分数 | 静默穿透 |
| **价格数据** | yfinance | 10 个回退源（FMP → Finnhub → ...） | 11 级级联 |
| **AI 洞察** | LLM 洞察评分器 | 确定性规则评分 | `model_generated=false` 标志 |
| **晨报管线** | LangGraph Pipeline | 直接数据获取（路由回退） | 对调用方透明 |
| **调仓 LLM 增强** | Agent + LLM 驱动 | 原始确定性调仓候选 | 任意失败时安全回退 |
| **仪表盘数据** | 实时 API 获取 | 内存缓存（stale-while-revalidate） | 基于 TTL 的新鲜度 |
| **检查点** | PostgreSQL | SQLite 本地文件 | 启动时自动检测 |
| **RAG 存储** | PostgreSQL + pgvector | 内存存储 | 自动回退 |
| **搜索** | Tavily | Exa → DuckDuckGo | 多引擎回退链 |

### LLM 熔断器

```
连续 3 次 LLM 失败 → 15 分钟冷却 → 纯规则模式
```

---

## 🧹 幻觉抑制

FinSight 实现了多层防御以对抗 LLM 幻觉，特别针对**编造的未来事件**（如"公司计划在 2026 Q3 推出 X"）：

| 层级 | 方法 | 阶段 |
|------|------|------|
| **Prompt 约束** | "闭卷"指令：仅使用提供的证据，不得编造事件 | 系统提示 |
| **正则模式匹配** | `_HALLUCINATION_EVENT_PATTERNS` — 检测未来事件声明 | 生成后处理 |
| **证据交叉验证** | `_claim_supported_by_evidence()` — 对照证据池验证声明 | 生成后处理 |
| **占位符替换** | 未验证声明替换为 `[此处信息未经证据验证，已移除]` | 生成后处理 |
| **时间锚定** | 强制所有数据引用标注日期 | Prompt + 后处理 |
| **去重** | 合并连续占位符为单个标记 | 清理 |

> 完整技术文档：[`docs/HALLUCINATION_MITIGATION.md`](docs/HALLUCINATION_MITIGATION.md)

---

## 🔧 技术栈

### 后端
| 技术 | 版本 | 用途 |
|------|------|------|
| **Python** | 3.11+ | 运行时 |
| **FastAPI** | 0.100+ | REST API + SSE 流式推送 |
| **LangGraph** | 0.2+ | 有状态智能体编排 |
| **LangChain** | 0.3+ | 工具框架、消息类型、文本切分 |
| **Langfuse** | 2.x | 分布式追踪与可观测性 |
| **yfinance** | 0.2+ | 市场数据（行情、财报、技术面） |
| **FlagEmbedding** | latest | bge-m3 嵌入模型 |
| **sentence-transformers** | latest | bge-reranker-v2-m3 交叉编码器 |
| **APScheduler** | 3.x | 预警调度（cron 式） |
| **Pydantic** | 2.x | Schema 验证 |

### 前端
| 技术 | 版本 | 用途 |
|------|------|------|
| **React** | 19 | UI 框架 |
| **Vite** | 6.x | 构建工具 |
| **TypeScript** | 5.x | 类型安全 |
| **Zustand** | 5.x | 状态管理（3 个 Store） |
| **ECharts** | 5.x | 图表可视化（via echarts-for-react） |
| **TailwindCSS** | 4.x | 样式（CSS 变量主题） |
| **react-markdown** | latest | 对话/报告中 Markdown 渲染 |

### 模型
| 模型 | 维度 | 用途 |
|------|------|------|
| **LLM**（可配置） | — | `create_llm()` 工厂支持 OpenAI、Gemini、DeepSeek、Anthropic、本地 |
| **BAAI/bge-m3** | 1024 | RAG Dense + Sparse 嵌入 |
| **BAAI/bge-reranker-v2-m3** | — | 交叉编码器精排 |
| **paraphrase-multilingual-MiniLM-L12-v2** | 384 | 旧版知识库（ChromaDB） |

---

## 🚀 快速开始

### 前置条件

- Python 3.11+
- Node.js 18+（pnpm）
- 至少一个 LLM API Key（OpenAI / Gemini / DeepSeek）

### 后端启动

```bash
# 1. 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
copy .env.example .env
# 编辑 .env，填入 API Key：
#   OPENAI_API_KEY=sk-...
#   GOOGLE_API_KEY=...        (Gemini)
#   FMP_API_KEY=...           (Financial Modeling Prep)
#   FINNHUB_API_KEY=...       (Finnhub)
#   TAVILY_API_KEY=...        (Tavily Search)
#   FRED_API_KEY=...          (FRED 经济数据)

# 4. 启动服务
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

### 前端启动

```bash
cd frontend
pnpm install
pnpm dev
# 打开 http://localhost:5173
```

### 可选：PostgreSQL（RAG 后端）

```bash
# 设置环境变量启用 PostgreSQL
# RAG_BACKEND=postgres
# DATABASE_URL=postgresql://user:pass@localhost:5432/finsight
```

### 可选：邮件预警

```bash
# 启用预警调度器
# ALERTS_ENABLED=true
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=your-email@gmail.com
# SMTP_PASSWORD=your-app-password
```

---

## 📁 项目结构

```
FinSight/
├── backend/
│   ├── api/                    # FastAPI 路由
│   │   ├── main.py             # 应用入口 + CORS + 生命周期
│   │   ├── chat_router.py      # POST /api/chat（SSE 流式）
│   │   ├── dashboard_router.py # GET /api/dashboard + /insights
│   │   ├── execution_router.py # POST /api/execute（工作台）
│   │   ├── alerts_router.py    # GET /api/alerts/feed
│   │   └── tools_router.py     # GET /api/tools（工具清单）
│   ├── graph/                  # LangGraph 管线
│   │   ├── builder.py          # 图构建（16 节点 + 边）
│   │   ├── state.py            # GraphState 定义
│   │   ├── report_builder.py   # ReportIR 结构构建
│   │   └── nodes/              # 各节点实现
│   │       ├── build_initial_state.py
│   │       ├── reset_turn_state.py  # Per-turn 临时字段 + trace 运行时清除
│   │       ├── chat_respond.py
│   │       ├── resolve_subject.py
│   │       ├── parse_operation.py   # 4 级优先链（对比 → 护栏 → 多标的 → qa）
│   │       ├── compare_gate.py      # 对比证据门控（3 个谓词函数）
│   │       ├── policy_gate.py
│   │       ├── planner.py
│   │       ├── execute_plan_stub.py
│   │       └── synthesize.py   # 冲突检测 + 幻觉洗涤
│   ├── agents/                 # 智能体实现
│   │   ├── base_agent.py       # BaseFinancialAgent（反思循环）
│   │   ├── price_agent.py
│   │   ├── news_agent.py
│   │   ├── fundamental_agent.py
│   │   ├── technical_agent.py
│   │   ├── macro_agent.py
│   │   ├── risk_agent.py
│   │   └── deep_search_agent.py
│   ├── dashboard/              # 仪表盘数据 & AI 洞察
│   │   ├── data_service.py     # yfinance/FMP 数据获取
│   │   ├── cache.py            # DashboardCache（16 类 TTL）
│   │   ├── insights_engine.py  # 洞察评分器编排（单次 LLM 调用，非自主智能体）
│   │   ├── insights_scorer.py  # 确定性评分回退
│   │   ├── insights_prompts.py # LLM Prompt 模板
│   │   └── schemas.py          # Pydantic Schema
│   ├── rag/                    # 混合 RAG 引擎
│   │   ├── hybrid_service.py   # 内存 + Postgres 后端
│   │   ├── embedder.py         # bge-m3 嵌入服务
│   │   ├── reranker.py         # bge-reranker-v2-m3
│   │   ├── rag_router.py       # 查询路由（SKIP/PRIMARY/PARALLEL）
│   │   └── chunker.py          # 文档切片策略
│   ├── tools/                  # 工具实现
│   │   ├── manifest.py         # 17 个工具（含元数据）
│   │   ├── market.py           # 价格数据（11 源级联）
│   │   ├── financial.py        # 财务报表
│   │   ├── technical.py        # 技术指标
│   │   ├── macro.py            # FRED + 市场情绪
│   │   └── sec_tools.py        # SEC EDGAR 文件
│   ├── services/               # 后台服务
│   │   ├── alert_scheduler.py  # 3 个预警调度器
│   │   ├── scheduler_runner.py # APScheduler 封装
│   │   ├── subscription_service.py
│   │   └── memory.py           # 按用户记忆存储
│   └── tests/                  # 700+ 测试
│       ├── test_graph_*.py
│       ├── test_agents_*.py
│       ├── test_dashboard_*.py
│       └── test_rag_*.py
├── frontend/
│   ├── src/
│   │   ├── api/client.ts       # API 客户端 + SSE parseSSEStream
│   │   ├── store/              # Zustand 状态管理
│   │   │   ├── useStore.ts     # 全局 Store（会话、认证）
│   │   │   ├── dashboardStore.ts  # 仪表盘状态
│   │   │   └── executionStore.ts  # 工作台执行状态
│   │   ├── components/
│   │   │   ├── dashboard/      # 仪表盘 UI
│   │   │   │   ├── tabs/       # 6 个标签面板
│   │   │   │   │   ├── OverviewTab.tsx
│   │   │   │   │   ├── FinancialTab.tsx
│   │   │   │   │   ├── TechnicalTab.tsx
│   │   │   │   │   ├── NewsTab.tsx
│   │   │   │   │   ├── ResearchTab.tsx
│   │   │   │   │   └── PeersTab.tsx
│   │   │   │   └── StockHeader.tsx
│   │   │   ├── SmartChart.tsx  # LLM 双模式智能图表
│   │   │   ├── ChatList.tsx    # 对话 + 内联图表
│   │   │   └── workbench/      # 工作台组件
│   │   ├── hooks/              # 自定义 React Hooks
│   │   │   ├── useLatestReport.ts
│   │   │   ├── useDashboardData.ts
│   │   │   ├── useDashboardInsights.ts
│   │   │   └── useChartTheme.ts
│   │   └── types/dashboard.ts  # TypeScript 类型定义
│   └── vite.config.ts
├── data/                       # 运行时数据存储
│   ├── memory/                 # 按用户 JSON 档案
│   ├── subscriptions.json      # 邮件预警订阅
│   └── *.sqlite                # SQLite 数据库
├── docs/                       # 技术文档
└── images/                     # 截图
```

---

## 🧪 Phase Labs（Phase 1–4）

实验性功能套件，访问路径 `/phase-labs`，基于核心平台扩展：

| 阶段 | 功能 | 描述 |
|------|------|------|
| **Phase 1** | 对话式价格提醒 | 在聊天中说"TSLA 涨到 300 提醒我" → LangGraph 自动提取股票/方向/阈值 → 调度器触发时发送邮件。支持 `price_change_pct`（冷却窗口）和 `price_target`（一次性触发）两种模式。|
| **Phase 2** | 智能选股 MVP | 多条件自然语言选股（PE < 20、营收增长 > 15% 等）。返回排序结果，并附 `capability_note` 说明 CN/HK 覆盖边界。|
| **Phase 3** | A 股市场数据 | 实时北向/南向资金流（`cn_market_flow`）、板块与概念板块热力图（`cn_market_board`）、概念关键词映射（`concept_map`）。覆盖 A 股与港股市场。|
| **Phase 4** | 策略回测 | SMA 双均线、MACD 信号、RSI 均值回归策略。强制 A 股 T+1 结算（不允许当日回转）、参数化佣金/滑点，通过 `t_plus_one` bar 偏移防止前视偏差。|

### 🔬 RAG Quality V2 — 三层评估体系

自研评估框架，用 6 维 Claim/Keypoint 指标替代 RAGAS，专为中文金融叙事场景设计。完整报告：[`tests/rag_qualityV2/REPORT.md`](./tests/rag_qualityV2/REPORT.md)

**三层定位：**

| 层级 | 测什么 | 输入 | 核心价值 |
|------|--------|------|----------|
| **L1** Mock 上下文 | LLM 生成基线 — 给定完美证据，模型能否正确回答？ | Mock 上下文 → 直接 Prompt | 建立与检索无关的生成能力上限 |
| **L2** 真实检索 | 检索 + 生成协同 — bge-m3 混合检索能否找到正确 chunk？ | 真实 Embedding + Top-K → synthesize_agent | 隔离检索质量，排除路由/编排噪声 |
| **L3** 端到端 | 完整 LangGraph 流程 — 真实用户看到的输出 | 完整 LangGraph 管线 | 最强信号，验证生产就绪性 |

**三层全 PASS**，覆盖 12 个中文金融用例（财报、电话会、新闻）：

| 层级 | KC | KCR | CSR | UCR ↓ | CR ↓ | NCR | 门控 |
|------|----|-----|-----|-------|------|-----|------|
| L1 Mock | 0.8796 | 0.9479 | 0.9431 | 0.057 | **0.0** | 0.9896 | ✅ PASS |
| L2 检索 | 0.8960 | 0.9623 | **1.0000** | **0.000** | **0.0** | 0.9861 | ✅ PASS |
| L3 E2E | **0.9072** | **0.9653** | 0.9924 | 0.008 | **0.0** | **1.0000** | ✅ PASS |

**L3 逐案结果（12/12 通过）：**

| # | 用例 | 类型 | KC | KCR | CSR | UCR ↓ | NCR | 结果 |
|---|------|------|----|-----|-----|-------|-----|------|
| 01 | 茅台 2024Q3 营收 | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ 满分 |
| 02 | 宁德时代毛利率 2024 | filing/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ 满分 |
| 03 | 比亚迪新能源销量 2024H1 | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ 满分 |
| 04 | 中国平安内含价值 | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ 满分 |
| 05 | 阿里云业绩指引 | transcript/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ 满分 |
| 06 | 腾讯游戏复苏 | transcript/analysis | 0.714 | 1.0 | 1.0 | 0.0 | 1.0 | ⚠️ KC |
| 07 | 美团盈利分析 | transcript/analysis | 0.833 | 0.833 | 1.0 | 0.0 | 1.0 | ⚠️ KC |
| 08 | 京东供应链 | transcript/analysis | 0.714 | 1.0 | 1.0 | 0.0 | 1.0 | ⚠️ KC |
| 09 | 美联储降息 → A 股 | news/list | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ 满分 |
| 10 | 中国电车出口壁垒 | news/list | 1.0 | 1.0 | 0.909 | 0.091 | 1.0 | ⚠️ UCR |
| 11 | iPhone 16 中国销售 | news/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ 满分 |
| 12 | 半导体出口管制 | news/analysis | 0.625 | 0.75 | 1.0 | 0.0 | 1.0 | ⚠️ KC |

> **三层 CR = 0.0** — 零矛盾幻觉。**L3 NCR = 1.0** — 端到端数值一致性完美。⚠️ 电话会/分析类 KC 偏低为生成侧问题（证据存在，`brief` 模式省略了产品级细节）。

---

## 📄 许可证

本项目基于 [MIT License](./LICENSE) 开源。

---

<p align="center">
  基于 LangGraph + React + ECharts 构建
</p>
