# 09 功能联动与摆设功能审计 Implementation Plan

> **For agentic workers:** 本文档 = 审计结论 + 处置任务。每个条目自带证据（文件:行号）、处置决定与验收标准，按编号执行，每条一次 commit。执行者无需重新判断"该不该做"——处置决定已做出；只有标注【盘点】的条目需要先跑盘点步骤再按分支执行。

**基线 commit:** `4a1c055`
**Goal:** 解决四个根因：①"图表不是真实数据"→ 图表真实性治理；②"功能之间没联动"→ 打通八条数据流；③"工作台不知道干嘛/一堆摆设"→ 逐件处置（打通/收纳/删除）+ 工作台信息架构重做；④实时监控只有离散 finding、没有从触发到图表复盘的闭环 → 落地 Kansoku 启发的最小实时链路。

**Architecture:** Part A 图表真实性（最高优先）→ Part B 联动矩阵（八条打通线）→ Part C 摆设处置清单（12 件）→ Part D 实时联动最小闭环（最小 prediction 基座 → 纯代码触发/心跳 → 页面 lease → 点评流 → 图表深链）。依赖：Part A 的徽标依赖 08 文档 Task 2 的 SourceBadge；Part B 部分条目依赖 WP6 F2 watchlist。09 D-0 自己交付闭环所需的最小 prediction contract/store/submit，10 只在其上扩展 Agent 记忆、战绩与成本，因此保持既定 `09 → 10` 顺序无循环依赖。

## Global Constraints

- 删除组件前必须 `grep -rn "组件名" frontend/src backend --include="*.ts*"` 确认零引用（测试文件除外，随组件一起删）。
- 所有"打通"新增的跳转必须双向可回（浏览器返回键正常），带上下文的跳转用 URL 参数而非仅内存状态（可分享、可刷新）。
- 每条目完成跑 `cd frontend && pnpm test:unit && pnpm build`；涉及后端的加 `python -m pytest backend/tests -x -q`。
- Kansoku 只作为交互与闭环参考：后端继续使用 **FastAPI + LangGraph + PostgreSQL**，图表继续使用 **ECharts**。不得引入 Longbridge、`pi-agent-core`、单用户 SQLite 新表、Fastify 内嵌 Vite 或 `lightweight-charts`。
- 行情序列与 AI 判断必须是两个独立数据面：K 线/报价/指标只能来自现有行情 API 与确定性计算；AI 只能提交 `prediction` 覆盖层，禁止把 AI 数值数组拼进真实行情 series。
- Part D 新增持久化表必须带 `user_id`，由服务端鉴权身份注入并落 PostgreSQL；客户端提交的 `user_id` 不可信且不得作为租户边界。

---

## Part A: 图表真实性治理（"图表感觉都不是真实数据"的根源）

**证据链:**
- `frontend/src/components/SmartChart.tsx:2-7`：组件自述支持两种模式——`<chart>`（**LLM 内联生成的 JSON 数据**）与 `<chart_ref>`（真实 API 数据引用）。
- `SmartChart.tsx:193-200`：inline 正则把 LLM 输出里的 JSON 直接当图表数据渲染。**也就是说：模型可以现编一串价格数字画成 K 线，界面上与真实数据毫无区分。**主人的直觉完全正确。
- `InlineChart.tsx:27-146`：K线/收益曲线的构建函数消费的就是这些 LLM 生成的 `KlineData`。

**处置决定（三层防线）:**

### A-1: 价格类 inline 图表禁止直接渲染，强制转真数据

**Files:**
- Modify: `frontend/src/components/ChatList.tsx`（图表块渲染分支）、`frontend/src/utils/chartIntent.ts`（WP4 T6 产物；若未做 WP4，改 ChatList 内联逻辑）

- [x] Step 1: 渲染层规则——解析出的 chart block 若 `mode === 'inline'` 且 `type` 属于 `{candlestick, kline, line_price, ohlc}`（价格语义类，对照 SmartChart 的 type 枚举 `grep -n "type ===" SmartChart.tsx` 列全）：**不渲染该 inline 块**，改为触发现有的真数据通道（`detectChartType + getChartData` 流程，ChatInput onDone 已有该管线）用同一 ticker 重取重画；取不到真数据则显示 EmptyState「行情图暂不可用」+ 重试按钮。
- [x] Step 2: 非价格类 inline（概念占比饼图、流程示意等）允许渲染，但**必挂** `<SourceBadge synthetic={true}/>`（「AI示意」黄标，08 Task 2/6 已定义）。
- [x] Step 3: vitest：inline candlestick block → 断言不渲染 ECharts 且触发真数据回调；inline pie → 渲染且含「AI示意」文案。
- [x] Commit: `fix(charts): price-like inline charts must use real data channel; synthetic badge on AI-generated illustrations`

