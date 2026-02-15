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
- [x] **P0-3c** 修改 `backend/graph/nodes/execute_plan_stub.py` — 将 fallback_reason 写入 evidence_pool/artifacts
  - synthesize 节点可读取，render 模板可展示
- [x] **P0-3d** 修改 `backend/graph/report_builder.py` — report payload 增加 `agent_diagnostics` 字段
  - 每个 agent 的: status, fallback_reason, retryable, error_stage, duration_ms
- [x] **P0-3e** 前端 ReportView 组件展示降级原因
  - AgentStatusGrid 中: 🟢正常 / 🟡限流降级(可重试) / 🔴执行失败
  - Tooltip 显示 error_stage + duration_ms

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

- [x] **P0-5a** 修改 `frontend/src/components/workbench/TaskSection.tsx`
  - 删除 `useMemo` 硬编码任务生成逻辑 (line 48-113)
  - 新增 `useEffect` 调用 `GET /api/tasks/daily?session_id=...&news_count=N`
  - 从 dashboardStore 获取 newsItems.length 作为 news_count
- [x] **P0-5b** 修改 `backend/services/daily_tasks.py` — 增强任务生成
  - 每个任务增加 `execution_params` 字段: `{ query, tickers, output_mode, agents }`
  - 任务 ID 使用稳定的 hash (ticker + category + date) 而非递增数字
  - 增加 "重新分析" 类型任务 (针对 stale 报告)
- [x] **P0-5c** 修改 `backend/api/task_router.py` — 响应格式增加 execution_params
- [x] **P0-5d** 前端 TaskSection 任务点击 → 调用 `executeAgent(task.execution_params)` → 就地显示进度
  - 不再 `navigate('/chat')`
  - 使用 per-task runStates 跟踪状态
  - 完成后显示"查看报告"按钮 (跳转 `/chat?report_id=xxx`)

---

## Phase 1: 前端状态管理 + 体验升级

> 前置: Phase 0 全部完成
> 目标: 全局执行状态管理、Dashboard 可操作化、watchlist 统一
> 文件数: 6 新建 + 14 修改

### 核心契约（实现前必须遵守）

**1. runId 生命周期**
- 创建: `startExecution()` 生成 `crypto.randomUUID()` → 插入 `activeRuns[]`
- 存活: `activeRuns[]` 持有引用，页面切换不影响 run 存活
- 结束: `_completeRun / _failRun / cancelExecution` → 从 `activeRuns[]` 移除 → 插入 `recentRuns[]` (FIFO max 20)
- GC: `recentRuns` 超 20 条自动淘汰最旧

**2. 执行状态机**
```
idle → running → done | error | cancelled (终态，不可回退)
```

**3. 进度映射（纯事件驱动，禁止预测 agent 数量）**
- `supervisor_start` → 5%, 从 `event.agents[]` 初始化已知 agents
- `agent_start/done/error` → `10 + (已完成agent数/已知agent总数) * 70`
- 若运行中出现未列出的 `agent_start` → 动态追加
- 首个 `token` → `max(当前, 85)`
- `done` → 100
- **progress 只升不降（取 max）**

**4. 取消语义**
- ExecutionBanner [×] / StreamingResultPanel [取消] / `useExecuteAgent.cancel()` → `cancelExecution(runId)`
- **`useExecuteAgent` 组件卸载默认不取消** (`cancelOnUnmount` 默认 `false`)
- cancel 动作: `abort()` → status='cancelled' → 移入 recentRuns

**5. 批次验证检查点**

| 批次 | 验证 |
|------|------|
| 1 | `pnpm tsc --noEmit` 通过；executionStore 单测通过；dashboardStore watchlist 不影响 Dashboard |
| 2 | `pnpm tsc --noEmit` 通过；useExecuteAgent hook 单测通过 |
| 3 | `pnpm build` 通过；三个 view 正常渲染；卡片按钮不破坏布局 |
| 4 | `pytest backend/tests/ -x -q` 通过；policy_gate 测试覆盖 preferences 过滤 |
| 5 | Sidebar 和 Dashboard watchlist 同步；最终 `pnpm build` 通过 |

### 执行顺序

```
批次1: P1-1a (ExecutionStore + types) + P1-6b (dashboardStore watchlist 改造)
批次2: P1-1b (useExecuteAgent) + P1-4a (StreamingResultPanel) + P1-5a (AgentControlPanel)
批次3: P1-2 (ExecutionBanner) + P1-3 (卡片可操作化) + P1-4b (execution tab)
批次4: P1-5b (policy_gate) + P1-5c (前端附带 prefs)
批次5: P1-6c (Sidebar 统一)
```

### P1-1: ExecutionStore (全局执行状态)

- [ ] **P1-1a** 新建 `frontend/src/types/execution.ts` + `frontend/src/store/executionStore.ts`
  - 类型: `AgentRunInfo` (name, status, error, fallbackReason), `ExecutionRun` (runId, query, tickers, source, status, agentStatuses, progress, streamedContent, report, error, abortController), `StartExecutionParams` (query, tickers?, outputMode?, agents?, source, budget?)
  - **前端统一 camelCase**: `outputMode` (构造 `ExecuteRequest` 时映射为 `output_mode`)
  - 独立 Zustand store (不扩展 useStore)
  - `startExecution(params)` → 生成 runId → AbortController → `apiClient.executeAgent()` → SSE 回调按事件驱动契约更新
  - `cancelExecution(runId)` → abort + status='cancelled' + 移入 recentRuns
  - `getActiveRunForTicker(ticker)` → 查找 activeRuns
- [ ] **P1-1b** 新建 `frontend/src/hooks/useExecuteAgent.ts`
  - 封装 `executionStore.startExecution()`
  - 返回 `{ execute, isRunning, progress, currentStep, result, error, cancel, runId }`
  - **`cancelOnUnmount` 默认 `false`** — 切页面不杀任务
  - 支持 `onComplete` / `onError` 回调

### P1-2: 全局执行进度条 (ExecutionBanner)

- [ ] **P1-2a** 新建 `frontend/src/components/execution/ExecutionBanner.tsx`
  - 订阅 `executionStore.activeRuns` **和** `recentRuns`
  - 活跃 run → 显示 ticker + agent 管道图 (○ pending / ⟳ running / ✓ done / ✗ error) + 进度
  - 完成 run → **基于 `recentRuns` 的 `completedAt` 保留 3 秒**后隐藏（不依赖 activeRuns）
  - 展开详情 + [取消] 按钮
