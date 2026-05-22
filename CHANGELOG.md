# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/) 规范。

---

## [Unreleased] - 2026-05-18

### 新增

- **对话执行路由与 TechnicalAgent 能力扩面**（2026-05-21）：
  - `understand_request` 不再允许 `direct_answer` 吞掉结构化可执行 `task_hints`；当前轮有 ticker / URL / selection / 显式取证信号时直接进入 research。
  - direct 聊天答复清理“是否启动研究/进入研究链路”类二次确认话术，避免明确请求被反问绕圈。
  - 显式深度报告 query（如 `deep report` / `filing document longform` / `10-K/10-Q`）可覆盖前端默认 `chat`，进入 `investment_report` 与 `report_generation` lane。
  - request-understanding tasks 路径的研报计划补齐 SEC 10-K/10-Q、CompanyFacts、8-K、权威媒体、业绩电话会 transcript 与报告 agent 步骤，避免只跑价格/新闻/公司信息。
  - 显式技术面 query 在 chat 模式也会计划 `technical_agent`，与 `get_stock_price`、`get_technical_snapshot` 一起执行。
  - 显式 `investment_report` 与技术面 query 在 `conversation_router` 走 fast path，不再先等待会话路由 LLM，降低报告/技术面请求的首段阻塞。
  - Agent 内部 LLM 分析、gap detection 与 summary update 增加硬超时；LLM 长尾时回退确定性摘要，避免单 Agent 拖垮整轮报告。
  - `technical_agent` 工具面从 K 线 + search 扩展为 K 线、当前报价、期权 IV/PCR/Skew、市场情绪和 search；确定性摘要补支撑/阻力、MA20 偏离、成交量相对均量，并把新增信号写入 evidence。
  - Docker 后端构建支持可配置 apt 镜像、45 秒下载超时与 5 次重试；生产 compose 默认使用 TUNA Debian 镜像，避免服务器发版卡在 `apt-get update`。
  - torch 预安装层复用生产 `PIP_INDEX_URL` 作为依赖 fallback，并加 300 秒超时与 10 次重试，避免 `files.pythonhosted.org` 依赖下载超时阻断发版。
  - 单公司深度报告会把竞品 ticker 收敛为 `peer_tickers` 上下文，不再把“覆盖 NVIDIA/AMD/TSMC 竞争”误判成多公司 compare 报告；显式“比较/对比/谁更值得买”仍保持 compare。
  - DeepSearch 财务研报查询保留用户点名主题（产品路线、分析师评级、竞品格局、估值、6-12 个月风险机会），并默认限制 gap follow-up 为 1 轮 / 1 条查询，减少报告长尾空转。
  - 技术面摘要默认使用确定性指标路径，不再等待 TechnicalAgent 内部 LLM；需要技术 Agent 自身 LLM 精修时可用 `TECHNICAL_AGENT_LLM_SUMMARY_ENABLED=1` 显式开启。
- **后端 Agent 能力诊断强化**（`315e519` 2026-05-20）：
  - Planner 输出 `agent_selection` 诊断，每个被跳过的 Agent 附带跳过原因与预算优先级排序，`plan_ready` / `decision_note` 事件同步携带。
  - Planner JSON Schema 容错：解析失败时自动构造重试 prompt 二次修复（`PlannerSchemaShapeError`）。
  - 对话路由安全边界：识别并拦截索取内幕/非公开信息的请求，阻止进入 research 链路。
  - 新闻引用兜底：当 plan 无新闻源时直接抓取文章，确保回复契约有可引用 URL。
  - 多轮对话上下文延续：用历史 ticker 补全当前轮主题提示。
  - Research 辩论新增只读裁决产物（`adjudications`）。
- **Evidence Research Agents**：新增证据驱动研究链路
  - `EvidenceLedger` / query coverage 合同，统一 `claims`、`sources`、`uncertainties`、`contradictions` 与未覆盖目标。
  - DeepSearch flow facade，阶段化 `plan_search -> fetch_sources -> extract_claims -> gap_check -> targeted_followup -> ledger_write`，新写入使用 `ws:deepsearch:*` working set。
  - 多空辩论节点 `research_debate`，输出 Bull/Bear/Judge scorecard、共识、分歧和待补数据。
  - SEC 13F / Form 4 公开持仓工具，US-only 起步，明确 13F 延迟和 Form 4 披露边界。
  - 报告页展示 Evidence Ledger、Debate Scorecard、Holdings Watch 和 query coverage warning。
  - 只读研究 API、MCP server facade、A2A agent card/long-task adapter，默认 feature flag 关闭。