### A-2: 后端图表指令改为 chart_ref 优先

**Files:**
- Modify: 图表指令注入点（`grep -rn "chart_ref\|<chart" backend/graph/nodes/chat_renderer.py backend/graph/nodes/synthesize.py backend/prompts -l` 定位 prompt/模板）

- [x] Step 1: prompt 规则改写：要求模型对价格/行情/财务序列一律输出 `<chart_ref source=… fields=…/>`，`<chart>` 内联仅允许"无真实数据源的概念示意"，且必须在 JSON 外附一句"（示意图，非真实数据）"。
- [x] Step 2: 金样/既有图表测试回归（`python -m pytest backend/tests -k chart -q`）。
- [x] Commit: `fix(prompt): chart_ref-first policy — LLM may not fabricate price series for inline charts`

### A-3: Dashboard 数据来源审计（一次性盘点 + 补标注）

- [x] Step 1【盘点】: 逐 tab（Overview/Financial/Technical/News/Research/Peers）追一条数据链：组件 → hook → `/api/dashboard/*` → 后端 service → 数据源；把结论写进 `docs/superpowers/plans/2026-07-03-finsight-overhaul/notes-dashboard-data-sources.md`（表：tab | 数据 | 真实来源 | 降级路径 | 是否已标注）。
- [x] Step 2: 据表给每个数据卡/图表补 `<SourceBadge/>`（大概率全是真数据，问题只是"没标"，标注即可消除"假数据感"）；AI 洞察卡片统一标注「AI 评分 · 基于 {n} 项真实指标 · 置信度 {x}%」（字段从 `/api/dashboard/insights` 响应取，`grep -n "confidence" backend/dashboard` 对齐）。
- [x] Commit: `feat(dashboard): provenance badges on every data card, insight cards disclose basis and confidence`

### A-4: 真实行情基底与 AI prediction 覆盖层严格分离

**Files:**
- Create: `frontend/src/types/chartPrediction.ts`、`frontend/src/components/charts/PredictionOverlay.ts`
- Modify: `frontend/src/components/SmartChart.tsx`、`frontend/src/components/chatChartIntent.ts`
- Test: `frontend/src/components/SmartChart.test.ts`、`frontend/src/components/ChatInput.smartchart.test.ts`

**契约:**

```ts
type PredictionOverlay = {
  predictionId: string
  symbol: string
  direction: 'long' | 'short' | 'neutral'
  anchor: { timeframe: string; time: string; price: number }
  entry?: number
  stop?: number
  target1?: number
  target2?: number
  range?: { low: number; high: number }
  zones?: Array<{ low: number; high: number; label: string }>
  status: 'waiting' | 'open' | 'triggered' | 'invalidated' | 'hit_target' | 'hit_stop' | 'held_range' | 'broke_range'
}
```

- [x] Step 1: 写失败测试，构造同一份真实 OHLC 响应与两份不同 prediction，断言 candle/line series 的 `data` 逐项完全相同，只有 overlay 的 `markLine/markPoint/markArea` 改变；prediction 中即使夹带 `bars/series/data` 字段也必须被解析层丢弃。
- [x] Step 2: `SmartChart` 明确拆成 `marketSeries` 与 `predictionOverlay` 两个输入。`marketSeries` 只接受现有 `getChartData` 返回；`PredictionOverlay` 只产出 ECharts 标注：anchor=`markPoint` + 锚点 bar 背景 `markArea`，entry/stop/T1/T2=`markLine`，neutral range/zones=`markArea`。状态为 invalidated/resolved 时只改变线型、颜色和 label 后缀，不改历史行情。
- [x] Step 3: `chart_ref`/URL 深链只传 `predictionId`，前端通过受鉴权 API 读取 09 D-0 已校验归档的 prediction；禁止把完整 prediction 或行情数组塞进 URL。加载失败时仍渲染真实行情，并显示「AI 标注暂不可用」。
- [x] Step 4: vitest 覆盖 anchor 精确落在对应时间点、四类价位 label、neutral range、越权/404 prediction 降级，以及「AI 标注」与真实数据 SourceBadge 同时可辨识。
- [x] 验收: 浏览器 Network 中行情请求与 prediction 请求可独立观察；关闭 AI overlay 后 OHLC 图不重取、不变形；诱导模型生成伪 K 线数组不能改变 ECharts 行情 series。
- [x] Commit: `feat(charts): render validated AI predictions as overlays on immutable real market series`

---

## Part B: 联动矩阵（八条打通线）

**现状总诊断:** 每个功能都是终点站，没有下一步。下表每行 = 一条要打通的数据流。