- [ ] **P1-2b** 修改 `frontend/src/components/layout/WorkspaceShell.tsx`
  - 在 Sidebar 之后、view 内容之前插入 ExecutionBanner（包裹 flex-col 容器）
  - 所有 view (chat / dashboard / workbench) 都可见

### P1-3: Dashboard 卡片可操作化

- [ ] **P1-3a** 修改 Dashboard SnapshotCard — 增加 action 按钮
  - 新增 props: `ticker?: string`
  - "深入分析" → `execute({ query, tickers, agents: ['price_agent','news_agent'], source: 'dashboard_snapshot' })`
  - "生成报告" → `execute({ query, tickers, outputMode: 'investment_report', source: 'dashboard_snapshot' })`
  - 执行中 spinner，完成变"查看结果"
- [ ] **P1-3b** 修改 Dashboard NewsFeed — 每条新闻增加"分析影响"按钮
  - 使用 `useExecuteAgent({ onComplete: (report) => useStore.getState().addMessage({...}) })`
  - 结果注入 MiniChat (via: 'mini')
- [ ] **P1-3c** 修改 Dashboard MacroCard — 占位区改为"宏观详解"按钮
- [ ] 同步修改 `DashboardWidgets.tsx` 传入 `ticker` prop

### P1-4: 流式结果展示面板 (StreamingResultPanel)

- [ ] **P1-4a** 新建 `frontend/src/components/execution/StreamingResultPanel.tsx`
  - Props: `runId: string | null`, `compact?: boolean`
  - running → Agent 状态条 + markdown 实时流 (react-markdown) + 进度条 + 取消
  - done → 有 report 渲染 `<ReportView>`，否则渲染最终 markdown
  - error → 错误信息 + 可重试按钮
- [ ] **P1-4b** 修改 RightPanel 系列组件
  - `right-panel/types.ts`: 扩展 `RightPanelTab` 增加 `'execution'`
  - `RightPanelHeader.tsx`: 新增 execution tab 按钮 (Sparkles + badge)
  - `RightPanel.tsx`: 新增 execution tab → `<StreamingResultPanel compact />`
  - **自动切换仅在新 run 启动时 (0→N) 触发**，用 `useRef` 防频繁抢焦点

### P1-5: Agent 控制面板

- [ ] **P1-5a** 新建 `frontend/src/components/settings/AgentControlPanel.tsx`
  - 类型: `AgentDepth = 'standard' | 'deep' | 'off'`, `AgentPreferences = { agents: Record<string, AgentDepth>, maxRounds: number, concurrentMode: boolean }`
  - 6 个 Agent 行: 名称 + 深度下拉 + 健康指示灯 (从 /health)
  - 预算滑块 (1-10) + 并发开关
  - localStorage 持久化 (`finsight-agent-preferences`)，**仅作输入，后端做最终校验**
  - 嵌入 `SettingsModal.tsx`
- [ ] **P1-5b** 修改 `backend/graph/nodes/policy_gate.py`
  - 读取 `ui_context.agent_preferences` / `agents_override` / `budget_override`
  - **后端白名单强校验**: agent 名 ∈ `REPORT_AGENT_CANDIDATES`、depth ∈ `{standard, deep, off}`、budget ∈ `[1, 10]`，不合法值回退默认
  - `agents_override` 优先级最高 → `depth='off'` 移除候选 → `depth='deep'` 增加 max_rounds → `budget_override` 覆盖
- [ ] **P1-5c** 前端执行时自动附带 agent_preferences
  - `api/client.ts`: `ExecuteRequest` 新增 `agent_preferences?` 字段
  - `backend/api/execution_router.py`: 写入 `ui_context["agent_preferences"]`
  - `executionStore.startExecution()`: 从 localStorage 读取 → 编码到 request

### P1-6: Watchlist 统一

- [ ] **P1-6b** 修改 `frontend/src/store/dashboardStore.ts`
  - watchlist 初始化为空数组 (移除 localStorage 加载)
  - 新增 `initWatchlist()`: 调 API 加载 watchlist
    - **in-flight 防重入**: `_isWatchlistLoading` 标记，React StrictMode 双 mount 不重复请求
  - 新增 `addWatchItemApi(ticker)` / `removeWatchItemApi(ticker)`: 先调 API → 再更新本地
  - 移除 watchlist localStorage 持久化
- [ ] **P1-6c** 修改 `frontend/src/components/Sidebar.tsx`
  - 删除本地 watchlist 状态，改从 `useDashboardStore` 读取
  - 保留本地 `quotes` state 获取价格 (每 60s 刷新)
  - `handleAddTicker` / `handleRemoveTicker` → 调用 dashboardStore API actions
  - `useEffect` 调 `initWatchlist()` 初始化

### 文件变更清单

| 文件 | 操作 | 批次 |
|------|------|------|
| `frontend/src/types/execution.ts` | 新建 | 1 |
| `frontend/src/store/executionStore.ts` | 新建 | 1 |
| `frontend/src/store/dashboardStore.ts` | 改 | 1 |
| `frontend/src/hooks/useExecuteAgent.ts` | 新建 | 2 |
| `frontend/src/components/execution/StreamingResultPanel.tsx` | 新建 | 2 |
| `frontend/src/components/settings/AgentControlPanel.tsx` | 新建 | 2 |
| `frontend/src/components/execution/ExecutionBanner.tsx` | 新建 | 3 |
| `frontend/src/components/layout/WorkspaceShell.tsx` | 改 | 3 |
| `frontend/src/components/cards/SnapshotCard.tsx` | 改 | 3 |
| `frontend/src/components/dashboard/NewsFeed.tsx` | 改 | 3 |
| `frontend/src/components/cards/MacroCard.tsx` | 改 | 3 |
| `frontend/src/components/dashboard/DashboardWidgets.tsx` | 改 | 3 |
| `frontend/src/components/RightPanel.tsx` | 改 | 3 |
| `frontend/src/components/right-panel/RightPanelHeader.tsx` | 改 | 3 |
| `frontend/src/components/right-panel/types.ts` | 改 | 3 |
| `frontend/src/components/SettingsModal.tsx` | 改 | 3 |
| `backend/graph/nodes/policy_gate.py` | 改 | 4 |
| `backend/api/execution_router.py` | 改 | 4 |
| `frontend/src/api/client.ts` | 改 | 4 |
| `frontend/src/components/Sidebar.tsx` | 改 | 5 |