- **单 Agent 质量合同**：新增 `agent_quality_contract`、`agent_research_loop` 和 fixture eval gate
  - Fundamental / News / Risk Agent 输出 source-backed native claims，并写入 `evidence_quality.agent_quality`。
  - Agent 自检输出 `agent_self_check`，对缺证据、缺 claims、claim 未挂源、freshness 缺口给出 deterministic gap plan。
  - `scripts/agent_quality_eval.py` + `tests/eval/agent_quality_cases.json` 提供可重复 before/after 质量门禁。
- **Evidence Research 评估门禁**：新增 `tests/eval/evidence_research_cases.json` 与 `scripts/evidence_research_eval.py`，覆盖深研、辩论、持仓、CN 市场拒绝和 unsafe insider 边界。
- **README 截图扩充**：Platform Preview 新增两张截图
  - ThinkingBubble 用户视图 — 折叠式推理节点（逻辑查图 / 规划策略 / 执行分析）
  - 执行时间线 + 分析师摘要卡片 — 逐 Agent 步骤追踪、11 智能体完成网格
  - 同步更新 `README.md`（英文）与 `readme_cn.md`（中文）
- **`frontend/docs/DELETION_LOG.md`**：P3-2 死代码清理完整记录
  - 删除 12 个文件、1 个目录（`src/components/cards/`），合计 -2002 行
  - Tier 1：3 个直接孤立文件（alertFeed.ts、DashboardWidgets.tsx、NewsFilterPills.tsx）
  - Tier 2：9 个级联孤立文件（SnapshotCard、MarketChartCard 等 v1 遗留卡片）
  - TypeScript 编译零错误验证通过

### 修复

- **前端单测入口**：`npm --prefix frontend run test:unit` 限定到 `src`，避免 Vitest 误收集 `frontend/e2e/*.spec.ts` 的 Playwright 测试。
- **`ReportView.tsx`**：`sections` 变量包裹 `useMemo`，消除 `catalystItems` / `metricItems` 不必要的重复计算
- **`ErrorBoundary.tsx`**：eslint 禁用注释移至行尾，消除多余空行
- **`taskStateMachine.ts`**：移除未使用的 `ListTodo` 图标导入

### 文档

- 新增 `docs/release_evidence/2026-05-18_evidence_research_agents.md`，记录本分支验证命令、chat-router eval 环境阻塞、默认关闭 flags 和残余风险。

---

## [1.1.1] - 2026-03-05

### 修复与硬化 (Core Fixes & Stability)

- **网络连接性深度硬化 (SSE & Tunnel 重构)**
  - 架构更新：将所有 API 后端流量物理分离，独立到专属的 `api.finsight-ai.chat` 二级域名子通道，解决 Cloudflare Tunnel HTTP/2 强制复用导致的前端静态资源与流式拉取互相干涉断联问题。
  - 强化反发呆心跳协议：SSE 心跳由弱穿透的空白注释（`: heartbeat`）变更为伪装数据的硬性数据事件投喂，心跳间隔由 15s 缩短至 8s。
  - 深度防断层防御：前端 API Client 加入严密的边界接管，针对断联进行 `sawError`/`sawDone` 状态监测并增加兜底自动报错防僵死。
  - 网关链路拉长：Nginx 针对深度生成类请求的 `proxy_read_timeout` 与 `proxy_send_timeout` 预先扩大到 `2400s`。
- **Agent 执行跟踪修复**：修复 LangGraph 内部长流事件 (`langgraph_*`) 发送至前端在 `AgentLogPanel` 的源路由判定，同时在 `ThinkingUserView` 中主动过滤空 pending 阶段的白版占据。

### 文档 (Documentation)

- 新增：`docs/12_PRODUCTION_SSE_TUNNEL_POSTMORTEM.md`，深度记录了此次大模型长轮询被代理网关（Tunnel底层的 H2 Reset）连坐断网的根因诊断复盘记录。
- 更新说明 `README.md` 中暴露前端的反向代理端口映射记录，并插入了系统 Logo。

---

## [1.1.0] - 2026-03-02

在 v1.0.0 核心平台基础上，新增 Phase 1-4 实验性功能套件，覆盖对话式提醒、智能选股、A 股市场数据与策略回测。

### 新增

- **Phase 1 — 对话式价格提醒闭环**
  - LangGraph 自动提取提醒参数（ticker / direction / threshold）via `alert_extractor` 节点
  - `alert_action` 落库写入 `subscriptions.json`，支持与现有订阅类型（news/risk）合并
  - 调度器支持两种触发模式：`price_change_pct`（冷却窗口，`PRICE_ALERT_COOLDOWN_MINUTES` 可配）、`price_target`（一次性触发后设 `price_target_fired` 标志）
  - 前端 `SubscribeModal` 新增 `%涨跌` / `到价` 两种模式，移除 `either` 模糊选项
  - 聊天上下文自动注入 `user_email`，无邮箱时返回引导提示而非静默失败

