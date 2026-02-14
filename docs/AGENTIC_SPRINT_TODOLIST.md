# FinSight Agentic Sprint — 超级 TodoList

> 生成时间: 2026-02-12
> 分支: feat/v1.1.0-sprint2 → 建议新开 feat/v1.2.0-agentic
> 执行原则: 从上往下依次执行，每完成一项打 ✅，阻塞项标 🚫

---

## Phase 0: 基础设施（先做，其他全依赖这些）

### P0-1: 抽取公共执行服务（避免 chat_router 逻辑分叉）

> **为什么先做**: /api/execute 和 /chat/supervisor/stream 共享同一套 producer 逻辑，
> 先抽公共层，后面两个入口都调它，不会分叉。

- [x] **P0-1a** 新建 `backend/services/execution_service.py` — 抽取 `chat_router.py:150-232` 的 `_producer()` 为公共 `run_graph_pipeline()`
  - 入参: `query, session_id, tickers, output_mode, ui_context, agents_override, budget_override`
  - 返回: `AsyncGenerator[dict, None]` (SSE 事件流)
  - 含: event_bus 设置、GraphRunner 调用、markdown 分块、report 构建、report_index 持久化
  - 含: 错误处理与 fallback
- [x] **P0-1b** 重构 `backend/api/chat_router.py` — `POST /chat/supervisor/stream` 改为调用 `execution_service.run_graph_pipeline()`
  - 保持 API 签名不变，内部逻辑委托给公共服务
  - 移除原有 `_producer()` 内联函数
  - 验证: 原有 Chat 流式功能不受影响
- [x] **P0-1c** 新建 `backend/api/execution_router.py` — `POST /api/execute`
  - 接受: `{ query, tickers, output_mode, agents?, budget?, source }`
  - 调用同一个 `execution_service.run_graph_pipeline()`
  - SSE 响应格式与 `/chat/supervisor/stream` 完全一致
  - source 字段传入 ui_context 供追踪
- [x] **P0-1d** 注册路由 `backend/api/main.py` — 挂载 execution_router
- [x] **P0-1e** 前端 `frontend/src/api/client.ts` — 新增 `executeAgent()` 方法
  - 复用 `sendMessageStream()` 的 SSE 解析逻辑（先抽为公共函数 `parseSSEStream()`）
  - 支持 source 参数

### P0-2: report_id 回放闭环

> **为什么紧跟**: 后端 + 前端 API 都已就绪，只差消费端 3 行代码。最小改动最大收益。

- [x] **P0-2a** 修改 `frontend/src/App.tsx` — ChatRoute 解析 `?report_id=` 查询参数
  - 从 URL searchParams 读取 report_id
  - 传入 ChatWorkspace / ChatInput 作为 prop
- [x] **P0-2b** 修改 `frontend/src/components/ChatInput.tsx` 或 `ChatWorkspace.tsx`
  - 接收 report_id prop
  - 若非空，调用 `apiClient.getReportReplay(reportId)` 获取报告
  - 将报告插入为一条带 `report` 字段的消息，触发 ReportView 渲染
  - 加载完成后清除 URL 参数（避免刷新重复加载）
- [x] **P0-2c** 验证: TaskSection / ReportSection 点击 → 跳转 `/chat?report_id=xxx` → 自动加载报告

### P0-3: fallback_reason 细分 + 可观测性

> **为什么现在做**: 后面所有 Agent 可操作化都需要前端区分"限流等待" vs "真实错误"。

- [x] **P0-3a** 修改 `backend/graph/adapters/agent_adapter.py` — `_build_agent_fallback_output()` 增加结构化降级信息
  - 新增字段: `fallback_reason` (枚举: rate_limit_timeout / execution_error / confidence_skip / budget_exceeded)
  - 新增字段: `retryable` (bool)
  - 新增字段: `error_stage` (枚举: token_acquire / llm_invoke / parse / tool / unknown)
  - 修改 `_normalize_agent_output()` 透传这些字段