---

## 开工前 Gate (P2+P3 阻塞项, 必须先完成)

> **更新 (2026-02-15)**: 以下 6 项必须在 Phase 2/3 开工前解决，否则后续开发反复返工。

- [x] **Gate-1** LangGraph Interrupt 实现 — 使用官方 `interrupt()` + `Command(resume=...)` + `astream_events`
  - 文件: `backend/graph/runner.py` 新增 `confirmation_gate` 节点
  - 条件触发: 仅 `state.require_confirmation=True` 时中断 (report 模式), brief 模式直接执行
  - 禁止: `raise GraphInterrupt` 或捕获 `GraphInterrupt` 异常
- [x] **Gate-2** GraphRunner 新增 `resume()` 方法
  - 文件: `backend/graph/runner.py` (~30行)
  - 返回 `AsyncIterator[StreamEvent]` (流语义, 使用 `astream_events`, 非 `ainvoke`)
  - `resume_graph_pipeline()` 必须通过 `runner.resume()` 调用, 不可绕过封装
- [x] **Gate-3** 冻结 DashboardData v2 契约
  - 新建: `backend/dashboard/contracts.py` (~40行)
  - 定义: valuation / financials / technicals / peers 字段结构
  - 前端先用 mock 数据开发, API 响应头携带 `X-Dashboard-Version: v2`
- [x] **Gate-4** P2-B 性能预算表
  - 文件: `backend/dashboard/data_service.py`
  - 每路请求定义: 超时 / 缓存 TTL / 并行上限 / fallback 策略
  - snapshot 5s/30s | valuation 5s/300s | financials 8s/3600s | technicals 5s/60s | peers 10s/3600s
  - 实现: `asyncio.wait_for()` + `asyncio.gather(return_exceptions=True)`
- [x] **Gate-5** 独立持仓存储
  - 新建: `backend/services/portfolio_store.py` (~80行)
  - 独立 SQLite: `data/portfolio.db` (不与 checkpointer 的 `data/checkpoints.db` 共库)
  - 表: `portfolio_positions` (session_id, ticker, shares, avg_cost) + `rebalance_suggestions`
- [x] **Gate-6** Rebalance 证据快照
  - 新增 `EvidenceSnapshot` schema: evidence_id / source / quote / report_id / captured_at
  - 生成建议时将证据深拷贝到 `RebalanceAction.evidence_snapshots`
  - 前端优先读快照, 仅 fallback 反查 report

---

## 硬约束 (全局生效, 贯穿 P2+P3)

> 以下 2 条约束在整个 Phase 2 + Phase 3 开发中始终有效。

**HC-1: Dashboard v2 可空子模块必须附 `fallback_reason`**

每个 v2 新增的可空字段返回 None 时, 必须附带 `xxx_fallback_reason` 字符串。
前端对 None 字段统一显示 `<DataFallback reason={fallbackReason} />`。

**HC-2: Rebalance 服务端强制 `suggestion_only` + `executable=false`**

无论客户端传入什么值, 服务端在返回前强制覆盖:
- `suggestion.mode = "suggestion_only"`
- `suggestion.executable = False`
- `suggestion.disclaimer = "本建议仅供参考，不构成投资建议。"`

Pydantic schema 用 `Literal[False]` 编译时约束 + router 运行时覆盖。

---

## Phase 2: 仪表盘 TradingKey 风格改造 (v2)

> **更新 (2026-02-15)**: 从简单卡片滚动 → TradingKey 风格 6-Tab 专业金融终端。
> **设计原则**: Tab1 "无报告也能用" — 基于实时数据自动生成基线评分; report 只是增强。
> **详细设计**: 见 `plans/snuggly-sleeping-mango.md` Phase 2 部分。
> **批次纪律**: 每批次完成后: `pnpm tsc --noEmit` + `pnpm build` + `pytest` + 单独 git commit。

### 批次 2-A: 前端基础层

#### P2-1: 主题 Token + ECharts 暗色适配

- [x] **P2-1a** 修改 `frontend/src/index.css` — `:root.dark` 更新 TradingKey 暗色变量
  - 背景层次: --fin-bg #12141a / --fin-card #1e2028 / --fin-panel #252830
  - 强调色: --fin-primary #fa8019(橙) / --fin-success #0cad92(绿) / --fin-danger #f74f5c(红)
- [x] **P2-1b** 新建 `frontend/src/styles/echarts-theme.ts` (~80行)
  - ECharts 暗色主题注册 + `getChartColors(isDark)` 工具函数
  - 修改 MarketChartCard / RevenueTrendCard 等使用 `getChartColors()`
- [x] **P2-1c** 修改 `frontend/tailwind.config.js` — 字体添加 PingFang SC / Microsoft YaHei

#### P2-2: Dashboard 布局重构

- [x] **P2-2a** 新建 `frontend/src/components/dashboard/StockHeader.tsx` (~150行)
  - 股票代码 + 中文名 + 实时价格 + 涨跌幅 + "加自选"/"快速分析"/"生成报告" 按钮
- [x] **P2-2b** 新建 `frontend/src/components/dashboard/MetricsBar.tsx` (~120行)
  - 7 列指标横条: market_cap / PE / PB / EPS / dividend_yield / 52week_range / beta
  - 数据源: `dashboardData.valuation` (P2-B1)
- [x] **P2-2c** 新建 `frontend/src/components/dashboard/DashboardTabs.tsx` (~100行)
  - 6 Tab: 综合分析 / 财务报表 / 技术面 / 新闻动态 / 深度研究 / 同行对比
  - URL 同步: `?tab=overview|financial|technical|news|research|peers`
- [x] **P2-2d** 修改 `frontend/src/pages/Dashboard.tsx` (~60行改动)
  - 新结构: Watchlist aside | StockHeader + MetricsBar + DashboardTabs
  - 移除 DashboardWidgets 直接引用

### 批次 2-B: 后端数据扩展 (与 2-A 可并行)

