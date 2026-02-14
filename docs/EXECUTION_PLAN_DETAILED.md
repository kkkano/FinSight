# FinSight 精细化执行计划 — 从当前状态到工作台完成

> 生成时间: 2026-02-13
> 当前分支: `feat/v1.1.0-sprint2`
> 目标: 完成 Phase 0 剩余 → Phase 1 → Phase 2 → Phase 3 → Phase 4 (相关项)

---

## 设计参考来源

### 仪表盘 — TradingKey 风格

**参考原型**: 项目内已有 4 份 HTML 静态原型，位于 `docs/prototype/` 目录：

| 文件 | 说明 | 状态 |
|------|------|------|
| `docs/prototype/dashboard_tradingkey_style.html` | TradingKey 暗色风格初版 — 单页综合分析 | 初版，已迭代 |
| `docs/prototype/dashboard_tradingkey_style_v2.html` | **TradingKey V2 (主参考)** — 完整 6-Tab 布局、Stock Header、Metrics Bar、综合评分环、雷达图、技术面表格、新闻情绪面板 | ✅ 主设计稿 |
| `docs/prototype/dashboard_v2.html` | 早期 Dashboard V2 探索 | 已废弃 |
| `docs/prototype/dashboard_v3.html` | Dashboard V3 — 6-Tab 结构验证 | 结构参考 |
| `docs/dashboard_v2_preview.html` | Dashboard V2 预览 | 已废弃 |

**核心设计语言** (提取自 `dashboard_tradingkey_style_v2.html`):

```css
/* TradingKey Dark Palette */
--w1: #181a1f;   /* 页面底色 */
--w2: #1e2025;   /* 卡片/面板 */
--w3: #24282f;   /* 悬浮/弹出层 */
--w4: #2b3139;   /* 边框/分隔 */
--w5: #363d47;   /* 禁用/占位 */
--o1: #fa8019;   /* 主橙色 (Tab 下划线、按钮) */
--profit: #0cad92;  /* 涨/利好 */
--loss: #f74f5c;    /* 跌/利空 */
--r: 10px;          /* 圆角 */
--shadow: 0 4px 20px 2px rgba(0,0,0,.4);
```