- [x] **P0-3b** 修改 agent_adapter 中调用 agent 的 try/except 块（约 line 250-290）
  - asyncio.TimeoutError → `fallback_reason="rate_limit_timeout", retryable=True, error_stage="token_acquire"`
  - RateLimitError 类 → `fallback_reason="rate_limit_timeout", retryable=True, error_stage="llm_invoke"`
  - 其他 Exception → `fallback_reason="execution_error", retryable=False, error_stage="unknown"`
- [ ] **P0-3c** 修改 `backend/graph/nodes/execute_plan_stub.py` — 将 fallback_reason 写入 evidence_pool/artifacts
  - synthesize 节点可读取，render 模板可展示
- [x] **P0-3d** 修改 `backend/graph/report_builder.py` — report payload 增加 `agent_diagnostics` 字段
  - 每个 agent 的: status, fallback_reason, retryable, error_stage, duration_ms
- [ ] **P0-3e** 前端 ReportView 组件展示降级原因
  - AgentStatusGrid 中: 🟢正常 / 🟡限流降级(可重试) / 🔴执行失败
  - Tooltip 显示 error_stage

### P0-4: 限流策略统一 — 全局桶 + 每 agent 保底配额

> **为什么现在做**: 不解决这个，后续并发执行会频繁降级。

- [x] **P0-4a** 修改 `backend/services/rate_limiter.py` — 引入分层令牌桶
  - 全局桶: RPM=300, burst=50（保持不变）
  - 每 agent 保底配额: 每个 agent 在任意 60s 窗口内至少获得 MIN_TOKENS_PER_AGENT=8 个令牌
  - 实现: `acquire_llm_token(agent_name=None, timeout=120.0)` — 新增可选 agent_name 参数
  - 逻辑: 先检查 agent 保底配额是否可用 → 再从全局桶扣减
- [x] **P0-4b** 修改所有 agent 调用处传入 agent_name
  - `agent_adapter.py` 中 `acquire_llm_token()` 调用增加 agent_name
  - `deep_search_agent.py` `_call_llm()` 中同样传入
  - `base_agent.py` `_identify_gaps()` 和 `_update_summary()` 传入 self.AGENT_NAME
  - `forum.py` 传入 agent_name="forum_synthesis"
  - `llm_retry.py` 新增 agent_name 参数并透传到 acquire_fn
- [x] **P0-4c** 修改 `backend/services/llm_retry.py` — 日志区分限流重试 vs 真实错误重试
  - 限流重试: `logger.info("[LLM] Rate limit retry ...")` (不报 warning)
  - 真实错误: `logger.warning("[LLM] Execution error retry ...")`
- [x] **P0-4d** 编写测试 `backend/tests/test_rate_limiter_quota.py`
  - 测试: 6 agent 并发请求时，每个 agent 都能获得至少 MIN_TOKENS
  - 测试: 全局桶耗尽时保底配额仍可用

### P0-5: TaskSection 接入后端 API

> **为什么在限流之后**: TaskSection 触发执行需要限流稳定。

- [ ] **P0-5a** 修改 `frontend/src/components/workbench/TaskSection.tsx`
  - 删除 `useMemo` 硬编码任务生成逻辑 (line 48-113)
  - 新增 `useEffect` 调用 `GET /api/tasks/daily?session_id=...&news_count=N`
  - 从 dashboardStore 获取 newsItems.length 作为 news_count
- [ ] **P0-5b** 修改 `backend/services/daily_tasks.py` — 增强任务生成
  - 每个任务增加 `execution_params` 字段: `{ query, tickers, output_mode, agents }`
  - 任务 ID 使用稳定的 hash (ticker + category + date) 而非递增数字
  - 增加 "重新分析" 类型任务 (针对 stale 报告)
- [ ] **P0-5c** 修改 `backend/api/task_router.py` — 响应格式增加 execution_params
- [ ] **P0-5d** 前端 TaskSection 任务点击 → 调用 `executeAgent(task.execution_params)` → 就地显示进度
  - 不再 `navigate('/chat')`
  - 使用 executionStore 跟踪状态
  - 完成后显示"查看报告"按钮 (跳转 `/chat?report_id=xxx`)

---

## Phase 1: 前端状态管理 + 体验升级