#### P2-B1: 估值指标 + 财务报表

- [x] **P2-B1a** 修改 `backend/dashboard/schemas.py` — 新增 `ValuationData` + `FinancialStatement` schema
- [x] **P2-B1b** 修改 `backend/dashboard/data_service.py` — 新增 `fetch_valuation()` + `fetch_financial_statements()`
  - 数据源: `yfinance.Ticker.info` + `quarterly_income_stmt / balance_sheet / cashflow`
  - 遵循 Gate-4 性能预算 (5s/8s 超时 + 300s/3600s 缓存)
- [x] **P2-B1c** 修改 `backend/api/dashboard_router.py` — 并行获取 valuation + financials
  - 返回 `data.valuation` + `data.financials` (含 fallback_reason, HC-1)
- [x] **P2-B1d** 修改 `frontend/src/types/dashboard.ts` — 新增 TypeScript 类型

#### P2-B2: 技术指标独立端点

- [x] **P2-B2a** 新建 `backend/tools/technical.py` (~100行)
  - 从 `technical_agent.py::_compute_indicators()` 提取公共计算逻辑
  - 新增: Stochastic / ADX / CCI / Williams %R / Bollinger Bands / S-R levels
- [x] **P2-B2b** 修改 `backend/dashboard/data_service.py` — 新增 `fetch_technical_indicators()`
- [x] **P2-B2c** 修改 `backend/dashboard/schemas.py` — 新增 `TechnicalData` schema
- [x] **P2-B2d** 修改 `backend/api/dashboard_router.py` — 并行获取 technicals

#### P2-B3: 同行对比数据

- [x] **P2-B3a** 新建 `backend/dashboard/peer_service.py` (~120行)
  - `resolve_peers(symbol, limit=6)` + `fetch_peer_comparison(symbol, peers)`
  - 缓存 1h TTL
- [x] **P2-B3b** 修改 `backend/dashboard/schemas.py` — 新增 `PeerData` schema
- [x] **P2-B3c** 修改 `backend/api/dashboard_router.py` — 并行获取 peers

### 批次 2-C: Tab 实现 (依赖 2-A + 部分依赖 2-B)

#### P2-3: Tab1 综合分析 ("无报告也能用")

- [x] **P2-3a** 新建 `frontend/src/hooks/useLatestReport.ts` (~40行)
  - 从 `apiClient.listReportIndex()` 获取最新报告, 缓存在 ref
- [x] **P2-3b** 新建 `OverviewTab.tsx` + `overview/ScoreRing.tsx` (~120行)
  - 基线评分: 基于 valuation + technicals 自动计算 (PE/RSI/Beta/趋势/新闻情绪)
  - 增强评分: 有 report 时使用 confidence_score 覆盖
- [x] **P2-3c** 新建 `overview/AnalystRatingCard.tsx` (~80行)
  - 无 report: 技术信号共识 (偏多/偏空/中性); 有 report: 完整评级
- [x] **P2-3d** 新建 `overview/DimensionRadar.tsx` (~90行)
  - ECharts 5维雷达: 基本面/技术面/新闻/深度研究/宏观
  - 无 report: 3 维有值, 2 维显示 "待分析"
- [x] **P2-3e** 新建 `overview/KeyInsightsCard.tsx` (~70行)
  - 无 report: 自动生成 3 条实时洞察 (PE对比/MA信号/新闻倾向)
- [x] **P2-3f** 新建 `overview/RiskMetricsCard.tsx` (~70行)
- [x] **P2-3g** 新建 `overview/HighlightsCard.tsx` (~60行)

#### P2-4: Tab2 财务报表 (依赖 P2-B1)

- [x] **P2-4a** 新建 `FinancialTab.tsx` + `financial/IncomeTable.tsx` (~120行)
- [x] **P2-4b** 新建 `financial/ProfitabilityChart.tsx` (~80行)
- [x] **P2-4c** 新建 `financial/ValuationGrid.tsx` (~70行)
- [x] **P2-4d** 新建 `financial/BalanceSheetSummary.tsx` (~80行)

#### P2-5: Tab3 技术面 (依赖 P2-B2)

- [x] **P2-5a** 新建 `TechnicalTab.tsx` + `technical/TechnicalSummaryCard.tsx` (~80行)
- [x] **P2-5b** 新建 `technical/MovingAverageTable.tsx` (~90行)
- [x] **P2-5c** 新建 `technical/OscillatorTable.tsx` (~90行)
- [x] **P2-5d** 新建 `technical/SupportResistanceChart.tsx` (~100行)
- [x] **P2-5e** 新建 `technical/BollingerVolumeCard.tsx` (~80行)

#### P2-6: Tab4 新闻动态 (无新后端依赖)

- [x] **P2-6a** 新建 `NewsTab.tsx` + `news/SentimentStatsBar.tsx` (~60行)
- [x] **P2-6b** 新建 `news/NewsFilterPills.tsx` (~40行)
- [x] **P2-6c** 改造 `NewsFeed.tsx` — 抽取 `NewsListView`, 接收筛选条件 prop
- [x] **P2-6d** 新建 `news/AiNewsSummaryCard.tsx` (~60行)

#### P2-7: Tab5 深度研究 (无新后端依赖)

- [x] **P2-7a** 新建 `ResearchTab.tsx` + `research/ResearchMetadata.tsx` (~60行)
- [x] **P2-7b** 新建 `research/ExecutiveSummary.tsx` (~50行)
- [x] **P2-7c** 新建 `research/CoreFindings.tsx` (~80行)
- [x] **P2-7d** 新建 `research/ConflictPanel.tsx` (~70行)
- [x] **P2-7e** 新建 `research/ReferenceList.tsx` (~50行)

#### P2-8: Tab6 同行对比 (依赖 P2-B3)

- [x] **P2-8a** 新建 `PeersTab.tsx` + `peers/PeerScoreGrid.tsx` (~80行)
- [x] **P2-8b** 新建 `peers/PeerComparisonTable.tsx` (~100行)
- [x] **P2-8c** 新建 `peers/ValuationBarChart.tsx` (~70行)
- [x] **P2-8d** 新建 `peers/RevenueGrowthChart.tsx` (~70行)
- [x] **P2-8e** 新建 `peers/AiPeerSummary.tsx` (~50行)