| # | 从 → 到 | 现状证据 | 打通后行为 |
|---|---------|----------|-----------|
| B-1 | 对话中的 ticker → 看板 | AI 回答中 ticker 是纯文本 | 点 ticker 直达 `/dashboard/AAPL` |
| B-2 | 看板 → 对话 | dashboard 无提问入口；MiniChat 只挂在 RightPanel（`grep -rln "MiniChat"` 仅 RightPanel.tsx） | 看板每个 tab 右上「问 AI」带上下文提问 |
| B-3 | 报告 → 工作台归档 | chat 生成的报告与 workbench ReportSection 列表无互链 | 报告消息尾部「已归档到工作台 · 查看」 |
| B-4 | 监控发现 → 对话 | FindingCard.tsx:150 有 `case 'chat'` 但上下文不全 | 发现卡「问 AI」带 finding 全文入对话 |
| B-5 | 筛选器结果 → 看板/自选/对话 | screener 结果行是死数据 | 行内三个动作：看板/加自选/问 AI |
| B-6 | 持仓 → 对话 | 后端 `_positions_from_ui_context` 支持 positions（understand_request.py:2083），前端是否传？【盘点】 | 「分析我的持仓」一键带真实持仓提问 |
| B-7 | 晨报 → 对话/报告 | MorningBriefCard 是只读卡 | 晨报每条要点可「深入分析」 |
| B-8 | 自选股 → 快捷建议/晨报/监控 | WP6 F2 已 spec | （执行归 WP6，此处仅登记） |

### B-1: ticker 链接化

**Files:** Create `frontend/src/components/common/TickerLink.tsx`；Modify ChatList 的 markdown 渲染（ReactMarkdown components 映射处，`grep -n "ReactMarkdown\|components=" ChatList.tsx`）

- [x] Step 1: `TickerLink`：`<a>` 样式 `font-mono text-t-accent hover:underline cursor-pointer`，onClick → `navigate('/dashboard/' + ticker)`。
- [x] Step 2: markdown 后处理：对 AI 消息文本用已有 `extractTickers`（utils/ticker.ts）识别的 ticker 集合做精确词替换为 TickerLink（只替换本条消息确认过的 ticker，避免误伤普通大写词；在 ReactMarkdown 的 `text` 节点 renderer 里做）。
- [x] Step 3: vitest：含 "AAPL" 的消息渲染出可点链接，"CEO" 不变。
- [x] Commit: `feat(linkage): tickers in chat replies deep-link to dashboard`

### B-2: 看板「问 AI」

**Files:** Modify `frontend/src/pages/Dashboard.tsx`（顶栏），复用 `MiniChat.tsx`

- [x] Step 1: Dashboard 顶栏加 ghost 按钮「问 AI」→ 打开右侧 MiniChat（或滑出面板），预填上下文：`ui_context.active_symbol = 当前symbol`、输入框预置 `关于 {symbol} 的{当前tab中文名}，` 让用户接着问。
- [x] Step 2: 确认 MiniChat 发送时把 `active_symbol` 写进请求 ui_context（`grep -n "active_symbol" frontend/src/components/MiniChat.tsx frontend/src/api/client.ts`；后端 understand_request 的 active_symbol 兜底机制立即生效——这是把现有后端能力接上前端的零成本联动）。
- [x] Commit: `feat(linkage): ask-AI from dashboard with active symbol context`

### B-3: 报告 ↔ 工作台互链

**Files:** Modify ChatList（报告消息尾部）、`frontend/src/components/workbench/ReportSection.tsx`

- [x] Step 1【盘点】: 确认 chat 深度报告落库路径：`grep -rn "report_index\|save_report" backend/api/chat_router.py backend/graph` → 找到 report_id 在 SSE done 事件或响应里的字段名。
- [x] Step 2: 报告消息 done 后尾部渲染一行 `已归档 · 在工作台查看 →`（拿 Step 1 的 report_id 跳 `/workbench?report={id}`）；Workbench 读该参数自动展开对应报告。
- [x] Step 3: 反向：ReportSection 每条报告加「继续追问」→ 跳 `/chat` 并预填 `基于报告《{title}》，`（thread 上下文里 report 已可被 RAG 召回，零后端改动）。
- [x] Commit: `feat(linkage): chat reports link to workbench archive and back`

### B-4: 发现卡上下文完整化

**Files:** Modify `frontend/src/components/workbench/FindingCard.tsx:150` 附近

- [x] Step 1: 现有 `case 'chat'` 的跳转只带标题（读代码确认），改为把 finding 的 `title + summary + ticker + 触发规则` 拼成预填问题：`监控发现：{title}（{ticker}）。{summary}。帮我分析这个发现的影响和应对。`，并设 `ui_context.active_symbol = ticker`。
- [x] Commit: `feat(linkage): monitor findings open chat with full context`

### B-5: 筛选器结果行动作

**Files:** Modify `frontend/src/components/screener/**` 结果表组件（`ls frontend/src/components/screener/`）