### P1-1: ExecutionStore (全局执行状态)

- [ ] **P1-1a** 新建 `frontend/src/store/executionStore.ts`
  - `ExecutionRun`: runId, query, tickers, source, status, agentStatuses, progress, report, fallbackReasons
  - `activeRuns[]`, `recentRuns[]` (最多 20 条)
  - `startExecution()` → 调用 `apiClient.executeAgent()` → 解析 SSE → 更新 run
  - `getActiveRunForTicker(ticker)` → 查找当前 ticker 是否有正在执行的任务
- [ ] **P1-1b** 新建 `frontend/src/hooks/useExecuteAgent.ts`
  - 封装 executionStore.startExecution()
  - 返回 `{ execute, isRunning, progress, result, error }`
  - 支持 AbortController 取消

### P1-2: 全局执行进度条 (ExecutionBanner)

- [ ] **P1-2a** 新建 `frontend/src/components/execution/ExecutionBanner.tsx`
  - 订阅 executionStore.activeRuns
  - 无活跃任务时不渲染
  - 展示: ticker + agent 进度管道图 (price ✓ → news ⟳ → fundamental ○)
  - 支持点击展开详情 / 取消执行
- [ ] **P1-2b** 修改 `frontend/src/components/layout/WorkspaceShell.tsx`
  - 在 topbar 下方、内容区上方插入 ExecutionBanner
  - 所有 view (chat / dashboard / workbench) 都可见

### P1-3: Dashboard 卡片可操作化

- [ ] **P1-3a** 修改 Dashboard SnapshotCard — 增加 action 按钮
  - "🔍 深入分析" → `useExecuteAgent({ agents: ['price_agent', 'news_agent'] })`
  - "📊 生成报告" → `useExecuteAgent({ output_mode: 'investment_report' })`
  - 按钮在执行中显示 spinner，完成后变为"查看结果"
- [ ] **P1-3b** 修改 Dashboard NewsFeed — 新闻条目增加分析按钮
  - 每条新闻右侧: "🤖 分析影响" → 触发带新闻上下文的 agent 执行
  - 结果注入 MiniChat 作为新消息
- [ ] **P1-3c** 修改 Dashboard MacroCard — 增加宏观深度分析按钮
  - "📈 宏观详解" → `useExecuteAgent({ agents: ['macro_agent'] })`

### P1-4: 流式结果展示面板 (StreamingResultPanel)

- [ ] **P1-4a** 新建 `frontend/src/components/execution/StreamingResultPanel.tsx`
  - 可嵌入: Dashboard 右侧面板 / Workbench 任务旁 / 弹出模态框
  - 订阅 executionStore 特定 runId
  - 实时渲染: markdown 流式输出 + agent 状态 + 降级标记
  - 完成后: 展示完整 ReportView
- [ ] **P1-4b** 修改 `frontend/src/components/layout/ContextPanelShell.tsx`
  - 新增 "执行结果" tab (与 MiniChat 并列)
  - 有活跃执行时自动切换到此 tab

### P1-5: Agent 控制面板

- [ ] **P1-5a** 新建 `frontend/src/components/settings/AgentControlPanel.tsx`
  - 6 个 Agent 开关 + 深度选择 (标准/深度/关闭)
  - 预算上限滑块 (max_rounds: 1-10)
  - 并发模式开关
  - 当前 Agent 健康状态 (从 /health 获取)
  - 存储到 useStore 或 localStorage
- [ ] **P1-5b** 修改 `backend/graph/nodes/policy_gate.py`
  - 读取 `ui_context.agent_preferences`
  - 覆盖 capability_registry 的 agent 选择
  - 映射深度到 budget.max_rounds
- [ ] **P1-5c** 前端执行时自动附带 agent_preferences 到 ui_context

### P1-6: Watchlist 统一

- [ ] **P1-6a** 确定单一数据源: 以后端 `/api/user/profile` + `/api/user/watchlist/*` 为准
  - dashboardStore.watchlist 改为从 API 加载，不再用 localStorage
  - Sidebar 和 Dashboard 共享同一份数据