### 批次 2-D: 清理 + 整合

- [x] **P2-9** 旧 DashboardWidgets 垂直滚动代码清理
- [x] **P2-10** 响应式 + 移动端适配 (移动端 Tab 横向滚动 Pills / 平板 2 列 / 桌面 3 列)

---

## Phase 3: 工作台升级 — AI 任务执行中心 + 调仓建议

> **更新 (2026-02-15)**:
> 工作台从「被动信息展示面板」转型为「AI 驱动的任务执行中心」。
> - 砍掉 NewsSection（与 Dashboard 完全重复）
> - ReportSection 降级为折叠式 Timeline
> - 核心: AI 任务生成 → 一键执行 → LangGraph interrupt 追问 → 结果展示
> - **新增**: 调仓建议 RebalanceSuggestion (suggestion_only, 不执行交易)
> **详细设计**: 见 `plans/snuggly-sleeping-mango.md` Phase 3 部分。

### 批次 3-A: 清理 + 布局 (无外部依赖)

#### P3-1: 清理 + 布局重构

- [x] **P3-1a** 删除 `frontend/src/components/workbench/NewsSection.tsx` (292行)
  - 同步修改 index.ts / Workbench.tsx 移除引用
- [x] **P3-1b** 修改 `WorkspaceShell.tsx` — 移除 `useDashboardData(view==='workbench')` 和 newsItems props
- [x] **P3-1c** Workbench 布局重构: 主区域 (TaskSection + ReportTimeline) + 右侧面板 (ContextPanelShell)
- [x] **P3-1d** 新建 `frontend/src/components/workbench/PortfolioSummaryBar.tsx` (~80行)
  - 横条: 总市值 | 今日盈亏 | 持仓数 | 最大持仓
  - 先用 localStorage 数据, P3-5 后接入后端 API

### 批次 3-B: LangGraph Interrupt (核心全栈)

#### P3-2: LangGraph Interrupt 机制

> **实现方式**: 使用官方 `interrupt()` 函数 + `Command(resume=...)` + `astream_events` 事件流。
> 参见 Gate-1 / Gate-2。

- [x] **P3-2a** 修改 `backend/graph/runner.py` — 添加 `confirmation_gate` 条件节点
  - 触发条件: `state.require_confirmation=True` (仅 report 模式)
  - brief/快速分析 → 不中断, 直接执行
  - 修改 `backend/graph/state.py` 新增字段
- [x] **P3-2b** 验证 Checkpointer 为 sqlite 持久化
- [x] **P3-2c** 新增 `POST /api/execute/resume` — 接受 `thread_id + resume_value`
  - `execution_service.resume_graph_pipeline()` 调用 `runner.resume()` (astream_events 流语义)
- [x] **P3-2d** 新建 `frontend/src/components/execution/InterruptCard.tsx` (~120行)
- [x] **P3-2e** 修改 `TaskSection.tsx` 状态机: `idle → running → done|error|interrupted`
- [x] **P3-2f** SSE 事件扩展: 后端检测 `on_interrupt` 事件 + 前端 `onInterrupt` 回调

### 批次 3-C: AI 任务生成 (依赖 3-B)

#### P3-3: AI 任务生成 (双层: 规则+LLM)

- [x] **P3-3a** 新建 `backend/services/task_generator.py` (~200行)
  - 规则层 (确定性): 价格异动 / 财报日历 / 研报时效 / 持仓集中度
  - LLM 层 (可选, `use_llm_enhancement`): 持仓×新闻交叉分析, 1h 缓存
- [x] **P3-3b** 新建 `backend/api/task_schemas.py` (~30行) — `AITask` schema
- [x] **P3-3c** 修改 `backend/api/task_router.py` — 调用 TaskGenerator, 新增 portfolio 参数
- [x] **P3-3d** 前端 TaskSection 适配: 分类图标 + reason + priority
- [x] **P3-3e** 测试 (规则层覆盖 + LLM mock)

### 批次 3-D: Report Timeline + 持仓

#### P3-4: Report Timeline

- [x] **P3-4a** 修改 `ReportSection.tsx` → 时间线视图 (按日期分组, 默认折叠)
- [x] **P3-4b** 新增 `GET /api/reports/compare?id1=X&id2=Y`
- [x] **P3-4c** 对比模式 UI: 双栏对比 + 差异高亮

#### P3-5: 持仓数据接入

- [x] **P3-5a** 新建 `backend/api/portfolio_router.py` (~120行)
  - `GET /api/portfolio/summary` + `POST/PUT/DELETE /api/portfolio/positions`
  - 存储: 独立 `data/portfolio.db` (Gate-5)
- [x] **P3-5b** 新建 `frontend/src/hooks/usePortfolioData.ts` (~50行)
- [x] **P3-5c** PortfolioSummaryBar 接入 usePortfolioData

### 批次 3-E: 调仓建议 RebalanceSuggestion (依赖 3-D)

> **定位**: suggestion_only — 只生成建议, 不执行交易。强制 `executable: false` (HC-2)。

#### P3-6: 调仓建议

**后端**:

- [x] **P3-6a** 新建 `backend/api/rebalance_schemas.py` (~80行)
  - `RebalanceAction` / `RebalanceSuggestion` (mode=Literal["suggestion_only"], executable=Literal[False])
  - `GenerateRebalanceRequest` / `PatchSuggestionRequest`
- [x] **P3-6b** 新建 `backend/services/rebalance_engine.py` (~300行) — 四步流水线
  - Step 1: 持仓诊断 | Step 2: 候选操作 (规则+可选LLM) | Step 3: 约束求解 | Step 4: 解释生成
  - 证据绑定: evidence_snapshots 深拷贝 (Gate-6)
- [x] **P3-6c** 新建 `backend/api/rebalance_router.py` (~120行) — factory+DI
  - `POST generate` / `GET list` / `PATCH status` (HC-2 强制覆盖)
- [x] **P3-6d** 注册 `backend/api/main.py` — portfolio_router + rebalance_router

**前端**:

- [x] **P3-6e** 新建 `frontend/src/hooks/useRebalanceSuggestion.ts` (~80行)
- [x] **P3-6f** 修改 `frontend/src/api/client.ts` — 新增 rebalance API 方法
- [x] **P3-6g** 修改 `frontend/src/types/dashboard.ts` — 新增 Rebalance 类型
- [x] **P3-6h** 新建 `RebalanceEntryCard.tsx` (~100行) — 入口卡片
- [x] **P3-6i** 新建 `rebalance/RebalanceParamPanel.tsx` (~90行) — 参数面板
- [x] **P3-6j** 新建 `rebalance/RebalanceResultView.tsx` (~50行) — 结果容器
- [x] **P3-6k** 新建 `rebalance/SuggestionSummaryCard.tsx` (~60行)
- [x] **P3-6l** 新建 `rebalance/ActionList.tsx` (~120行)
- [x] **P3-6m** 新建 `rebalance/EvidenceLinks.tsx` (~50行) — 快照优先
- [x] **P3-6n** 新建 `rebalance/DisclaimerBanner.tsx` (~30行)
- [x] **P3-6o** 新建 `rebalance/ActionButtons.tsx` (~50行) — 发送到对话/忽略/重新生成

**测试**:

- [x] **P3-6p** 新建 `backend/tests/test_rebalance_engine.py` (~150行)

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

## 执行顺序总览（旧版，含记忆模块版请见 Phase M 章节末尾）

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

Phase 3 (工作台 AI 任务执行中心) ← 依赖 P0-5 + P1-1
  P3-1 (清理+布局) → P3-2 (LangGraph interrupt) → P3-3 (AI 任务生成) → P3-4 (Timeline) → P3-5 (持仓)

Phase 4 (产品打磨) ← 可并行
  P4-1 → P4-2 → P4-3 → P4-4 → P4-5
