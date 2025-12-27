# FinSight AI 升级蓝图（Sub-Agent & 深度研究方向）

> 目标：从「单一智能助手」升级为「多 Agent 协作 + 主动提醒 + 深度研究」的一体化投研平台。

---

## 一、现有架构概览（NOW）

### 1.1 总体架构（后端视角）

```mermaid
flowchart LR
    U[用户] --> FE[前端 React 应用]
    FE -->|HTTP/WS| API[FastAPI 网关]

    subgraph Core Agent 层
        API --> CIO[主 CIO Agent\n(单一 ReAct/LangGraph Agent)]
        CIO --> TOOLS[工具编排层\nlangchain_tools + backend.tools]
    end

    subgraph Data Sources
        TOOLS --> MKT[行情/指数 API\n(yfinance, Finnhub, Alpha Vantage...)]
        TOOLS --> NEWS[新闻 / 搜索\nTavily, DDGS, Yahoo, Wikipedia]
        TOOLS --> MACRO[宏观 & 情绪\nFear&Greed, 经济日历]
    end
```

### 1.2 前端架构（NOW）

```mermaid
flowchart TB
    App[App.tsx 布局] --> Chat[ChatList + ChatInput]
    App --> Chart[StockChart + InlineChart]
    App --> Settings[SettingsModal]

    subgraph Store
        Store[Zustand useStore] --> Theme[主题状态]
        Store --> Msg[消息列表 & Thinking steps]
        Store --> Ticker[当前关注 Ticker]
    end

    Chat --> APIClient[前端 apiClient 封装] -->|REST| FastAPI
    Chart --> APIClient
```

现状特点：
- 已有：多数据源容错工具层、LangGraph Agent（CIO 风格）、思考过程可视化、K 线 + 简单收益曲线。
- 未有：多 Agent 协作、告警系统、邮件订阅、深度「研究/报告库」和用户侧的 watchlist / dashboard。

---

## 二、未来能力蓝图（FUTURE）

### 2.1 多 Agent 协作架构（Sub-Agent 设计）

设计思路：用一个 **CIO Orchestrator** 作为总控，下挂多个专业子 Agent，每个 Agent 有自己的工具集和风格。

```mermaid
flowchart TB
    U[用户问题] --> Router[意图路由 / CIO Orchestrator]

    subgraph Sub-Agents
        SA1[价格&技术子 Agent\n(Technical Agent)]
        SA2[基本面子 Agent\n(Fundamental Agent)]
        SA3[宏观&情绪子 Agent\n(Macro Agent)]
        SA4[比较&回撤子 Agent\n(Quant Agent)]
        SA5[深度研究子 Agent\n(Research / DeepSearch Agent)]
    end

    Router --> SA1 & SA2 & SA3 & SA4 & SA5
    SA1 --> Merge[结果融合 & 冲突消解]
    SA2 --> Merge
    SA3 --> Merge
    SA4 --> Merge
    SA5 --> Merge

    Merge --> Report[统一报告生成模块\n(模板 + 样式 + 可导出)]
    Report --> U
```

实现要点：
- LangGraph 层：使用 **多个子图（subgraph）**，每个图绑定不同工具/提示词，顶层图通过 `router node` 调度。
- 每个子 Agent：
  - 有自己独立的工具白名单（例如 Technical Agent 只用 K 线 / 技术指标工具）。
  - 输出统一结构（JSON：结论 + 证据 + 置信度），便于融合。
- 顶层 CIO：
  - 决定调用哪些子 Agent（基于意图分类）。
  - 对各子结论做「投票 + 解释」，输出更专业的综合观点。

---

## 三、邮件订阅 & 主动提醒体系

### 3.1 功能愿景

- 用户可以：
  - 订阅某个股票 / 指数的「重大新闻」「财报」「大跌/大涨」「宏观事件」提醒。
  - 配置提醒渠道：邮件（必做）、未来可扩展到 Webhook / 企业微信 / 钉钉等。
  - 接收由 Agent 自动生成的「事件 + 快速解读」小报告。

### 3.2 后端事件流架构

```mermaid
flowchart LR
    subgraph Scheduler & Watcher
        CRON[定时任务\n(如 APScheduler)] --> FETCH[数据拉取任务]
    end

    FETCH --> RAW[原始事件流\n(新闻/行情/宏观日历)]
    RAW --> FILTER[过滤 & 去重\n(按订阅 + 关键词)]
    FILTER --> ENRICH[上下文增强\n(调用 Tools / DeepSearch)]
    ENRICH --> ALERT_AGENT[Alert Agent\n生成解读]
    ALERT_AGENT --> QUEUE[通知队列]

    subgraph Delivery
        QUEUE --> MAIL[邮件服务\n(smtplib / 外部 SMTP)]
        QUEUE --> FUTURE[未来: 推送到 App 通知中心]
    end
```

### 3.3 数据模型（建议）

- `subscriptions` 表：
  - `user_id`
  - `ticker` / `topic`（如 `^GSPC`, `MACRO_US`, `AAPL`）
  - `channels`（email / webhook）
  - `event_types`（`EARNINGS`, `BIG_MOVE`, `MACRO`, `NEWS_KEYWORD`）
  - `thresholds`（如 日内波动 > 5%）