- [x] Step 1: 结果表每行尾部三个 ghost 图标按钮：看板（navigate）/ 加自选（WP6 F2 的 `POST /api/watchlist`，未做 WP6 前该按钮隐藏）/ 问 AI（`/chat` 预填 `分析一下 {ticker}，它在筛选条件"{当前筛选条件摘要}"下入选`）。
- [x] Commit: `feat(linkage): screener rows act — dashboard / watchlist / ask-AI`

### B-6: 持仓上下文接线【盘点】

- [x] Step 1【盘点】: `grep -rn "positions" frontend/src/api/client.ts frontend/src/components/ChatInput.tsx frontend/src/store | head`——确认发消息时 ui_context 是否携带 positions。
- [x] Step 2 分支 a（未携带）：从 workbench PortfolioEditor 的数据源（`grep -rn "usePortfolio\|portfolio" frontend/src/hooks`）取当前持仓，在 ChatInput 发送时写入 `ui_context.positions`（字段结构对齐 understand_request.py:2083 `_positions_from_ui_context` 期待的形状——先读该函数确认键名）。分支 b（已携带）：跳过。
- [x] Step 3: PortfolioSummaryBar 加「分析我的持仓」按钮 → `/chat` 预填 `我的持仓该怎么调整？`（后端 portfolio 意图路径此刻能拿到真持仓，blocked_tasks 的"缺持仓"分支不再误触发）。
- [x] Commit: `feat(linkage): real positions flow into chat portfolio analysis`

### B-7: 晨报要点深入

**Files:** Modify `frontend/src/components/workbench/MorningBriefCard.tsx`

- [x] Step 1: 晨报每个要点行尾加「深入 →」ghost 链接：`/chat` 预填 `晨报提到：{要点文本}。展开讲讲对 {关联ticker（若有）} 的影响。`
- [x] Commit: `feat(linkage): morning brief bullets expand into chat analysis`

### B-8: 自选股联动登记

- [x] 登记：WP6-F2 已将用户自选股接入 ChatInput 快捷建议、晨报选标的优先级与 monitor 默认 targets；实现提交 `e0a91fc`，当前 `backend/tests/test_watchlist.py` 5 项回归通过。

---

## Part C: 摆设/死件处置清单（12 件，证据 + 决定 + 步骤）

### C-1: ResearchCard —— 删除

**证据:** `grep -rln "import.*ResearchCard" frontend/src --include="*.tsx"` 除自身外零引用（2026-07-03 复核）。
- [x] `git rm frontend/src/components/ResearchCard.tsx`（连同其测试若有）→ build 绿 → Commit: `chore(frontend): remove dead ResearchCard component`

### C-2: MiniChat —— 保留并升级为全局"随处问"

**证据:** 仅 RightPanel.tsx 引用；功能完好但可发现性≈0。
**决定:** B-2 已把它接进 dashboard；此外给它一个全局快捷键。
- [x] CommandPalette 加一条命令「问 AI（带当前页面上下文）」；MiniChat 打开时读当前路由推断上下文（dashboard→symbol，workbench→无）。Commit: `feat(minichat): global ask-AI command with route context`

### C-3: CommandPalette —— 保留，可见性已由 08 Task 7 解决

- [x] 登记项：确认 08 Task 7 的 ⌘K 假输入框已实装；补充命令清单：导航到各页 / 问 AI / 切主题 / 切涨跌色（`grep -n "commands\|items" frontend/src/components/CommandPalette.tsx` 对齐其命令注册结构后追加）。

### C-4: Skills 三件套（SkillAutocomplete / SkillLibraryDrawer / skills_router）——【盘点】

**证据:** 前端三组件互相引用成环，但 skills 实际内容未知。
- [x] Step 1【盘点】: `curl -s localhost:8000/api/skills | python -m json.tool | head -40`（或读 `backend/api/skills_router.py` + `backend/skills/` 目录）统计可用 skill 数量与质量。
- [x] Step 2 分支 a（≥3 个真实可用 skill）：保留，且在 ChatInput 输入 `/` 时的提示文案里写明可用技能数；分支 b（<3 或全是演示）：三组件与入口全部隐藏到开发者模式（`finsight_dev` 条件，同 08 Task 5 层3），不删代码。把结论写进 notes。
- [x] Commit: `chore(skills): gate skill UI by real skill availability`

**盘点结论（notes）:** builtin registry 当前稳定加载 7 个非演示 skill；每项都有真实 required facets、工具/Agent 偏好、预算与输出合同，其中财报影响、A股研究、估值校验直接连接生产工具，缠论/波浪/均线/成长质量作为显式分析视角且不会自动劫持普通请求。因此走分支 a：保留 Skills UI，并在 `/` 提示顶部展示服务端实际返回的可用技能总数。

### C-5: @agent 提及与 agent 偏好 ——【盘点】接线