- **Phase 2 — 智能选股 MVP**
  - `screen_stocks` 工具支持多条件自然语言选股，响应含 `capability_note` 覆盖边界提示
  - 新增 `GET /api/screener/screen` 路由
  - 前端 `/phase-labs` 入口，含 `ScreenerResultPanel` 结果面板

- **Phase 3 — A 股市场扩展**
  - `cn_market_flow`：北向/南向资金净流入，含近 5 日历史趋势
  - `cn_market_board`：板块与概念板块实时涨跌排行
  - `concept_map`：关键词 → 概念板块映射表（用于意图识别辅助）
  - 新增 `GET /api/cn-market/flow`、`/board`、`/concept-map` 三条路由
  - 前端 `CNMarketPanel` 集成至 `/phase-labs`

- **Phase 4 — 策略回测**
  - 内置三种策略：SMA 双均线、MACD 信号线交叉、RSI 均值回归
  - A 股 T+1 结算强制执行（买入当日不可卖出）
  - 参数化佣金率与滑点对最终净值有可验证影响
  - 通过 `t_plus_one` bar 偏移防止前视偏差（look-ahead bias）
  - 新增 `POST /api/backtest/run` 路由
  - 前端 `BacktestPanel` 集成至 `/phase-labs`

### 技术

- `parse_operation` 意图优先级更新：`backtest` 前移，避免被 `technical` 意图截胡
- 新增 58 个测试（Phase 1: 26 个，Phase 2-4 + 回归: 32 个），全部通过
- `RAG_ENABLE_RERANKER` 改为显式开关（默认关闭），稳定 CI 测试环境

---

## [1.0.0] - 2026-02-08

从 v0.8.0 LangGraph 管线基础上完成生产就绪化，覆盖 LLM 容错、UI 打磨、安全加固与文档体系建设。

### 新增

- **LLM 端点轮询容错**：通过 `llm_factory` 注入实现多端点 round-robin 故障切换，429/配额错误时自动旋转至下一端点（`LLM_RATE_LIMIT_RETRY_MAX_ATTEMPTS` 可配）
- **raw_url 代理模式**：支持完整代理 URL 直通，兼容企业级 API 网关场景
- **消息持久化**：对话消息通过 `localStorage` 自动持久化，页面刷新后恢复会话历史
- **移动端侧边栏**：响应式抽屉式侧边栏，带遮罩层，支持手势关闭
- **共享 UI 组件库**：抽取 `Button`、`Card`、`Badge`、`Input` 四个基础组件至 `frontend/src/components/ui/`，统一设计规范
- **GraphState 类型契约**：定义 `Policy`、`PlanIR`、`Artifacts`、`Trace` 等 TypedDict 契约，贯通前后端状态流转
- **证据质量信号**：Agent 卡片展示证据质量评分与新鲜度徽章
- **执行进度条**：聊天界面显示当前执行步骤的实时进度状态
- **Agent 选择评分可视化**：Trace 面板暴露并渲染 Agent 选择分数与决策理由
- **章节级引用**：报告 payload 与模板中支持 section-level citations
- **渐进式升级策略**：Agent 证据质量信号触发渐进式数据源升级
- **Filing 指标标准化**：基本面 Agent 统一 YoY/QoQ 同比环比指标格式
- **宏观 Agent 增强**：来源优先级合并与冲突感知的证据质量评估
- **检索评估增强**：新增漂移门控与 Postgres 夜间基准测试

### 修复

- **配置端点安全加固**：`/api/config` 接口添加字段白名单过滤，API Key 返回时自动脱敏
- **深色模式悬停可见性**：修复深色主题下悬停状态颜色对比度不足的问题
- **编码损坏修复**：解决 `ChatInput.tsx` 和 `client.ts` 中非 ASCII 字符编码异常
- **比较结论硬编码**：移除 MSFT/AAPL 比较报告中硬编码的结论文本，改为动态生成
- **updateLastMessage 变异模式**：重构为不可变更新模式，消除 Zustand 状态直接修改
- **report_builder 最小字符数**：`min_chars` 阈值从 2000 降低至 800，减少短报告被误判为不合格

### 变更

- **AgentLogPanel 拆分**：将 Agent 日志面板拆分为独立子组件，提升可维护性
- **ReportView 组件拆分**：报告视图按职责拆分为多个聚焦组件

### 样式

- **text-2xs 设计令牌**：新增超小号文本尺寸令牌
- **NavItem 设计令牌修复**：修正导航项令牌引用错误
- **border-radius 统一**：全局圆角值归一化，消除不一致
- **ARIA 无障碍**：关键交互元素补充 `aria-label` 和 `role` 属性