**设计特征**:
- 暗色系为主，高对比度文本
- 橙色 (#fa8019) 作为唯一强调色 (Tab 下划线、主按钮、高亮)
- 绿/红 仅用于涨跌和利好/利空
- 卡片使用 10px 圆角 + 深色阴影
- 7 列 Metrics Bar (市值/PE/PB/EPS/股息率/52周/Beta)
- 6 Tab 切换 (橙色下划线指示器)
- Stock Header: Logo + 名称 + 实时价格 (大字号 38px) + 涨跌变化

### 工作台 — Mission Control 风格

**参考原型**:

| 文件 | 说明 |
|------|------|
| `docs/workbench_v2_preview.html` | **Workbench V2 预览 (主参考)** — 深蓝暗色系、任务卡片、报告时间线、右侧面板 |

**设计特征**:
- 更深的暗蓝色调 (`#080b12` 底色, `#111a2a` 卡片)
- 蓝色主色 (`#69a7ff` primary) 而非橙色
- 任务卡片带状态指示 (绿/黄/红)
- 右侧面板用于实时执行结果展示
- 上下两栏: 任务队列 + 报告/新闻

---

## 已完成项概览

| 编号 | 名称 | 状态 |
|------|------|------|
| P0-1 | 公共执行服务 (execution_service + execution_router) | ✅ 全部完成 |
| P0-2 | report_id 回放闭环 | ✅ 全部完成 |
| P0-3a/b/d | fallback_reason 结构化 (agent_adapter + report_builder) | ✅ 已完成 |
| P0-3c | execute_plan_stub 写入 evidence_pool | ❌ 未完成 |
| P0-3e | 前端 ReportView 降级展示 | ❌ 未完成 |
| P0-4 | 限流策略统一 (分层令牌桶 + per-agent 配额) | ✅ 全部完成 |

---

## 依赖关系图

```
P1-1a executionStore ──┬──→ P1-1b useExecuteAgent ──┬──→ P0-5d TaskSection 执行触发
                       │                             ├──→ P1-3 Dashboard 可操作化
                       │                             └──→ P1-5c agent_preferences 附带
                       ├──→ P1-2 ExecutionBanner
                       ├──→ P1-4 StreamingResultPanel
                       └──→ P3 Workbench (全部)

P0-5b/c (后端任务增强) ──→ P0-5a (前端 API 调用) ──→ P0-5d (执行触发)

P0-3c (evidence_pool) ──→ P0-3e (前端展示)

P1-3 (Dashboard 可操作化) ──→ P2 (TradingKey 改造)

P0-5 + P1-1 + P1-4 ──→ P3 (Workbench Mission Control)

P1-5/P1-6 ──→ 独立，可并行

P2 + P3 ──→ P4 (产品打磨)
```

---

## 第 1 阶段: 核心状态基础设施 ⭐ 关键路径

> 这是整个计划的 **最关键阶段**。P1-1 (ExecutionStore) 是后续 80% 任务的前置依赖。
> 同时并行推进 P0 后端剩余项，最大化效率。

### 1.1 创建 ExecutionStore (P1-1a) — 最高优先级

**文件**: `frontend/src/store/executionStore.ts` (新建)

- [ ] 1.1.1 定义 `ExecutionRun` 类型接口
  - `runId: string` (uuid)
  - `query: string`
  - `tickers: string[]`
  - `source: 'chat' | 'dashboard' | 'workbench' | 'command_palette'`
  - `status: 'pending' | 'running' | 'done' | 'error' | 'cancelled'`
  - `agentStatuses: Record<string, AgentRunStatus>` (per-agent: idle/running/done/fallback)
  - `progress: number` (0-100)
  - `report: ReportData | null`
  - `fallbackReasons: Record<string, FallbackInfo>`
  - `startedAt: number`
  - `completedAt: number | null`
  - `error: string | null`
- [ ] 1.1.2 定义 `AgentRunStatus` 类型
  - `status: 'idle' | 'running' | 'done' | 'fallback'`
  - `fallbackReason?: string`
  - `retryable?: boolean`
  - `errorStage?: string`
  - `durationMs?: number`
- [ ] 1.1.3 创建 Zustand store `useExecutionStore`
  - `activeRuns: ExecutionRun[]`
  - `recentRuns: ExecutionRun[]` (最多保留 20 条)
  - `startExecution(params) → runId` — 创建 run，调用 `apiClient.executeAgent()`
  - `updateRunFromSSE(runId, event)` — 解析 SSE 事件，更新 agentStatuses/progress/report
  - `cancelExecution(runId)` — AbortController.abort()
  - `getActiveRunForTicker(ticker) → ExecutionRun | null`
  - `clearRecentRuns()`
- [ ] 1.1.4 实现 SSE 事件解析逻辑
  - `event: agent_status` → 更新 `agentStatuses[agentName]`
  - `event: progress` → 更新 `progress` 百分比
  - `event: chunk` → 累积 markdown 内容
  - `event: report` → 设置 `report` 字段，status → 'done'
  - `event: error` → 设置 `error` 字段，status → 'error'
  - `event: done` → status → 'done'，记录 `completedAt`
- [ ] 1.1.5 实现 `moveToRecent()` — 完成/错误的 run 从 activeRuns 移到 recentRuns
- [ ] 1.1.6 单元测试: store 状态流转 (pending → running → done/error)

### 1.2 创建 useExecuteAgent Hook (P1-1b)

**文件**: `frontend/src/hooks/useExecuteAgent.ts` (新建)

- [ ] 1.2.1 定义 hook 接口
  ```typescript
  function useExecuteAgent(): {
    execute: (params: ExecuteParams) => Promise<string>  // 返回 runId
    isRunning: boolean
    progress: number
    result: ExecutionRun | null
    error: string | null
    cancel: () => void
  }
  ```
- [ ] 1.2.2 内部实现: 调用 `useExecutionStore.startExecution()`
- [ ] 1.2.3 支持 AbortController — `cancel()` 调用 `abortController.abort()`
- [ ] 1.2.4 支持多并发执行 (每次 execute 返回独立 runId)
- [ ] 1.2.5 cleanup: 组件卸载时自动取消活跃执行

### 1.3 后端任务服务增强 (P0-5b) — 与 1.1 并行

**文件**: `backend/services/daily_tasks.py` (修改)

- [ ] 1.3.1 每个任务增加 `execution_params` 字段
  ```python
  execution_params = {
      "query": f"分析 {ticker} 的最新投资机会",
      "tickers": [ticker],
      "output_mode": "investment_report",
      "agents": ["price_agent", "news_agent", "fundamental_agent", "technical_agent"]
  }
  ```
- [ ] 1.3.2 任务 ID 改为稳定 hash: `hashlib.md5(f"{ticker}:{category}:{date}".encode()).hexdigest()[:12]`
- [ ] 1.3.3 新增 "重新分析" 类型任务 — 查找 stale 报告 (超过 3 天未更新的 watchlist ticker)
- [ ] 1.3.4 新增 "深度研究" 类型任务 — 针对新闻量突增的 ticker
- [ ] 1.3.5 单元测试: execution_params 格式验证 + hash 稳定性

### 1.4 后端任务路由增强 (P0-5c) — 依赖 1.3

**文件**: `backend/api/task_router.py` (修改)

- [ ] 1.4.1 `GET /api/tasks/daily` 响应体增加 `execution_params` 字段
- [ ] 1.4.2 确保 `execution_params` 不泄露内部配置 (只暴露 query/tickers/output_mode/agents)
- [ ] 1.4.3 增加 `task_id` 字段 (稳定 hash)

### 1.5 fallback_reason 写入 evidence_pool (P0-3c) — 与 1.1 并行

**文件**: `backend/graph/nodes/execute_plan_stub.py` (修改)

- [ ] 1.5.1 读取每个 agent 输出的 `fallback_reason` / `retryable` / `error_stage` 字段
- [ ] 1.5.2 写入 `state.evidence_pool` 的 `agent_diagnostics` 字段
- [ ] 1.5.3 确保 synthesize 节点能读取 agent_diagnostics 用于报告渲染
- [ ] 1.5.4 单元测试: fallback 信息透传验证

---

## 第 2 阶段: 执行链路完整化

> 把 TaskSection 从"硬编码占位"升级为真正可触发 Agent 执行的入口。
> 前端 fallback 展示也在此阶段完成。

### 2.1 TaskSection 前端接入后端 API (P0-5a) — 依赖 1.3/1.4

**文件**: `frontend/src/components/workbench/TaskSection.tsx` (修改)

- [ ] 2.1.1 删除 `useMemo` 硬编码任务生成逻辑 (当前 line 48-113 的静态任务列表)
- [ ] 2.1.2 新增 `useEffect` — 组件挂载时调用 `GET /api/tasks/daily?session_id=...&news_count=N`
- [ ] 2.1.3 从 `dashboardStore` 获取 `newsItems.length` 作为 `news_count` 参数
- [ ] 2.1.4 任务数据状态管理: `tasks[]` + `loading` + `error`
- [ ] 2.1.5 加载态: Skeleton placeholder (3 个脉冲动画卡片)
- [ ] 2.1.6 空态: "暂无任务建议" + 刷新按钮
- [ ] 2.1.7 错误态: 友好提示 + 重试按钮

### 2.2 TaskSection 执行触发 (P0-5d) — 依赖 1.2 (useExecuteAgent)

**文件**: `frontend/src/components/workbench/TaskSection.tsx` (修改)

- [ ] 2.2.1 每个任务卡片增加"执行"按钮
- [ ] 2.2.2 点击执行 → 调用 `useExecuteAgent().execute(task.execution_params)`
- [ ] 2.2.3 **不再** `navigate('/chat')` — 就地显示进度
- [ ] 2.2.4 执行中: 卡片边框变橙色 + spinner + 进度百分比
- [ ] 2.2.5 完成后: 卡片变绿色 + 显示"查看报告"按钮 → `navigate('/chat?report_id=xxx')`
- [ ] 2.2.6 失败时: 卡片变红色 + 显示错误信息 + 可选"重试"按钮 (仅 retryable=true 时)

### 2.3 前端 ReportView 降级原因展示 (P0-3e) — 依赖 1.5

**文件**: `frontend/src/components/ReportView.tsx` (修改)

- [ ] 2.3.1 读取 report 中的 `agent_diagnostics` 字段
- [ ] 2.3.2 新建 `AgentStatusGrid` 子组件
  - 6 个 Agent 状态卡 (2x3 网格)
  - 每卡: Agent 名称 + 状态图标 + 耗时
  - 🟢 正常完成 / 🟡 限流降级 (可重试) / 🔴 执行失败
- [ ] 2.3.3 Tooltip 展示详细信息: `fallback_reason` + `error_stage` + `duration_ms`
- [ ] 2.3.4 可重试的 Agent 显示"重新执行"小按钮 (触发单 agent 重跑)
- [ ] 2.3.5 在 ReportView 顶部增加 diagnostics 折叠面板 (默认收起)

---

## 第 3 阶段: 全局体验层

> ExecutionBanner + StreamingResultPanel — 让用户在任何页面都能感知执行状态。

### 3.1 ExecutionBanner 组件 (P1-2a)

**文件**: `frontend/src/components/execution/ExecutionBanner.tsx` (新建)

- [ ] 3.1.1 订阅 `useExecutionStore.activeRuns`
- [ ] 3.1.2 无活跃任务时返回 `null` (不占空间)
- [ ] 3.1.3 布局: 固定高度 48px 横条
  ```
  ┌──────────────────────────────────────────────────────────────┐
  │ 🔄 分析 AAPL ...  [price ✓] → [news ⟳] → [fundamental ○]  │
  │                                            [取消] [展开详情] │
  └──────────────────────────────────────────────────────────────┘
  ```
- [ ] 3.1.4 Agent 管道进度图: 6 个圆点/图标，按顺序标记 ✓(完成) / ⟳(执行中) / ○(等待) / ✗(失败)
- [ ] 3.1.5 多任务时: 显示最新一个 + "另有 N 个执行中" badge
- [ ] 3.1.6 "取消"按钮 → `cancelExecution(runId)`
- [ ] 3.1.7 "展开详情" → 滑出详细面板 (agent 列表 + 日志)
- [ ] 3.1.8 完成动画: 进度条从橙色渐变为绿色，2 秒后自动收起

### 3.2 ExecutionBanner 集成 (P1-2b)

**文件**: `frontend/src/components/layout/WorkspaceShell.tsx` (修改)

- [ ] 3.2.1 在 topbar 下方、内容区上方插入 `<ExecutionBanner />`
- [ ] 3.2.2 确保 Chat / Dashboard / Workbench 三个视图都可见
- [ ] 3.2.3 Banner 出现/消失使用 `transition-all duration-300` 动画

### 3.3 StreamingResultPanel 组件 (P1-4a)

**文件**: `frontend/src/components/execution/StreamingResultPanel.tsx` (新建)

- [ ] 3.3.1 接收 `runId` prop — 订阅 executionStore 中对应的 run
- [ ] 3.3.2 三段式布局:
  - **顶部**: Agent 状态管道图 (复用 Banner 逻辑) + 总进度条
  - **中部**: Markdown 流式输出区 (使用 react-markdown 实时渲染)
  - **底部**: 操作栏 (取消/重试/查看完整报告)
- [ ] 3.3.3 流式渲染: 新 chunk 到达时追加到内容区，自动滚动到底部
- [ ] 3.3.4 降级标记: fallback 的 Agent 在内容区显示黄色提示条
  ```
  ⚠️ news_agent 因限流降级，使用缓存数据 (可重试)
  ```
- [ ] 3.3.5 完成后: 替换为完整 `<ReportView report={run.report} />`
- [ ] 3.3.6 错误状态: 显示错误信息 + 诊断详情 + 重试按钮
- [ ] 3.3.7 可嵌入模式: `embedded` prop 控制是否显示外框边框

### 3.4 ContextPanelShell 集成 (P1-4b)

**文件**: `frontend/src/components/layout/ContextPanelShell.tsx` (修改)

- [ ] 3.4.1 新增 "执行结果" tab (与 MiniChat 并列)
- [ ] 3.4.2 Tab 切换逻辑: 有活跃执行时自动切换到"执行结果"
- [ ] 3.4.3 "执行结果" tab 内嵌 `<StreamingResultPanel runId={latestActiveRunId} />`
- [ ] 3.4.4 执行完成后保持在"执行结果" tab 3 秒，然后允许手动切换

---

## 第 4 阶段: Dashboard 可操作化

> 让 Dashboard 从"只读展示"进化为"可触发分析的操作面板"。

### 4.1 SnapshotCard 增加 Action 按钮 (P1-3a)

**文件**: Dashboard SnapshotCard 组件 (修改)

- [ ] 4.1.1 在卡片底部增加两个操作按钮:
  - "🔍 深入分析" → `useExecuteAgent({ query, tickers, agents: ['price_agent', 'news_agent'] })`
  - "📊 生成报告" → `useExecuteAgent({ query, tickers, output_mode: 'investment_report' })`
- [ ] 4.1.2 按钮状态管理:
  - 空闲: 正常按钮样式
  - 执行中: spinner + "分析中..." + 禁用点击
  - 完成: "查看结果" 绿色按钮 → 导航到报告
- [ ] 4.1.3 通过 `executionStore.getActiveRunForTicker(ticker)` 检测是否已有执行中的任务

### 4.2 NewsFeed 分析按钮 (P1-3b)

**文件**: Dashboard NewsFeed 组件 (修改)

- [ ] 4.2.1 每条新闻右侧增加 "🤖 分析影响" 小按钮
- [ ] 4.2.2 点击触发: `useExecuteAgent({ query: '分析这条新闻对 {ticker} 的影响: {headline}', tickers })`
- [ ] 4.2.3 结果注入 MiniChat 作为新消息 (通过 chatStore.addMessage)
- [ ] 4.2.4 执行中: 按钮变为 spinner，该新闻条目边框变橙色

### 4.3 MacroCard 深度分析按钮 (P1-3c)

**文件**: Dashboard MacroCard 组件 (修改)

- [ ] 4.3.1 卡片右上角增加 "📈 宏观详解" 按钮
- [ ] 4.3.2 点击触发: `useExecuteAgent({ query: '深度分析当前宏观经济环境', agents: ['macro_agent'] })`
- [ ] 4.3.3 结果展示: 右侧面板 StreamingResultPanel 自动展开

---

## 第 5 阶段: Agent 控制 + Watchlist 统一

> 两个独立模块，可并行开发，不阻塞后续。

### 5.1 Agent 控制面板前端 (P1-5a)

**文件**: `frontend/src/components/settings/AgentControlPanel.tsx` (新建)

- [ ] 5.1.1 6 行 Agent 配置列表:
  ```
  ┌────────────────────────────────────────────────┐
  │ Agent            深度          状态      开关   │
  │ ─────────────────────────────────────────────── │
  │ 🏷 PriceAgent    ● 标准        🟢 健康   [ON]  │
  │ 📰 NewsAgent     ● 标准        🟢 健康   [ON]  │
  │ 💰 Fundamental   ○ 深度        🟡 限流   [ON]  │
  │ 📊 Technical     ● 标准        🟢 健康   [ON]  │
  │ 🌍 MacroAgent    ● 标准        🟢 健康   [ON]  │
  │ 🔍 DeepSearch    ○ 深度        🟢 健康   [OFF] │
  └────────────────────────────────────────────────┘
  ```
- [ ] 5.1.2 每个 Agent 的深度选择: 标准 / 深度 / 关闭 (三态切换)
- [ ] 5.1.3 预算上限滑块: `max_rounds: 1-10` (默认 3)
- [ ] 5.1.4 并发模式开关: 开启时所有 Agent 并行执行 (默认开启)
- [ ] 5.1.5 Agent 健康状态: 从 `GET /health` 获取，显示 🟢/🟡/🔴
- [ ] 5.1.6 存储到 localStorage (`agent_preferences` key)
- [ ] 5.1.7 "恢复默认"按钮 — 重置所有配置

### 5.2 后端 policy_gate 集成 (P1-5b)

**文件**: `backend/graph/nodes/policy_gate.py` (修改)

- [ ] 5.2.1 读取 `state.ui_context.get("agent_preferences", {})`
- [ ] 5.2.2 根据 `enabled` 字段过滤 agent 选择 (关闭的 agent 不执行)
- [ ] 5.2.3 根据 `depth` 字段映射 budget:
  - 标准 → `max_rounds=3`
  - 深度 → `max_rounds=8`
- [ ] 5.2.4 `concurrent_mode` 字段控制 agent 调度策略
- [ ] 5.2.5 单元测试: agent_preferences 各种组合验证

### 5.3 前端附带 agent_preferences (P1-5c)

**文件**: `frontend/src/api/client.ts` 和相关调用处 (修改)

- [ ] 5.3.1 `executeAgent()` 和 `sendMessageStream()` 自动从 localStorage 读取 agent_preferences
- [ ] 5.3.2 附带到请求体的 `ui_context.agent_preferences` 字段
- [ ] 5.3.3 如果 localStorage 无配置则不发送 (后端使用默认值)

### 5.4 Watchlist 数据源统一 (P1-6a) — 与 5.1 并行

- [ ] 5.4.1 确定规则: 后端 `/api/user/profile` + `/api/user/watchlist/*` 为唯一数据源
- [ ] 5.4.2 审计现有 localStorage 使用点 (dashboardStore + Sidebar)
- [ ] 5.4.3 确认后端 API 已支持 CRUD (GET/POST/DELETE watchlist)

### 5.5 dashboardStore Watchlist 迁移 (P1-6b)

**文件**: `frontend/src/store/dashboardStore.ts` (修改)

- [ ] 5.5.1 `watchlist` 初始化: 从 `apiClient.getUserProfile()` 获取，不再从 localStorage
- [ ] 5.5.2 `addWatchlist(ticker)`: 先调 `POST /api/user/watchlist` → 成功后更新本地状态
- [ ] 5.5.3 `removeWatchlist(ticker)`: 先调 `DELETE /api/user/watchlist/:ticker` → 成功后更新本地状态
- [ ] 5.5.4 移除 localStorage 持久化逻辑
- [ ] 5.5.5 错误处理: API 失败时 toast 提示，不修改本地状态

### 5.6 Sidebar Watchlist 统一 (P1-6c)

**文件**: Sidebar watchlist 相关组件 (修改)

- [ ] 5.6.1 改为从 `dashboardStore.watchlist` 读取 (而非独立 fetch)
- [ ] 5.6.2 移除 Sidebar 自有的 watchlist fetch 逻辑
- [ ] 5.6.3 验证: Dashboard 和 Sidebar 展示的 watchlist 完全一致

---

## 第 6 阶段: TradingKey 设计系统搭建

> 参考原型: `docs/prototype/dashboard_tradingkey_style_v2.html` (主设计稿)
> 先搭设计 Token 和布局骨架，再逐 Tab 填充组件。

### 6.1 设计 Token 定义 (P2-1a)

**文件**: `frontend/src/styles/tradingkey-theme.ts` (新建)

- [ ] 6.1.1 定义色板常量 (直接从原型 CSS 变量提取):
  - 背景层次: `w1=#181a1f`, `w2=#1e2025`, `w3=#24282f`, `w4=#2b3139`, `w5=#363d47`
  - 强调色: `o1=#fa8019` (橙), `profit=#0cad92` (绿), `loss=#f74f5c` (红)
  - 文本层次: `t1=hsla(0,0%,100%,.9)`, `t2=rgba(235,239,245,.6)`, `t3=rgba(235,239,245,.3)`
- [ ] 6.1.2 定义圆角、阴影、字体族常量
- [ ] 6.1.3 导出 `tradingKeyTheme` 对象供全局引用

### 6.2 Tailwind 集成 (P2-1b)

**文件**: `frontend/tailwind.config.js` (修改) + `frontend/src/index.css` (修改)

- [ ] 6.2.1 `tailwind.config.js` — `theme.extend.colors` 新增 `tk-*` 颜色命名空间
  ```
  tk-base, tk-surface, tk-raised, tk-subtle, tk-muted,
  tk-orange, tk-green, tk-red, tk-blue
  ```
- [ ] 6.2.2 `tailwind.config.js` — `theme.extend.fontSize` 新增 `text-2xs: ['11px', { lineHeight: '16px' }]`
- [ ] 6.2.3 `index.css` — 暗色模式 `--fin-hover: #283548` (修复与 --fin-card 相同的问题)
- [ ] 6.2.4 迁移现有 CSS 变量 `--fin-*` 到 TradingKey token (渐进式，保持向后兼容)
- [ ] 6.2.5 清空 `frontend/src/App.css` 中的 Vite 模板残留
- [ ] 6.2.6 全局替换 `text-[10px]` → `text-2xs` (约 15 个文件)

### 6.3 DashboardTabs 容器 (P2-2a)

**文件**: `frontend/src/components/dashboard/DashboardTabs.tsx` (新建)

- [ ] 6.3.1 6 个 Tab 定义:
  ```typescript
  const TABS = [
    { id: 'overview',  label: '综合分析', icon: '📊' },
    { id: 'financial', label: '财务报表', icon: '💰' },
    { id: 'technical', label: '技术面',   icon: '📈' },
    { id: 'news',      label: '新闻动态', icon: '📰' },
    { id: 'research',  label: '深度研究', icon: '🔍' },
    { id: 'peers',     label: '同行对比', icon: '🏢' },
  ]
  ```
- [ ] 6.3.2 Tab 栏样式: TradingKey 风格 — 底部 2px 橙色下划线指示器 + 滑动动画
- [ ] 6.3.3 路由集成: URL `?tab=overview` 与 Tab 状态双向同步
- [ ] 6.3.4 Tab 内容区: `React.lazy` + `Suspense` 按需加载各 Tab 组件
- [ ] 6.3.5 Tab 切换动画: fade-in 150ms

### 6.4 Stock Header (P2-2b)

**文件**: `frontend/src/components/dashboard/StockHeader.tsx` (新建)

- [ ] 6.4.1 布局: 左侧 (Logo + 名称 + 交易所) + 右侧 (操作按钮)
- [ ] 6.4.2 价格显示: 大字号 38px + 涨跌额 + 涨跌幅百分比
  - 涨: `tk-green` + ▲
  - 跌: `tk-red` + ▼
- [ ] 6.4.3 盘后数据: 非交易时段显示 "盘后: $xxx.xx ▲x.x%"
- [ ] 6.4.4 操作按钮: "★ 关注" (切换 watchlist) + "🤖 快速分析" (触发 Agent)
- [ ] 6.4.5 数据源: `useDashboardData()` → `snapshot.market`

### 6.5 Metrics Bar (P2-2c)

**文件**: `frontend/src/components/dashboard/MetricsBar.tsx` (新建)

- [ ] 6.5.1 7 列 CSS Grid 布局 (`grid-template-columns: repeat(7, 1fr)`)
- [ ] 6.5.2 每列: 指标名 (text-2xs, 灰色) + 数值 (text-lg, 白色, font-bold)
- [ ] 6.5.3 数值格式化: 市值缩写 ($3.1T), PE 1位小数, 百分比等
- [ ] 6.5.4 52周区间: 显示为渐变范围条 + 当前价格标记点
- [ ] 6.5.5 数据源: `useDashboardData()` → `snapshot.fundamentals`

---

## 第 7 阶段: TradingKey 6-Tab 组件实现

> 参考原型: `docs/prototype/dashboard_tradingkey_style_v2.html`
> 每个 Tab 独立开发，可按优先级调整顺序。
> 建议顺序: Tab 1 (综合) → Tab 4 (新闻) → Tab 3 (技术) → Tab 2 (财务) → Tab 5 (研究) → Tab 6 (同行)

### 7.1 Tab 1 — 综合分析 (P2-3) — 最高优先

**目录**: `frontend/src/components/dashboard/overview/`

- [ ] 7.1.1 **ScoreRing.tsx** — 综合评分环
  - SVG 环形进度条 (0-100)
  - 中心大字号评分 + 星级 (1-5 星)
  - 颜色映射: ≥80 绿色, 60-79 橙色, <60 红色
  - 数据源: synthesize → `investment_score`
- [ ] 7.1.2 **AnalystRatingCard.tsx** — 分析师评级卡
  - 共识评级文字 (Strong Buy / Buy / Hold / Sell / Strong Sell)
  - 堆叠水平条: 5 段颜色条显示各评级占比
  - 目标上涨空间百分比
  - 数据源: fundamental → `analyst_consensus`
- [ ] 7.1.3 **TargetPriceCard.tsx** — 目标价格卡
  - 三个数字: 最低 / 平均 / 最高 目标价
  - 渐变范围条: 从最低到最高，当前价格用竖线标记
  - 数据源: fundamental → `target_prices`
- [ ] 7.1.4 **HighlightsCard.tsx** — 公司亮点与风险
  - 左列 🟢: 利好要点列表 (3-5 条)
  - 右列 🔴: 利空/风险要点列表 (3-5 条)
  - 数据源: synthesize → `highlights` + `risks`
- [ ] 7.1.5 **DimensionRadar.tsx** — 维度评分雷达图
  - SVG 五边形雷达图
  - 5 个维度: 基本面 / 技术面 / 新闻 / 深度研究 / 宏观
  - 每个维度 0-100 分
  - 填充区域半透明橙色
  - 数据源: 各 agent 评分汇总
- [ ] 7.1.6 **AIInsightsCard.tsx** — 关键洞察卡
  - AI 生成的投资摘要 (react-markdown 渲染)
  - 标题: "🤖 AI 投资洞察"
  - 底部: 更新时间 + 数据来源标注
  - 数据源: synthesize → `investment_summary`
- [ ] 7.1.7 **RiskMetricsCard.tsx** — 风险指标卡
  - 四宫格: Beta / 波动率(60日) / 夏普比率 / 最大回撤
  - 每个指标: 数值 + 小型进度条 + 风险等级标签
  - 底部: 4 条风险告警 (来自 synthesize → `risk_alerts`)
  - 数据源: price → risk indicators
- [ ] 7.1.8 OverviewTab 容器组件 — 将 7 个组件组装为 2x3+1 网格布局

### 7.2 Tab 4 — 新闻动态 (P2-6) — 次高优先 (数据已有)

**目录**: `frontend/src/components/dashboard/news/`

- [ ] 7.2.1 **SentimentStatsCards.tsx** — 情绪统计三卡
  - 三个并排卡片: 正面 / 中性 / 负面
  - 每卡: 百分比数字 + 数量 + 彩色进度条
  - 颜色: 正面=tk-green, 中性=灰色, 负面=tk-red
  - 数据源: 计算 news items 的 sentiment 分布
- [ ] 7.2.2 **NewsFilterPills.tsx** — 筛选器胶囊
  - Pills: 全部 / 利好 / 中性 / 利空 / 财报 / 产品 / 监管
  - 选中态: tk-orange 背景
  - 支持多选 (组合筛选)
  - 联动 NewsList 过滤
- [ ] 7.2.3 **NewsListTimeline.tsx** — 新闻列表时间线
  - 每条: 情绪标签 (Badge) + 标题 + 摘要 (2 行截断) + 来源 + 时间
  - 点击展开: 显示完整内容 + "🤖 分析影响" 按钮
  - 虚拟列表 (react-window) 处理大量新闻
  - 数据源: `/api/market/news` + NewsAgent 输出
- [ ] 7.2.4 **AINewsSummaryCard.tsx** — AI 新闻摘要
  - 顶部固定位: NewsAgent 生成的综合分析摘要
  - Markdown 渲染
  - 底部: "重新生成" 按钮 (触发 NewsAgent 单独执行)
- [ ] 7.2.5 NewsTab 容器组件 — 三卡 + 筛选 + 列表 + AI 摘要布局

### 7.3 Tab 3 — 技术面 (P2-5)

**目录**: `frontend/src/components/dashboard/technical/`

- [ ] 7.3.1 **CandlestickChart.tsx** — K 线图占位
  - 初版: 简单 ECharts candlestick (日线, 60 交易日)
  - 数据源: price → `historical_prices`
  - 后续接入 TechnicalAgent 实时数据
- [ ] 7.3.2 **TechnicalSummary.tsx** — 技术面综合评估
  - 综合评分 + 信号文字 (Strong Buy → Strong Sell)
  - 两列统计: "N 个均线看多 / N 个看空" + "N 个震荡看多 / N 个看空"
  - 颜色编码: 绿色看多、红色看空
- [ ] 7.3.3 **MovingAveragesTable.tsx** — 均线指标表
  - 8 行: MA5 / MA10 / MA20 / MA50 / MA100 / MA200 / EMA12 / EMA26
  - 每行: 名称 / 值 / 信号 (Badge: 买入=绿, 卖出=红, 中性=灰)
  - 数据源: technical → `moving_averages`
- [ ] 7.3.4 **OscillatorsTable.tsx** — 震荡指标表
  - 6 行: RSI / Stochastic / MACD / ADX / CCI / Williams %R
  - 每行: 名称 / 值 / 信号 (同上)
  - 数据源: technical → `oscillators`
- [ ] 7.3.5 **SupportResistance.tsx** — 支撑与阻力可视化
  - 竖向标尺: R3 → R2 → R1 → 当前价 → S1 → S2 → S3
  - 当前价用橙色横线高亮
  - 支撑位绿色，阻力位红色
  - 数据源: technical → `pivot_points`
- [ ] 7.3.6 **BollingerVolume.tsx** — 布林带 & 成交量
  - 上半: 上轨 / 中轨 / 下轨 三线 + 当前价位置
  - 下半: 日均成交量 vs 今日成交量柱状对比
  - 数据源: technical → `bollinger` + price → `volume`
- [ ] 7.3.7 TechnicalTab 容器组件 — K 线图 + 总评 + 两表并排 + 支撑阻力 + 布林带

### 7.4 Tab 2 — 财务报表 (P2-4)

**目录**: `frontend/src/components/dashboard/financial/`

- [ ] 7.4.1 **IncomeStatementTable.tsx** — 利润表
  - 5 年年度数据: 2022-2026E
  - 行: 营收 / 毛利 / EBITDA / 经营利润 / 净利润 / EPS
  - 每列同比变化 (绿色涨/红色跌)
  - 数据源: fundamental → `income_statement`
- [ ] 7.4.2 **ProfitabilityChart.tsx** — 盈利能力趋势图
  - ECharts 柱状图: 毛利率 + 净利率 (双系列)
  - X 轴: 5 年
  - 右侧 Y 轴: 百分比
  - 数据源: fundamental → `profitability_ratios`
- [ ] 7.4.3 **ValuationGrid.tsx** — 关键估值指标四宫格
  - 4 个卡片: PE / PEG / EV-EBITDA / FCF Yield
  - 每卡: 数值 + 行业对比 (高于/低于行业中位数)
  - 颜色: 低估=绿色, 合理=灰色, 高估=红色
  - 数据源: fundamental → `valuation_metrics`
- [ ] 7.4.4 **BalanceSheetSummary.tsx** — 资产负债表摘要
  - 4 行核心项: 总资产 / 总负债 / 净资产 / 现金
  - 每行: 当前值 + 同比变化 + 迷你柱状图 (5 年趋势)
  - 数据源: fundamental → `balance_sheet`
- [ ] 7.4.5 FinancialTab 容器组件 — 利润表 + 趋势图 + 四宫格 + 资产负债

### 7.5 Tab 5 — 深度研究 (P2-7)

**目录**: `frontend/src/components/dashboard/research/`

- [ ] 7.5.1 **ResearchMetaBar.tsx** — 研究元数据栏
  - 4 个指标: 信心度 (环形) / 引用数 (数字) / 证据质量 (Badge) / 冲突数 (数字)
  - 水平排列，卡片式
  - 数据源: deep_search → metadata
- [ ] 7.5.2 **ExecutiveSummaryCard.tsx** — 执行摘要
  - 大面积 Markdown 渲染区
  - 标题: "📋 研究执行摘要"
  - 数据源: deep_search → `executive_summary`
- [ ] 7.5.3 **CoreFindingsPanel.tsx** — 核心发现
  - 可折叠的分节列表
  - 每节: 标题 + 内容 (Markdown) + 引文证据块
  - 引文证据: 来源名 + URL (可点击) + 引述文字 (灰色斜体)
  - 数据源: deep_search → `findings[]`
- [ ] 7.5.4 **ConflictPanel.tsx** — 观点冲突面板
  - 左右两列对照布局:
    - 左列 🟢 乐观观点 + 来源
    - 右列 🔴 悲观观点 + 来源
  - 中间: 争议主题
  - 数据源: deep_search → `conflicts[]`
- [ ] 7.5.5 **ReferencesList.tsx** — 参考文献列表
  - 表格: 序号 / 标题 (链接) / 来源类型 (Badge) / 可信度 (进度条)
  - 来源类型: 新闻 / 研报 / SEC 文件 / 社交媒体
  - 数据源: deep_search → `references[]`
- [ ] 7.5.6 ResearchTab 容器组件 — 元数据栏 + 摘要 + 发现 + 冲突 + 引用

### 7.6 Tab 6 — 同行对比 (P2-8)

**目录**: `frontend/src/components/dashboard/peers/`

- [ ] 7.6.1 **PeerScoreCards.tsx** — 同行评分卡
  - 6 个圆形评分卡 (flex wrap)
  - 当前股票: 橙色边框高亮
  - 每卡: Logo/首字母 + ticker + 评分 (0-100)
  - 数据源: 后端 peer_comparison → `peers[].score`
- [ ] 7.6.2 **PeerComparisonTable.tsx** — 详细指标对比表
  - 行: 各公司 (当前股票高亮行)
  - 列: PE / PEG / PB / EV-EBITDA / 净利率 / ROE / 营收增速 / 股息率 / 综合评分
  - 最优值绿色高亮，最差值红色高亮
  - 可排序 (点击列头)
  - 数据源: peer_comparison → `peers[]`
- [ ] 7.6.3 **ValuationBars.tsx** — 估值水平横向条形图
  - ECharts 水平条形图: 各公司 PE (或 EV-EBITDA)
  - 行业中位数虚线标记
  - 当前股票橙色高亮
- [ ] 7.6.4 **GrowthBars.tsx** — 营收增速横向条形图
  - ECharts 水平条形图: 各公司营收增速
  - 0 基准线
  - 正值绿色，负值红色
- [ ] 7.6.5 **PeerAISummaryCard.tsx** — AI 同行分析摘要
  - Markdown 渲染: 相对优势 / 相对劣势 / 适合投资者类型
  - 数据源: synthesize → peer_analysis
- [ ] 7.6.6 PeersTab 容器组件 — 评分卡 + 对比表 + 两个条形图 + AI 摘要
- [ ] 7.6.7 后端 peer_comparison 数据接口增强
  - 确认 `/api/dashboard` 返回 `peer_comparison` 字段
  - 如不存在，新增 peer 数据聚合逻辑 (基于同行业 ticker)

---

## 第 8 阶段: Workbench Mission Control ⭐ 最终目标

> 参考原型: `docs/workbench_v2_preview.html`
> 前置: P0-5 (TaskSection 接后端) + P1-1 (ExecutionStore) + P1-4 (StreamingResultPanel)

### 8.1 Workbench 右侧面板 (P3-1a)

**文件**: `frontend/src/components/layout/WorkspaceShell.tsx` (修改)

- [ ] 8.1.1 Workbench 视图检测: 当前路由为 `/workbench` 时激活右侧面板
- [ ] 8.1.2 右侧面板容器: `w-[480px] border-l border-fin-border`
- [ ] 8.1.3 嵌入 `ContextPanelShell`，包含两个 Tab:
  - "执行结果" — `<StreamingResultPanel />` (来自第 3 阶段)
  - "对话" — `<MiniChat />`
- [ ] 8.1.4 面板可折叠: 点击 toggle 按钮收起/展开
- [ ] 8.1.5 有活跃执行时自动展开并切换到"执行结果" Tab
- [ ] 8.1.6 响应式: 窗口宽度 < 1200px 时面板自动收起为浮层

### 8.2 Workbench 主区域上下两栏 (P3-1b)

**文件**: `frontend/src/pages/Workbench.tsx` (修改)

- [ ] 8.2.1 主区域布局改为 `flex flex-col`
- [ ] 8.2.2 上栏: `TaskSection` (任务队列 + 执行状态) — 占 40%
- [ ] 8.2.3 下栏: `ReportSection` (时间线) + `NewsSection` — 占 60%，左右并排
- [ ] 8.2.4 上下栏之间可拖拽调整比例 (resize 手柄)
- [ ] 8.2.5 下栏内部: ReportSection 占 60%, NewsSection 占 40%

### 8.3 TaskSection 任务状态机 (P3-2a)

**文件**: `frontend/src/components/workbench/TaskSection.tsx` (修改)

- [ ] 8.3.1 定义任务状态枚举:
  ```typescript
  type TaskStatus = 'pending' | 'running' | 'done' | 'expired'
  ```
- [ ] 8.3.2 每个任务卡片的状态样式:
  | 状态 | 边框 | 图标 | 操作 |
  |------|------|------|------|
  | pending | `border-tk-subtle` | ▶ 播放 | 点击执行 |
  | running | `border-tk-orange animate-pulse` | ⟳ 旋转 | 查看进度 |
  | done | `border-tk-green` | ✓ 勾选 | 查看报告/重新执行 |
  | expired | `border-tk-muted opacity-50 line-through` | ✗ | 不可操作 |
- [ ] 8.3.3 running 状态卡片内嵌 Agent 管道进度:
  ```
  price ✓ → news ⟳ → fundamental ○ → technical ○ → macro ○
  ```
- [ ] 8.3.4 done 状态卡片底部两个按钮:
  - "📄 查看报告" → `navigate('/chat?report_id=xxx')`
  - "🔄 重新执行" → 重置为 pending 并触发新执行
- [ ] 8.3.5 任务过期逻辑: 创建超过 24 小时的任务自动标记为 expired
- [ ] 8.3.6 任务队列顶部: "待办 N / 执行中 N / 已完成 N" 统计条

### 8.4 任务执行历史 (P3-2b)

**文件**: `frontend/src/components/workbench/ExecutionHistory.tsx` (新建)

- [ ] 8.4.1 列表: 最近 10 次执行记录 (来自 executionStore.recentRuns)
- [ ] 8.4.2 每条记录:
  - ticker + 查询摘要
  - 执行耗时 (如 "耗时 23s")
  - Agent 状态摘要 (5/6 成功, 1 降级)
  - 结论快照 (投资评级 + 置信度)
- [ ] 8.4.3 点击记录 → `navigate('/chat?report_id=xxx')` 回放报告
- [ ] 8.4.4 折叠在 TaskSection 底部，默认收起

### 8.5 ReportSection 时间线视图 (P3-3a)

**文件**: `frontend/src/components/workbench/ReportSection.tsx` (重写)

- [ ] 8.5.1 按日期分组: 使用 `date-fns` groupBy 日期
- [ ] 8.5.2 每个日期组的视觉:
  ```
  ── 2026-02-13 ──────────────────────
  │
  ├─ AAPL  BUY ★★★★   87%  "Apple AI 驱动增长"
  │
  ├─ TSLA  HOLD ★★★   72%  "交付不及预期"
  ```
- [ ] 8.5.3 每个节点: ticker + 投资评级 (Badge) + 星级 + 置信度 + 标题摘要
- [ ] 8.5.4 点击节点 → 调用 `getReportReplay(id)` → 右侧面板渲染 ReportView
- [ ] 8.5.5 多选模式: 勾选两份报告 → 底部出现"对比分析"按钮
- [ ] 8.5.6 过滤器: 按 ticker / 评级 / 日期范围筛选
- [ ] 8.5.7 空态: "暂无报告，试试执行一个任务？" + 指向 TaskSection 的箭头

### 8.6 报告对比 API 及前端 (P3-3b)

**后端**: `backend/api/dashboard_router.py` 或新建路由

- [ ] 8.6.1 新增 `GET /api/reports/compare?id1=X&id2=Y`
- [ ] 8.6.2 返回结构化差异:
  - `rating_change`: "HOLD → BUY"
  - `confidence_change`: "+12%"
  - `price_change`: "+5.3%"
  - `new_risks[]` / `removed_risks[]`
  - `score_changes`: 各维度评分变化
- [ ] 8.6.3 单元测试: 对比 API 格式验证

**前端**: `frontend/src/components/workbench/ReportCompare.tsx` (新建)

- [ ] 8.6.4 双栏布局: 左侧报告 A / 右侧报告 B
- [ ] 8.6.5 差异高亮:
  - 评分提升: 绿色箭头 ↑
  - 评分下降: 红色箭头 ↓
  - 新增风险: 红色标签 [NEW]
  - 消除风险: 绿色删除线
- [ ] 8.6.6 弹出模态框展示 (Overlay)

---

## 第 9 阶段: 产品打磨

> 完成核心功能后的精打细磨，提升整体使用体验。

### 9.1 Command Palette 增强 (P4-1a)

**文件**: `frontend/src/components/CommandPalette.tsx` (修改)

- [ ] 9.1.1 新增命令解析器:
  - `/analyze {ticker}` → 触发 `executeAgent({ tickers: [ticker] })`
  - `/compare {ticker1} vs {ticker2}` → 触发对比报告
  - `/agents` → 打开 AgentControlPanel
  - `/report {ticker}` → 查找并跳转最新报告
- [ ] 9.1.2 命令自动补全: 输入 `/` 后显示可用命令列表
- [ ] 9.1.3 ticker 自动补全: 从 watchlist + 热门 ticker 中匹配
- [ ] 9.1.4 命令执行反馈: 执行后显示 toast 通知

### 9.2 Dashboard ↔ Agent 联动 (P4-2)

- [ ] 9.2.1 **自动刷新** (P4-2a): executionStore 监听 `run.status === 'done'`
  - 如果 `run.tickers` 包含当前 dashboard symbol → 触发 `useDashboardData` 重新加载
- [ ] 9.2.2 **异常检测** (P4-2b): SnapshotCard 中增加波动预警
  - 当日跌幅 > 3% → 显示 "⚠️ 异常波动，建议深入分析" 横幅
  - 横幅内置"一键分析"按钮

### 9.3 Agent 健康仪表盘 (P4-3)

**后端**:
- [ ] 9.3.1 (P4-3a) `GET /health` 响应新增 `agent_health` 字段:
  ```json
  {
    "agent_health": {
      "price_agent": { "success_rate": 0.95, "avg_latency_ms": 1200, "circuit_breaker": "closed" },
      "news_agent": { "success_rate": 0.88, "avg_latency_ms": 3500, "circuit_breaker": "closed" },
      ...
    }
  }
  ```
- [ ] 9.3.2 健康数据来源: 从 rate_limiter.snapshot() + agent_adapter 统计中聚合

**前端**:
- [ ] 9.3.3 (P4-3b) AgentControlPanel 健康状态列展示:
  - 🟢 健康 (成功率 > 90%)
  - 🟡 降级 (50-90%)
  - 🔴 不可用 (< 50%)
- [ ] 9.3.4 Tooltip 展示: 平均延迟 + 最近错误 + circuit_breaker 状态

### 9.4 DRY 代码清理 (P4-5)

- [ ] 9.4.1 (P4-5a) 合并 `extractTickers()` 重复:
  - 从 `ChatInput.tsx` 和 `ChatList.tsx` 中提取
  - 创建 `frontend/src/utils/tickers.ts`
  - 两处改为 import 公共函数
- [ ] 9.4.2 (P4-5b) Dashboard API 调用迁入 apiClient:
  - `useDashboardData.ts` 中的直接 `fetch()` 调用 → 改为 `apiClient.getDashboard()`
  - 确保走统一的 axios 实例 (含 baseURL、错误处理、拦截器)
- [ ] 9.4.3 (P4-5c) 清理后端遗留代码:
  - `backend/api/streaming.py` 中 ThinkingStream 等旧版 API 引用
  - 确认无其他文件引用这些遗留类

---

## 统计总览

### 任务量统计

| 阶段 | 子项数 | 新建文件 | 修改文件 | 关键组件 |
|------|--------|----------|----------|----------|
| 第 1 阶段: 核心基础 | 26 | 2 | 3 | executionStore, useExecuteAgent |
| 第 2 阶段: 执行链路 | 18 | 1 | 3 | TaskSection, AgentStatusGrid |
| 第 3 阶段: 体验层 | 19 | 2 | 2 | ExecutionBanner, StreamingResultPanel |
| 第 4 阶段: Dashboard 可操作 | 10 | 0 | 3 | SnapshotCard, NewsFeed, MacroCard |
| 第 5 阶段: Agent+Watchlist | 21 | 1 | 5 | AgentControlPanel, policy_gate |
| 第 6 阶段: 设计系统 | 18 | 4 | 2 | theme, DashboardTabs, StockHeader, MetricsBar |
| 第 7 阶段: 6-Tab 组件 | 42 | 31+ | 1 | 31 个 Tab 子组件 + 6 容器 |
| 第 8 阶段: Workbench MC | 27 | 3 | 3 | Timeline, Compare, ExecutionHistory |
| 第 9 阶段: 产品打磨 | 12 | 1 | 6 | CommandPalette, health, DRY |
| **合计** | **193** | **~45** | **~28** | |

### 关键路径 (决定总工期)

```
1.1 executionStore → 1.2 useExecuteAgent → 2.2 TaskSection 执行
                                          → 3.1 ExecutionBanner
                                          → 3.3 StreamingResultPanel → 8.1 Workbench 右侧面板
                                          → 4.1 SnapshotCard → 7.1 Tab 1 综合分析 → ... → 7.6 Tab 6
```

### 并行度优化建议

| 可并行的组合 | 说明 |
|-------------|------|
| 1.1 + 1.3 + 1.5 | executionStore + 后端任务增强 + fallback evidence_pool |
| 5.1/5.2/5.3 + 5.4/5.5/5.6 | Agent 控制 + Watchlist (完全独立) |
| 7.1 + 7.2 + 7.3 + 7.4 | 各 Tab 组件 (互不依赖) |
| 8.3 + 8.5 | 任务状态机 + 报告时间线 (同一页面不同区域) |
| 9.1 + 9.2 + 9.3 + 9.4 | 打磨项全部独立 |

### 里程碑检查点

| 检查点 | 完成标志 | 对应阶段 |
|--------|----------|----------|
| **M1: 可执行** | TaskSection 点击任务 → Agent 执行 → 流式返回结果 | 第 1-2 阶段完成 |
| **M2: 可观测** | ExecutionBanner 全局进度 + StreamingResultPanel 实时展示 | 第 3 阶段完成 |
| **M3: 可操作** | Dashboard 卡片一键分析 + Agent 控制面板 | 第 4-5 阶段完成 |
| **M4: TradingKey** | 6-Tab Dashboard 完整运行 + 暗色主题 | 第 6-7 阶段完成 |
| **M5: Mission Control** | Workbench 右侧面板 + 任务状态机 + 报告时间线 + 对比 | 第 8 阶段完成 ✅ 目标达成 |
| **M6: 产品级** | Command Palette + 联动 + 健康 + DRY 清理 | 第 9 阶段完成 |

---