**证据:** AgentMention 在 ChatInput/MiniChat 可用（`agents_override` 后端有强制直达逻辑，runner._route_after_understand_request:101-107 尊重它）；但 `agent_router.py` 的 GET/PUT `/api/agents/preferences` 前端消费点未知。
- [ ] Step 1【盘点】: `grep -rn "preferences" frontend/src/api frontend/src/components/settings` → 找偏好 UI。
- [ ] Step 2 分支 a（有 UI）：在设置里给它加说明文案（"控制报告默认参与的智能体"）并确认保存生效；分支 b（无 UI）：SettingsModal 加「智能体偏好」区（7 个 agent 的开关 + max_reflections 滑条，读写现有 preferences 端点——字段结构照 `backend/api/agent_router.py` 的 schema）。
- [ ] Commit: `feat(settings): agent preferences surfaced and wired`

### C-6: StockChart vs SmartChart vs InlineChart 三套图表组件 —— 合并

**证据:** StockChart 仅 RightPanelChartTab 引用；InlineChart 与 SmartChart 的 line/candle builder 重复。
- [ ] Step 1: RightPanelChartTab 改用 SmartChart 的 ref 模式（传 symbol + 真数据 fields）；`git rm` StockChart。
- [ ] Step 2: InlineChart 的 buildLineOption/buildCandleOption 与 SmartChart 对应 builder 合并到一处（08 Task 6 的主题重写时顺路做，放 `charts/builders` 或先合入 SmartChart）。
- [ ] Commit: `refactor(charts): one chart component family — StockChart removed, builders deduped`

### C-7: rag-inspector / cost-audit —— 移出主导航，收进设置

**证据:** 两页是内部诊断工具（RagInspectorPage 1412 行），出现在普通用户导航里加重"这产品是给开发者用的"感。
- [ ] Step 1: 路由保留（直链可达），Sidebar 入口删除（08 Task 7 已做则登记）；SettingsModal「高级」区加「诊断工具」链接组（RAG Inspector / 成本审计 / 开发者模式开关）。
- [ ] Commit: `chore(nav): diagnostics pages accessible via settings advanced section only`

### C-8: 订阅/邮件提醒入口 —— 提升

**证据:** SubscribeModal 存在但入口深；预警是核心卖点之一却难被发现。
- [ ] Step 1: Sidebar「订阅与提醒」入口（08 Task 7 结构已含）→ 打开一个聚合页/抽屉：邮件订阅管理（SubscribeModal 内容平铺）+ 监控规则跳转（workbench MonitorConfigPanel 的深链）。
- [ ] Commit: `feat(alerts): first-class subscriptions & alerts entry`

### C-9: `/api/supabase` 前端残留 ——【盘点】

**证据:** 前端 4 处引用 `/api/supabase`（client.ts 等），后端 24 个 router 无此前缀。
- [ ] Step 1【盘点】: `grep -rn "/api/supabase" frontend/src` 逐处看语义：若是走 Supabase 官方 SDK 的相对路径拼接则改注释澄清；若是调不存在的后端端点则为死代码 → 删除该调用及其 UI 分支。结论写 notes。
- [ ] Commit: `chore(frontend): resolve phantom /api/supabase references`

### C-10: daily_tasks / task_generator 任务质量 ——【盘点】

**证据:** TaskSection 从 `/api/tasks` 拉"今日任务"（task_generator 自动生成），生成质量未知——若任务是"看看 AAPL"这种水话，就是摆设感的直接来源。
- [ ] Step 1【盘点】: 读 `backend/services/task_generator.py` 的生成规则 + 实际调一次看输出。判据：任务是否可执行（有明确对象+动作+入口）。
- [ ] Step 2 分支 a（质量可）：TaskCard 加"去执行"按钮直连对应功能（分析→chat 预填；盯盘→monitor 配置）；分支 b（水话）：TaskSection 改为由**真实信号**驱动——只显示三类：watchlist 异动（monitor findings）、晨报待读、报告待对比，删除生成式任务。
- [ ] Commit: `feat(workbench): tasks are real signals with execute actions (or pruned)`

### C-11: Workbench 重定位 ——「今日驾驶舱」信息架构（"工作台不知道是干嘛的"的根治）

**现状:** MorningBriefCard + TaskSection + RebalanceEntryCard + ReportSection 四个孤岛卡片堆放（Workbench.tsx:133-401），没有回答"我为什么每天要来这"。
**目标信息架构（按晨间工作流纵向叙事）:**

```
  今日 · 7月3日 周五                        [生成晨报] 上次 08:30
  ─────────────────────────────────────────────────────
  ① 晨报速览        3 条要点 · 每条带「深入 →」(B-7)
  ② 需要你注意      监控发现 2 条(B-4) + 到价提醒 1 条 —— 空则显示"一切平静"
  ③ 我的持仓        SummaryBar + [分析持仓](B-6) + [再平衡建议]
  ④ 研究归档        最近报告时间线 · 每份[继续追问](B-3) [对比] [回测](WP6 F7)
```