- [ ] **P1-6b** 修改 `frontend/src/store/dashboardStore.ts`
  - `watchlist` 初始化从 `apiClient.getUserProfile()` 获取
  - `addWatchlist` / `removeWatchlist` 先调 API 再更新本地状态
  - 移除 localStorage 持久化 (由 API 持久化)
- [ ] **P1-6c** 修改 Sidebar watchlist 组件 — 改为从 dashboardStore 读取 (而非独立 fetch)

---

## Phase 2: 仪表盘 TradingKey 风格改造

> 依赖: P1-3 (卡片可操作化) 完成后再改造 UI，否则改了还要改。

### P2-1: 设计 Token 与主题系统

- [ ] **P2-1a** 新建 `frontend/src/styles/tradingkey-theme.ts` — TradingKey 暗色主题变量
  - 色板: #181a1f, #1e2025, #24282f, #2b3139, #363d47
  - 强调色: #fa8019 (橙), #0cad92 (绿), #f74f5c (红)
  - 圆角: 10px, 阴影: 0 4px 20px 2px rgba(0,0,0,.4)
  - 字体: -apple-system, "PingFang SC", "Microsoft YaHei"
- [ ] **P2-1b** 迁移现有 CSS 变量 / Tailwind config 到 TradingKey token

### P2-2: Dashboard 布局重构 (6-Tab)

- [ ] **P2-2a** 新建 `frontend/src/components/dashboard/DashboardTabs.tsx`
  - 6 个 Tab: 综合分析 / 财务报表 / 技术面 / 新闻动态 / 深度研究 / 同行对比
  - TradingKey 风格 Tab 栏 (橙色下划线)
  - 路由: `/dashboard/:symbol?tab=overview|financial|technical|news|research|peers`
- [ ] **P2-2b** Stock Header 组件 — 股票信息头部
  - Logo + 名称 + 交易所 + 实时价格 + 涨跌 + 盘后数据
  - 关注按钮 + 快速分析按钮 (触发 Agent)
- [ ] **P2-2c** Metrics Bar — 7 列关键指标条
  - 市值 / PE / PB / EPS / 股息率 / 52周区间 / Beta
  - 数据源: /api/dashboard 的 snapshot

### P2-3: Tab 1 — 综合分析

- [ ] **P2-3a** 综合评分环 (Score Ring) — SVG 环形图 + 评分 + 星级
- [ ] **P2-3b** 分析师评级卡 — 共识评级 + 堆叠评级条 + 上涨空间
- [ ] **P2-3c** 目标价格卡 — 最低/平均/最高 + 渐变范围条 + 当前价标记
- [ ] **P2-3d** 公司亮点与风险卡 — 绿点利好 + 红点利空列表
- [ ] **P2-3e** 维度评分雷达图 — SVG 五边形 (基本面/技术面/新闻/深度/宏观)
- [ ] **P2-3f** 关键洞察卡 — AI 生成摘要 (来自 synthesize 的 investment_summary)
- [ ] **P2-3g** 风险指标卡 — Beta/波动率/夏普/最大回撤 + 4 条风险告警

### P2-4: Tab 2 — 财务报表

- [ ] **P2-4a** 利润表组件 — 5 年年度数据表 (FundamentalAgent 数据)
- [ ] **P2-4b** 盈利能力趋势图 — 毛利率/净利率柱状图
- [ ] **P2-4c** 关键估值指标 — PE/PEG/EV-EBITDA/FCF Yield 四宫格
- [ ] **P2-4d** 资产负债表摘要 — 核心行项目 + 同比变化

### P2-5: Tab 3 — 技术面

- [ ] **P2-5a** K 线图占位 → 后续接入 TechnicalAgent 实时数据
- [ ] **P2-5b** 技术面综合评估 — 评分 + 均线信号 + 震荡信号
- [ ] **P2-5c** 均线指标表 — MA5/10/20/50/100/200/EMA12/EMA26
- [ ] **P2-5d** 震荡指标表 — RSI/Stoch/MACD/ADX/CCI/Williams
- [ ] **P2-5e** 支撑与阻力可视化 — R3-R1 / 当前 / S1-S3
- [ ] **P2-5f** 布林带 & 成交量 — 上中下轨 + 日均/今日成交量