```

---

## Phase M: 记忆/上下文管理模块（LangGraph 原生方案）

> **为什么需要**: 当前对话全堆在窗口里，LLM 每次执行都是无上下文的单轮对话。
> **技术选型 (2026-02-15)**: 全部使用 LangGraph 原生能力，不造轮子。
>
> **现状审计 (2026-02-15)**:
>
> | 组件 | 状态 | 说明 |
> |------|------|------|
> | `checkpointer.py` (SQLite/Postgres/Memory) | ✅ 已实现 | 支持三种后端，`runner.py` 已 `compile(checkpointer=...)` |
> | `GraphState.messages` + `add_messages` reducer | ✅ 已定义 | 同一 thread_id 下 messages **自动累积追加** |
> | `runner.ainvoke()` 传 `thread_id` | ✅ 已传 | `config={"configurable": {"thread_id": thread_id}}` |
> | `trim_messages()` (langchain-core 1.2.7) | ✅ 已装 | **但从未使用** — messages 无限增长无裁剪 |
> | `tiktoken==0.12.0` | ✅ 已装 | **但从未 import** |
> | pipeline 节点读取 messages 历史 | 🔴 未实现 | planner/synthesize 完全不看 messages，只读 query |
> | graph 出口追加 AIMessage | 🔴 未实现 | AI 回复未写回 messages，checkpointer 只存 HumanMessage |
> | `conversation/context.py` (ContextManager) | 🟡 遗留 | 仅 main.py 用于指代消解，应迁移到 graph 层 |
> | `services/memory.py` (MemoryService) | 🟡 孤立 | 仅服务 user_router API，graph pipeline 不读取 |
> | `LangGraph Store API` | ⏳ PM1-0 升级后可用 | 最新 langgraph 已提供，升级后用于替代 MemoryService |
>
> **三层漏斗策略**:
> ```
> ┌──────────────────────────────────────────────────────┐
> │              Context Window 预算分配                  │
> │                                                      │
> │  System Prompt              ~2k tokens (固定)        │
> │  用户画像 (MemoryService)    ~200 tokens (长期记忆)  │
> │  历史摘要 (压缩后)           ~500 tokens (老对话)    │
> │  最近 6 轮原文               ~3-6k tokens (保真)     │
> │  当前 query                  ~100-500 tokens         │
> │  Agent 证据 (动态)           ~10-30k tokens (核心)   │
> │  输出预算                    8192 tokens             │
> │  安全余量 10%                                        │
> │                                                      │
> │  总计: ~50k tokens / 128k window (~40% 使用率)       │
> └──────────────────────────────────────────────────────┘
> ```
>
> **压缩触发**:
> - messages ≤ 12 条 (6 轮) → 全量保留，仅 `trim_messages()` 兜底
> - messages > 12 条 → 触发 `summarize_history` 节点压缩老消息
> - 跨会话 (新 thread) → 从 MemoryService 加载用户画像注入 system prompt

### PM0: LangGraph 原生记忆接入（~80 行改动）

> **前置条件**: 无，可立即开始。与 Phase 0/1 并行。
> **为什么最高优先**: checkpointer 已在工作，只差节点接线。
> **原则**: 用 LangGraph 自带能力，不手写持久化/裁剪逻辑。
> **执行状态**: ✅ 全部完成 (2026-02-15)

- [x] **PM0-1a** 验证 checkpointer 实际工作
  - 文件: `backend/tests/test_checkpointer_messages.py`
  - 确认: add_messages reducer 正确累积 HumanMessage，thread_id 隔离正确
  - 测试: 3 个测试全部通过 — 累积、隔离、内容验证
- [x] **PM0-1b** graph 出口节点追加 AIMessage
  - 文件: `backend/graph/nodes/render_stub.py`
  - 新增: `_build_ai_reply_message()` 函数，从 draft_markdown 提取摘要写入 AIMessage
  - 所有 3 个返回路径均追加 AIMessage — checkpointer 内 messages 交替包含 Human/AI
  - 测试: `backend/tests/test_ai_message_persistence.py` — 3 个测试全部通过
- [x] **PM0-1c** planner 节点注入对话历史
  - 文件: `backend/graph/planner_prompt.py`
  - 新增: `_format_conversation_history()` 函数，从 state["messages"] 提取最近 12 条消息
  - 格式化为 `<conversation_history>` XML 块注入 prompt，constraints 增加第 7 条
  - 测试: 15 个 planner 回归测试全部通过
- [x] **PM0-1d** synthesize 节点注入对话历史
  - 文件: `backend/graph/nodes/synthesize.py`
  - 新增: `_format_conversation_history_for_synth()` 函数，注入到 narrative 和 llm mode prompt
  - 测试: 7 个 synthesize 回归测试全部通过
- [x] **PM0-2a** 加入 `trim_messages()` 安全兜底
  - 新建: `backend/graph/nodes/trim_conversation_history.py`
  - 使用 `RemoveMessage` (LangGraph 原生) + `trim_messages()` + `tiktoken` token 计数
  - 在 graph 中插入 `build_initial_state → trim_history → ...`
  - 默认预算: 8000 tokens (env: `LANGGRAPH_MAX_HISTORY_TOKENS`)
  - 测试: `backend/tests/test_trim_conversation_history.py` — 5 个测试全部通过
- [x] **PM0-2b** 添加 `summarize_history` 条件节点
  - 新建: `backend/graph/nodes/summarize_history.py`
  - 使用 `RemoveMessage` 删除旧消息 + `SystemMessage` 存储确定性摘要
  - 阈值: 12 条消息 (env: `LANGGRAPH_SUMMARIZE_THRESHOLD`)，保留最近 6 条
  - 在 graph 中插入: `trim_history → summarize_history → normalize_ui_context`
  - 测试: `backend/tests/test_summarize_history.py` — 6 个测试全部通过
- [x] **PM0-3** 清理硬编码模型名 (安全保守策略)
  - `cli_app.py`: 3 处硬编码 "gemini-2.5-flash" → 改为空字符串，由 llm_config 统一管理
  - `langchain_agent.py`: 2 处硬编码 "gemini-2.5-flash" → 改为空字符串
  - `conversation/` 目录: 标记为 deprecated 但**未删除** (api/main.py/streaming.py 仍在使用)
  - `llm_config.py` fallback defaults: 保留不动 (这是配置系统本身)
  - 验收: 69 个核心测试全部通过，22 个预先存在的环境问题失败 (sqlite 模块缺失 + auth 配置)

### PM1: LangGraph Store + 长期记忆

> **前置条件**: PM0 完成 + langgraph 升级至最新版
> **技术选型**: 使用 LangGraph Store API (跨 thread 长期记忆)，替代 MemoryService (JSON 文件)
> **长期记忆内容**: 用户画像 + 持仓 + 分析历史 + 偏好

- [ ] **PM1-0** 升级 langgraph/langchain 至最新稳定版
  - `pip install --upgrade langgraph langgraph-checkpoint langgraph-checkpoint-sqlite langchain-core`
  - 更新 `requirements.txt`
  - 验证: `from langgraph.store.memory import InMemoryStore` 可用
  - 验证: 现有 graph pipeline 运行正常 (回归测试)
- [ ] **PM1-1a** 配置 LangGraph Store
  - 新建: `backend/graph/store.py` (类似 checkpointer.py 的 store 管理)
  - `graph = builder.compile(checkpointer=checkpointer, store=store)`
  - Store 数据分 namespace: `("user", user_id, "profile")`, `("user", user_id, "portfolio")`, `("user", user_id, "analyses")`
  - 验收: graph 节点可通过 `store` 参数读写数据
- [ ] **PM1-1b** 迁移 MemoryService → Store
  - 将 `UserProfile` 数据写入 Store: risk_tolerance, investment_style, watchlist
  - **新增持仓数据**: `portfolioPositions` (ticker → shares/avg_cost) 写入 Store namespace `("user", user_id, "portfolio")`
  - 前端 portfolio 变更时通过 API → Store 同步
  - 保留 `user_router.py` API 接口，后端改为读写 Store
  - 验收: `/api/user/profile` 和 `/api/user/watchlist` 仍正常工作
- [ ] **PM1-2a** build_initial_state 从 Store 注入用户画像 + 持仓
  - 文件: `backend/graph/nodes/build_initial_state.py`
  - 从 Store 读取用户画像 + 当前持仓
  - 注入到 `state["ui_context"]["user_profile"]` 和 `state["ui_context"]["portfolio"]`
  - 验收: planner/synthesize 能看到用户持仓和风险偏好
- [ ] **PM1-2b** planner/synthesize prompt 消费用户画像 + 持仓
  - 文件: `planner_prompt.py`, `synthesize.py`
  - 在 prompt 中加入:
    ```xml
    <user_profile>
      风险偏好: 激进型 | 关注列表: AAPL, TSLA, NVDA
      持仓: AAPL 100股@$150, TSLA 50股@$220
      投资风格: 成长型
    </user_profile>
    ```
  - 验收: 分析报告能说"考虑到您持有 AAPL 100 股..."
- [ ] **PM1-3a** 对话摘要生成 — graph 出口自动生成
  - 文件: `backend/graph/nodes/finalize_response.py` (PM0-1b 建的)
  - 每次分析完成后，用 LLM 生成结构化摘要:
    ```json
    {"ticker": "AAPL", "sentiment": "bullish", "key_point": "...", "date": "2026-02-15"}
    ```
  - 写入 Store namespace `("user", user_id, "analyses")`
  - 验收: Store 中能查到历史分析记录
- [ ] **PM1-3b** 新会话自动加载上次焦点
  - 文件: `build_initial_state.py`
  - 如果 messages 为空 (新 thread)，从 Store 搜索最近 5 次分析摘要
  - 注入为 SystemMessage: "用户最近分析: AAPL(看涨,2/14), TSLA(中性,2/13)"
  - 验收: 新会话中 LLM 知道用户历史
- [ ] **PM1-4** Checkpointer 后端确认为 SQLite + Store 持久化
  - 确保 `LANGGRAPH_CHECKPOINTER_BACKEND=sqlite`
  - Store 配置持久化后端 (如支持 SQLite/Postgres)
  - 验收: 重启后端后，对话记忆 + 用户画像 + 持仓均不丢失
- [ ] **PM1-5** 删除旧 MemoryService
  - 迁移完成后删除 `backend/services/memory.py`
  - 删除 `data/memory/` JSON 文件存储
  - 更新所有 import
  - 验收: 无 memory.py 引用残留

### PM2: 智能记忆（进阶）

> **前置条件**: PM1 完成 + Phase 2 仪表盘改造后启动
> **为什么低优先**: 属于产品差异化功能，基础记忆完善后再做。

- [ ] **PM2-1** 向量化长期记忆 — 历史对话/报告摘要写入向量数据库
  - 使用 Chroma/Qdrant 存储历史对话 embedding
  - 用户问"上次分析 TSLA 说了什么"时可检索
  - 与 DASHBOARD_DEVELOPMENT_GUIDE 中 RAG 数据入库策略对齐
- [ ] **PM2-2** 分析偏好学习 — 自动提取用户行为偏好
  - 从操作历史中提取: 偏好哪些 agent、关注技术面 vs 基本面
  - 持久化到 MemoryService
  - 验收: 分析自动侧重用户关注的维度
- [ ] **PM2-3** 跨会话上下文传递 — 新会话自动加载上次焦点
  - 新会话自动加载: 上次聚焦的 ticker、关键结论、未完成任务
  - 验收: 新开对话窗口自动提示"上次在分析 AAPL"
- [ ] **PM2-4** 上下文窗口自适应 — 根据请求类型动态调整 history 长度
  - 简单问答: 只要 3 轮 history
  - 深度分析: 需要 10+ 轮 history
  - 优化 token 消耗，按任务类型动态裁剪

---

## 执行顺序总览（含 Gate + 记忆模块 + 调仓建议）

```
Phase 0 (基础设施) ← ✅ 全部完成
  P0-1 ~ P0-5 ✅