- [ ] Step 1: Workbench.tsx 按上述四段重排（组件全部复用现有：MorningBriefCard/FindingsFeed/PortfolioSummaryBar/RebalanceEntryCard/ReportSection，只动布局与段落标题）；段标题规格 `text-2xs uppercase tracking-wider text-t-text3`；顶部日期行 + 主操作。
- [ ] Step 2: 每段空态用 EmptyState 带动作（晨报空→生成；发现空→"一切平静 · 配置监控"；持仓空→录入持仓；报告空→"去对话生成第一份报告"）。
- [ ] Step 3: 路由默认 tab 逻辑不变；截图前后对比。
- [ ] Commit: `feat(workbench): daily-cockpit information architecture — brief / attention / portfolio / archive`

### C-12: thinking/ 与 execution/ 两套过程组件 —— 代码收编

**证据:** `components/thinking/`（ThinkingProcess 等 5 件）与 `components/execution/`（17 件）都在展示"AI 在干嘛"，08 Task 5 已在 UI 层收敛为三层；本条处理代码层。
- [ ] Step 1: `grep -rln "ThinkingProcess\|ThinkingUserView" frontend/src --include="*.tsx" | grep -v thinking/` 确认收敛后的引用面；把仍被引用的 thinking 组件迁入 `execution/`（同域合并），零引用的删除。
- [ ] Commit: `refactor(execution): merge thinking/ components into execution/, drop unreferenced`

---

## Part D: Kansoku 启发的实时联动最小闭环

**范围:** 只做「真实数据 → 纯代码触发 → 有 lease 才运行高频点评 → PostgreSQL 点评流水 → 图表 prediction 深链」。第一期不做持久 Agent 会话、不做模型分层路由重构，也不替换现有 L1 monitor/邮件提醒。

### D-0: 最小 prediction contract / store / submit 基座

**Files:**
- Create: `backend/agents/prediction_contract.py`、`backend/agents/prediction_submit.py`、`backend/services/agent_prediction_store.py`
- Modify: `backend/api/agents_router.py`
- Test: `backend/tests/test_prediction_contract.py`、`backend/tests/test_prediction_submit.py`、`backend/tests/test_agent_prediction_store.py`

**最小合同:** prediction 只允许 `symbol/agent/direction/confidence/thesis/anchor/entry_type/entry/stop/target1/target2/invalidation_price/range_low/range_high`；`extra="forbid"`，严禁 `bars/candles/series/ohlc/data`。`entry_type` 固定为 `market | limit | stop`；long/short 必须有数值 `entry/stop/target1/invalidation_price`，neutral 必须只有包含 anchor 的 range。服务端用现有真实 K 线覆盖最终 anchor time/price，并覆盖 `symbol/agent/user_id/run_id`。

**PostgreSQL:** `agent_predictions` 必须带 `UNIQUE(id, user_id)`，所有读取带 `user_id`；不新增 SQLite。09 只存最小可校验字段，10 Task 5/6 在同表/关联表上扩展 scenarios、历史记忆、outcome 与成本。

- [ ] Step 1: TDD 覆盖 extra 行情字段拒绝、long/short/neutral 字段关系、entry_type、数值 invalidation、RR、伪造 symbol/anchor/user_id 以及跨租户读写隔离。
- [ ] Step 2: 实现 PostgreSQL store 与受鉴权 `GET /api/agents/predictions/{id}`；数据库不可用或无权限时 fail closed，A-4 仍只显示真实行情。
- [ ] Step 3: 实现服务端 `submit_prediction` 校验；仅 concrete ticker 且 operation 属于 `investment_opinion/technical/earnings_impact/report_generation` 的可计分 agent step 暴露工具。首次非法可纠正一次，第二次仍非法则不落库；其他 agent/tool/qa/macro step 允许零提交且不得被迫造价位。
- [ ] Step 4: 固化逐 bar 入场规则：market 从 anchor 后首根完整 bar 入场；limit 仅在 bar 区间触及 entry 时入场；stop 仅在顺方向穿越 entry 时入场；入场前触及 `invalidation_price` 为 invalidated；跳空按首个可交易 bar 的 open 保守成交。同 bar 入场并同时触及 stop/target 时判 hit_stop。
- [ ] 验收: 09 不依赖 10 即可创建、校验、鉴权读取 prediction 并供 ECharts overlay/monitor 使用；非法 prediction 和 AI 行情数组均无法入库。
- [ ] Commit: `feat(prediction): minimal server-validated postgres prediction foundation`

### D-1: 纯代码触发库 + 心跳判定