### P2-6: Tab 4 — 新闻动态

- [ ] **P2-6a** 情绪统计三卡 — 正面/中性/负面百分比 + 进度条
- [ ] **P2-6b** 筛选器 Pills — 全部/利好/中性/利空/财报/产品/监管
- [ ] **P2-6c** 新闻列表 — 情绪标签 + 标题摘要 + 来源时间
- [ ] **P2-6d** AI 新闻摘要卡 — NewsAgent 综合分析

### P2-7: Tab 5 — 深度研究

- [ ] **P2-7a** 研究元数据 — 信心度/引用数/证据质量/冲突数
- [ ] **P2-7b** 执行摘要 — DeepSearchAgent synthesis
- [ ] **P2-7c** 核心发现 — 分节 + 引文证据块 (引用来源 + 引述)
- [ ] **P2-7d** 观点冲突 — 乐观 vs 悲观对照面板
- [ ] **P2-7e** 参考文献列表

### P2-8: Tab 6 — 同行对比

- [ ] **P2-8a** 评分对比 — 6 公司圆形评分卡 (当前股票高亮)
- [ ] **P2-8b** 详细指标对比表 — 12+ 列 (PE/PEG/PB/EV-EBITDA/净利率/ROE/营收增速/股息率/评分)
- [ ] **P2-8c** 估值水平横向条形图
- [ ] **P2-8d** 营收增速横向条形图
- [ ] **P2-8e** AI 同行分析摘要

---

## Phase 3: 工作台升级 — Mission Control

### P3-1: Workbench 布局重构

- [ ] **P3-1a** 修改 WorkspaceShell — Workbench 视图增加右侧面板 (ContextPanelShell)
  - 包含: StreamingResultPanel + AgentLogPanel
  - 执行任务时右侧实时展示结果
- [ ] **P3-1b** Workbench 主区域改为上下两栏
  - 上: TaskSection (任务队列) + 执行状态
  - 下: ReportSection (历史报告时间线) + NewsSection

### P3-2: 任务执行状态机

- [ ] **P3-2a** TaskSection 任务卡片增加状态指示
  - pending (默认) → running (点击执行) → done (完成) → expired (过期)
  - running 状态: 显示 agent 管道进度
  - done 状态: 显示"查看报告"/"重新执行"按钮
- [ ] **P3-2b** 任务执行历史 — 最近 10 次执行记录，含 duration、agent 状态、结论快照

### P3-3: Report Timeline

- [ ] **P3-3a** ReportSection 升级为时间线视图
  - 按日期分组，每个节点: ticker + 标题 + 评分 + 置信度
  - 点击 → 回放 (调用 getReportReplay → ReportView)
  - 支持: 对比模式 (选两份报告 diff)
- [ ] **P3-3b** 后端新增 `GET /api/reports/compare?id1=X&id2=Y`
  - 返回两份报告的结构化差异 (评分变化、新增/删除风险、价格变动)

---

## Phase 4: 产品打磨

### P4-1: Command Palette 增强

- [ ] **P4-1a** 修改 `frontend/src/components/CommandPalette.tsx`
  - 支持: `/analyze AAPL` → 触发 executeAgent
  - 支持: `/compare AAPL vs TSLA` → 触发对比报告
  - 支持: `/agents` → 打开 Agent 控制面板
  - 支持: `/report AAPL` → 跳转最新 AAPL 报告回放

### P4-2: Dashboard ↔ Agent 联动

- [ ] **P4-2a** Agent 完成分析后自动刷新 Dashboard
  - executionStore 监听 run.status === 'done'
  - 如果 run.tickers 包含当前 dashboard symbol → 触发 useDashboardData refresh
- [ ] **P4-2b** Dashboard 异常检测 → 自动建议分析
  - 当价格跌幅 > 3% 时，SnapshotCard 显示 "⚠️ 异常波动，建议分析"

### P4-3: Agent 健康仪表盘

