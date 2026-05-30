


<p align="center">
  <img src="frontend/public/logo.svg" alt="FinSight AI Logo" width="80" height="80" />
</p>

<h1 align="center">FinSight AI</h1>

<p align="center">
  <strong>Multi-Agent Financial Research Platform powered by LangGraph</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> |
  <a href="./README_CN.md">中文</a> |
  <a href="./docs/DOCS_INDEX.md">Docs Index</a>
</p>

<p align="center">
  🌐 <strong>Live Demo:</strong> <a href="https://finsight-ai.chat">https://finsight-ai.chat</a>
</p>

---

**FinSight AI** is a production-grade, multi-agent financial research system built on **LangGraph**. It unifies conversational AI analysis, a professional dashboard with 6 analytical tabs, autonomous task execution (Workbench), and proactive email alerts into one coherent platform.

> 7 Research Agents (autonomous, multi-tool) · 1 Synthesize Node (conflict detection + hallucination guard) · 5 Dashboard Scorers (per-tab AI cards) | Hybrid RAG (bge-m3) | Real-time ECharts | LLM-driven Smart Charts | Conflict detection across 8 agent pairs | Email subscription alerts

---

## Table of Contents

- [Key Features](#-key-features)
- [Current Request Path](#-current-request-path)
- [Platform Preview](#-platform-preview)
- [System Architecture](#%EF%B8%8F-system-architecture)
- [LangGraph Pipeline](#-langgraph-pipeline-current-runtime--target-refactor)
- [Agent Ecosystem](#-agent-ecosystem)
- [Dashboard](#-dashboard---6-analytical-tabs)
- [RAG Engine](#-rag-engine---hybrid-search-pipeline)
- [Smart Charts](#-smart-charts---llm-driven-visualization)
- ["Ask About This" Feature](#-ask-about-this-问这条)
- [Conflict Detection](#%EF%B8%8F-conflict-detection)
- [Email Alerts & Subscriptions](#-email-alerts--subscriptions)
- [Phase Labs (Phase 1–4)](#-phase-labs-phase-14)
- [Data & Storage Architecture](#-data--storage-architecture)
- [Cache System](#-cache-system)
- [Memory & User Profiles](#-memory--user-profiles)
- [Resilience & Fallbacks](#%EF%B8%8F-resilience--fallbacks)
- [Hallucination Mitigation](#-hallucination-mitigation)
- [Tech Stack](#-tech-stack)
- [Getting Started](#-getting-started)
- [Project Structure](#-project-structure)

---

## 🧭 Current Request Path

FinSight now treats intent as an evidence contract, not as a single coarse operation label.

1. `conversation_router.py` resolves the turn: direct chat, research, alert, clarification, scope, current tickers, selection, and follow-up context.
2. `intent_contract.py` compiles each resolved frame from the query into semantic facets and required evidence. Operations are legacy projections for planner/renderer compatibility.
3. `policy_gate.py` and `planner_stub.py` read `required_evidence` to select tools and agents. For example, valuation comparison becomes per-ticker valuation evidence plus synthesis-only compare, while external-entity impact such as "Will SpaceX affect Tesla?" becomes price/news/risk evidence for TSLA.
4. `chat_renderer.py` / `synthesize.py` render from the reply and render contracts, with tool failures kept in diagnostics instead of evidence.
5. Ordinary mechanism explanations stay direct unless the user asks for current data, sources, links, news, prices, or a concrete company impact judgment. Router `task_hints` are corrected before planning when they conflict with that reply contract.

Agent-side LLM refinement is opt-in at runtime through environment and UI preferences. Production can force full research behavior with `FINSIGHT_FORCE_AGENT_RESEARCH_CONFIG=true` and enable agent LLM passes with `AGENT_LLM_ANALYZE_ENABLED=true`.

2026-05-25 release posture: production runs the request-frame contract in `FINSIGHT_INTENT_CONTRACT_MODE=enforce`, keeps the contextual router enabled, caps chat-mode per-ticker research at `FINSIGHT_CHAT_MULTI_TICKER_RESEARCH_LIMIT=3`, enables holdings evidence with `SEC_HOLDINGS_ENABLED=true`, and sets `BASE_AGENT_MAX_REFLECTIONS=0` so Agent LLM refinement is available without the extra reflection loop multiplying calls. The important boundary is semantic, not keyword-driven: mechanism explanations stay direct when no live evidence is requested; current market impact, valuation ranking, holdings, backtests, URL/news/source requests, and external-entity company impact all compile to explicit evidence obligations or workflow actions before planning.

---

## ✨ Key Features

| Category | Highlights |
|----------|-----------|
| **Multi-Agent Orchestration** | 7 specialized research agents (Price, News, Fundamental, Technical, Macro, Risk, DeepSearch) running in parallel execution groups |
| **LangGraph Pipeline** | Stateful LangGraph runtime for GPT-like chat, alerts, URL/article analysis, quick market answers, and explicit report generation. Ordinary chat uses the LLM conversation router for resolution, then the evidence-first intent contract for decomposition before planning. |
| **Professional Dashboard** | 6 analytical tabs (Overview, Financial, Technical, News, Research, Peers) with ECharts visualization |
| **AI-Powered Insights** | 5 Dashboard Scorers generate real-time AI analysis cards for each tab via single LLM call + deterministic fallback (1-3s each) |
| **Hybrid RAG Engine** | bge-m3 (1024-dim Dense + Sparse) with bge-reranker-v2-m3 cross-encoder reranking |
| **Smart Charts** | Dual-mode LLM-driven charts: `<chart>` (inline data) + `<chart_ref>` (real data reference) |
| **Conflict Detection** | Automatic cross-agent conflict analysis across 8 comparable dimension pairs |
| **Proactive Alerts** | 3 alert schedulers (Price, News, Risk) with email notification via SMTP |
| **Workbench** | Autonomous task execution, portfolio rebalancing with LLM enhancement, SSE streaming progress, report timeline, and quick analysis bar |
| **"Ask About This"** | Context-aware follow-up on any news, insight, or risk item via MiniChat integration |
| **ThinkingBubble** | Three-layer execution display: thinking bubble (typewriter effect) → agent summary cards → detailed timeline |
| **Morning Brief Pipeline** | One-click portfolio morning brief via LangGraph Pipeline with deterministic synthesis (zero LLM cost) |
| **Rebalance LLM Enhancement** | Agent-backed LLM priority refinement for rebalance suggestions with evidence snapshots |
| **Hallucination Defense** | Multi-layer scrubbing: regex pattern matching + evidence cross-validation on LLM outputs |
| **Conversational Price Alerts** | Chat-driven alert setup — say "alert me when AAPL drops below $180" → auto-extracted, persisted, and triggered by scheduler (Phase 1) |
| **Stock Screener** | Natural-language stock screening with multi-condition filters; `capability_note` boundary hints for CN/HK coverage (Phase 2) |
| **A-Share Market Data** | Northbound/Southbound capital flow, sector heat maps, concept board rankings for CN & HK markets (Phase 3) |
| **Strategy Backtesting** | SMA crossover, MACD, RSI strategies with T+1 settlement, cost/slippage modeling, and look-ahead bias prevention (Phase 4) |

---

## 📸 Platform Preview

<p align="center">
  <img src="images/cb70fece-c319-4964-91fc-d7be91211b91.png" alt="FinSight AI Dashboard" width="100%"/>
</p>


<p align="center">
  <img src="images/4dc0e95c-2963-4422-ba3e-d86a3788b4b1.png" alt="FinSight AI Dashboard" width="100%"/>
</p>
### RAG Inspector

<p align="center">
  <img src="images/142bc537-d76f-4ab1-9a84-4d86a0db2af5.png" alt="RAG Inspector overview with run list, 24h counters, event payloads, and chunk previews" width="100%"/>
</p>

<p align="center">
  <img src="images/6352da18-d7e9-418a-a219-15150cbeebcb.png" alt="RAG Inspector detail view with original source text and chunk metadata" width="100%"/>
</p>

The RAG Inspector opens up the retrieval pipeline for direct inspection. It shows recent DeepSearch / hybrid RAG runs, 24-hour activity counters, event-by-event payloads, chunk slices, original source text, and chunk metadata so operators can verify exactly what was searched, chunked, retrieved, and stored.


<table>
<tr>
<td width="50%">

**Overview Tab** - AI Score Ring, Fear & Greed Gauge, Agent Coverage, Risk Metrics


</td>
<td width="50%">

**Financial Tab** - 8Q Profitability Chart, EPS Surprise, Analyst Target Price

<img src="images/12e7daa8071f4983b85e578bbca7a0e1.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**Technical Tab** - Candlestick K-line, RSI, MACD, Support/Resistance Levels

<img src="images/7dd48dd6d1d3b1aa6e7b3d33e1dcc492.png" width="100%"/>
</td>
<td width="50%">

**News Tab** - AI News Summary, Sentiment Bar, Tag Chips, Rich News Cards

<img src="images/48f1bedaef4381457d3ad98e5ae80201.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**Peers Tab** - PE/Revenue Growth Comparison, Detailed Metrics Table

<img src="images/060fdf7b3d8f93ebda65cb3daaaacf21.png" width="100%"/>
</td>
<td width="50%">

**Research Tab** - Multi-Agent Deep Analysis with Conflict Matrix & Citations

<img src="images/3e47bb167c44c8f9cdcb23b20f905ada.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**Thinking Process - User View** - Collapsible Reasoning Sections (Logic / Planning / Execution)

<img src="images/2b674275d75b4838f1e77de5d5980dfc.png" width="100%"/>
</td>
<td width="50%">

**Execution Timeline + Agent Summary Cards** - Per-Agent Step Tracking, 11-Agent Completion Grid

<img src="images/78247136de4dd9db0d96c6ca5f574e3f.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**Chat + "Ask About This"** - Conversational AI with Portfolio Panel

<img src="images/chat-report.png" width="100%"/>
</td>
<td width="50%">

**Deep Research Report** - Agent Confidence, Catalysts, Risk Alerts

<img src="images/report1.png" width="100%"/>
</td>
</tr>
<tr>
<td width="50%">

**Workbench** - Task Execution, Portfolio Rebalancing, Report Timeline

<img src="images/workbench.png" width="100%"/>
</td>
</tr>
</table>

<details>
<summary>More Screenshots</summary>

| Chat with Inline Charts | Console & SSE Events |
|:-:|:-:|
| ![Chat Report](images/019a9f4cfab8326ea62828c13c4d6aca.png) | ![Console](images/console.png) |

| Research Report (Full) | Commodity Analysis |
|:-:|:-:|
| ![Research](images/a2970ffd1a178745f2c65b40a7d9f7b3.png) | ![Gold Analysis](images/ceb05773fea497b36b11f34ef68313a2.png) |

</details>

---

## 🏗️ System Architecture

```mermaid
graph TB
    subgraph "Frontend (React + Vite)"
        UI[Dashboard / Chat / Workbench / Settings]
        STORE[Zustand Stores<br/>dashboardStore · executionStore · useStore]
        PREFS[AgentControlPanel<br/>timeout · LLM analysis · reflections]
        API_CLIENT[API Client<br/>SSE parseSSEStream]
    end

    subgraph "Backend (FastAPI + 28 Routers)"
        ROUTER[API Routers<br/>chat · agent · dashboard · research · execute · alerts · ...]
        subgraph "LangGraph Pipeline (27 Nodes)"
            UNDERSTAND[understand_request<br/>LLM Router · ReplyContract]
            FRAME[IntentContract<br/>facets → required_evidence → evidence_plan]
            POLICY[policy_gate<br/>evidence floor · market filter]
            PLANNER[planner_stub<br/>contract-driven plan generation]
            EXEC[execute_plan<br/>parallel agent groups]
            SYNTH[synthesize<br/>conflict detection · hallucination scrub]
            RENDER[chat_renderer<br/>chat / compare / report output]
        end
        MEM_SCOPE[Memory Scope<br/>user profile · current thread focus]
        AGENTS[Agent Layer<br/>7 Research Agents + 5 Insight Scorers]
        TOOLS[Tool Layer<br/>26 Tool Modules]
    end

    subgraph "Data Layer"
        RAG[Hybrid RAG<br/>bge-m3 · bge-reranker-v2-m3]
        CACHE[Dashboard Cache<br/>16 TTL Categories]
        MEMORY[Scoped Memory Store<br/>Per-user JSON + thread focus]
        DB[(SQLite / PostgreSQL<br/>Checkpoints · Reports · Portfolio)]
    end

    subgraph "External"
        YFINANCE[yfinance]
        FMP[FMP API]
        FINNHUB[Finnhub]
        TAVILY[Tavily / Exa / DDG]
        FRED[FRED API]
        SEC[SEC EDGAR]
        LLM_API[LLM Provider<br/>OpenAI / Gemini / DeepSeek / Anthropic]
    end

    UI --> STORE --> PREFS
    UI --> API_CLIENT --> ROUTER
    ROUTER --> UNDERSTAND --> FRAME --> POLICY --> PLANNER --> EXEC
    EXEC --> SYNTH --> RENDER
    UNDERSTAND --> MEM_SCOPE --> MEMORY
    EXEC --> AGENTS --> TOOLS
    TOOLS --> YFINANCE & FMP & FINNHUB & TAVILY & FRED & SEC
    AGENTS --> LLM_API
    AGENTS --> RAG
    UNDERSTAND --> CACHE & DB
```

---

## 🔄 LangGraph Pipeline (Conversational Runtime)

The FinSight chat runtime is a LangGraph stateful graph. The current path is `prepare_context -> chat_respond -> understand_request`: `chat_respond` only short-circuits pure social turns, while ordinary chat, follow-ups, non-financial boundaries, URL/page requests, alerts, market questions, and report requests go through the LLM conversation router inside `understand_request`.

The router decides whether the turn should be answered directly, clarified, turned into an alert, or planned as research. Research turns produce `understanding`, `tasks[]`, `blocked_tasks[]`, and a compatibility projection for the existing policy/planner/executor boundary. URL/page/article work is exposed as the planner/agent tool `fetch_url_content`; the request-understanding layer does not pre-fetch URLs.

`understand_request` also writes a structured `ReplyContract` so downstream nodes do not infer UX intent from raw keywords again. The current lanes are:

| Lane | Trigger | Output rule |
|------|---------|-------------|
| `chat_answer` | Default for ordinary explanations, follow-ups, corrections, and "no news / no links / direct answer" turns | Natural conversational answer; no forced news lookup and no report scaffold |
| `source_grounded_answer` | Explicit news, links, URL/article reading, real-time quote, citation, or data-evidence request | Use source-capable tools; cite usable URLs or disclose that a usable source was unavailable |
| `report_generation` | Report button, `output_mode=investment_report`, or explicit "generate report / research report" request | Use report structure and report citation policy |

Evidence is split from tool diagnostics. `EvidenceItem`/`evidence_pool` is reserved for usable source material. Tool failures such as `403`, `rejected`, `empty`, `timeout`, or other failed outputs are recorded as `ToolError` rows in `artifacts.tool_diagnostics` and must not be rendered as news, sources, or conclusions.

The implementation and acceptance spec are tracked in [`docs/plans/2026-05-03_request_understanding_task_graph_spec.md`](docs/plans/2026-05-03_request_understanding_task_graph_spec.md). The current full chat UX acceptance run is [`docs/qa/chat-router-100-final100-current-state.md`](docs/qa/chat-router-100-final100-current-state.md) with JSON next to it: `100/100 PASS`, including `95` hard red-line cases across context continuity, session isolation, report follow-ups, URL/news/quote source grounding, no-news correction, and tool-error evidence boundaries. The older 40-query run remains as legacy regression evidence in [`docs/qa/chat-ux-40-query-final40-post-context-binding.md`](docs/qa/chat-ux-40-query-final40-post-context-binding.md).

Dashboard Scorers are served by `/api/dashboard/insights` and are not graph nodes in the chat pipeline.

Conversation UX is now split deliberately: the frontend keeps the active browser runtime in localStorage, while `/api/conversations` owns backend thread lifecycle and a lightweight server snapshot store for `messages`, `title`, `pinned`, and `archive` metadata. Creating, switching, renaming, and deleting conversations go through the backend API; deletion clears session context, report/citation index rows, thread RAG memory/working-set collections, and matching RAG observability runs. Stream stop uses `AbortController` plus backend cancellation events and executor/agent cancellation tokens, preserving partial answers instead of treating cancellation as an error.

Memory is scoped before routing. Durable user preferences and historical focus are loaded for personalization, but only `current_thread_focus` and `current_report` from the active `thread_id` can bind deictic follow-ups such as "that report" or "the third point". Legacy user-level `last_report`, `last_focus`, and `recent_focuses` are kept as historical memory and are not exposed to the conversation router as current referents.

Runtime preferences are passed with chat options as `agent_preferences`. `timeoutSeconds=0` means system default; positive values are clamped to `30-1200` seconds and applied to chat, planner, synthesis, and both sync/stream graph execution budgets.

```mermaid
flowchart TD
    START((Start)) --> INIT["① build_initial_state<br/><i>Parse input, load memory</i>"]
    INIT --> MEMSCOPE["memory_scope<br/><i>user profile + current thread only</i>"]
    MEMSCOPE --> RESET["② reset_turn_state<br/><i>Clear ephemeral fields + trace runtime</i>"]
    RESET --> PREPARE["③ prepare_context<br/><i>Bound history, summarize, normalize UI hints</i>"]
    PREPARE --> CHATRESP["④ chat_respond<br/><i>Pure social only</i>"]
    CHATRESP -->|"pure greeting / thanks / bye"| END_CHAT((End))
    CHATRESP -->|"all other turns"| UNDERSTAND{"⑤ understand_request<br/><i>LLM router + tasks + trace</i>"}

    UNDERSTAND -->|"direct / clarify / out_of_scope"| END_CHAT
    UNDERSTAND -->|"alert"| ALERT_EX["⑥ alert_extractor<br/><i>Extract alert params</i>"]
    ALERT_EX -->|"valid"| ALERT_ACT["⑥b alert_action<br/><i>Save & schedule</i>"]
    ALERT_EX -->|"invalid"| END_ALERT_INVALID((End))
    ALERT_ACT --> END_ALERT((End))
    UNDERSTAND -->|"research"| POLICY["⑦ policy_gate<br/><i>Capability scoring + task tool union</i>"]
    POLICY --> PLAN["⑧ planner<br/><i>LLM Planner or Stub Fallback</i>"]

    PLAN --> CONFIRM{"⑨ confirmation_gate<br/><i>HITL approval?</i>"}
    CONFIRM -->|"cancel"| END_CANCEL((End))
    CONFIRM -->|"adjust"| PLAN
    CONFIRM -->|"confirm"| EXEC["⑩ execute_plan<br/><i>Tools, agents, URL fetch</i>"]

    EXEC --> SYNTH["⑪ synthesize<br/><i>Merge outputs + conflict/evidence checks</i>"]
    SYNTH --> RENDER["⑫ render<br/><i>Chat or report output</i>"]
    RENDER --> END((End))

    subgraph "Execution Engine (⑩)"
        direction LR
        EG1["Group 1<br/>price · news"] --> EG2["Group 2<br/>fundamental · technical"]
        EG2 --> EG3["Group 3<br/>macro · risk · deep_search"]
    end

    EXEC -.-> EG1

    style RESET fill:#a855f7,color:#fff
    style SYNTH fill:#ff9800,color:#000
    style POLICY fill:#2196f3,color:#fff
```

`report_builder` and hallucination/evidence checks are implementation helpers inside the graph runtime, not separate graph nodes in `backend/graph/runner.py`.

### Request Understanding (`understand_request`)

`understand_request` is now the semantic source of truth for the chat front-half:

| Output | Purpose |
|--------|---------|
| `understanding` | Route, summary, confidence, assumptions, and user-visible task explanation |
| `memory_context` | Scoped memory: `user_profile_memory`, `historical_focus_memory`, `current_thread_focus`, `current_report` |
| `tasks[]` | Ready tasks such as `company/GOOGL/price`, `macro/analyze_impact`, `portfolio/rebalance_check` |
| `blocked_tasks[]` | Locally blocked tasks, e.g. missing portfolio holdings, without blocking ready tasks |
| compatibility `subject` / `operation` | Primary-task projection so the existing policy/planner/executor path remains stable |
| `trace` event | `type="trace"`, `visibility="user"`, `stage="understanding"` for frontend process UI |

`chat_respond` remains in the main path only as a pure-social fast path. Legacy subject/operation nodes such as `resolve_subject`, `clarify`, and `parse_operation` are compatibility helpers or archived history; they are not the main routing surface.

### GraphState Fields

The pipeline maintains a rich state object (`GraphState`) across all nodes:

| Field | Type | Description |
|-------|------|-------------|
| `messages` | `Annotated[list, add_messages]` | Conversation history (append-only via LangGraph reducer) |
| `memory_context` | `dict` | Scoped memory payload; only `current_thread_focus` / `current_report` can bind current follow-ups |
| `subject` | `dict` | Resolved entity — `{type, ticker, name, market}` |
| `understanding` | `dict` | Request understanding result for the current turn |
| `reply_contract` | `dict` | Structured UX contract: lane, style, length preference, context binding, source constraints, citation policy, continuation target |
| `tasks` | `list[dict]` | Ready task decomposition for multi-task requests |
| `blocked_tasks` | `list[dict]` | Local missing-context tasks that should not block the whole turn |
| `output_mode` | `str` | `"chat"` / compatibility `"brief"` / explicit `"investment_report"` |
| `plan_ir` | `dict` | Execution plan with steps, groups, dependencies, cost estimates |
| `step_results` | `dict` | Raw outputs from each agent/tool execution |
| `evidence_pool` | `list[dict]` | Collected evidence items with source attribution |
| `artifacts.tool_diagnostics` | `list[dict]` | Tool failures and empty/rejected/timeout diagnostics kept out of `evidence_pool` |
| `rag_context` | `list[dict]` | Retrieved documents from hybrid RAG search |
| `artifacts` | `dict` | Synthesized report, citations, charts |
| `trace` | `dict` | Observability: latencies, token counts, failures |
| `agent_preferences` | `dict` | UI-injected agent toggles and runtime preferences such as `timeoutSeconds` |
| `ui_context` | `dict` | Frontend hints: active_tab, selection_context, news_mode, agent_preferences |

### LangChain / LangGraph APIs Used

| API | Usage |
|-----|-------|
| `langgraph.graph.MessagesState` | Base state with `add_messages` reducer for conversation history |
| `langgraph.checkpoint.sqlite.SqliteSaver` | Persistent conversation checkpoints (SQLite backend) |
| `langgraph.checkpoint.postgres.PostgresSaver` | Optional PostgreSQL checkpoint backend |
| `langgraph.types.interrupt()` | Human-in-the-loop pause at `confirmation_gate` |
| `langgraph.types.Command(resume=)` | Resume execution after HITL approval |
| `langchain_core.messages.HumanMessage / SystemMessage / RemoveMessage` | Message type construction |
| `langchain_core.messages.trim_messages` | Context window management — trim old messages |
| `langfuse.decorators.langfuse_observe` | Distributed tracing integration with Langfuse |

---

## 🤖 Agent Ecosystem

### Research Agents (7)

Each research agent inherits from `BaseFinancialAgent` and implements a `research()` method with reflection loops, tool calling, and evidence collection.

```mermaid
graph TB
    subgraph EXECUTOR["Execution Engine"]
        direction TB
        POLICY["Policy Gate<br/>Capability scoring"]
        PLANNER["Planner Node<br/>LLM / Stub"]
        PARALLEL["Parallel Groups"]
    end

    subgraph AGENTS["7 Research Agents"]
        direction TB

        subgraph PA["🏷️ PriceAgent"]
            PA_T1["get_stock_price"]
            PA_T2["get_option_chain_metrics"]
            PA_T3["search (Tavily)"]
            PA_CASCADE["11-source Price Cascade<br/>yfinance → FMP → Finnhub → ..."]
        end

        subgraph NA["📰 NewsAgent"]
            NA_T1["get_company_news"]
            NA_T2["get_news_sentiment"]
            NA_T3["get_event_calendar"]
            NA_T4["score_news_source_reliability"]
            NA_T5["search (Tavily)"]
        end

        subgraph FA["📊 FundamentalAgent"]
            FA_T1["get_financial_statements"]
            FA_T2["get_company_info"]
            FA_T3["get_earnings_estimates"]
            FA_T4["get_eps_revisions"]
            FA_T5["search (Tavily)"]
        end

        subgraph TA["📈 TechnicalAgent"]
            TA_T1["get_stock_historical_data"]
            TA_T2["search (Tavily)"]
            TA_CALC["Internal: RSI, MACD, BB<br/>MA, Stochastic, ADX, CCI"]
        end

        subgraph MA["🌍 MacroAgent"]
            MA_T1["get_fred_data"]
            MA_T2["get_market_sentiment"]
            MA_T3["get_economic_events"]
            MA_T4["search (Tavily)"]
        end

        subgraph RA["⚠️ RiskAgent"]
            RA_T1["evaluate_ticker_risk"]
            RA_T2["get_factor_exposure"]
            RA_T3["run_portfolio_stress_test"]
        end

        subgraph DS["🔍 DeepSearchAgent"]
            DS_T1["Tavily → Exa → DDG<br/>Multi-engine fallback"]
            DS_T2["Document Fetcher<br/>SSRF protection"]
            DS_T3["Self-RAG Loop<br/>SearchConvergence"]
        end
    end

    POLICY --> PLANNER --> PARALLEL
    PARALLEL --> PA & NA & FA & TA & MA & RA & DS
```

### Agent Details

<details>
<summary><b>PriceAgent</b> — Real-time & Historical Pricing</summary>

- **Tools**: `get_stock_price`, `get_option_chain_metrics`, `search`
- **Specialty**: 11-source price cascade fallback chain:
  ```
  yfinance → FMP quote → FMP historical → Finnhub quote →
  Finnhub candles → Alpha Vantage → Polygon → Twelve Data →
  MarketStack → web search → hardcoded fallback
  ```
- **Output**: Current price, change %, volume, 52-week range, option metrics
- **Reflection**: 2-round max with gap analysis

</details>

<details>
<summary><b>NewsAgent</b> — Market News & Sentiment</summary>

- **Tools**: `get_company_news`, `get_news_sentiment`, `get_event_calendar`, `score_news_source_reliability`, `search`
- **Data Sources**: Finnhub company news, Finnhub sentiment, economic calendar
- **Specialty**: Source reliability scoring (domain whitelist + quality heuristics), breaking news detection
- **Output**: Categorized news items with sentiment scores, impact tags, source reliability ratings

</details>

<details>
<summary><b>FundamentalAgent</b> — Financial Analysis</summary>

- **Tools**: `get_financial_statements`, `get_company_info`, `get_earnings_estimates`, `get_eps_revisions`, `search`
- **Data Sources**: yfinance (8 quarters), FMP (financials, profiles)
- **Specialty**: Revenue/earnings trend analysis, margin decomposition, balance sheet health
- **Output**: Quarterly financial data, valuation metrics, earnings surprise history

</details>

<details>
<summary><b>TechnicalAgent</b> — Technical Indicators & Signals</summary>

- **Tools**: `get_stock_historical_data`, `search`
- **Internal Calculations**: RSI(14), MACD(12,26,9), Bollinger Bands(20,2), Stochastic %K/%D, ADX(14), CCI(20), Williams %R, 8 Moving Averages (MA5/10/20/50/100/200, EMA12/26)
- **Output**: Support/resistance levels, trend signals (bullish/bearish/neutral), indicator time series (120-day)

</details>

<details>
<summary><b>MacroAgent</b> — Macroeconomic Context</summary>

- **Tools**: `get_fred_data`, `get_market_sentiment`, `get_economic_events`, `search`
- **Data Sources**: FRED (GDP, CPI, unemployment, interest rates), CNN Fear & Greed Index
- **Specialty**: Macro-micro linkage analysis (how macro trends affect specific sectors/stocks)
- **Output**: Economic indicators, market sentiment score, upcoming economic events

</details>

<details>
<summary><b>RiskAgent</b> — Risk Assessment</summary>

- **Tools**: `evaluate_ticker_risk_lightweight`, `get_factor_exposure`, `run_portfolio_stress_test`
- **Custom research()**: Does not use standard `BaseFinancialAgent.research()` — implements direct tool calling
- **Calculations**: Beta, VaR(95%), max drawdown, Sharpe ratio, sector exposure
- **Output**: Risk score, factor exposures, stress test results, risk warnings

</details>

<details>
<summary><b>DeepSearchAgent</b> — Web Intelligence</summary>

- **Tools**: Multi-engine search (Tavily → Exa → DuckDuckGo), document fetcher
- **Architecture**: Self-RAG loop with `SearchConvergence` tracking
  ```
  Plan search → Execute search → Grade results →
  Identify gaps → Refine query → Re-search (max 3 rounds)
  ```
- **Security**: SSRF protection (private IP blocking), domain whitelist for persistence
- **Quality Control**: `_doc_quality_score()` = source_score * 0.5 + freshness * 0.25 + depth * 0.25
- **Output**: Curated web findings with confidence scores, high-quality results (confidence ≥ 0.7) persisted to RAG

</details>

### Dashboard Insight Scorers (5)

Lightweight scorers (**not** autonomous agents — no tool use, no planning, no reflection loops) that generate AI insight cards for each dashboard tab. They accept already-fetched API data (zero network calls) and produce structured JSON via a **single LLM call**, with deterministic rule-based fallback when LLM is unavailable. These run independently from the LangGraph research pipeline via `/api/dashboard/insights`.

| Scorer | Tab | Input Data | Analysis Focus | Latency |
|-------------|-----|------------|----------------|---------|
| `OverviewDigest` | Overview | valuation + technicals + news | Composite score, key insights, overall risk | 1-3s |
| `FinancialDigest` | Financial | financials + valuation | Earnings quality, financial health, valuation | 1-3s |
| `TechnicalDigest` | Technical | technicals + indicator_series | Trend judgment, signal convergence, key levels | 1-3s |
| `NewsDigest` | News | market_news + impact_news | Topic extraction, sentiment analysis, risk events | 1-3s |
| `PeersDigest` | Peers | peers + valuation | Competitive positioning, industry ranking | 1-3s |

Each scorer has a **deterministic fallback** (rule-based) that activates when LLM is unavailable:

```
Score = Base(5) + RSI_normal(+1) + Trend_up(+2) + MACD_aligned(+1) + MA_bullish(+1) + Overbought(-1)
```

---

## 📊 Dashboard — 6 Analytical Tabs

### Overview Tab
> Composite AI analysis with ScoreRing, Fear & Greed Gauge, Agent Coverage Matrix, Dimension Radar, Risk Metrics, Highlights, and Analyst Target Price.

![Overview](images/2cae8333a4ce78d259c9734254e2f38d.png)

### Financial Tab
> 8-quarter financial data table, Profitability ECharts combo chart (revenue bars + margin lines), EPS Surprise chart, Analyst Target Price gauge, Balance Sheet summary.

### Technical Tab
> Real ECharts candlestick K-line with support/resistance markLines, RSI(14) time-series chart, MACD(12,26,9) with histogram, Bollinger Bands position, moving average signals.

### News Tab
> Three sub-views (Stock-specific / Market 7x24 / Breaking Events), 7 topic filter chips, time range selector, sentiment stats bar, rich NewsCards with tags and impact badges.

### Peers Tab
> Peer score grid, PE/PB horizontal bar chart, revenue growth divergent bar chart, detailed comparison table with 10+ metrics.

### Research Tab
> Multi-agent deep analysis with per-agent sections (price, news, technical, fundamental, macro, deep_search), conflict matrix, citation tracking, confidence scoring.

---

## 🔍 RAG Engine — Hybrid Search Pipeline

FinSight uses a production-grade hybrid retrieval pipeline replacing the legacy SHA1 hash-based pseudo-embeddings.

```mermaid
flowchart LR
    QUERY["User Query"] --> ROUTER["RAG Router<br/><i>SKIP / SECONDARY / PRIMARY</i>"]

    ROUTER -->|PRIMARY| EMBED["bge-m3 Encode<br/><i>1024-dim Dense + Sparse lexical</i>"]
    ROUTER -->|SKIP| LIVE["Live Tools Only"]

    EMBED --> DENSE["Dense Search<br/><i>Cosine similarity</i>"]
    EMBED --> SPARSE["Sparse Search<br/><i>Lexical weight matching</i>"]

    DENSE --> RRF["RRF Fusion<br/><i>+ Scope Boost</i>"]
    SPARSE --> RRF

    RRF --> RERANK["Cross-Encoder Rerank<br/><i>bge-reranker-v2-m3</i><br/>Top-30 → Top-8"]

    RERANK --> OUTPUT["rag_context<br/><i>Injected into synthesize prompt</i>"]

    style EMBED fill:#4caf50,color:#fff
    style RERANK fill:#ff9800,color:#000
```

### Key Components

| Component | File | Model / Algorithm |
|-----------|------|-------------------|
| **Embedder** | `rag/embedder.py` | `BAAI/bge-m3` — 1024-dim Dense + Sparse (lexical weights) |
| **Hybrid Search** | `rag/hybrid_service.py` | RRF fusion with scope boosting: persistent +0.15, medium_ttl +0.05 |
| **Reranker** | `rag/reranker.py` | `BAAI/bge-reranker-v2-m3` Cross-Encoder, Top-30 → Top-8 |
| **Router** | `rag/rag_router.py` | Rule-based: SKIP (realtime quotes) / PRIMARY (historical) / PARALLEL (deep research) |
| **Chunker** | `rag/chunker.py` | Per-doc-type strategy: news (no split) / filings (1000/200) / transcripts (800/100) |
| **Store** | `rag/hybrid_service.py` | In-Memory or PostgreSQL (`pgvector` VECTOR(1024) + `tsvector`) |

### Document Lifecycle

| Source | Scope | TTL | Trigger |
|--------|-------|-----|---------|
| Agent outputs (evidence) | `ephemeral` | Request-scoped | Every analysis execution |
| News items | `medium_ttl` | 7 days | NewsAgent fetch |
| DeepSearch results (confidence ≥ 0.7) | `persistent` | Permanent | Auto-persist on high quality |
| SEC filings (future) | `persistent` | Permanent | Scheduled ETL |

### Prompt Injection (synthesize.py)

RAG results and real-time evidence are injected as XML-tagged blocks:

```xml
<realtime_evidence>
  {evidence_pool from current execution}
</realtime_evidence>

<historical_knowledge>
  {rag_context from hybrid search}
</historical_knowledge>

<evidence_priority_rules>
  1. Real-time data overrides historical when conflicting
  2. Historical data must include date attribution
  3. Unverifiable data must be marked with date qualifier
</evidence_priority_rules>
```

### Quality Benchmarks — RAG Quality V2

A **3-layer eval pyramid** (`tests/rag_qualityV2/`) measuring retrieval and generation quality across 12 Chinese financial cases (filings, transcripts, news) with 6 diagnostic metrics:

| Layer | Scope | KC | KCR | CSR | UCR ↓ | CR ↓ | NCR | Gate |
|-------|-------|----|-----|-----|-------|------|-----|------|
| **L1** Mock Context | LLM generation baseline | 0.8796 | 0.9479 | 0.9431 | 0.057 | **0.0** | 0.9896 | ✅ PASS |
| **L2** Real Retrieval | Retrieval + generation | 0.8960 | 0.9623 | **1.0000** | **0.000** | **0.0** | 0.9861 | ✅ PASS |
| **L3** E2E Pipeline | Full LangGraph flow | **0.9072** | **0.9653** | 0.9924 | 0.008 | **0.0** | **1.0000** | ✅ PASS |

> **CR = 0.0 across all layers** — zero contradicted claims.  **NCR = 1.0 at E2E** — numeric consistency is perfect end-to-end. *\*Based on 12 test cases; production results may vary.*

Metrics: KC (Keypoint Coverage) · KCR (Keypoint Context Recall) · CSR (Claim Support Rate) · UCR (Unsupported Claim Rate) · CR (Contradiction Rate) · NCR (Numeric Consistency Rate)

---

## 📈 Smart Charts — LLM-Driven Visualization

FinSight supports **dual-mode** inline charts where the LLM autonomously decides when visualization aids understanding.

```mermaid
flowchart LR
    subgraph "Mode A: LLM-Generated Data"
        LLM1["LLM generates<br/>&lt;chart type='bar'&gt;<br/>{labels, values}"]
        LLM1 --> PARSE1["Frontend extracts<br/>before Markdown render"]
        PARSE1 --> ECHART1["ECharts renders<br/>bar / line / pie / scatter / gauge"]
    end

    subgraph "Mode B: Real Data Reference"
        LLM2["LLM generates<br/>&lt;chart_ref source='peers'<br/>fields='trailing_pe'/&gt;"]
        LLM2 --> PARSE2["Frontend reads<br/>dashboardStore data"]
        PARSE2 --> ECHART2["ECharts renders<br/>with real API values"]
    end
```

| Mode | Tag | Data Source | Use Case | Precision |
|------|-----|------------|----------|-----------|
| LLM Inline | `<chart>` | LLM fills JSON data | Trend overviews, qualitative comparisons | Approximate |
| API Reference | `<chart_ref>` | Frontend reads `dashboardData` | Exact value charts, historical series | Precise |

**Processing**: Chart tags are extracted from LLM output **before** Markdown rendering (same pattern as `[CHART:TICKER:TYPE]`), ensuring `react-markdown` never sees raw XML.

---

## 💬 "Ask About This" (问这条)

A context-aware follow-up feature allowing users to ask AI about any specific news item, AI insight, or risk warning directly from the dashboard.

```mermaid
sequenceDiagram
    participant User
    participant Card as NewsCard / AiInsightCard
    participant Store as dashboardStore
    participant Chat as MiniChat
    participant API as Backend SSE

    User->>Card: Click "问这条" button
    Card->>Store: setActiveSelection(SelectionItem)
    Store->>Chat: MiniChat reads activeSelection
    Chat->>Chat: Auto-populate context pill
    User->>Chat: Type follow-up question
    Chat->>API: POST /api/chat with selection_context
    API->>API: LangGraph pipeline processes with context
    API-->>Chat: SSE stream response
```

### SelectionItem Types

| Type | Source Component | Context Sent to Backend |
|------|-----------------|------------------------|
| `news` | NewsCard | `{title, summary, source, ts, sentiment}` |
| `filing` | Research citations | `{title, url, type}` |
| `doc` | Report sections | `{title, content_snippet}` |
| `insight` | AiInsightCard | `{tab, score, summary, key_points}` |
| `risk` | RiskMetricsCard | `{risk_type, description, severity}` |

---

## ⚔️ Conflict Detection

When multiple agents analyze the same ticker, their conclusions may conflict. FinSight automatically detects and discloses these disagreements.

### 8 Comparable Agent Pairs

| Agent A | Agent B | Comparison Dimension |
|---------|---------|---------------------|
| Technical | Fundamental | Direction judgment (signals vs. fundamentals) |
| Technical | News | Price momentum vs. event impact |
| Technical | Price | Technical signals vs. actual price action |
| Fundamental | News | Fundamentals vs. event-driven narrative |
| Fundamental | Macro | Stock fundamentals vs. macro environment |
| News | Macro | Event sentiment vs. macro cycle |
| Price | News | Price trend vs. news sentiment |
| Macro | Technical | Macro trend vs. technical signals |

### Trigger Formula

```
detect = deep_report OR (success_agents ≥ 2 AND comparable_claims ≥ 1)
```

Conflicts are surfaced both as **structured JSON** (for matrix visualization) and **inline text** (for report readability).

---

## 📧 Email Alerts & Subscriptions

<img src="images/ae7cbf42-a393-4ea8-bc75-ccf2d239e2c8.png" width="400" align="right"/>

FinSight includes 3 automated alert schedulers running via APScheduler:

| Scheduler | Trigger | Check Interval |
|-----------|---------|---------------|
| **PriceChangeScheduler** | Price moves beyond threshold (e.g., ±0.1%) | 15 min |
| **NewsScheduler** | High-impact news for watchlisted tickers | 30 min |
| **RiskScheduler** | RSI extreme / VaR breach / drawdown events | 60 min |

### Email Pipeline

```
Scheduler → Rule Engine → Alert Created →
HTML Template (Jinja2) → SMTP Send →
Delivery Tracking (transient vs permanent errors) →
Auto-disable after 3 permanent failures
```

### Subscription Management

- `POST /api/subscriptions` — Create subscription (email + tickers + alert types)
- `GET /api/subscriptions/{email}` — List active subscriptions
- `DELETE /api/subscriptions/{id}` — Remove subscription
- Storage: `data/subscriptions.json` with per-user settings

<br clear="right"/>

---

## 💾 Data & Storage Architecture

```mermaid
graph TB
    subgraph "SQLite (Local)"
        CP[(checkpoints.sqlite<br/><i>LangGraph state snapshots</i>)]
        RI[(report_index.sqlite<br/><i>Report metadata + citations</i>)]
        PF[(portfolio.sqlite<br/><i>Holdings + transactions</i>)]
    end

    subgraph "JSON Files (data/)"
        MEM["memory/{user_id}.json<br/><i>User profiles + watchlists</i>"]
        SUB["subscriptions.json<br/><i>Email alert subscriptions</i>"]
        ALERTS["alerts/{user_id}.json<br/><i>Alert feed history</i>"]
    end

    subgraph "Optional PostgreSQL"
        PG_CP["langgraph_checkpoints<br/><i>Scalable checkpoint backend</i>"]
        PG_RAG["rag_documents_v2<br/><i>VECTOR(1024) + tsvector</i>"]
    end

    subgraph "In-Memory"
        DCACHE["DashboardCache<br/><i>16 TTL categories</i>"]
        ICACHE["InsightsCache<br/><i>1h TTL + stale-while-revalidate</i>"]
        RAGMEM["RAG InMemoryStore<br/><i>Fallback when no PostgreSQL</i>"]
    end
```

### Database Schemas

<details>
<summary><b>Report Index (SQLite)</b></summary>

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
<summary><b>Portfolio (SQLite)</b></summary>

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
<summary><b>RAG Documents (PostgreSQL)</b></summary>

```sql
CREATE TABLE rag_documents_v2 (
    id          TEXT PRIMARY KEY,
    collection  TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   VECTOR(1024),       -- bge-m3 dense vector
    ts_content  tsvector,           -- Chinese full-text search
    metadata    JSONB,
    scope       TEXT DEFAULT 'ephemeral',  -- ephemeral | medium_ttl | persistent
    created_at  TIMESTAMP DEFAULT NOW()
);
```

</details>

---

## 🗄️ Cache System

The `DashboardCache` manages 16 distinct TTL categories:

| Category | TTL | Description |
|----------|-----|-------------|
| `quote` | 30s | Real-time price quotes |
| `technical_snapshot` | 60s | Technical indicator values |
| `company_news` | 300s (5m) | Company-specific news |
| `company_info` | 600s (10m) | Company profiles |
| `sec_filings` | 900s (15m) | SEC filing data |
| `market_chart` | 300s (5m) | OHLCV price data |
| `financials` | 600s (10m) | Quarterly financial statements |
| `peers` | 600s (10m) | Peer comparison data |
| `earnings_history` | 1800s (30m) | EPS history |
| `analyst_targets` | 1800s (30m) | Analyst price targets |
| `recommendations` | 1800s (30m) | Buy/hold/sell ratings |
| `indicator_series` | 300s (5m) | Technical indicator time series |
| `insights` | 3600s (1h) | AI digest insights (stale-while-revalidate up to 4h) |

### Stale-While-Revalidate Pattern (Insights)

```
Fresh (< 1h)    → Return immediately, cached=true
Stale (1h-4h)   → Return stale data + background async refresh
Expired (> 4h)  → Wait for fresh generation
```

---

## 🧠 Memory & User Profiles

Per-user memory stored as JSON files in `data/memory/{user_id}.json`:

```json
{
  "user_id": "abc123",
  "watchlist": ["AAPL", "GOOGL", "TSLA"],
  "preferences": {
    "language": "zh-CN",
    "risk_tolerance": "moderate",
    "default_depth": "report",
    "timeoutSeconds": 0,
    "thread_focuses": {
      "thread_abc": {
        "primary_subject": {"type": "company", "ticker": "NVDA"},
        "last_report": {"report_id": "rpt_123", "title": "NVDA report"}
      }
    }
  },
  "interaction_history": [
    {"ticker": "AAPL", "action": "deep_research", "timestamp": "2026-02-18T10:30:00Z"}
  ]
}
```

`timeoutSeconds=0` keeps the system default. User-specified positive values are validated and clamped to `30-1200` seconds.

The memory system integrates with:
- **Watchlist API**: `POST /api/user/watchlist/add` / `remove` — persisted and used by alert schedulers
- **LangGraph Memory**: Loaded at `build_initial_state` as scoped memory. Durable user profile can personalize answers, while report/focus follow-ups bind only to the active thread's focus.
- **Dashboard Store**: Frontend `dashboardStore` syncs watchlist via API on init

---

## 🛡️ Resilience & Fallbacks

FinSight is designed for production reliability with multiple fallback layers:

| Component | Primary | Fallback | Behavior |
|-----------|---------|----------|----------|
| **Planner** | LLM Planner (structured output) | `planner_stub` (contract/task projection fallback) | Auto-switch on timeout; user `timeoutSeconds` can extend the budget |
| **Embedding** | `BAAI/bge-m3` (1024-dim) | SHA1 hash embedding (96-dim) | Graceful degradation if model not loaded |
| **Reranker** | `bge-reranker-v2-m3` | Skip reranking, use RRF scores directly | Silent passthrough |
| **Price Data** | yfinance | 10 fallback sources (FMP → Finnhub → ...) | 11-level cascade |
| **AI Insights** | LLM Insight Scorers | Deterministic rule-based scoring | `model_generated=false` flag |
| **Morning Brief** | LangGraph Pipeline | Direct data fetch (router fallback) | Transparent to caller |
| **Rebalance Enhancement** | Agent-backed LLM | Original deterministic candidates | Safety fallback on any failure |
| **Dashboard Data** | Live API fetch | In-memory cache (stale-while-revalidate) | TTL-based freshness |
| **Checkpoints** | PostgreSQL | SQLite local file | Auto-detect on startup |
| **RAG Store** | PostgreSQL + pgvector | In-memory store | Auto-fallback |
| **Search** | Tavily | Exa → DuckDuckGo | Multi-engine fallback chain |

### LLM Circuit Breaker

```
3 consecutive LLM failures → 15-min cooldown → Pure rule-based mode
```

---

## 🧹 Hallucination Mitigation

FinSight implements a multi-layer defense against LLM hallucinations, particularly targeting **fabricated future events** (e.g., "Company plans to launch X in 2026 Q3"):

| Layer | Method | Stage |
|-------|--------|-------|
| **Prompt Constraints** | "Closed-book" instructions: only use provided evidence, never invent events | System prompt |
| **Regex Pattern Matching** | `_HALLUCINATION_EVENT_PATTERNS` — detect future event claims | Post-generation |
| **Evidence Cross-Validation** | `_claim_supported_by_evidence()` — verify claims against evidence pool | Post-generation |
| **Placeholder Replacement** | Unverified claims replaced with `[此处信息未经证据验证，已移除]` | Post-generation |
| **Time Anchoring** | Force date attribution on all data references | Prompt + post-processing |
| **Deduplication** | Collapse consecutive placeholders into single marker | Cleanup |

> Full technical documentation: [`docs/HALLUCINATION_MITIGATION.md`](docs/HALLUCINATION_MITIGATION.md)

---

## 🔧 Tech Stack

### Backend
| Technology | Version | Purpose |
|------------|---------|---------|
| **Python** | 3.11+ | Runtime |
| **FastAPI** | 0.100+ | REST API + SSE streaming |
| **LangGraph** | 0.2+ | Stateful agent orchestration |
| **LangChain** | 0.3+ | Tool framework, message types, text splitters |
| **Langfuse** | 2.x | Distributed tracing & observability |
| **yfinance** | 0.2+ | Market data (quotes, financials, technicals) |
| **FlagEmbedding** | latest | bge-m3 embedding model |
| **sentence-transformers** | latest | bge-reranker-v2-m3 cross-encoder |
| **APScheduler** | 3.x | Alert scheduling (cron-based) |
| **Pydantic** | 2.x | Schema validation |

### Frontend
| Technology | Version | Purpose |
|------------|---------|---------|
| **React** | 19 | UI framework |
| **Vite** | 6.x | Build tooling |
| **TypeScript** | 5.x | Type safety |
| **Zustand** | 5.x | State management (3 stores) |
| **ECharts** | 5.x | Chart visualization (via echarts-for-react) |
| **TailwindCSS** | 4.x | Styling with CSS variables theming |
| **react-markdown** | latest | Markdown rendering in chat/reports |

### Models
| Model | Dimension | Purpose |
|-------|-----------|---------|
| **LLM** (configurable) | — | `create_llm()` factory supports OpenAI, Gemini, DeepSeek, Anthropic, local |
| **BAAI/bge-m3** | 1024 | Dense + Sparse embedding for RAG |
| **BAAI/bge-reranker-v2-m3** | — | Cross-encoder reranking |
| **paraphrase-multilingual-MiniLM-L12-v2** | 384 | Legacy knowledge base (ChromaDB) |

---

## 🚀 Getting Started

### 🐳 Docker One-Click Deployment (Recommended)

```bash
# 1. Clone repository
git clone https://github.com/kkkano/FinSight.git
cd FinSight

# 2. Configure environment
cp .env.server.example .env.server
# Edit .env.server with your real API keys (see "API Keys" section below)

# 3. Start all services
docker compose --env-file .env.server up -d --build
# Frontend: http://localhost:5173
# Backend:  http://localhost:8000
# PostgreSQL: localhost:5432
```

> 💡 Docker deployment includes PostgreSQL with pgvector for production-grade RAG.

### 🔑 API Keys (Required vs Optional)

| API Key | Required? | Purpose | If Not Configured |
|---------|-----------|---------|-------------------|
| `OPENAI_COMPATIBLE_API_KEY` | ✅ **Required** | Default OpenAI-compatible LLM endpoint (`mimo-v2.5-pro` service) | App won't function |
| `OPENAI_COMPATIBLE_API_BASE` | ✅ **Required** | OpenAI-compatible base URL (`https://token-plan-cn.xiaomimimo.com/v1` by default) | Uses the code default |
| `OPENAI_COMPATIBLE_MODEL` | ✅ **Required** | Default model ID (`mimo-v2.5-pro` by default) | Uses the code default |
| `GEMINI_PROXY_API_KEY` or `OPENAI_API_KEY` | Optional | Alternative LLM providers | OpenAI-compatible endpoint is used |
| `FMP_API_KEY` | ⭐ Recommended | Financial data (earnings, ratios) | Falls back to yfinance |
| `FINNHUB_API_KEY` | Optional | Real-time quotes, news | Falls back to other sources |
| `TAVILY_API_KEY` | Optional | Web search | Falls back to DuckDuckGo |
| `FRED_API_KEY` | Optional | Macro economic data | Limited macro features |
| `ALPHA_VANTAGE_API_KEY` | Optional | Additional price data | Uses other price sources |

> **Minimum Setup**: configure `OPENAI_COMPATIBLE_API_KEY` in `.env.server`. All other APIs have automatic fallbacks.

### 💾 Database Initialization

SQLite tables (`checkpoint`, `report`, `portfolio`, `subscriptions`) are **auto-created on first startup** — no manual migration needed.

For PostgreSQL (optional), tables are created via SQLAlchemy models automatically.

---

### Manual Setup (Alternative)

#### Prerequisites

- Python 3.11+
- Node.js 18+ with pnpm
- At least one LLM API key (OpenAI / Gemini / DeepSeek)

#### Backend Setup

```bash
# 1. Create virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.server.example .env.server
# Edit .env.server with your API keys:
#   OPENAI_COMPATIBLE_API_KEY=sk-...
#   OPENAI_COMPATIBLE_API_BASE=https://token-plan-cn.xiaomimimo.com/v1
#   OPENAI_COMPATIBLE_MODEL=mimo-v2.5-pro
#   OPENAI_API_KEY=sk-...
#   GOOGLE_API_KEY=...        (for Gemini)
#   FMP_API_KEY=...           (Financial Modeling Prep)
#   FINNHUB_API_KEY=...       (Finnhub)
#   TAVILY_API_KEY=...        (Tavily Search)
#   FRED_API_KEY=...          (FRED Economic Data)

# 4. Run Server
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

### Frontend Setup

```bash
cd frontend
pnpm install
pnpm dev
# Open http://localhost:5173
```

### Validation

```bash
pytest -q backend/tests/test_understand_request.py backend/tests/test_langgraph_skeleton.py backend/tests/test_policy_gate.py
pytest -q backend/tests/test_reply_contract_lanes.py backend/tests/test_evidence_diagnostics_gate.py
python scripts/chat_ux_router_eval.py --dataset tests/eval/chat_router_100.json --run-id local100
npm run build --prefix frontend
npm run test:e2e --prefix frontend
```

The current chat UX acceptance set lives at `tests/eval/chat_router_100.json` and is executed by `scripts/chat_ux_router_eval.py`; the final current-state artifact is `docs/qa/chat-router-100-final100-current-state.md` / `.json` with `100` PASS, `0` REVIEW, and `0` FAIL. It covers 18 categories: ordinary explanation, no-news correction, news links, quotes, tool-failure boundaries, context binding, session isolation, compound intent, confusion correction, report follow-up, portfolio/alert, URL/article, macro transmission, UI selection, safety boundary, language style, context continuity, and report-button follow-up. Known residual risk is operational rather than semantic: upstream LLM/tool latency, quota, 403, or inaccessible URLs can still occur, but failed tool outputs are kept in diagnostics and must not render as evidence.

### Optional: PostgreSQL for RAG

```bash
# Set environment variable to enable PostgreSQL backend
# RAG_BACKEND=postgres
# DATABASE_URL=postgresql://user:pass@localhost:5432/finsight
```

### Optional: Email Alerts

```bash
# Enable alert schedulers
# ALERTS_ENABLED=true
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=your-email@gmail.com
# SMTP_PASSWORD=your-app-password
```

---

## 📁 Project Structure

```
FinSight/
├── backend/
│   ├── api/                    # FastAPI routers (28 modules)
│   │   ├── main.py             # App entry point + CORS + lifespan
│   │   ├── chat_router.py      # POST /api/chat (SSE streaming)
│   │   ├── agent_router.py     # Agent preferences API
│   │   ├── dashboard_router.py # GET /api/dashboard + /insights
│   │   ├── conversation_router.py # Conversation lifecycle API
│   │   ├── execution_router.py # POST /api/execute (workbench)
│   │   ├── research_router.py  # Research mode API
│   │   ├── alerts_router.py    # GET /api/alerts/feed
│   │   ├── portfolio_router.py # Holdings management
│   │   ├── rebalance_router.py # Portfolio rebalancing
│   │   ├── report_router.py    # Report management
│   │   ├── backtest_router.py  # Strategy backtesting
│   │   ├── screener_router.py  # Stock screener
│   │   ├── cn_market_router.py # A-Share / HK market
│   │   ├── tools_router.py     # GET /api/tools (manifest)
│   │   └── ...                 # system/user/market/config etc.
│   ├── graph/                  # LangGraph pipeline core
│   │   ├── runner.py           # Graph construction + GraphRunner
│   │   ├── state.py            # GraphState definition
│   │   ├── intent_contract.py  # Evidence-first intent contract
│   │   ├── request_frame.py    # Request frame model
│   │   ├── request_task_contract.py # Task contract
│   │   ├── memory_scope.py     # Scoped memory
│   │   ├── capability_registry.py # Capability registry
│   │   ├── coverage_validator.py  # Coverage validation
│   │   ├── executor.py         # Plan executor
│   │   ├── report_builder.py   # ReportIR helper
│   │   ├── plan_ir.py          # Plan intermediate representation
│   │   ├── cancellation.py     # Cancellation tokens
│   │   ├── preference_timeouts.py # User timeout preferences
│   │   └── nodes/              # 27 pipeline nodes
│   │       ├── understand_request.py # Request understanding (LLM router)
│   │       ├── chat_respond.py      # Pure-social fast path
│   │       ├── conversation_router.py # Contextual router
│   │       ├── policy_gate.py       # Policy gate + evidence floor
│   │       ├── planner_stub.py      # Contract-driven planning fallback
│   │       ├── chat_renderer.py     # Chat / compare rendering
│   │       ├── synthesize.py        # Conflict detection + hallucination scrub
│   │       ├── compare_gate.py      # Compare evidence gate
│   │       ├── execute_plan_stub.py # Plan execution
│   │       └── ...                  # build/reset/prepare/alert/confirm etc.
│   ├── agents/                 # 7 research agents + base class
│   │   ├── base_agent.py       # BaseFinancialAgent (reflection + configure_research)
│   │   ├── price_agent.py      # 11-source price cascade
│   │   ├── news_agent.py       # News + sentiment + source scoring
│   │   ├── fundamental_agent.py # Financials + valuation
│   │   ├── technical_agent.py  # Technical indicator calculation
│   │   ├── macro_agent.py      # FRED + macro sentiment
│   │   ├── risk_agent.py       # Risk assessment
│   │   └── deep_search_agent.py # Self-RAG multi-engine search
│   ├── tools/                  # 26 tool modules
│   │   ├── manifest.py         # Tool manifest (with market annotations)
│   │   ├── price.py            # Price data (11-source cascade)
│   │   ├── financial.py        # Financial statements
│   │   ├── technical.py        # Technical indicators
│   │   ├── news.py             # News fetching
│   │   ├── macro.py            # FRED + sentiment
│   │   ├── search.py           # Multi-engine search
│   │   ├── sec.py / sec_holdings.py # SEC EDGAR + holdings
│   │   ├── earnings_transcripts.py  # Earnings call transcripts
│   │   ├── local_disclosure.py      # Non-US market filings
│   │   ├── cn_market_flow.py / cn_market_board.py # A-Share tools
│   │   └── ...                 # screener/fmp/web/http etc.
│   ├── dashboard/              # Dashboard data & AI insights
│   │   ├── data_service.py     # yfinance/FMP data fetching
│   │   ├── cache.py            # DashboardCache (16 TTL categories)
│   │   ├── insights_engine.py  # 5 Insight Scorers orchestrator
│   │   └── schemas.py          # Pydantic schemas
│   ├── rag/                    # Hybrid RAG engine
│   │   ├── hybrid_service.py   # InMemory + Postgres backends
│   │   ├── embedder.py         # bge-m3 embedding service
│   │   ├── reranker.py         # bge-reranker-v2-m3
│   │   ├── rag_router.py       # Query routing (SKIP/PRIMARY/PARALLEL)
│   │   └── chunker.py          # Document chunking strategies
│   ├── config/                 # Ticker mapping, market config
│   ├── conversation/           # Conversation management layer
│   ├── orchestration/          # Orchestration (budget, tracking)
│   ├── report/                 # Report IR, validation, citations
│   ├── research/               # Research flows
│   ├── security/               # SSRF protection
│   ├── services/               # Background services (alerts, subscriptions, memory)
│   └── tests/                  # Backend tests
├── frontend/
│   ├── src/
│   │   ├── api/client.ts       # API client + SSE parseSSEStream
│   │   ├── store/              # Zustand stores
│   │   │   ├── useStore.ts     # Global store (session, auth)
│   │   │   ├── dashboardStore.ts  # Dashboard state
│   │   │   └── executionStore.ts  # Workbench execution state
│   │   ├── components/
│   │   │   ├── dashboard/      # Dashboard UI (6 tab panels)
│   │   │   ├── settings/       # Settings panel (AgentControlPanel)
│   │   │   ├── SmartChart.tsx   # LLM-driven dual-mode charts
│   │   │   ├── ChatList.tsx     # Chat + inline charts
│   │   │   └── workbench/       # Workbench components
│   │   ├── hooks/              # Custom React hooks
│   │   └── types/              # TypeScript type definitions
│   └── vite.config.ts
├── data/                       # Runtime data storage
│   ├── memory/                 # Per-user JSON profiles
│   ├── subscriptions.json      # Email alert subscriptions
│   └── *.sqlite                # SQLite databases
├── docs/                       # Technical documentation (see docs/DOCS_INDEX.md)
├── scripts/                    # Operations & evaluation scripts
├── tests/                      # Regression tests & evaluators
├── images/                     # Screenshots
├── docker-compose.yml          # Docker orchestration
├── Dockerfile                  # Backend image
├── requirements.txt            # Python dependencies
└── .env.server.example         # Environment variable template
```

---

## 🧪 Phase Labs (Phase 1–4)

An experimental feature suite accessible at `/phase-labs`, built on top of the core platform:

| Phase | Feature | Description |
|-------|---------|-------------|
| **Phase 1** | Conversational Price Alerts | Say "alert me when TSLA hits $300" in chat → LangGraph extracts ticker/direction/threshold → scheduler fires email when triggered. Supports `price_change_pct` (cooldown window) and `price_target` (one-shot). |
| **Phase 2** | Stock Screener MVP | Multi-condition natural-language screener (PE < 20, revenue growth > 15%, etc.). Returns ranked results with a `capability_note` on CN/HK coverage limits. |
| **Phase 3** | A-Share Market Data | Real-time Northbound/Southbound capital flow (`cn_market_flow`), sector & concept board heat maps (`cn_market_board`), concept keyword map (`concept_map`). Covers both A-Share and HK markets. |
| **Phase 4** | Strategy Backtesting | SMA crossover, MACD signal, RSI mean-reversion strategies. Enforces A-Share T+1 settlement (no same-day round-trip), parameterized commission/slippage, and look-ahead bias prevention via `t_plus_one` bar offset. |

### 🔬 RAG Quality V2 — 3-Layer Evaluation

A custom eval framework replacing RAGAS with 6 claim/keypoint-level metrics tailored for Chinese financial narratives. Full report: [`tests/rag_qualityV2/REPORT.md`](./tests/rag_qualityV2/REPORT.md)

**Layer overview:**

| Layer | What it tests | Input | Key insight |
|-------|--------------|-------|-------------|
| **L1** Mock Context | LLM generation baseline — given perfect evidence, can the model answer correctly? | Mock contexts → direct prompt | Establishes the generation ceiling independent of retrieval |
| **L2** Real Retrieval | Retrieval + generation pipeline — does bge-m3 hybrid search surface the right chunks? | Real embedding + Top-K → synthesize_agent | Isolates retrieval quality from routing/orchestration noise |
| **L3** E2E Pipeline | Full LangGraph end-to-end — exactly what a real user gets | Complete LangGraph flow | Strongest signal; validates production readiness |

**All 3 layers PASSED** across 12 Chinese financial cases (filings, transcripts, news):

| Layer | KC | KCR | CSR | UCR ↓ | CR ↓ | NCR | Gate |
|-------|----|-----|-----|-------|------|-----|------|
| L1 Mock | 0.8796 | 0.9479 | 0.9431 | 0.057 | **0.0** | 0.9896 | ✅ PASS |
| L2 Retrieval | 0.8960 | 0.9623 | **1.0000** | **0.000** | **0.0** | 0.9861 | ✅ PASS |
| L3 E2E | **0.9072** | **0.9653** | 0.9924 | 0.008 | **0.0** | **1.0000** | ✅ PASS |

**Layer 3 per-case results (12/12 PASS):**

| # | Case | Type | KC | KCR | CSR | UCR ↓ | NCR | Result |
|---|------|------|----|-----|-----|-------|-----|--------|
| 01 | Moutai 2024Q3 Revenue | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ Perfect |
| 02 | CATL Gross Margin 2024 | filing/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ Perfect |
| 03 | BYD EV Sales 2024H1 | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ Perfect |
| 04 | PICC Embedded Value | filing/factoid | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ Perfect |
| 05 | Alibaba Cloud Guidance | transcript/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ Perfect |
| 06 | Tencent Gaming Recovery | transcript/analysis | 0.714 | 1.0 | 1.0 | 0.0 | 1.0 | ⚠️ KC |
| 07 | Meituan Profitability | transcript/analysis | 0.833 | 0.833 | 1.0 | 0.0 | 1.0 | ⚠️ KC |
| 08 | JD Supply Chain | transcript/analysis | 0.714 | 1.0 | 1.0 | 0.0 | 1.0 | ⚠️ KC |
| 09 | Fed Rate Cut → A-Share | news/list | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ Perfect |
| 10 | China EV Export Controls | news/list | 1.0 | 1.0 | 0.909 | 0.091 | 1.0 | ⚠️ UCR |
| 11 | iPhone 16 China Sales | news/analysis | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | ✅ Perfect |
| 12 | Semiconductor Export Ban | news/analysis | 0.625 | 0.75 | 1.0 | 0.0 | 1.0 | ⚠️ KC |

> **CR = 0.0 across all layers** — zero contradicted claims. **NCR = 1.0 at E2E** — numeric consistency perfect end-to-end. ⚠️ KC gaps on transcript/analysis are generation-side (evidence exists, `brief` mode omits product-level detail). *\*Based on 12 test cases; production results may vary.*

---

## 📄 License

This project is licensed under the [MIT License](./LICENSE).

---

<p align="center">
  Built with LangGraph + React + ECharts
</p>
