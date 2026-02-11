# FinSight LangGraph 全流程深度拆解

> 版本：v1.1.0-sprint2 | 更新时间：2026-02-11 | 节点数：11 | Agent 数：6

---

## 目录

1. [架构总览](#1-架构总览)
2. [主流程图（完整 11 节点）](#2-主流程图)
3. [GraphState 状态模型](#3-graphstate-状态模型)
4. [节点逐层拆解](#4-节点逐层拆解)
5. [Agent 子系统](#5-agent-子系统)
6. [能力注册表与评分机制](#6-能力注册表与评分机制)
7. [模板系统与路由矩阵](#7-模板系统与路由矩阵)
8. [Report Builder 构建流程](#8-report-builder-构建流程)
9. [LLM 重试与端点轮转](#9-llm-重试与端点轮转)
10. [Prompt 体系全览](#10-prompt-体系全览)
11. [端到端数据流示例](#11-端到端数据流示例)
12. [故障降级策略](#12-故障降级策略)

---

## 1. 架构总览

```mermaid
graph TB
    subgraph "前端 (React + Vite)"
        UI[用户界面] --> ChatInput[ChatInput 组件]
        ChatInput --> SSE[SSE 流式连接]
        SSE --> ReportView[ReportView 渲染]
    end

    subgraph "API 层 (FastAPI)"
        SSE --> ChatRouter[chat_router.py]
        ChatRouter --> GraphRunner[GraphRunner]
    end

    subgraph "LangGraph 管道 (11 节点)"
        GraphRunner --> N1[build_initial_state]
        N1 --> N2[normalize_ui_context]
        N2 --> N3[decide_output_mode]
        N3 --> N4[resolve_subject]
        N4 --> N5[clarify]
        N5 -->|需要澄清| END1[END: 返回提问]
        N5 -->|继续| N6[parse_operation]
        N6 --> N7[policy_gate]
        N7 --> N8[planner]
        N8 --> N9[execute_plan]
        N9 --> N10[synthesize]
        N10 --> N11[render]
        N11 --> END2[END: 返回结果]
    end

    subgraph "Agent 执行层"
        N9 --> PA[PriceAgent]
        N9 --> NA[NewsAgent]
        N9 --> FA[FundamentalAgent]
        N9 --> TA[TechnicalAgent]
        N9 --> MA[MacroAgent]
        N9 --> DA[DeepSearchAgent]
    end

    subgraph "数据源层"
        PA --> YF[yfinance]
        PA --> FH[finnhub]
        NA --> FH2[finnhub news]
        NA --> TV[tavily]
        FA --> YF2[yfinance financials]
        TA --> YF3[yfinance historical]
        MA --> FRED[FRED API]
        DA --> EXA[Exa neural search]
        DA --> TV2[tavily advanced]
    end

    subgraph "报告构建"
        END2 --> RB[report_builder]
        RB --> Payload[ReportIR Payload]
    end
```

### 核心设计原则

| 原则 | 实现方式 |
|------|---------|
| **确定性优先** | 默认 stub 模式，所有节点不依赖 LLM 即可输出 |
| **渐进升级** | chat → brief → investment_report 三档模式 |
| **故障隔离** | 每个 Agent 独立断路器 + 缓存 + 降级 |
| **端点轮转** | LLM 调用失败自动切换到下一个 API 端点 |
| **可观测** | 全量 trace 事件 + timing + failure 记录 |

---

## 2. 主流程图

### 2.1 完整节点路由

```mermaid
flowchart TD
    START((START)) --> A[build_initial_state]
    A --> B[normalize_ui_context]
    B --> C[decide_output_mode]
    C --> D[resolve_subject]
    D --> E[clarify]

    E -->|"needed=true<br/>空 query / 问候 / 无法识别主体"| END_CLARIFY((END<br/>返回澄清提问))
    E -->|"needed=false<br/>主体已识别"| F[parse_operation]

    F --> G[policy_gate]
    G --> H[planner]
    H --> I[execute_plan]
    I --> J[synthesize]
    J --> K[render]
    K --> END_RESULT((END<br/>输出结果))

    style A fill:#4a9eff,color:#fff
    style E fill:#ff9f43,color:#fff
    style H fill:#ee5a24,color:#fff
    style I fill:#0abde3,color:#fff
    style J fill:#10ac84,color:#fff
    style K fill:#5f27cd,color:#fff
    style END_CLARIFY fill:#ff6b6b,color:#fff
    style END_RESULT fill:#1dd1a1,color:#fff
```

### 2.2 output_mode 三档路由

```mermaid
flowchart LR
    Q[用户查询] --> DM{decide_output_mode}

    DM -->|"含 '投资报告/研报/report'"| IR[investment_report]
    DM -->|"UI 显式设定"| EXPLICIT[UI 指定模式]
    DM -->|"默认"| BRIEF[brief]

    IR --> FULL[完整研报<br/>6 Agent + 模板 + ReportIR]
    BRIEF --> QUICK[快速回答<br/>最小工具集 + 简洁模板]

    style IR fill:#ee5a24,color:#fff
    style BRIEF fill:#4a9eff,color:#fff
    style FULL fill:#ff6348,color:#fff
    style QUICK fill:#54a0ff,color:#fff
```

---

## 3. GraphState 状态模型

### 3.1 顶层 State 结构

```mermaid
classDiagram
    class GraphState {
        +list messages
        +str thread_id
        +str schema_version
        +str query
        +dict ui_context
        +Subject subject
        +Operation operation
        +str output_mode
        +bool strict_selection
        +Clarify clarify
        +Policy policy
        +PlanIR plan_ir
        +Artifacts artifacts
        +Trace trace
    }

    class Subject {
        +str subject_type
        +list~str~ tickers
        +list~str~ selection_ids
        +list~str~ selection_types
        +list~dict~ selection_payload
    }

    class Operation {
        +str name
        +float confidence
        +dict params
    }

    class Policy {
        +int max_tool_calls
        +int max_rounds
        +int max_seconds
        +list~str~ allowed_agents
        +list~str~ denied_agents
        +str budget_label
    }

    class Artifacts {
        +list~dict~ evidence_pool
        +dict agent_outputs
        +dict render_vars
        +dict report
        +str response
        +str draft_markdown
    }

    GraphState --> Subject
    GraphState --> Operation
    GraphState --> Policy
    GraphState --> Artifacts
```

### 3.2 字段生命周期

| 字段 | 写入节点 | 读取节点 | 类型 |
|------|---------|---------|------|
| `query` | 外部输入 | 所有节点 | `str` |
| `ui_context` | 外部输入, normalize_ui_context | resolve_subject, policy_gate | `dict` |
| `subject` | resolve_subject | clarify, parse_operation, policy_gate, planner, execute_plan, synthesize, render | `Subject` |
| `operation` | parse_operation | policy_gate, planner, execute_plan, synthesize, render | `Operation` |
| `output_mode` | decide_output_mode | policy_gate, planner, synthesize, render, report_builder | `str` |
| `clarify` | clarify | 路由条件 `_route_after_clarify` | `Clarify` |
| `policy` | policy_gate | planner, execute_plan | `Policy` |
| `plan_ir` | planner | execute_plan | `PlanIR` |
| `artifacts` | execute_plan, synthesize, render | synthesize, render, report_builder | `Artifacts` |
| `trace` | 所有节点 (追加) | 可观测性 | `Trace` |

### 3.3 subject_type 类型枚举

| subject_type | 触发条件 | 典型场景 |
|-------------|---------|---------|
| `company` | query 中包含 ticker 或公司名 | "分析 AAPL" |
| `news_item` | 选中单条新闻 | 点击新闻卡片 |
| `news_set` | 选中多条新闻 | 多选新闻 |
| `filing` | 选中财报/公告 | 选择 10-K 文件 |
| `research_doc` | 选中研究文档 | 选择研报 PDF |
| `portfolio` | 投资组合相关 | "我的持仓分析" |
| `unknown` | 无法识别主体 | "你好" / 模糊查询 |

---

## 4. 节点逐层拆解

### 4.1 build_initial_state

```mermaid
flowchart TD
    IN[输入: query, thread_id] --> CHECK{query 非空?}
    CHECK -->|是| MSG[创建 HumanMessage]
    CHECK -->|否| EMPTY[messages = 空列表]
    MSG --> TRACE[初始化 trace<br/>schema_version, routing_chain]
    EMPTY --> TRACE
    TRACE --> OUT[输出: messages, trace,<br/>schema_version, thread_id]
```

| 项 | 详情 |
|----|------|
| **输入** | `query`, `thread_id`, `trace` |
| **输出** | `trace`, `schema_version`, `thread_id`, `messages` |
| **错误处理** | 无（纯确定性） |
| **耗时** | < 1ms |

---

### 4.2 normalize_ui_context

| 项 | 详情 |
|----|------|
| **输入** | `ui_context.selections` |
| **输出** | `ui_context`（去重 + 标准化） |
| **标准化规则** | `type="report"` → `"doc"`（遗留兼容） |
| **去重** | 按 `(type, id)` 唯一键去重 |
| **容错** | 忽略非 dict 类型的 selection |

---

### 4.3 decide_output_mode

```mermaid
flowchart TD
    IN[输入: output_mode, query] --> CHECK1{UI 显式设定<br/>output_mode?}
    CHECK1 -->|是| USE_UI[使用 UI 值]
    CHECK1 -->|否| CHECK2{query 含<br/>report 触发词?}
    CHECK2 -->|"投资报告/研报/report<br/>(排除含 analysis)"| IR[investment_report]
    CHECK2 -->|否| BRIEF[brief]

    style IR fill:#ee5a24,color:#fff
    style BRIEF fill:#4a9eff,color:#fff
```

**report 触发词完整列表：**

| 语言 | 触发词 |
|------|--------|
| 简体中文 | 投资报告, 研报, 生成报告, 深度研究 |
| 繁体中文 | 投資報告, 研報, 生成報告 |
| English | in-depth report, report (排除含 "analysis" 的查询), deep research |

---

### 4.4 resolve_subject

```mermaid
flowchart TD
    IN[输入: selections, active_symbol, query] --> HAS_SEL{有 UI selections?}

    HAS_SEL -->|是 - 单选| SINGLE{type?}
    SINGLE -->|news| NI[news_item]
    SINGLE -->|filing| FI[filing]
    SINGLE -->|其他| RD[research_doc]

    HAS_SEL -->|是 - 多选| MULTI{全部同 type?}
    MULTI -->|全 news| NS[news_set]
    MULTI -->|全 filing| FI2[filing]
    MULTI -->|混合| RD2[research_doc]

    HAS_SEL -->|否| TICKER{query 含 ticker?}
    TICKER -->|是| COMPANY[company<br/>tickers 提取]
    TICKER -->|否| SYMBOL{有 active_symbol?}
    SYMBOL -->|是| COMPANY2[company]
    SYMBOL -->|否| UNKNOWN[unknown]

    style COMPANY fill:#10ac84,color:#fff
    style UNKNOWN fill:#ff6b6b,color:#fff
```

**ticker 提取机制：**
- 使用 `backend.config.ticker_mapping.extract_tickers()`
- 支持 600+ 公司名到 ticker 的映射
- 支持中文公司名（苹果→AAPL，特斯拉→TSLA）
- 正则匹配 1-5 字符大写字母组合

---

### 4.5 clarify（条件路由节点）

```mermaid
flowchart TD
    IN[输入: subject_type, query] --> CHECK{subject_type<br/>!= unknown?}
    CHECK -->|是| PASS[needed=false<br/>继续流程]
    CHECK -->|否| ANALYZE{分析 query}

    ANALYZE -->|空 query| EMPTY["needed=true<br/>question: '请问您想了解什么？'<br/>suggestions: 股票/新闻/对比"]
    ANALYZE -->|问候语| GREET["needed=true<br/>question: '你好！请告诉我...'<br/>suggestions: 实时行情/新闻/研报"]
    ANALYZE -->|无法识别| UNKNOWN["needed=true<br/>question: '请提供股票代码...'<br/>suggestions: 公司名/代码/选择"]

    PASS --> CONTINUE[→ parse_operation]
    EMPTY --> STOP[→ END]
    GREET --> STOP
    UNKNOWN --> STOP

    style STOP fill:#ff6b6b,color:#fff
    style CONTINUE fill:#1dd1a1,color:#fff
```

**问候语检测词：** `hi, hello, hey, 你好, 嗨, 哈喽` + 正则 `^(hi|hey|hello|你好|嗨)\s*[!！.。]?$`

---

### 4.6 parse_operation

**操作类型完整优先级表：**

| 优先级 | 操作名 | 置信度 | 中文触发词 | 英文触发词 |
|--------|--------|--------|-----------|-----------|
| 1 | `compare` | 0.80 | 对比, 比較, 相比, 哪个更 | vs, compare |
| 2 | `analyze_impact` | 0.75 | 影响, 冲击, 利好, 利空 | impact |
| 3 | `technical` | 0.85 | 技术面, 技术分析, 均线, 支撑, 阻力 | technical analysis, macd, rsi, kdj |
| 4 | `price` | 0.80 | 股价, 现价, 报价, 行情, 多少钱 | price, quote |
| 5 | `summarize` | 0.75 | 总结, 概括, 摘要, 要点 | tl;dr, summary |
| 6 | `extract_metrics` | 0.70 | 抽取, 提取, 指标 (仅 filing/doc) | extract, metrics, eps, guidance |
| 7 | `fetch` | 0.65 | 获取, 列出, 有哪些, 新闻, 最新 | fetch, latest, what happened |
| 8 | `qa` (默认) | 0.40-0.55 | — | — |

> **注意**：ASCII 短词（≤3字符如 "ma", "rsi"）使用 `\b` 词边界匹配，避免 "market" 误匹配 "ma"。

---

### 4.7 policy_gate

```mermaid
flowchart TD
    IN[输入: subject, output_mode, operation] --> BUDGET[计算预算基线]
    BUDGET --> TOOLS[确定工具白名单]
    TOOLS --> MODE{output_mode?}

    MODE -->|investment_report| AGENT_SELECT[Agent 评分选择<br/>capability_registry]
    MODE -->|brief/chat| NO_AGENT[无 Agent 执行]

    AGENT_SELECT --> SCHEMA[提取工具/Agent JSON Schema]
    NO_AGENT --> SCHEMA
    SCHEMA --> OUT[输出: policy<br/>预算 + 白名单 + Schema]

    style AGENT_SELECT fill:#ee5a24,color:#fff
```

**预算基线配置：**

| output_mode | max_rounds | max_tool_calls | max_seconds |
|-------------|-----------|----------------|-------------|
| `investment_report` | 6 | 8 | 120 |
| `chat` | 4 | 4 | 60 |
| `brief` | 3 | 4 | 60 |

**工具白名单矩阵：**

| subject_type | operation | 允许的工具 |
|-------------|-----------|-----------|
| news_item/news_set | * | get_company_news, search, get_current_datetime |
| company | price | get_stock_price, get_current_datetime, search |
| company | technical | + get_technical_snapshot |
| company | compare | + get_performance_comparison |
| company | 其他 (investment_report) | **全量 7 个工具** |
| filing/research_doc | * | search, get_current_datetime |

---

### 4.8 planner（核心调度）

```mermaid
flowchart TD
    IN[输入: 全部 state] --> MODE{LANGGRAPH_PLANNER_MODE?}

    MODE -->|"stub (默认)"| STUB[planner_stub<br/>确定性规则引擎]
    MODE -->|"llm"| LLM_INIT[create_llm]

    LLM_INIT -->|成功| PROMPT[build_planner_prompt<br/>含 A/B variant]
    LLM_INIT -->|失败| STUB

    PROMPT --> INVOKE[ainvoke_with_rate_limit_retry]
    INVOKE -->|成功| PARSE[_extract_json_object]
    INVOKE -->|失败| STUB

    PARSE -->|有效 JSON| ENFORCE[_enforce_policy<br/>强制约束]
    PARSE -->|无效| STUB

    ENFORCE --> VALIDATE[PlanIR.model_validate]
    VALIDATE -->|通过| OUT[输出: plan_ir]
    VALIDATE -->|失败| STUB

    STUB --> STUB_STEPS[规则生成步骤]
    STUB_STEPS --> VALIDATE

    style STUB fill:#10ac84,color:#fff
    style LLM_INIT fill:#ee5a24,color:#fff
```

**Planner A/B 测试：**

| Variant | 特征 | 适用场景 |
|---------|------|---------|
| **A** | 最少步骤, 强确定性, 低成本 | 生产默认 |
| **B** | 可解释性优先, why 字段详细, parallel_group | 实验对照 |

分桶逻辑：`SHA256(salt + thread_id) % 100 < split_percent → B，否则 A`

**_enforce_policy 强制约束流程：**
1. 强制 output_mode/budget 覆盖（防 LLM 自我升级）
2. 过滤 steps 到白名单工具/Agent
3. 标准化 step 输入格式
4. 注入必需工具步骤（若缺失）
5. 注入 `report_agents` 并行组
6. 高成本 Agent 标记 `__escalation_stage`
7. 预算断言 + 超出时渐进裁剪

---

### 4.9 execute_plan（执行引擎）

```mermaid
flowchart TD
    IN[输入: plan_ir.steps] --> MODE{LANGGRAPH_EXECUTE<br/>_LIVE_TOOLS?}

    MODE -->|"false (默认)"| DRY[dry_run 模式<br/>跳过实际调用]
    MODE -->|"true"| LIVE[live 模式<br/>实际调用工具/Agent]

    LIVE --> GROUP{有 parallel_group?}
    GROUP -->|是| PARALLEL[asyncio.gather<br/>并行执行]
    GROUP -->|否| SEQUENTIAL[顺序执行]

    PARALLEL --> COLLECT[收集结果]
    SEQUENTIAL --> COLLECT

    COLLECT --> EVIDENCE[构建 evidence_pool<br/>去重 + 标准化]
    DRY --> EVIDENCE

    EVIDENCE --> RAG{RAG v2<br/>启用?}
    RAG -->|是| INGEST[ingest_documents<br/>向量化存储]
    RAG -->|否| OUT
    INGEST --> OUT[输出: artifacts]

    style DRY fill:#ffa502,color:#fff
    style LIVE fill:#1dd1a1,color:#fff
    style PARALLEL fill:#0abde3,color:#fff
```

**Agent 执行并发模型：**

```mermaid
gantt
    title Agent 并行执行 (parallel_group="report_agents")
    dateFormat  X
    axisFormat  %s

    section 并行组
    PriceAgent      :a1, 0, 2
    NewsAgent       :a2, 0, 5
    FundamentalAgent:a3, 0, 3
    TechnicalAgent  :a4, 0, 2
    MacroAgent      :a5, 0, 8

    section 高成本（可选）
    DeepSearchAgent :a6, 0, 15
```

**evidence_pool 构建流程：**

| 来源 | 格式 | 去重键 |
|------|------|--------|
| selection_payload | 直接复制 | `(url, title)` |
| 工具输出 | `_append_tool_evidence()` | `(url, title)` |
| Agent 输出 | `_append_agent_evidence()` (summary + evidence[]) | `(url, title)` |

**RAG v2 TTL 策略：**

| subject_type | TTL |
|-------------|-----|
| filing / research_doc | 永久 |
| news / selection | 7 天 |
| 其他 | 12 小时 |

---

### 4.10 synthesize（数据合成）

```mermaid
flowchart TD
    IN[输入: subject, operation,<br/>output_mode, artifacts] --> MODE{LANGGRAPH_SYNTHESIZE_MODE?}

    MODE -->|"stub (默认)"| STUB_ROUTE{subject_type?}
    MODE -->|"llm"| LLM[LLM 填充 RenderVars JSON]

    STUB_ROUTE -->|news_item/news_set| NEWS_VARS[新闻模板变量]
    STUB_ROUTE -->|company + fetch| CNEWS_VARS[公司新闻变量]
    STUB_ROUTE -->|company + compare| CMP_VARS[对比变量]
    STUB_ROUTE -->|company + 其他| FULL_VARS[完整公司变量]
    STUB_ROUTE -->|filing/research_doc| DOC_VARS[文档变量]

    FULL_VARS --> THESIS[_build_investment_thesis<br/>多维信号交叉验证]
    FULL_VARS --> CONCLUSION[_build_conclusion_from_agents<br/>结构化结论]
    FULL_VARS --> VALUATION[_build_valuation_from_agents<br/>财务数据提取]
    FULL_VARS --> CATALYST[_build_catalysts_from_agents<br/>新闻催化]
    FULL_VARS --> RISK[_build_risks_from_agents<br/>风险聚合]

    LLM --> MERGE[stub 默认值 + LLM 覆盖<br/>protected_keys 保护]

    THESIS --> OUT[输出: artifacts.render_vars]
    CONCLUSION --> OUT
    VALUATION --> OUT
    CATALYST --> OUT
    RISK --> OUT
    MERGE --> OUT

    style THESIS fill:#10ac84,color:#fff
    style LLM fill:#ee5a24,color:#fff
```

**investment_thesis 信号聚合逻辑：**

```mermaid
flowchart LR
    PA[PriceAgent<br/>涨跌方向] --> AGG{信号聚合}
    TA[TechnicalAgent<br/>RSI/MACD/趋势] --> AGG
    FA[FundamentalAgent<br/>营收/利润 YoY] --> AGG
    MA[MacroAgent<br/>宏观环境] --> AGG
    NA[NewsAgent<br/>近期事件] --> AGG

    AGG --> COUNT[计算<br/>bull/bear 数量]

    COUNT -->|"bull >= bear+2"| BULLISH["偏多 (Bullish)"]
    COUNT -->|"bear >= bull+2"| BEARISH["偏空 (Bearish)"]
    COUNT -->|"bull > bear"| SLIGHT_BULL["中性偏多"]
    COUNT -->|"bear > bull"| SLIGHT_BEAR["中性偏空"]
    COUNT -->|"bull == bear"| NEUTRAL["中性 (Neutral)"]

    style BULLISH fill:#1dd1a1,color:#fff
    style BEARISH fill:#ff6b6b,color:#fff
    style NEUTRAL fill:#ffa502,color:#fff
```

**利多/利空信号提取规则：**

| 来源 | 利多条件 | 利空条件 |
|------|---------|---------|
| PriceAgent | summary 含 "up" / "上涨" | summary 含 "down" / "下跌" |
| TechnicalAgent | RSI oversold, MACD bullish | RSI overbought, MACD bearish |
| FundamentalAgent | Revenue YoY > +5% | Revenue YoY < -5% |
| FundamentalAgent | Net Income YoY > +10% | Net Income YoY < -10% |

---

### 4.11 render（模板渲染）

| 项 | 详情 |
|----|------|
| **输入** | `subject`, `output_mode`, `operation`, `artifacts.render_vars` |
| **输出** | `artifacts.draft_markdown` |
| **渲染引擎** | Python `string.Template.safe_substitute()` |
| **evidence 显示** | 仅 `LANGGRAPH_SHOW_EVIDENCE=true` 时输出 |

---

## 5. Agent 子系统

### 5.1 Agent 继承体系

```mermaid
classDiagram
    class BaseFinancialAgent {
        +str AGENT_NAME
        +int MAX_REFLECTIONS = 2
        +research(query, ticker, selection_ids)
        +analyze_stream(query, ticker, selection_ids)
        -_initial_search(query, ticker)
        -_first_summary(raw_data)
        -_identify_gaps(summary) LLM
        -_targeted_search(gaps)
        -_update_summary(summary, new_data) LLM
        -_format_output(summary, evidence)
    }

    class PriceAgent {
        +MAX_REFLECTIONS = 0
        +CACHE_TTL = 30s
        -_get_price_data(ticker)
        -Circuit Breaker: threshold=5
    }

    class NewsAgent {
        +CACHE_TTL = 600s
        -_get_news(ticker)
        -Circuit Breaker: threshold=3
    }

    class FundamentalAgent {
        +CACHE_TTL = 86400s
        -_get_financials(ticker)
        -_normalize_metrics(data)
    }

    class TechnicalAgent {
        +CACHE_TTL = 1800s
        -_compute_indicators(history)
        -MIN_POINTS = 30
    }

    class MacroAgent {
        -_multi_source_fetch()
        -_conflict_detection()
        -_merge_by_priority()
    }

    class DeepSearchAgent {
        +MAX_REFLECTIONS = env(2)
        +CACHE_TTL = 3600s
        -SearchConvergence
        -Self-RAG controller LLM
        -_fetch_full_document(url)
    }

    BaseFinancialAgent <|-- PriceAgent
    BaseFinancialAgent <|-- NewsAgent
    BaseFinancialAgent <|-- FundamentalAgent
    BaseFinancialAgent <|-- TechnicalAgent
    BaseFinancialAgent <|-- MacroAgent
    BaseFinancialAgent <|-- DeepSearchAgent
```

### 5.2 Agent 详细对比表

| 属性 | PriceAgent | NewsAgent | FundamentalAgent | TechnicalAgent | MacroAgent | DeepSearchAgent |
|------|-----------|-----------|-----------------|---------------|------------|----------------|
| **反思轮次** | 0 | 2 | 2 | 2 | 2 | env(2) |
| **缓存 TTL** | 30s | 600s | 86400s | 1800s | — | 3600s |
| **断路器阈值** | 5 | 3 | — | — | — | — |
| **断路器恢复** | 60s | 180s | — | — | — | — |
| **主数据源** | yfinance | finnhub news | yfinance financials | yfinance historical | FRED | tavily/exa |
| **备用数据源** | finnhub → alpha_vantage → tavily | get_company_news → tavily → search | get_company_info | — | market_sentiment → events → search | exa → search |
| **置信度范围** | 0.5-1.0 | 0.1-0.8 | 0.2-0.92 | 0.3-0.85 | 0.2-0.95 | 0.6-0.95 |
| **输出** | price, change, direction | headlines, summary | metrics, YoY/QoQ | MA/RSI/MACD/趋势 | 6 项宏观指标 | summary + evidence |
| **风险检测** | — | — | 负利润, 高杠杆 | 超买/超卖 | 收益率倒挂 | 信号冲突 |

### 5.3 BaseAgent 反思循环

```mermaid
flowchart TD
    START[research 入口] --> SEARCH[_initial_search<br/>首轮数据获取]
    SEARCH --> SUMMARY[_first_summary<br/>初始摘要]

    SUMMARY --> LOOP{反思轮次<br/>< MAX_REFLECTIONS?}

    LOOP -->|是| GAPS[_identify_gaps<br/>LLM 识别信息缺口]
    GAPS -->|有缺口| TARGET[_targeted_search<br/>针对性搜索]
    GAPS -->|无缺口| FORMAT
    TARGET --> UPDATE[_update_summary<br/>LLM 整合新信息]
    UPDATE --> LOOP

    LOOP -->|否| FORMAT[_format_output<br/>输出 summary + evidence + confidence]

    style GAPS fill:#ffa502,color:#fff
    style UPDATE fill:#0abde3,color:#fff
```

### 5.4 DeepSearchAgent Self-RAG 流程

```mermaid
flowchart TD
    START[deep_search 入口] --> QUERIES[生成搜索查询<br/>5-8 个主题]
    QUERIES --> SEARCH[Tavily/Exa 搜索<br/>每个查询 8 结果]
    SEARCH --> FETCH[获取完整文档<br/>HTTP + HTML解析 + PDF解析]
    FETCH --> DEDUP[SearchConvergence 去重]
    DEDUP --> SUMMARIZE[_summarize_docs<br/>LLM 生成摘要 + 引用]

    SUMMARIZE --> SELFRAG{Self-RAG 评估<br/>LLM JSON 判断}
    SELFRAG -->|"needs_more=true<br/>信息缺口存在"| NEWQ[提取新查询词]
    SELFRAG -->|"needs_more=false<br/>信息完整"| FORMAT[输出]

    NEWQ --> SEARCH2[补充搜索]
    SEARCH2 --> FETCH2[获取文档]
    FETCH2 --> UPDATE[_update_summary<br/>整合新信息]
    UPDATE --> SELFRAG

    style SELFRAG fill:#ee5a24,color:#fff
    style FORMAT fill:#1dd1a1,color:#fff
```

**SearchConvergence 停止条件：**
- `info_gain < threshold` (信息增量不足)
- 达到 MAX_REFLECTIONS
- 文档数达到 MAX_DOCS

---

## 6. 能力注册表与评分机制

### 6.1 评分公式

```
score = 0.05 (base)
      + subject_weight       (0.0 ~ 0.85)
      + operation_weight     (0.0 ~ 0.75)
      + output_mode_weight   (0.0 ~ 0.35)
      + keyword_boost        (0.0 ~ 0.45)
```

### 6.2 评分矩阵热力图

| Agent ↓ \ subject → | company | news_item | news_set | filing | research_doc | portfolio |
|---------------------|---------|-----------|----------|--------|-------------|-----------|
| **price_agent** | 0.55 | 0.20 | 0.20 | — | — | 0.40 |
| **news_agent** | 0.45 | 0.70 | 0.75 | — | — | — |
| **fundamental_agent** | 0.60 | — | — | 0.60 | 0.45 | — |
| **technical_agent** | 0.50 | — | — | — | — | 0.35 |
| **macro_agent** | 0.35 | — | 0.35 | — | — | 0.45 |
| **deep_search_agent** | 0.10 | — | — | 0.85 | 0.85 | — |

### 6.3 investment_report 必需 Agent 规则

| 条件组合 | 必需 Agent |
|---------|-----------|
| subject=company + output_mode=investment_report | **price, news, fundamental, macro, technical** (全5个) |
| subject=filing/research_doc | deep_search, fundamental |
| subject=news_item/news_set | news, price |
| operation=technical | price, technical |
| operation=compare | price, fundamental |
| query 含宏观关键词 | + macro |
| query 含深度关键词 | + deep_search |

### 6.4 Agent 选择流程

```mermaid
flowchart TD
    REQ[请求上下文<br/>subject, operation, query, output_mode] --> REQUIRED[计算 required_agents<br/>硬编码规则]

    REQUIRED --> SCORE[对所有 6 个 Agent 评分]
    SCORE --> SORT[按分数降序排列]
    SORT --> FILL[先填充 required<br/>再按分数补齐]
    FILL --> CAP[max_agents 截断<br/>默认 4 个]
    CAP --> OUT[allowed_agents 列表]

    style REQUIRED fill:#ee5a24,color:#fff
    style SCORE fill:#ffa502,color:#fff
```

---

## 7. 模板系统与路由矩阵

### 7.1 模板选择完整矩阵

| subject_type | operation | output_mode | 模板文件 | 模板变量 |
|-------------|-----------|-------------|---------|---------|
| news_item/news_set | * | brief/chat | `news_brief.md` | news_summary, impact_analysis, next_watch, risks |
| news_item/news_set | * | investment_report | `news_report.md` | query + 上述 |
| company | fetch | brief/chat | `company_news_brief.md` | ticker, query, news_summary, conclusion, risks |
| company | fetch | investment_report | `company_news_report.md` | ticker, query, news_summary, impact_analysis, next_watch, risks |
| company | * (多ticker) | brief/chat | `company_compare_brief.md` | tickers, query, comparison_conclusion, comparison_metrics, risks |
| company | * (多ticker) | investment_report | `company_compare_report.md` | tickers, query, comparison_conclusion, comparison_metrics, risks, evidence |
| company | * (单ticker) | brief/chat | `company_brief.md` | ticker, query, conclusion, price_snapshot, technical_snapshot, risks |
| **company** | ***** | **investment_report** | **`company_report.md`** | **ticker, query, investment_thesis, company_overview, price_snapshot, technical_snapshot, catalysts, valuation, risks, conclusion** |
| filing/research_doc | * | brief/chat | `filing_brief.md` | query, summary, highlights, section_citations, risks |
| filing/research_doc | * | investment_report | `filing_report.md` | query, summary, highlights, section_citations, analysis, risks |
| unknown | * | * | `company_brief.md` (降级) | — |

### 7.2 company_report.md 模板结构

```
## 投资研报：$ticker
  **问题**：$query
## 综合投资观点         ← _build_investment_thesis()
  $investment_thesis
## 公司与业务           ← _build_company_overview_from_agents()
  $company_overview
## 价格快照             ← _fmt_price_snapshot()
  $price_snapshot
## 技术面               ← _fmt_technical_snapshot()
  $technical_snapshot
## 关键催化剂           ← _build_catalysts_from_agents()
  $catalysts
## 财务与估值           ← _build_valuation_from_agents()
  $valuation
## 风险                 ← _build_risks_from_agents()
  $risks
## 结论与展望           ← _build_conclusion_from_agents()
  $conclusion
---
*免责声明*
```

---

## 8. Report Builder 构建流程

```mermaid
flowchart TD
    IN[输入: state + query + thread_id] --> CHECK{output_mode ==<br/>investment_report?}
    CHECK -->|否| NULL[return None]
    CHECK -->|是| CITATIONS[_build_citations<br/>evidence_pool → 标准引用]

    CITATIONS --> STATUS[_agent_status_from_steps<br/>每个 agent 状态/置信度]
    STATUS --> SUMMARIES[_agent_summaries_from_steps<br/>有序摘要列表]
    SUMMARIES --> SECTIONS[构建 sections<br/>+ citation_refs 桥接]
    SECTIONS --> RISKS[_extract_risks<br/>提取风险项]
    RISKS --> TAGS[_derive_report_tags_and_hints<br/>compare/conflict 标签]
    TAGS --> SYNTHESIS[_build_long_synthesis_report<br/>base_markdown + 引用来源]
    SYNTHESIS --> CONFIDENCE[计算 confidence_score<br/>成功 agent 平均置信度]
    CONFIDENCE --> VALIDATE[ReportValidator<br/>验证 + 修复]
    VALIDATE --> PAYLOAD[ReportIR Payload]

    style PAYLOAD fill:#1dd1a1,color:#fff
```

**ReportIR Payload 最终结构：**

```json
{
  "title": "AAPL 分析报告",
  "query": "深度分析 Apple",
  "thread_id": "xxx",
  "generated_at": "2026-02-11T...",
  "confidence_score": 0.85,
  "tickers": ["AAPL"],
  "sections": [...],
  "citations": [...],
  "meta": {
    "filing_section_citations": [...],
    "report_hints": { "is_compare": false, "has_conflict": false }
  },
  "synthesis_report": "## AAPL 综合研究报告\n...",
  "agent_status": {
    "price_agent": { "status": "success", "confidence": 1.0 },
    "fundamental_agent": { "status": "success", "confidence": 0.92 },
    ...
  },
  "risks": ["Leverage ratio elevated", ...],
  "tags": [],
  "report_hints": { "is_compare": false, "has_conflict": false }
}
```

---

## 9. LLM 重试与端点轮转

### 9.1 端点管理架构

```mermaid
flowchart TD
    CALL[LLM 调用] --> TRY[尝试当前端点]
    TRY -->|成功| SUCCESS[report_llm_success<br/>重置权重]
    TRY -->|失败| DETECT{错误类型?}

    DETECT -->|rate_limit / transient| RETRY{有 llm_factory?}
    DETECT -->|permanent| FAIL[抛出异常]

    RETRY -->|是| ROTATE[llm_factory()<br/>创建新 LLM 实例<br/>绑定下一端点]
    RETRY -->|否| BACKOFF[sleep + jitter<br/>原地重试]

    ROTATE --> TRY2[立即重试<br/>wait=0]
    BACKOFF --> TRY

    TRY2 -->|达到 max_attempts| FAIL

    style ROTATE fill:#0abde3,color:#fff
    style BACKOFF fill:#ffa502,color:#fff
    style FAIL fill:#ff6b6b,color:#fff
```

### 9.2 端点轮转算法

```
EndpointManager (加权 Smooth 轮转):

  for each endpoint:
    current_weight += weight

  selected = max(current_weight)
  selected.current_weight -= total_weight

  if selected is cooling_down:
    skip → select next

  if all cooling_down:
    select earliest recovery
```

### 9.3 重试参数配置

| 参数 | 默认值 | 环境变量 |
|------|--------|---------|
| max_attempts | 6 | `LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS` |
| sleep_seconds | 5 | `LLM_RATE_LIMIT_RETRY_SLEEP_SECONDS` |
| jitter_seconds | 2 | `LLM_RATE_LIMIT_RETRY_JITTER_SECONDS` |
| cooldown_sec | 90 | `LLM_ENDPOINT_DEFAULT_COOLDOWN_SEC` |
| acquire_timeout | 3600 | — |

### 9.4 可重试错误检测

| 类别 | 匹配模式 |
|------|---------|
| Rate Limit | "429", "rate limit", "too many requests", "quota", "exceeded" |
| HTTP 状态码 | 401, 403, 404, 408, 409, 425, 429, 500, 502, 503, 504 |
| 临时错误 | "unauthorized", "forbidden", "timeout", "ssl", "eof", "connection" |
| 中文错误 | "无可用渠道", "资源不足" |

---

## 10. Prompt 体系全览

### 10.1 Prompt 清单

| # | Prompt 名称 | 文件 | 语言 | 质量 | 调用时机 |
|---|------------|------|------|------|---------|
| 1 | CIO System Prompt | `langchain_agent.py:53` | EN | ⭐⭐⭐⭐⭐ | LangChain Agent 模式 |
| 2 | Followup System | `prompts/system_prompts.py:20` | EN | ⭐⭐⭐⭐ | 追问处理 |
| 3 | Forum Synthesis | `prompts/system_prompts.py:57` | CN | ⭐⭐⭐⭐⭐ | 报告合成（270行） |
| 4 | Gap Detection | `agents/base_agent.py:164` | CN | ⭐⭐⭐⭐ | Agent 反思循环 |
| 5 | Summary Update | `agents/base_agent.py:264` | CN | ⭐⭐⭐⭐ | Agent 摘要整合 |
| 6 | Self-RAG Controller | `agents/deep_search_agent.py:234` | CN | ⭐⭐⭐⭐⭐ | 深度搜索缺口检测 |
| 7 | Deep Research Memo | `agents/deep_search_agent.py:758` | CN | ⭐⭐⭐⭐⭐ | 研究备忘录生成 |
| 8 | Planner Prompt | `graph/planner_prompt.py:56` | EN | ⭐⭐⭐⭐ | LLM 规划模式 |
| 9 | Synthesize LLM | `graph/nodes/synthesize.py:1070` | EN | ⭐⭐⭐ | LLM 合成模式 |
| 10 | Intent Classifier | `orchestration/intent_classifier.py:443` | EN/CN | ⭐⭐⭐ | 意图分类回退 |
| 11 | Schema Router | `conversation/schema_router.py:583` | EN | ⭐⭐⭐ | 工具路由 |
| 12 | News Summary | `agents/news_agent.py:437` | CN | ⭐⭐⭐ | 新闻摘要流式生成 |

### 10.2 Prompt 调用链路

```mermaid
flowchart LR
    USER[用户查询] --> IC[Intent Classifier<br/>Prompt #10]
    IC --> SR[Schema Router<br/>Prompt #11]

    subgraph "LangGraph Pipeline"
        SR --> PLANNER[Planner<br/>Prompt #8]
        PLANNER --> AGENTS[Agent 执行]
        AGENTS --> SYNTH[Synthesize<br/>Prompt #9]
    end

    subgraph "Agent 内部"
        AGENTS --> GAP[Gap Detection<br/>Prompt #4]
        GAP --> UPDATE[Summary Update<br/>Prompt #5]
        AGENTS --> SELFRAG[Self-RAG<br/>Prompt #6]
        SELFRAG --> MEMO[Deep Memo<br/>Prompt #7]
    end

    SYNTH --> FORUM[Forum Synthesis<br/>Prompt #3]

    USER -->|追问| FOLLOWUP[Followup<br/>Prompt #2]

    style FORUM fill:#ee5a24,color:#fff
    style SELFRAG fill:#0abde3,color:#fff
```

---

## 11. 端到端数据流示例

### 示例：`"深度研究 Apple 投资报告"`

```mermaid
sequenceDiagram
    participant U as 用户
    participant API as ChatRouter
    participant G as LangGraph
    participant PA as PriceAgent
    participant NA as NewsAgent
    participant FA as FundamentalAgent
    participant TA as TechnicalAgent
    participant MA as MacroAgent
    participant RB as ReportBuilder

    U->>API: "深度研究 Apple 投资报告"
    API->>G: ainvoke(query, thread_id)

    Note over G: build_initial_state
    Note over G: normalize_ui_context
    Note over G: decide_output_mode → "investment_report"
    Note over G: resolve_subject → company, tickers=["AAPL"]
    Note over G: clarify → needed=false
    Note over G: parse_operation → qa (0.55)
    Note over G: policy_gate → 5 agents, 7 tools
    Note over G: planner → PlanIR (7 steps)

    par execute_plan (parallel)
        G->>PA: research("AAPL")
        PA-->>G: price=$273.31, change=-0.48%
        G->>NA: research("AAPL")
        NA-->>G: 5 headlines, summary
        G->>FA: research("AAPL")
        FA-->>G: revenue, net_income, YoY
        G->>TA: research("AAPL")
        TA-->>G: MA/RSI/MACD/trend
        G->>MA: research("AAPL")
        MA-->>G: fed_rate, cpi, unemployment
    end

    Note over G: synthesize → RenderVars<br/>investment_thesis: "中性偏空"<br/>conclusion: 技术面+基本面+后续关注
    Note over G: render → company_report.md 模板渲染

    G->>RB: build_report_payload(state)
    RB-->>G: ReportIR payload

    G-->>API: state (含 draft_markdown + report)
    API-->>U: SSE stream (synthesis_report + agent cards)
```

### 状态流转表

| 步骤 | 节点 | state 变更 | 耗时估算 |
|------|------|-----------|---------|
| 1 | build_initial_state | +messages, +trace, +schema_version | <1ms |
| 2 | normalize_ui_context | ui_context 标准化 | <1ms |
| 3 | decide_output_mode | output_mode = "investment_report" | <1ms |
| 4 | resolve_subject | subject = {type: "company", tickers: ["AAPL"]} | ~5ms |
| 5 | clarify | clarify = {needed: false} | <1ms |
| 6 | parse_operation | operation = {name: "qa", confidence: 0.55} | <1ms |
| 7 | policy_gate | policy = {agents: 5个, tools: 7个, rounds: 6} | ~10ms |
| 8 | planner | plan_ir = {steps: [tools + agents]} | ~50ms (stub) |
| 9 | execute_plan | artifacts = {evidence_pool, agent_outputs} | **5-30s** |
| 10 | synthesize | artifacts.render_vars = {thesis, conclusion, ...} | ~10ms |
| 11 | render | artifacts.draft_markdown = 完整 Markdown | ~5ms |
| 12 | report_builder | report payload = ReportIR | ~20ms |

---

## 12. 故障降级策略

### 12.1 降级链路

```mermaid
flowchart TD
    LLM_PLANNER[LLM Planner] -->|失败| STUB_PLANNER[Stub Planner]
    LLM_SYNTH[LLM Synthesize] -->|失败| STUB_SYNTH[Stub Synthesize]

    AGENT_PRIMARY[Agent 主数据源] -->|失败| AGENT_FALLBACK[备用数据源]
    AGENT_FALLBACK -->|失败| AGENT_SEARCH[通用搜索]
    AGENT_SEARCH -->|失败| AGENT_CACHE[缓存数据]
    AGENT_CACHE -->|失败| AGENT_EMPTY[空输出 + 低置信度]

    DEEP_LLM[DeepSearch LLM 摘要] -->|失败| DEGRADED[_build_degraded_summary<br/>拼接标题/snippet]

    REPORT[报告生成] -->|失败| REPORT_NONE[report = None<br/>仅返回 draft_markdown]

    style STUB_PLANNER fill:#ffa502,color:#fff
    style AGENT_EMPTY fill:#ff6b6b,color:#fff
    style DEGRADED fill:#ffa502,color:#fff
```

### 12.2 故障记录格式

```json
{
  "schema_version": "failure.v1",
  "ts": "2026-02-11T...",
  "node": "planner",
  "stage": "llm_invoke",
  "error": "Rate limit exceeded",
  "fallback": "planner_stub",
  "retryable": true,
  "retry_attempts": 3,
  "metadata": { "endpoint": "api.openai.com" }
}
```

### 12.3 环境变量速查

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LANGGRAPH_PLANNER_MODE` | stub | planner 模式: stub / llm |
| `LANGGRAPH_SYNTHESIZE_MODE` | stub | synthesize 模式: stub / llm |
| `LANGGRAPH_EXECUTE_LIVE_TOOLS` | false | 是否实际调用工具 |
| `LANGGRAPH_SHOW_EVIDENCE` | false | 渲染时是否显示 evidence |
| `LANGGRAPH_PLANNER_AB_ENABLED` | false | A/B 测试开关 |
| `LANGGRAPH_REPORT_MAX_AGENTS` | 4 | 最大 Agent 数 |
| `LANGGRAPH_REPORT_MIN_AGENTS` | 2 | 最小 Agent 数 |
| `DEEPSEARCH_MAX_REFLECTIONS` | 2 | DeepSearch 最大反思轮次 |
| `LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS` | 6 | LLM 最大重试次数 |
| `LLM_ENDPOINT_DEFAULT_COOLDOWN_SEC` | 90 | 端点冷却时间 |

---

> 文档由 FinSight AI 工程团队维护 | 最后更新：2026-02-11