- [ ] **P4-3a** 后端 `/health` 增加 Agent 级别指标
  - 每个 agent: 成功率、平均延迟、最近错误、circuit_breaker 状态
- [ ] **P4-3b** 前端 AgentControlPanel 展示健康数据
  - 🟢 健康 (成功率 > 90%) / 🟡 降级 (50-90%) / 🔴 不可用 (< 50%)

### P4-4: 定时调度

- [ ] **P4-4a** 后端 — 扩展 scheduler_runner.py
  - 每日 08:00 UTC+8 自动刷新 watchlist 中所有 ticker 的报告
  - 新闻评分超阈值时自动触发 DeepSearch
- [ ] **P4-4b** 前端 — 订阅管理页面展示自动刷新状态

### P4-5: DRY 代码清理

- [ ] **P4-5a** 合并 `ChatInput.tsx` 和 `ChatList.tsx` 中重复的 `extractTickers()` → 抽到 `frontend/src/utils/tickers.ts`
- [ ] **P4-5b** Dashboard API 调用迁入 apiClient (当前 useDashboardData.ts 直接 fetch 绕过 axios)
- [ ] **P4-5c** 清理 `backend/api/streaming.py` 遗留代码 (ThinkingStream 等旧版 API 引用)

---

## 执行顺序总览

```
Phase 0 (基础设施) ← 必须先完成
  P0-1 (公共执行服务) → P0-1a → P0-1b → P0-1c → P0-1d → P0-1e
  P0-2 (report_id 回放) → P0-2a → P0-2b → P0-2c
  P0-3 (fallback 细分) → P0-3a → P0-3b → P0-3c → P0-3d → P0-3e
  P0-4 (限流统一) → P0-4a → P0-4b → P0-4c → P0-4d
  P0-5 (TaskSection 接后端) → P0-5a → P0-5b → P0-5c → P0-5d

Phase 1 (前端状态 + 体验) ← 依赖 Phase 0
  P1-1 (ExecutionStore) → P1-1a → P1-1b
  P1-2 (ExecutionBanner) → P1-2a → P1-2b
  P1-3 (Dashboard 可操作) → P1-3a → P1-3b → P1-3c
  P1-4 (StreamingResultPanel) → P1-4a → P1-4b
  P1-5 (Agent 控制面板) → P1-5a → P1-5b → P1-5c
  P1-6 (Watchlist 统一) → P1-6a → P1-6b → P1-6c

Phase 2 (TradingKey 改造) ← 依赖 P1-3
  P2-1 → P2-2 → P2-3 → P2-4 → P2-5 → P2-6 → P2-7 → P2-8

Phase 3 (工作台 Mission Control) ← 依赖 P0-5 + P1-1
  P3-1 → P3-2 → P3-3

Phase 4 (产品打磨) ← 可并行
  P4-1 → P4-2 → P4-3 → P4-4 → P4-5
```

---

## 关键 ADR 记录

### ADR-001: SSE > WebSocket
- **决策**: 继续用 SSE，不引入 WebSocket
- **原因**: 现有基础设施完备，Agent 执行是单向推送，不需要双向通信

### ADR-002: ExecutionStore 独立于 ChatStore
- **决策**: 新建独立 executionStore，不混入 useStore
- **原因**: 执行状态跨 Dashboard/Workbench/Chat 共享，不应耦合 Chat UI 状态

### ADR-003: /api/execute 复用公共执行服务
- **决策**: 先抽 execution_service.py，/chat/stream 和 /api/execute 都调它
- **原因**: 避免两套流式执行代码分叉（主人的建议 ✓）

### ADR-004: 限流采用全局桶 + 保底配额
- **决策**: 不只做权重，而是全局桶 + 每 agent MIN_TOKENS=8 保底
- **原因**: 权重方案在高峰时 deepsearch 仍会被饿死（主人的建议 ✓）

### ADR-005: fallback_reason 含 retryable + error_stage
- **决策**: 不只区分 reason，还加 retryable 和 error_stage
- **原因**: 前端需要知道"能不能重试"和"在哪一步挂的"才能真正可观测（主人的建议 ✓）