Phase M0 (LangGraph 原生记忆) ← ✅ 全部完成
  PM0-1a → PM0-1b → PM0-1c/1d → PM0-2a → PM0-2b → PM0-3 ✅

Phase 1 (前端状态 + 体验) ← 依赖 Phase 0
  P1-1 ~ P1-6

═══ Gate (P2/P3 开工前阻塞项) ═══
  Gate-1 (LangGraph interrupt) → Gate-2 (resume 方法)
  Gate-3 (v2 契约) → Gate-4 (性能预算)
  Gate-5 (持仓存储) → Gate-6 (证据快照)

Phase 2 (TradingKey 改造) ← 依赖 P1-3 + Gate-3/4
  批次 2-A (前端): P2-1 → P2-2      ┐
  批次 2-B (后端): P2-B1/B2/B3       ├ 可并行
  批次 2-C (Tab): P2-3~P2-8 (依赖 2-A + 2-B)
  批次 2-D (清理): P2-9 → P2-10

Phase M1 (LangGraph Store + 长期记忆) ← 依赖 PM0
  PM1-0 → PM1-1a/1b → PM1-2a/2b → PM1-3a/3b → PM1-4 → PM1-5

Phase 3 (工作台 + 调仓建议) ← 依赖 P0-5 + P1-1 + Gate-1/2/5/6
  批次 3-A (清理+布局): P3-1
  批次 3-B (Interrupt): P3-2
  批次 3-C (AI 任务): P3-3
  批次 3-D (Report+持仓): P3-4 + P3-5
  批次 3-E (调仓建议): P3-6

Phase 4 (产品打磨) ← 可并行
  P4-1 → P4-2 → P4-3 → P4-4 → P4-5

Phase M2 (智能记忆) ← 依赖 PM1 + Phase 2
  PM2-1 → PM2-2 → PM2-3 → PM2-4
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

### ADR-006: 记忆模块全部使用 LangGraph 原生能力
- **决策**: Checkpointer + trim_messages + Store，不手写持久化/裁剪
- **原因**: 项目已用 LangGraph，checkpointer 已配好只差接线；langchain-core 自带 trim_messages；最新 langgraph 提供 Store API
- **现状审计 (2026-02-15)**: checkpointer 已工作但 AI 回复未写回 messages、pipeline 节点不读 messages、无 trim

### ADR-007: 升级 langgraph/langchain 至最新版
- **决策**: 全量升级 langgraph + langchain-core + langchain 生态至最新稳定版
- **原因**: 解锁 LangGraph Store API (跨 thread 长期记忆)，避免在旧版上造轮子
- **影响**: PM1 可用 Store 替代 MemoryService (JSON文件)，更统一

### ADR-008: MemoryService 迁移到 LangGraph Store
- **决策**: 将 MemoryService (用户画像 JSON 文件) 迁移到 LangGraph Store
- **原因**: Store 与 graph pipeline 天然集成，节点可直接 store.search/put；消除孤立系统
- **前提**: langgraph 升级完成，Store API 可用

### ADR-009: LangGraph Interrupt 使用官方 interrupt() 函数
- **决策**: 使用 `interrupt()` + `Command(resume=...)` + `astream_events`, 不用 `raise GraphInterrupt`
- **原因**: 官方 API 更稳定; 异常捕获方式在 astream_events 中行为不确定; resume 需要 Command 语义

### ADR-010: 条件性 confirmation_gate 替代全局 interrupt_before
- **决策**: 新增 `confirmation_gate` 条件节点, 非全局 `interrupt_before=["execute_plan"]`
- **原因**: 全局 interrupt 会阻塞所有执行 (包括快速分析 brief 模式), 条件节点可按 output_mode 决定

### ADR-011: 持仓存储独立于 Checkpointer
- **决策**: 使用独立 SQLite `data/portfolio.db`, 不与 checkpointer 共库
- **原因**: 避免锁冲突和迁移耦合; 持仓数据生命周期与 graph checkpoint 不同

### ADR-012: Rebalance 证据快照优先
- **决策**: 生成建议时深拷贝 evidence 到 `evidence_snapshots`, 前端读快照优先
- **原因**: 报告可能被删除/更新, 反查不稳定; 快照解耦保证证据可追溯

### ADR-013: Rebalance 强制 suggestion_only
- **决策**: 服务端双重保护 — Pydantic `Literal[False]` + router 运行时覆盖 `executable=False`
- **原因**: 法律合规要求, 不执行任何实际交易; 客户端不可绕过

### ADR-014: Dashboard v2 可空字段附带 fallback_reason
- **决策**: 每个 v2 新增可空字段返回 None 时必须附带 fallback_reason
- **原因**: 前端需要区分 "数据未加载" vs "获取失败(超时/错误)" 以提供精确降级提示

### ADR-015: LLM 调用可选化 (use_llm_enhancement)
- **决策**: 调仓引擎和任务生成器的 LLM 层默认关闭, 用户可选开启
- **原因**: 避免工作台加载时 3+ LLM 调用导致高成本和高延迟; 模板层可覆盖 80% 场景