**Files:**
- Create: `backend/services/monitor_signals.py`
- Modify: `backend/services/monitor_engine.py`
- Test: `backend/tests/test_monitor_signals.py`、`backend/tests/test_monitor_engine.py`

**接口:**

```python
@dataclass(frozen=True)
class MonitorTrigger:
    kind: str          # level_break | zone_break | day_level_break | macd_cross | flow_flip | volume_spike | heartbeat
    detail: str        # 同时进入点评 prompt 与前端「触发」行
    observed_at: str
    severity: str      # info | warn | alert

def detect_triggers(*, previous: MarketSnapshot, current: MarketSnapshot,
                    prediction: AgentPrediction | None) -> list[MonitorTrigger]: ...  # AgentPrediction 来自 D-0
def heartbeat_due(*, last_comment_at: datetime | None, now: datetime,
                  interval_seconds: int = 300) -> bool: ...
```

- [ ] Step 1: TDD 覆盖价位上/下穿、zone 进入/离开、MACD 柱符号翻转、资金流零轴抖动抑制（末值绝对值小于峰值 5% 不触发）、量能大于前 20 根均量 3 倍，以及 5 分钟心跳边界。所有测试使用固定行情 fixture，禁止 mock LLM。
- [ ] Step 2: 实现无 I/O 的纯函数触发库；所有价格、指标和 prediction 都作为显式参数传入。`detail` 必须包含触发前值、触发后值和命中的命名价位，供日志、prompt、点评流复用。
- [ ] Step 3: 在 `monitor_engine` 增加无调度副作用的 `evaluate_realtime_snapshot(previous, current, prediction, last_comment_at, now)`，只返回 triggers（显式信号优先，只有无显式信号且心跳到期时才返回 heartbeat），不得直接调用 LLM 或写库。
- [ ] Step 4: 盘前/休市等市场时段沿用 FinSight 现有 market-hours 与市场映射，不写死 ET、不接 Longbridge。行情缺字段时返回可诊断的 data-gap 结果，不把缺数据伪装成 heartbeat 成功。
- [ ] 验收: 固定输入的 trigger 输出逐字节稳定；重复调用纯函数无外部副作用；heartbeat 在第 299 秒为 false、第 300 秒为 true，且显式 trigger 与 heartbeat 不重复发两条。
- [ ] Commit: `feat(monitor): deterministic trigger library and heartbeat policy`

### D-2: 页面 lease 门控（没人看，不跑高频 AI）

**Files:**
- Create: `backend/services/monitor_lease_store.py`、`frontend/src/hooks/useMonitorLease.ts`
- Modify: `backend/api/monitor_router.py`、`backend/services/monitor_engine.py`、`backend/api/lifespan.py`、`frontend/src/pages/Dashboard.tsx`
- Test: `backend/tests/test_monitor_lease_store.py`、`backend/tests/test_monitor_router.py`、`frontend/src/hooks/useMonitorLease.test.ts`

**PostgreSQL 表:** `monitor_page_leases(id UUID, user_id TEXT, session_id TEXT, symbol TEXT, lease_token_hash TEXT, expires_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`；唯一约束为 `(user_id, lease_token_hash)`，并建 `(user_id, session_id, symbol, expires_at)` 查询索引，允许同一用户的两个页面实例各持一个 lease。默认 TTL 90 秒，只存 token hash，不存明文 lease token。

- [ ] Step 1: TDD 覆盖 acquire/renew/release/过期清理、不同 user 同 symbol 隔离、伪造 user_id 无效，以及两个页面实例分别持有 lease 时关闭一个不会误释放另一个。
- [ ] Step 2: FastAPI 增加 `POST /api/monitor/leases`、`PUT /api/monitor/leases/{id}`、`DELETE /api/monitor/leases/{id}`；user_id 从鉴权上下文取得，renew/release 同时校验 lease token 与租户。数据库或鉴权不可用时 fail closed，不启动高频 AI。
- [ ] Step 3: `useMonitorLease(symbol)` 在 Dashboard/技术图表可见且页面非 hidden 时 acquire，每 30 秒 renew；`visibilitychange`、symbol 变化和 unmount 时 release。网络瞬断允许服务端 TTL 自然回收，前端不得无限重试。
- [ ] Step 4: 在现有 lifespan scheduler 装配 60 秒实时 tick，并用 PostgreSQL advisory lock 保证多 worker 只有一个 tick 执行。每个未过期 lease 自身创建一个临时高频 target；若同 symbol 已有持久 monitor target 则继承其阈值，否则用只读默认阈值。仅有 trigger/heartbeat 才进入 LangGraph L2/点评调用；原有低频持仓扫描/邮件提醒不受 lease 影响。
- [ ] 验收: 打开两个 symbol 页面即只运行对应两个临时高频目标（无需预建 monitor target）；关闭后 90 秒内停止；直接伪造请求不能为其他用户续租；PostgreSQL 中无永不过期 lease；连续运行 10 分钟 60 秒 tick 无重入、无活跃 lease 时 LLM 调用为 0、heartbeat 每 symbol 最多 5 分钟一次。
- [ ] Commit: `feat(monitor): tenant-safe page leases gate high-frequency AI monitoring`