- `events` 表：
  - `source`（news/api/manual）
  - `ticker` / `tag`
  - `title` / `summary` / `link`
  - `severity_score` / `novelty_score`

Alert Agent：
- 负责「短篇即时解读」：
  - 说明发生了什么（发生时间 / 事件性质）。
  - 粗略判断「短期影响 & 风险方向」。
  - 给出是否值得进一步生成完整报告（可调用 CIO Agent）。

---

## 四、DeepSearch / 深度研究能力

### 4.1 DeepSearch 目标

> 让系统不只依赖单次搜索，而是构建可复用的「研究档案」，支持长期跟踪同一标的。

建议引入：
- `DeepSearch Service`：
  - 聚合 Tavily / DDGS / 官网 / 研报等多源。
  - 使用向量数据库（如 Chroma / Qdrant）存储「文档片段 + 元数据」。
  - 提供 RAG 风格接口给 Research Agent。

```mermaid
flowchart LR
    Query[Research Agent 请求\n(如: 深度分析 TSLA)] --> DS[DeepSearch Service]
    DS --> CRAWLER[多源抓取 & 抽取]
    CRAWLER --> VDB[向量库\n(存储分片 + Embedding)]
    VDB --> RAG[检索 + 重排 + 证据拼装]
    RAG --> ResearchAgent[Research Sub-Agent\n生成长文研究]
    ResearchAgent --> CIO[主 CIO Agent\n整合到终版报告]
```

DeepSearch 可以支持：
- 公司历史大事件时间线（收购、重大产品、监管事件）。
- 核心财报 / 管理层发言摘要。
- 估值区间历史（PE/PB 分位）。

---

## 五、前端未来升级方向（UX 视角）

### 5.1 Watchlist & 仪表盘

建议新增：
- 左侧/右侧「关注列表」：
  - 支持添加/移除标的。
  - 展示小卡片：最新价、日涨跌、YTD、情绪。
- 「今日概览」仪表盘：
  - 全市场情绪、指数概览（S&P / Nasdaq / CSI300 等）。
  - 用户关注标的的「今日重要事件」列表。

### 5.2 通知中心 & 时间线

前端模块：
- 通知中心：
  - 显示最近触发的 Alert（按严重程度排序）。
  - 可点击「展开详细解读」或一键生成完整报告。
- 时间线视图：
  - 某个 ticker 维度的事件 timeline（财报 / 新闻 / 大跌 / 评级变动）。

### 5.3 交互提升

- 「思考过程」视图：
  - 已有 ThinkingProcess，可以增加：
    - 每个 Step 的耗时。
    - 哪些工具被调用、成功/失败。
    - 一键复制整个推理链，便于审计。
- 场景预设按钮：
  - 「快速查看」：`估值是否偏贵？` / `过去一年最大回撤？` / `与纳指对比表现？`
  - 点击后自动帮用户构造高质量 prompt，减轻输入负担。
- 深色/浅色主题：已经实现，可后续加入「跟随系统」/「自定义配色」面板。

---

## 六、技术落地路线（建议分阶段）

### 阶段 1：Sub-Agent & 工具拆分（短期）

- 引入多 Agent 架构：
  - 新建 `backend/agents/technical_agent.py`、`fundamental_agent.py` 等子 Agent。
  - 现有 LangGraph CIO Agent 作为顶层 orchestrator。
- langchain_tools 拆分：
  - 按功能分组：价格/技术、新闻/搜索、宏观/情绪、比较/回撤。
  - 每个子 Agent 只绑定自己需要的工具 → 提高鲁棒性和可控性。

### 阶段 2：Alert & 邮件订阅（中期）

- 新增：
  - `backend/alerts/models.py`（订阅 & 事件模型）。
  - `backend/alerts/scheduler.py`（定时任务入口）。
  - `backend/alerts/agent.py`（AlertAgent 调用工具并生成文案）。
- FastAPI：
  - 完善 `/api/subscribe`、`/api/unsubscribe`、`/api/subscriptions` 为真正的数据持久化接口。
- 前端：
  - SettingsModal 中增加「订阅管理」页签：勾选标的 + 事件类型 + 邮箱。

### 阶段 3：DeepSearch & 研究档案（中长期）

- 引入：
  - `backend/research/deepsearch.py`（聚合搜索 + 抓取）。
  - `backend/research/vector_store.py`（向量库封装）。
  - `backend/research/agent.py`（ResearchAgent，专注长文研究）。
- 把 CIO 报告分为：
  - 快速报告（依赖实时工具）。
  - 深度研究（依赖 DeepSearch 语料 + 向量库）。

---

## 七、小结：优先级与收益

**短期高收益：**
- 多 Agent 拆分（提升稳定性和可解释性）。
- 邮件订阅 & AlertAgent（让系统「主动」工作）。

**中期提升：**
- Watchlist + 仪表盘 + 通知中心（用户留存和使用频率大幅提升）。

**长期差异化能力：**
- DeepSearch + 研究档案 + 事件时间线  
  → 从「聊天机器人」进化为「持续跟踪、可以审计的研究助手」。

这份蓝图可以作为未来重构和新功能的「总设计图」，后续每做一块功能，都可以在本文件中补上实际实现路径与接口列表。***
