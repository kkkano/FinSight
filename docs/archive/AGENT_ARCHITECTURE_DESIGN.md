# FinSight Agent 架构设计文档

> **版本**: v2.1 — Sprint 2 (Tool-Aware Reflection)
> **最后更新**: 2026-02-14
> **作者**: FinSight Architecture Team
> **状态**: Production

---

## 目录

1. [架构总览](#1-架构总览)
2. [核心数据契约](#2-核心数据契约)
3. [BaseFinancialAgent 基类设计](#3-basefinancialagent-基类设计)
4. [五个子 Agent 架构模式详解](#4-五个子-agent-架构模式详解)
5. [冲突检测与求证系统](#5-冲突检测与求证系统)
6. [LLM 分析子系统](#6-llm-分析子系统)
7. [降级与容错机制](#7-降级与容错机制)
8. [LangFuse 链路追踪](#8-langfuse-链路追踪)
9. [配置参考](#9-配置参考)
10. [设计决策记录 (ADR)](#10-设计决策记录-adr)

---

## 1. 架构总览

### 1.1 系统分层

```
┌─────────────────────────────────────────────────┐
│                  Frontend (React)                │
│          ReportView / AgentLogPanel              │
├─────────────────────────────────────────────────┤
│              Render Layer (Layer 4)              │
│     render_stub.py — 模板渲染 + 冲突展示        │
├─────────────────────────────────────────────────┤
│          Report Builder Layer (Layer 3)          │
│    report_builder.py — 冲突门禁 + 质量校验      │
├─────────────────────────────────────────────────┤
│           Synthesize Layer (Layer 2)             │
│    synthesize.py — 冲突裁决 + 叙事报告合成      │
├─────────────────────────────────────────────────┤
│             Agent Layer (Layer 1)                │
│   5 个子 Agent — 数据采集 + LLM 分析 + 冲突标注  │
├─────────────────────────────────────────────────┤
│           Executor / Planner / Graph             │
│   executor.py → planner.py → state.py           │
└─────────────────────────────────────────────────┘
```

### 1.2 数据流

```
Query → Planner (意图识别 → 选择 Agent 组合)
      → Executor (并行/串行执行各 Agent)
      → Agent Layer (每个 Agent: 搜索 → 分析 → 标注冲突 → 输出 AgentOutput)
      → Synthesize Layer (收集冲突 → 触发判定 → 裁决/降级 → 生成叙事报告)
      → Report Builder (冲突门禁 → 质量校验 → 构建 ReportIR)
      → Render Layer (模板渲染 → 前端展示)
```

### 1.3 Agent 组合策略

| 查询类型 | 触发 Agent | 冲突检测 |
|---------|-----------|---------|
| 单纯问价格 "AAPL price" | price_agent | ❌ 跳过 |
| 价格 + 原因 "AAPL 为什么涨" | price + news + technical | ✅ 开启 |
| 公司研究 "分析 TSLA" | 全部 5 个 | ✅ 开启 |
| 新闻影响 "特斯拉新闻影响" | news + price + technical + fundamental | ✅ 开启 |
| 深度研报 "AAPL deep report" | 全部 5 个 | ✅ 始终开启 |
| 仪表盘选数据提问 | 按 Planner 实际分配 | 按成功数判定 |

---

## 2. 核心数据契约

### 2.1 EvidenceItem

每条证据的最小单元。

```python
@dataclass
class EvidenceItem:
    text: str                              # 证据文本
    source: str                            # 数据源名称 (yfinance, finnhub, FRED...)
    url: Optional[str] = None              # 原始 URL
    timestamp: Optional[str] = None        # 数据时间戳
    confidence: float = 1.0                # 0-1 置信度
    title: Optional[str] = None            # 标题
    meta: Dict[str, Any] = field(...)      # 扩展元数据
```

### 2.2 ConflictClaim

结构化冲突记录，每条冲突都包含完整的来源、数值、裁决信息。

```python
@dataclass
class ConflictClaim:
    claim: str              # 冲突主题 (如 "短期动量方向"、"CPI 通胀率")
    source_a: str           # 来源 A 名称
    value_a: str            # 来源 A 的值
    source_b: str           # 来源 B 名称
    value_b: str            # 来源 B 的值
    severity: str           # "low" / "medium" / "high"
    resolved: bool          # 是否已裁决
    resolution: str | None  # 裁决依据 (如 "采信优先级更高的 FRED 数据")
    timestamp_a: str | None # 来源 A 时间戳
    timestamp_b: str | None # 来源 B 时间戳
```

**设计理由**：主人要求"每条冲突都要有：冲突点、来源A/B、时间戳、裁决依据、未解决原因、后续补证项"，因此采用完整结构化 dataclass 而非简单字符串。

### 2.3 AgentOutput（统一输出契约）

所有 5 个 Agent 必须返回此结构，确保下游 Synthesize/ReportBuilder 可以统一消费。

```python
@dataclass
class AgentOutput:
    # --- 核心字段 ---
    agent_name: str                                    # Agent 标识
    summary: str                                       # 分析摘要 (LLM 生成或确定性)
    evidence: List[EvidenceItem]                       # 证据列表
    confidence: float                                  # 0-1 置信度
    data_sources: List[str]                            # 使用的数据源列表
    as_of: str                                         # ISO 时间戳

    # --- 质量元数据 ---
    evidence_quality: Dict[str, Any] = field(...)      # 质量评分
    fallback_used: bool = False                        # 是否使用了降级数据
    risks: List[str] = field(...)                      # 风险提示列表
    trace: List[Dict[str, Any]] = field(...)           # 执行追踪

    # --- 冲突追踪 (Sprint 2 新增) ---
    conflict_flags: List[str] = field(...)             # 冲突标记 (人类可读)
    conflicting_claims: List[ConflictClaim] = field(...)# 结构化冲突记录

    # --- 降级可观测 (Sprint 2 新增) ---
    fallback_reason: Optional[str] = None              # 降级原因
    retryable: bool = True                             # 是否可重试
    error_stage: Optional[str] = None                  # 失败阶段
```

---

## 3. BaseFinancialAgent 基类设计

### 3.1 研究流程 (Research Pipeline)

```
research(query, ticker)
  │
  ├── _initial_search(query, ticker)       # 工具调用，获取原始数据
  │
  ├── _first_summary(data)                 # LLM 分析 (各子类重写)
  │     ├── _deterministic_summary(data)   # 确定性摘要 (fallback)
  │     └── _llm_analyze(summary, role, focus)  # LLM 增强分析
  │
  ├── [Reflection Loop] × MAX_REFLECTIONS  # 工具感知反思循环
  │     ├── _identify_gaps(summary)        # LLM: 识别缺口 + 建议工具 (JSON)
  │     ├── _targeted_search(gaps)         # 按工具注册表分发调用
  │     └── _update_summary(summary, new_data)  # LLM: 更新摘要
  │
  └── _format_output(summary, raw_data)    # 构建 AgentOutput
        ├── 生成 evidence 列表
        ├── 计算 confidence
        ├── 检测冲突 → conflict_flags + conflicting_claims
        └── 设置 fallback 可观测字段
```

### 3.2 工具注册表系统 (Tool Registry)

**v2.1 新增** — 让反射循环中 LLM 自主选择该调用哪个工具，而非所有 gap 都走 `search()`。

#### 3.2.1 工具注册表格式

每个子 Agent 覆写 `_get_tool_registry()` 方法，返回可用工具映射：

```python
def _get_tool_registry(self) -> dict:
    """返回 { "tool_name": { "func": callable, "description": str, "call_with": str } }"""
    return {
        "search": {
            "func": self.tools.search,
            "description": "通用网络搜索，可查询任意信息",
            "call_with": "query",   # "query" | "ticker" | "none"
        },
        "get_company_news": {
            "func": self.tools.get_company_news,
            "description": "获取公司新闻列表(ticker)",
            "call_with": "ticker",
        },
    }
```

#### 3.2.2 `call_with` 调用模式

| 模式 | 行为 | 适用场景 |
|------|------|---------|
| `"query"` | `func(f"{ticker} {gap_query}")` | 通用搜索 |
| `"ticker"` | `func(ticker)` | 专用 API (新闻、财务、K线) |
| `"none"` | `func()` | 无参数 API (市场情绪、经济日历) |

#### 3.2.3 各 Agent 工具注册表

| Agent | 工具数 | 工具列表 |
|-------|--------|---------|
| PriceAgent | 1 | `search` |
| NewsAgent | 3 | `search`, `get_company_news`, `get_news_sentiment` |
| FundamentalAgent | 3 | `search`, `get_financial_statements`, `get_company_info` |
| TechnicalAgent | 2 | `search`, `get_stock_historical_data` |
| MacroAgent | 4 | `search`, `get_fred_data`, `get_market_sentiment`, `get_economic_events` |

### 3.3 工具感知反射流程

#### 3.3.1 `_identify_gaps()` — JSON 结构化输出

反射时 LLM 被要求输出 JSON 格式的 gap 列表，每条包含建议工具：

```
<available_tools>
- search: 通用网络搜索
- get_company_news: 获取公司新闻列表(ticker)
- get_news_sentiment: 获取新闻情绪分析(ticker)
</available_tools>

<output_format>
每行一条 JSON: {"gap": "缺失信息", "tool": "工具名", "query": "搜索参数"}
信息已充分时: {"complete": true}
</output_format>
```

**向后兼容**：JSON 解析失败时退回纯文本模式（旧行为），将整行当作 search query。

#### 3.3.2 `_targeted_search()` — 工具分发逻辑

```
gap_item (dict/str)
  │
  ├── dict 格式 → 提取 tool + query
  │     ├── tool 在注册表中 → 调用对应工具
  │     └── tool 不在注册表中 → 降级到 search
  │
  └── str 格式 → 直接走 search (向后兼容)
```

**安全降级链**：
```
指定工具调用失败 → 退回 search → search 也失败 → 跳过该 gap
```

每次工具调用都通过 `trace_emitter` 发射事件，前端 AgentLogPanel 可见。

### 3.4 反射次数设计

| Agent | MAX_REFLECTIONS | 理由 |
|-------|----------------|------|
| PriceAgent | 1 | 价格可能需补充日内/历史对比数据 |
| NewsAgent | 1 | ReAct 模式：首轮观察 → 反射补充关联新闻 |
| FundamentalAgent | 1 | CoT 模式：首轮财务分析 → 反射检查遗漏风险 |
| TechnicalAgent | 1 | 信号共振：首轮指标 → 反射验证形态解读 |
| MacroAgent | 1 | Plan-Execute-Reflect：首轮数据 → 反射交叉验证 |

统一设为 1 而非更高的原因：
- **成本控制**：每次反射 = 1 次 LLM 调用 + N 次工具调用
- **延迟控制**：用户可接受 <15s 的报告生成时间
- **收益递减**：实测 2+ 轮反射对最终报告质量提升 <5%
- **可配置**：通过 `BASE_AGENT_MAX_REFLECTIONS` 环境变量全局覆盖

---

## 4. 五个子 Agent 架构模式详解

### 4.1 PriceAgent — Augmented Data（增强数据模式）

**文件**: `backend/agents/price_agent.py`

**选择理由**：
- 价格数据本身是客观事实（实时报价、日内变动百分比），不需要复杂推理
- 但"增强"意味着 LLM 将原始数字转化为有意义的市场解读
- 与 ReAct 的区别：价格查询不需要"推理→行动→观察"循环，一次查询即可获得全部所需数据

**架构模式**：
```
get_stock_price(ticker)
  │
  ├── 确定性摘要: "{ticker} 当前价格: USD {price}，日内涨跌 {pct}%"
  │
  └── LLM 增强分析 (role = "资深量化交易分析师")
      focus: "解读价格水平和日内变动：波动幅度是否异常、
             市场情绪、与近期趋势的关系、短期方向判断"
```

**冲突检测**：PriceAgent 本身不产生内部冲突（单一数据源），但其输出参与跨 Agent 冲突检测。

**降级路径**：
```
主数据源失败 → fallback_used=True, fallback_reason="primary_source_unavailable"
LLM 分析失败 → 退回 _deterministic_summary() (纯数字)
```

---

### 4.2 NewsAgent — ReAct（推理-行动模式）

**文件**: `backend/agents/news_agent.py`

**选择理由**：
- 新闻分析天然符合 ReAct 模式：先**观察**新闻标题，**推理**事件间关联，**评估**影响
- 新闻数据有时效性和情绪倾向，需要区分噪音 vs 趋势信号
- 与 CoT 的区别：新闻需要多步观察（先看标题→再分析关联→最后评估风险），不是单纯的逻辑链

**架构模式（真 ReAct — 工具感知反射）**：
```
search_news(query) → 获取 8-10 条新闻
  │
  ├── 确定性摘要: "Recent news includes: {headline1}; {headline2}; ..."
  │
  ├── LLM ReAct 分析 (role = "资深金融新闻分析师（ReAct 推理模式）")
  │     focus:
  │       1. Observe: 从新闻标题中识别核心主题
  │       2. Reason: 分析事件间关联性、情绪倾向
  │       3. Assess: 区分短期噪音 vs 中长期趋势
  │       4. Risk: 标注关键不确定性
  │
  └── [Reflection] LLM 可选择：
        - get_company_news: 补充更多公司新闻
        - get_news_sentiment: 获取量化情绪分析
        - search: 搜索关联事件
```

**工具注册表**: `search` + `get_company_news` + `get_news_sentiment` (反射时 LLM 自主选择)

**冲突检测**：新闻 Agent 不产生结构化数值冲突（新闻是定性信息），但其情绪判断参与跨 Agent 检测。

**降级路径**：
```
无新闻数据 → fallback_used=True, fallback_reason="no_news_data"
LLM 分析失败 → 退回标题列表
```

---

### 4.3 FundamentalAgent — Chain-of-Thought（链式推理模式）

**文件**: `backend/agents/fundamental_agent.py`

**选择理由**：
- 基本面分析需要**严格的逻辑推导链**：盈利质量 → 财务健康 → 增长持续性 → 估值含义 → 风险信号
- 每一步推导都基于上一步的结论，天然适合 CoT
- 与 ReAct 的区别：基本面数据来自同一次 API 调用（财务报表），不需要"行动-观察"循环
- 与 Plan-Execute 的区别：分析逻辑是固定的 5 步链，不需要动态规划

**架构模式（真 Chain-of-Thought — 2-step LLM 链）**：
```
get_financials(ticker) → 获取营收、利润率、增长率等
  │
  ├── 确定性摘要: "营收: {rev}，同比: {yoy}%，环比: {qoq}%，毛利率: {margin}%"
  │
  ├── Step 1: LLM 分析 (role = "资深卖方基本面分析师（CoT 第一步）")
  │     focus: "盈利质量 + 财务健康 + 关键发现"
  │
  └── Step 2: LLM 分析 (role = "资深卖方基本面分析师（CoT 第二步）")
        input: 确定性摘要 + Step 1 分析结果 (真链式依赖)
        focus: "增长持续性 + 估值含义 + 风险信号 + 综合判断"
```

**与"假 CoT"的区别**：
- v2.0 (旧): 单次 LLM 调用，prompt 里写"按 CoT 分析" — 本质是 prompt 伪装
- v2.1 (新): 真正的 2-step 链，Step 2 的输入包含 Step 1 的输出，LLM 基于前一步结论进行增量推理
- 降级链: Step 2 失败 → 返回 Step 1 结果; Step 1 失败 → 返回确定性摘要

**工具注册表**: `search` + `get_financial_statements` + `get_company_info` (反射时可选择拉取额外数据)

**冲突检测**：
```python
# 营收高增长 vs 毛利率下滑 → "盈利质量一致性" 冲突
if rev_yoy > 10 and margin_qoq < -5:
    conflict_flags.append("营收高增长 vs 毛利率下滑")
    conflicting_claims.append(ConflictClaim(
        claim="盈利质量一致性",
        source_a="营收同比", value_a=f"+{rev_yoy:.1f}%",
        source_b="毛利率环比", value_b=f"{margin_qoq:+.1f}%",
        severity="medium",
    ))
```

**降级路径**：
```
财务数据不完整 → fallback_reason="financial_data_incomplete"
LLM 分析失败 → 退回格式化的财务指标文本
```

---

### 4.4 TechnicalAgent — Signal Confluence（信号共振模式）

**文件**: `backend/agents/technical_agent.py`

**选择理由**：
- 技术分析的核心是**多信号共振验证**：均线趋势、RSI 动量、MACD 方向必须互相印证
- 当信号矛盾时（如 RSI 超买但 MACD 仍多头），这本身就是重要信息
- 与 CoT 的区别：技术指标之间是**并行对比**关系，不是线性推导链
- 与 ReAct 的区别：所有指标来自同一份 K 线数据，不需要多步搜索

**架构模式（Signal Confluence — 工具感知增强）**：
```
get_kline_data(ticker) → 获取 K 线
  │
  ├── _compute_indicators() → MA20/50/200, RSI(14), MACD/Signal
  │     ├── 趋势判断: uptrend / downtrend / sideways
  │     ├── RSI 状态: overbought / oversold / neutral
  │     └── 动量方向: bullish / bearish
  │
  ├── 确定性摘要: 指标数值 + 状态判断
  │
  ├── LLM 共振分析 (role = "资深技术分析师（Signal Confluence 模式）")
  │     focus: "均线趋势 → 动量评估 → 关键价位 → 信号共振 → 交易含义"
  │
  └── [Reflection] LLM 可选择：
        - get_stock_historical_data: 拉取更长周期 K 线验证
        - search: 搜索技术分析观点
```

**工具注册表**: `search` + `get_stock_historical_data` (反射时可重新拉取不同周期数据)

**冲突检测（核心功能）**：

| 冲突类型 | 条件 | 严重度 |
|---------|------|--------|
| RSI 超买 vs MACD 多头 | `rsi_state=="overbought" && momentum=="bullish"` | medium |
| RSI 超卖 vs MACD 空头 | `rsi_state=="oversold" && momentum=="bearish"` | medium |
| 均线多头 vs MACD 空头 | `trend=="uptrend" && momentum=="bearish"` | low |
| 均线空头 vs MACD 多头 | `trend=="downtrend" && momentum=="bullish"` | low |

**设计考量**：RSI vs MACD 矛盾标记为 `severity="medium"` 而非 `high`，因为短期超买+趋势延续在牛市中很常见，不一定意味着错误信号。

---

### 4.5 MacroAgent — Plan-Execute-Reflect（计划-执行-反思模式）

**文件**: `backend/agents/macro_agent.py`

**选择理由**：
- 宏观分析需要**动态规划**数据源：不同查询需要不同的指标组合（利率查询 vs 通胀查询 vs 就业查询）
- 多数据源采集后需要**交叉验证**（FRED vs 市场情绪 vs 经济日历）
- 数据冲突在宏观层面最常见（不同机构发布的数据可能不一致）
- 与 CoT 的区别：数据采集阶段需要动态决策"去哪里找"，不是固定链
- 与 ReAct 的区别：MacroAgent 的"反思"步骤更重——需要跨源一致性验证

**架构模式（真 Plan-Execute-Reflect — 最丰富工具集）**：
```
Phase 1 - Plan:
  根据 query 确定需要的宏观指标 (_INDICATORS map)

Phase 2 - Execute:
  并行采集: FRED API + Market Sentiment + Economic Calendar + Web Search

Phase 3 - Reflect (工具感知):
  _merge_indicator_sources() → 多源数据合并
    ├── 发现冲突 → 记录到 conflicts 列表
    ├── 优先级裁决 → 采信权威源 (FRED > Sentiment > Search)
    └── 一致性评分 → evidence_quality.overall_score

  [Reflection] LLM 可说"FRED 和搜索数据冲突" → 框架调用：
    - get_fred_data: 重新拉取 FRED 数据验证
    - get_market_sentiment: 获取 CNN 恐贪指数交叉验证
    - get_economic_events: 检查经济日历事件
    - search: 搜索补充验证
```

**工具注册表 (最丰富)**: `search` + `get_fred_data` + `get_market_sentiment` + `get_economic_events`

**冲突检测（最完整）**：

MacroAgent 是唯一支持**自动裁决**的 Agent：

```python
# 从 _merge_indicator_sources 输出中提取冲突
for conflict_item in conflicts:
    indicator_label = self._INDICATORS[indicator_key]["label"]
    delta = conflict_item["delta"]
    severity = "high" if delta > threshold * 2 else "medium"

    conflicting_claims.append(ConflictClaim(
        claim=indicator_label,
        source_a=chosen_source_name,     # 优先源 (FRED)
        value_a=str(chosen_value),
        source_b=other_source_name,      # 次优源
        value_b=str(other_value),
        severity=severity,
        resolved=True,                   # ← 自动裁决
        resolution=f"采信优先级更高的 {chosen_source_name} 数据",
    ))
```

**数据源优先级**：
```
FRED (官方统计) > CNN Fear & Greed (市场情绪) > Economic Calendar > Web Search
```

---

## 5. 冲突检测与求证系统

### 5.1 四层架构

```
┌─────────────────────────────────────┐
│  Layer 4: Render (只展示)            │
│  前端读 conflict_disclosure 直接渲染  │
├─────────────────────────────────────┤
│  Layer 3: Report Builder (门禁)      │
│  检测降级标记 → 惩罚 confidence      │
│  注入 risks → 追加 synthesis_report  │
│  打 tag: conflict / conflict_degraded│
├─────────────────────────────────────┤
│  Layer 2: Synthesize (裁决)          │
│  触发条件判定 → 收集冲突             │
│  生成 conflict_disclosure            │
│  降级标记 → narrative prompt 注入    │
├─────────────────────────────────────┤
│  Layer 1: Agent (标注)               │
│  各 Agent _format_output 中          │
│  检测内部冲突 → conflict_flags       │
│  生成 ConflictClaim → conflicting_claims│
└─────────────────────────────────────┘
```

### 5.2 触发条件公式

```
detect = deep_report || (success_agents >= 2 && comparable_claims >= 1)
```

**各变量定义**：

| 变量 | 定义 | 来源 |
|------|------|------|
| `deep_report` | `output_mode == "investment_report"` | GraphState |
| `success_agents` | 返回了非 skipped 且有 summary 的 Agent 数 | step_results 实际结果 |
| `comparable_claims` | 可比命题对数（两个成功 Agent 分析领域有交集） | 可比命题矩阵 |

### 5.3 可比命题矩阵

两个 Agent 的分析领域有交集时，它们的结论才可能冲突：

```python
_COMPARABLE_PAIRS = [
    ("technical_agent", "fundamental_agent", "方向判断"),
    ("technical_agent", "news_agent",        "价格动量 vs 事件冲击"),
    ("technical_agent", "price_agent",       "技术信号 vs 实际走势"),
    ("fundamental_agent", "news_agent",      "基本面 vs 事件影响"),
    ("fundamental_agent", "macro_agent",     "个股基本面 vs 宏观环境"),
    ("news_agent",        "macro_agent",     "事件情绪 vs 宏观周期"),
    ("price_agent",       "news_agent",      "价格走势 vs 新闻情绪"),
    ("macro_agent",       "technical_agent", "宏观趋势 vs 技术信号"),
]
```

### 5.4 触发判定场景

| 场景 | success | comparable | deep_report | detect? | 输出 |
|------|---------|-----------|-------------|---------|------|
| 单纯价格查询 | 1 | 0 | ❌ | ❌ | 跳过 |
| 价格+新闻 | 2 | 1 | ❌ | ✅ | 正常检测 |
| 深度研报，5 agent 全成功 | 5 | 8 | ✅ | ✅ | 完整检测 |
| 深度研报，仅 1 agent 成功 | 1 | 0 | ✅ | ✅ | **降级模式** |
| 深度研报，0 agent 成功 | 0 | 0 | ✅ | ✅ | **降级模式** |
| 仪表盘提问，2 agent 成功 | 2 | 1+ | ❌ | ✅ | 正常检测 |
| 仪表盘提问，1 agent 成功 | 1 | 0 | ❌ | ❌ | 跳过 |

### 5.5 降级模式

当 `deep_report && success_agents <= 1` 时：

```markdown
**冲突检测降级（证据不足）：**

仅 1 个智能体成功返回数据，无法执行跨维度交叉验证。建议：
- 检查数据源连通性（API Key、网络）
- 重试以获取更多智能体输出
- 当前结论仅基于单一维度，可信度受限
```

同时：
- `confidence_score` 上限压至 0.45
- `risks[0]` 插入 "冲突检测降级：仅单一维度证据可用，无法交叉验证"
- `report_tags` 追加 `"conflict_degraded"`

### 5.6 冲突披露输出格式

正常模式（有冲突时）：

```markdown
**跨智能体数据冲突（共 2 项，检测基础：3 个智能体成功 + 3 组可比命题）：**

1. 🟡 **短期动量方向**（technical）
   - RSI(14): 72.35 (超买>70)
   - MACD: 0.0234 > 信号线0.0189 (多头)
   - 裁决: ❓ 待进一步验证

2. 🟢 **CPI 通胀率**（macro）
   - FRED: 3.2%
   - CNN Fear & Greed: 3.5%
   - 裁决: ✅ 采信优先级更高的 FRED 数据

⚠️ 1 项冲突未裁决，结论可信度需打折。建议关注后续数据更新。
```

正常模式（无冲突时）：

```markdown
**冲突检测（3 个智能体成功 + 3 组可比命题）：**

✅ 已完成 3 组跨维度交叉验证，未发现显著数据冲突。
   验证维度：方向判断, 价格动量 vs 事件冲击, 基本面 vs 事件影响
```

---

## 6. LLM 分析子系统

### 6.1 _llm_analyze() 通用接口

所有 Agent 通过 `BaseFinancialAgent._llm_analyze()` 调用 LLM：

```python
async def _llm_analyze(
    self,
    raw_data_summary: str,   # 确定性数据摘要 (最大 3000 字符)
    *,
    role: str,                # LLM 角色设定
    focus: str,               # 分析聚焦方向
) -> Optional[str]:           # 返回分析文本或 None (失败)
```

**关键设计**：
- **输入截断**：`raw_data_summary[:3000]`，防止 token 溢出
- **输出验证**：`isinstance(content, str) and len(content.strip()) >= 80`
- **失败返回 None**：所有调用者 **必须** 处理 None → 退回确定性摘要
- **速率限制**：调用前 `acquire_llm_token()`，遵守全局 rate limiter
- **超时控制**：环境变量 `{AGENT_NAME}_LLM_ANALYZE_TIMEOUT_SECONDS` 或全局 `AGENT_LLM_ANALYZE_TIMEOUT_SECONDS`

### 6.2 各 Agent 的 LLM 角色与聚焦

| Agent | role | focus 关键词 |
|-------|------|-------------|
| PriceAgent | 资深量化交易分析师 | 波动幅度、市场情绪、短期方向 |
| NewsAgent | 资深金融新闻分析师（ReAct） | Observe→Reason→Assess→Risk |
| FundamentalAgent | 资深卖方基本面分析师（CoT） | 盈利质量→财务健康→增长持续性→估值→风险 |
| TechnicalAgent | 资深技术分析师（Signal Confluence） | 均线→动量→关键价位→信号共振→交易含义 |
| MacroAgent | 资深宏观经济分析师（Plan-Execute-Reflect） | 经济周期→政策环境→跨资产传导→数据冲突消解→前瞻风险 |

### 6.3 LLM Prompt 结构（统一格式）

```xml
<role>{role}</role>
<task>基于以下数据摘要，撰写一段专业的分析评论。...</task>
<context><query>{query}</query><ticker>{ticker}</ticker></context>
<data_summary>{raw_data_summary}</data_summary>
<analysis_focus>{focus}</analysis_focus>
<output_rules>
- 输出 200-500 字中文分析段落
- 必须包含：数据解读 + 趋势/方向判断 + 关键风险提示
- 引用具体数值支撑论点（不可编造数字）
- 区分事实与推断，推断标注"预计"/"可能"
- 禁止：标题、列表符号、分隔线、开场白
- 直接输出分析正文
</output_rules>
```

---

## 7. 降级与容错机制

### 7.1 三层降级链

```
LLM 可用 → LLM 增强分析 (最佳质量)
  │ 失败
  ▼
确定性摘要 (数据罗列，无解读)
  │ 数据也失败
  ▼
最小可用输出 (fallback_used=True, 低 confidence)
```

### 7.2 降级可观测性字段

| 字段 | 含义 | 示例 |
|------|------|------|
| `fallback_used` | 是否使用了降级数据 | `True` |
| `fallback_reason` | 降级原因 | `"primary_source_unavailable"` |
| `retryable` | 是否值得重试 | `True` (临时网络错误) / `False` (API key 无效) |
| `error_stage` | 失败发生的阶段 | `"initial_search"` / `"llm_analyze"` |

### 7.3 Mock/测试环境行为

- 测试中 `llm` 是 `MagicMock`，`await llm.ainvoke()` 抛 TypeError
- `_llm_analyze` 的 try/except 捕获 → 返回 None → 确定性摘要
- 所有测试验证的是**确定性路径**，LLM 路径在集成测试中验证

---

## 8. LangFuse 链路追踪

### 8.1 概述

LangFuse 提供 LLM 调用级别的可观测性，包括 token 用量、延迟、错误率等指标。FinSight 通过 `langfuse_tracer.py` 实现可选集成。

### 8.2 架构

```
LLM 调用 (via create_llm())
  │
  ├── LANGFUSE_ENABLED=true → 注入 CallbackHandler → LangFuse Cloud/Self-hosted
  │
  └── LANGFUSE_ENABLED=false (默认) → 无 callback，零开销
```

### 8.3 配置

```env
# .env / .env.example
LANGFUSE_ENABLED=false              # true 启用
LANGFUSE_PUBLIC_KEY=pk-...          # LangFuse 公钥
LANGFUSE_SECRET_KEY=sk-...          # LangFuse 私钥
LANGFUSE_HOST=https://cloud.langfuse.com  # 或自建地址
```

### 8.4 安全特性

- **懒初始化**：首次调用 `get_langfuse_callback()` 时初始化，结果缓存
- **零异常**：任何初始化失败（缺依赖、错 key、网络问题）均返回 `None`，不影响主流程
- **优雅关闭**：`main.py` 的 `shutdown` 事件调用 `flush_langfuse()`，确保 trace 数据不丢失
- **可选依赖**：`langfuse>=2.0.0,<4.0.0`，未安装时 `ImportError` 被静默处理

### 8.5 版本约束

`requirements.txt` 中设置 `langfuse>=2.0.0,<4.0.0`，加上限防止主版本破坏性更新。

---

## 9. 配置参考

### 8.1 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `AGENT_LLM_ANALYZE_ENABLED` | `true` | 全局开关：是否启用 Agent LLM 分析 |
| `AGENT_LLM_ANALYZE_TIMEOUT_SECONDS` | `30` | LLM 分析调用超时 (秒) |
| `{AGENT}_LLM_ANALYZE_TIMEOUT_SECONDS` | 继承全局 | 每个 Agent 独立超时 |
| `BASE_AGENT_MAX_REFLECTIONS` | 各 Agent 默认值 | 全局覆盖反射次数 |
| `BASE_AGENT_REFLECTION_TOKEN_TIMEOUT_SECONDS` | `12` | 反射 LLM token 获取超时 |
| `REPORT_SYNTHESIS_MIN_CHARS` | `2500` | 报告最小内容字符数 |
| `REPORT_AGENT_SUMMARY_MAX_CHARS` | `12000` | Agent 摘要在报告中的最大字符数 |
| `LANGGRAPH_SYNTHESIZE_TEMPERATURE` | `0.3` | Synthesize 层 LLM 温度 |

---

## 10. 设计决策记录 (ADR)

### ADR-001: 为什么每个 Agent 选择不同的架构模式？

**背景**：5 个 Agent 的职责差异大，统一用同一种模式（如全部 ReAct）会导致：
- PriceAgent 不需要多步推理，白白浪费 LLM 调用
- FundamentalAgent 需要严格推导链，ReAct 的开放式推理不够结构化
- MacroAgent 需要动态规划数据源，CoT 的固定链不够灵活

**决策**：根据每个 Agent 的核心职责匹配最适合的模式。

**结果**：每个 Agent 的 LLM prompt 更精准，输出质量更高，且可以独立调优。

### ADR-002: 为什么冲突检测用触发条件而非始终开启？

**背景**：如果每次查询都做冲突检测，单纯问价格也会生成空的冲突披露。

**决策**：使用公式 `detect = deep_report || (success_agents >= 2 && comparable_claims >= 1)`。

**理由**：
- 单一 Agent 没有冲突来源，检测无意义
- 两个不相关 Agent（如 price + macro 但查询只关心价格）也不需要
- 深度研报始终检测，因为用户期望看到完整性校验
- 按**实际成功数**判断（不是理论可用数），避免 Agent 失败时虚假安全感

### ADR-003: 为什么 ConflictClaim 要包含这么多字段？

**背景**：可以简单用字符串标记冲突。

**决策**：使用完整的 dataclass，包含来源、数值、严重度、裁决状态。

**理由**：
- 前端需要结构化数据来渲染冲突对比卡片
- Synthesize 层需要 `resolved` 字段判断是否需要 LLM 裁决
- Report Builder 需要 `severity` 计算 confidence 惩罚幅度
- 未来可以接入用户反馈：用户标记"已确认"→ 更新 resolved 状态

### ADR-004: 为什么 MacroAgent 是唯一自动裁决冲突的 Agent？

**背景**：所有 Agent 都可以自动裁决。

**决策**：目前仅 MacroAgent 自动裁决（通过数据源优先级）。

**理由**：
- 宏观数据有明确的权威度排序：FRED（官方统计）> 市场情绪 > 网络搜索
- 技术指标冲突（RSI vs MACD）是**正常的市场信号**，不应自动裁决——两个都对，只是反映不同时间尺度
- 基本面冲突（营收增长 vs 利润下滑）也是正常的——可能是扩张期投入导致，需要分析师判断
- 自动裁决应谨慎，错误裁决比不裁决更危险

### ADR-005: 为什么 _llm_analyze 失败返回 None 而非抛异常？

**背景**：可以让异常冒泡到上层处理。

**决策**：_llm_analyze 内部 try/except，返回 None。

**理由**：
- LLM 分析是**增强**而非**必需**——没有 LLM，确定性摘要仍然有用
- Agent 的核心价值是数据采集 + 结构化输出，不应因 LLM 不可用而完全失败
- 这保证了在 API 配额耗尽、网络中断、LLM 降级等情况下系统仍可运行
- 测试环境中 Mock LLM 自然返回 None → 测试验证确定性路径

### ADR-006: 为什么引入工具注册表而非继续用 search-only 反射？

**背景**：v2.0 中所有 Agent 的反射循环都只调用 `search()`，无论 LLM 识别出什么缺口。

**决策**：引入 `_get_tool_registry()` 让每个 Agent 注册自己的可用工具，`_identify_gaps()` 的 LLM 输出带 `tool` 字段指定建议工具，`_targeted_search()` 按注册表分发。

**理由**：
- NewsAgent 反射时需要的是"情绪分析数据"而非通用搜索
- MacroAgent 反射时需要"FRED 验证"而非通用搜索
- 通用搜索噪音大、精度低，专用 API 返回结构化数据
- 工具注册表是声明式的，各 Agent 独立维护，互不干扰

**向后兼容**：
- JSON 解析失败 → 纯文本 → search（100% 向后兼容）
- 工具名不在注册表 → 降级到 search
- 工具调用失败 → 降级到 search
- 无注册表 → 基类默认只有 search

**结果**：反射循环从"所有 gap 都走通用搜索"升级为"LLM 可选择最合适的工具"，零回归风险。

### ADR-007: 为什么 FundamentalAgent 使用 2-step LLM 链而非单次调用？

**背景**：v2.0 的 CoT 是在单次 LLM prompt 中写"按链式推理分析"——LLM 可能会跳过中间步骤。

**决策**：拆为两次独立 LLM 调用，Step 2 的输入显式包含 Step 1 的输出。

**理由**：
- 真正的链式依赖：Step 2 能看到 Step 1 的具体结论再推理
- 可观测性：trace 中能清晰看到两步的输入/输出
- 降级灵活：Step 2 失败只丢失增量分析，Step 1 结果仍可用
- 成本可控：两次短调用 vs 一次长调用，总 token 数接近

**代价**：多一次 LLM 调用 → 约增加 2-4 秒延迟。考虑到报告准确性优先，可接受。

---

> *以上架构设计持续迭代中，如有疑问请参考源代码注释或联系架构组。*