### D-3: 点评流 + prediction 图表深链

**Files:**
- Create: `backend/services/monitor_comment_store.py`、`frontend/src/hooks/useMonitorCommentFeed.ts`、`frontend/src/components/workbench/MonitorCommentFeed.tsx`
- Modify: `backend/api/monitor_router.py`、`backend/services/monitor_engine.py`、`frontend/src/components/workbench/FindingsFeed.tsx`、`frontend/src/components/SmartChart.tsx`
- Test: `backend/tests/test_monitor_comment_store.py`、`backend/tests/test_monitor_router.py`、`frontend/src/components/workbench/MonitorCommentFeed.test.tsx`

**PostgreSQL 表:** `monitor_comments(id UUID, user_id TEXT, session_id TEXT, symbol TEXT, ts TIMESTAMPTZ, level TEXT, text TEXT, trigger_kind TEXT, trigger_detail TEXT, source TEXT, escalated BOOLEAN, prediction_id UUID NULL)`；`FOREIGN KEY(prediction_id, user_id) REFERENCES agent_predictions(id, user_id)`，数据库层阻止跨租户错误关联。服务端根据 id 生成 `/dashboard/{symbol}?analysis={prediction_id}`，数据库不存前端 URL。

- [ ] Step 1: TDD 固化点评合同 `{ts,symbol,level,text,trigger,source,escalated,prediction_id}`，验证租户隔离、时间倒序、日期筛选、分页游标和相同 trigger 指纹去重。点评必须能追溯到 D-1 的 trigger；heartbeat 使用 info，异常使用 error。
- [ ] Step 2: 补生产者 TDD：D-2 scheduler 把 trigger + 真实 snapshot + 可选 prediction 交给 bounded LangGraph commentator，服务端校验 `{level,text,source,escalated,prediction_id}` 后绑定原 trigger 并写 `monitor_comments`；模型失败/非法输出写一条去重的 `source=system, level=error` 诊断，禁止静默丢失或写入别人的 prediction_id。
- [ ] Step 3: FastAPI 提供 `GET /api/monitor/comments` 与项目现有 SSE/事件通道的 comment 增量事件；订阅先返回当日快照，再发增量。断线重连按 `last_event_id` 补发并去重，不引入 Fastify/独立 WebSocket 服务。
- [ ] Step 4: `MonitorCommentFeed` 渲染倒序时间流、level 徽标、触发原因、agent/system 署名、升级状态；连续 heartbeat info 折叠为「HH:mm-HH:mm 无事 xN」，alert 未读数复用现有 workbench 状态。
- [ ] Step 5: 有 `prediction_id` 的点评显示「查看图表」深链；Dashboard 解析 `analysis` 参数，鉴权读取 prediction 后交给 A-4 overlay，并把视窗定位到 anchor 时间。无权限/已删除 prediction 返回 404，页面保留真实行情且不给出来源泄露提示。
- [ ] 验收: 从一条 level_break 点评可一键进入同 symbol 图表并看到 anchor/entry/stop/target；刷新深链仍可恢复；心跳折叠后 alert 不被折叠；两个用户不能互读点评或 prediction。
- [ ] Commit: `feat(monitor): attributable comment feed with replay and prediction chart deep-links`

---

## 09 完成门禁

- [ ] Part A: 让模型回答"画一下 AAPL 最近走势"→ 出的是真数据图（有来源徽标）；诱导模型输出内联价格图 → 不渲染或带「AI示意」标
- [ ] Part B: 八条联动逐条手工走通（B-8 由 WP6 验收）；每条录一段 5 秒操作视频贴 PR
- [ ] Part C: 12 条处置全部落地或按分支归档结论到 notes；`grep -rn "ResearchCard\|StockChart" frontend/src` → 0
- [ ] Part D: 固定行情回放触发结果确定；无 lease 时高频 LLM 调用为 0；有 lease 时 heartbeat/trigger 点评可重放并深链到同一 prediction anchor
- [ ] 技术栈反例: 依赖清单无 Longbridge、`pi-agent-core`、Fastify、`lightweight-charts`；新增 lease/comment/prediction 数据只落 PostgreSQL，不新增 SQLite 文件
- [ ] 综合场景验收（模拟新用户 10 分钟）: 欢迎页进入 → 问一只票 → 点 ticker 进看板 → 看板问 AI → 加自选 → 工作台看晨报点深入 → 全程无死链、无"这是什么"时刻