### 文档

- 新增 `LANGGRAPH_FLOW.md` -- LangGraph 11 节点管线可视化流程
- 新增 `AGENTS_GUIDE.md` -- 6 个金融子 Agent 能力与配置说明
- 新增 `WORKBENCH_ROADMAP.md` -- Workbench 分析师工作台路线图
- 新增 `ISSUE_TRACKER.md` -- 已知问题与待办追踪
- 新增 `CONTRIBUTING.md` -- 项目贡献指南
- 更新 `06_LANGGRAPH_REFACTOR_GUIDE.md` -- 补充 patch note 与 fund-domain 路线图

---

## [0.8.0] - 2026-02-07

从 Supervisor-Forum 架构迁移至 LangGraph StateGraph，实现 11 节点声明式管线编排，完成生产级发布。

### 新增

- **LangGraph 11 节点管线**：基于 `StateGraph` 架构实现完整编排链路
  - `BuildInitialState` -> `NormalizeUIContext` -> `DecideOutputMode` -> `ResolveSubject` -> `Clarify` -> `ParseOperation` -> `PolicyGate` -> `Planner` -> `ExecutePlan` -> `Synthesize` -> `Render`
- **6 个金融子 Agent**：每个 Agent 配备独立熔断器与重试策略
  - `PriceAgent` -- 实时行情（yfinance / Finnhub / Alpha Vantage 多源回退）
  - `NewsAgent` -- 新闻舆情（RSS + Finnhub + 反思循环 + 结构化输出）
  - `TechnicalAgent` -- 技术分析（MACD / RSI / 布林带）
  - `FundamentalAgent` -- 基本面研究（财报解读 + 估值模型）
  - `MacroAgent` -- 宏观分析（FRED API 实时数据）
  - `DeepSearchAgent` -- 深度研报（多轮搜索 + SSRF 防护 + 搜索收敛）
- **Planner-Executor 模式**：通过 `PlanIR` 中间表示驱动计划生成与执行
  - 支持 `stub`（确定性）和 `llm`（约束生成）两种 Planner 模式
  - A/B 实验框架：按 thread 稳定分桶，可配拆分比例与盐值
- **SSE 流式传输**：支持 `trace` 与 `raw` 两种事件类型的服务端推送
  - 前端实时消费 Agent 执行轨迹与中间结果
  - 支持 `EventSource` 与 `fetch` 两种客户端消费模式
- **Dashboard 仪表盘**：
  - Watchlist 自选股列表（实时行情卡片）
  - News Feed 新闻流（多选新闻上下文关联分析）
  - Market Data 市场概览数据
  - 多选新闻触发 NEWS 意图强制分类
- **Workbench 工作台**：面向分析师的专业工作流视图
- **设计系统**：`fin-*` CSS 自定义属性体系
  - 完整的浅色/深色双主题色板
  - 语义色定义（primary / success / danger / warning / predict）
  - 文本层级、边框、卡片、面板等组件级令牌
- **持久化 Checkpointer**：支持 `sqlite` 和 `postgres` 两种后端
  - 可控回退：`LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK` 开关
- **统一状态契约**：`subject_type + operation + output_mode` 三元组驱动全管线
- **PolicyGate 策略门控**：管线执行前的安全与合规校验节点
- **Session 上下文管理**：TTL 驱动的 LRU 会话上下文缓存
- **安全基础设施**：
  - API Key 认证（`API_AUTH_ENABLED`）
  - HTTP 速率限制（`RATE_LIMIT_ENABLED`）
  - CORS 精细控制
  - SSRF 防护（URL 校验 + 私有 IP 检测）

### 变更

- 主编排路径从 `SupervisorAgent + ForumHost` 迁移至 `LangGraph StateGraph`
- 旧 Supervisor/SchemaRouter/ConversationRouter 标记为 `@deprecated`
- API 路由入口统一为 `/chat/supervisor` 和 `/chat/supervisor/stream`
- 测试框架配置更新：`pytest.ini` 添加废弃警告过滤

### 依赖

- `langgraph` 升级至 `1.0.7`
- `langgraph-checkpoint` 升级至 `3.0.0`
- `langgraph-checkpoint-sqlite` 升级至 `3.0.3`
- `langgraph-checkpoint-postgres` 升级至 `3.0.4`
- `langchain` 升级至 `1.2.7`
- `langchain-core` 升级至 `1.2.7`

---

[1.1.0]: https://github.com/<org>/FinSight/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/<org>/FinSight/compare/v0.8.0...v1.0.0
[0.8.0]: https://github.com/<org>/FinSight/releases/tag/v0.8.0
