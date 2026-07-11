# 08 前端视觉与交互彻底重构 Implementation Plan（TERMINAL 设计语言）

> **For agentic workers:** 按 Task 顺序执行，每个 Task 一次 commit。本文档假设执行者是初级模型：所有样式给出**具体数值与完整代码**，禁止自由发挥配色与间距；拿不准时逐字复制本文档的值。

**基线 commit:** `4a1c055`（行号漂移以 grep 锚点为准）
**Goal:** 消灭"廉价 AI 模板感"：统一两套割裂的设计系统（欢迎页 `--bb-*` 终端风 vs 应用内 `--fin-*` 蓝色 SaaS 风）为一套**专业金融终端语言（代号 TERMINAL）**；对话区去气泡化、假进度条换真实阶段步进器、执行过程收敛为一条工作日志流、图表主题统一并标注数据来源。

**Architecture:** 自底向上五层：Token 层（CSS 变量 + Tailwind）→ 原子组件规范层 → 对话区 → 过程可视化区 → 页面层（导航/看板/工作台/欢迎页归一）。上层只允许使用下层定义的 token 与组件规范。

**设计立场（不可讨价还价的三条）:**
1. **深色优先**。金融终端的原生语境是深色；浅色作为完整适配的次要主题保留。
2. **等宽数字**。一切数值（价格、百分比、时间戳）必须 mono + `tabular-nums`；涨跌用语义 token `t-up/t-down`，禁止直接写红绿色值。
3. **信息密度 > 留白**。圆角收紧（卡片 8px、控件 6px、内边距 12px），删除一切渐变头像、彩虹渐变、弹跳动画。

## Global Constraints

- 允许的新依赖（需主人批准一次）：`@fontsource-variable/jetbrains-mono`（自托管等宽字体）。不批准则用系统 mono 栈回退，任务照常执行。
- **纯表现层重构**：不改任何 API 调用与业务逻辑；与 WP1/WP4 同文件冲突时先做逻辑 WP 再做本文档。
- 每个 Task 结束跑 `cd frontend && pnpm test:unit && pnpm build`；视觉 Task 附截图到 PR。
- 旧 `--fin-*` 变量经 Task 1 别名后仍有效，允许渐进迁移；但每个 Task 完成后，其负责区域内**禁用清单必须清零**。

**禁用清单（grep 可查的"廉价感"来源）:**
`bg-gradient-to-br from-blue-500`、`from-emerald-500 to-teal-600`、`animate-bounce`、`animate-ping`、对话与卡片区的 `rounded-xl`、深色模式下的 `shadow-lg`、写死的 `text-blue-400`/`#3b82f6` 类涨跌色、emoji 状态图标（✅❌⚠️ 换 lucide 单色图标）。

---

### Task 1: TERMINAL Token 层落地

**Files:**
- Modify: `frontend/src/index.css`（`:root` 与 `:root.dark` 两段整体替换 + 新增工具类）
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/main.tsx`（字体 import）
- Create: `frontend/src/styles/tokens.md`

- [x] **Step 1: 替换 `index.css` 变量段**（基线 5-45 行两个 `:root` 块）为：

```css
:root {
  /* ===== TERMINAL · 浅色 ===== */
  --t-bg: #f4f5f7;            /* 页面底 */
  --t-surface: #ffffff;        /* 面板 */
  --t-card: #ffffff;           /* 卡片 */
  --t-elevated: #f8f9fb;       /* 卡片内嵌块 */
  --t-border: #e2e5ea;
  --t-divider: #edeff3;
  --t-hover: #f0f2f6;

  --t-text: #17191d;
  --t-text-2: #565e6a;
  --t-text-3: #8a93a1;

  --t-accent: 224 122 24;      /* #E07A18 终端橙，rgb 三元组供 alpha */
  --t-accent-hi: #c96a0e;

  --t-up: #0f9960;             /* 涨（国际默认绿涨）*/
  --t-down: #d13d3d;
  --t-warning: #b97509;
  --t-info: #2f6fd0;
  --t-predict: #7048e8;

  --t-chart-grid: #e8eaef;
  --t-shadow-card: 0 1px 2px rgb(16 18 24 / 0.06);
}

:root.dark {
  /* ===== TERMINAL · 深色（主态）===== */
  --t-bg: #0a0c10;
  --t-surface: #10131a;
  --t-card: #12161f;
  --t-elevated: #171c27;
  --t-border: #232b3a;
  --t-divider: #1a2130;
  --t-hover: #182031;

  --t-text: #e8eaed;
  --t-text-2: #9aa3b2;
  --t-text-3: #5b6472;

  --t-accent: 255 138 0;       /* #FF8A00 */
  --t-accent-hi: #ffa133;

  --t-up: #2fbf7f;
  --t-down: #ff5d5d;
  --t-warning: #f5a623;
  --t-info: #6b9eff;
  --t-predict: #9775fa;

  --t-chart-grid: #1a2130;
  --t-shadow-card: none;       /* 深色不用投影，靠边框分层 */
}

/* ===== 旧 token 兼容别名（迁移期 --fin-* 全部有效）===== */
:root, :root.dark {
  --fin-bg: var(--t-bg);
  --fin-bg-secondary: var(--t-surface);
  --fin-card: var(--t-card);
  --fin-panel: var(--t-elevated);
  --fin-border: var(--t-border);
  --fin-hover: var(--t-hover);
  --fin-text: var(--t-text);
  --fin-text-secondary: var(--t-text-2);
  --fin-muted: var(--t-text-3);
  --fin-primary: var(--t-accent);
  --fin-success: var(--t-up);
  --fin-danger: var(--t-down);
  --fin-warning: var(--t-warning);
  --fin-predict: var(--t-predict);
}

/* ===== A股红涨绿跌模式（Task 9 在设置里接线）===== */
:root.cn-colors { --t-up: #d13d3d; --t-down: #0f9960; }
:root.dark.cn-colors { --t-up: #ff5d5d; --t-down: #2fbf7f; }

/* ===== 全局数字规范 ===== */
.num, .tabular {
  font-family: 'JetBrains Mono Variable', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}

/* ===== 终端光标（替代三点弹跳）===== */
@keyframes t-caret { 0%, 45% { opacity: 1; } 50%, 100% { opacity: 0; } }
.t-caret::after {
  content: "▍";
  color: rgb(var(--t-accent));
  animation: t-caret 1s steps(1) infinite;
  margin-left: 2px;
}

/* ===== 价格闪动（数据更新反馈）===== */
@keyframes t-flash-up { 0% { background: color-mix(in srgb, var(--t-up) 22%, transparent); } 100% { background: transparent; } }
@keyframes t-flash-down { 0% { background: color-mix(in srgb, var(--t-down) 22%, transparent); } 100% { background: transparent; } }
.t-flash-up { animation: t-flash-up 0.5s ease-out; }
.t-flash-down { animation: t-flash-down 0.5s ease-out; }

/* ===== 骨架屏 ===== */
@keyframes t-shimmer { 0% { background-position: -400px 0; } 100% { background-position: 400px 0; } }
.t-skeleton {
  border-radius: 4px;
  background: linear-gradient(90deg, var(--t-elevated) 25%, var(--t-hover) 37%, var(--t-elevated) 63%);
  background-size: 800px 100%;
  animation: t-shimmer 1.4s ease-in-out infinite;
}
```

（文件其余部分——滚动条、`.card` 等 @apply 段——保留，它们引用的 `--fin-*` 自动吃到新值。）

- [x] **Step 2: tailwind.config.js**：`colors` 里 `fin` 同级新增 `t` 组（双轨过渡，不删 fin）：

```js
        t: {
          bg: 'var(--t-bg)', surface: 'var(--t-surface)', card: 'var(--t-card)',
          elevated: 'var(--t-elevated)', border: 'var(--t-border)', divider: 'var(--t-divider)',
          hover: 'var(--t-hover)', text: 'var(--t-text)', text2: 'var(--t-text-2)', text3: 'var(--t-text-3)',
          accent: 'rgb(var(--t-accent) / <alpha-value>)', 'accent-hi': 'var(--t-accent-hi)',
          up: 'var(--t-up)', down: 'var(--t-down)', warning: 'var(--t-warning)', info: 'var(--t-info)',
        },
```

`fontFamily.mono` 数组最前插入 `'"JetBrains Mono Variable"'`。

- [x] **Step 3: 字体**（依赖获批时）：`pnpm add @fontsource-variable/jetbrains-mono`，`main.tsx` 顶部 `import '@fontsource-variable/jetbrains-mono';`。未批 → 跳过本步。

- [x] **Step 4:** 写 `src/styles/tokens.md` 速查表（约 20 行）：背景四层怎么选（页面=bg、面板=surface、卡片=card、卡内块=elevated）、文字三层（正文=text、辅助=text2、元信息=text3）、涨跌必用 t-up/t-down、accent 只用于主操作/焦点/进行中、圆角表（卡 8 / 控件 6 / chip 4）。

- [x] **Step 5:** `pnpm build` + 全站肉眼过一遍（整体换肤为终端橙但布局未动）。
Commit: `feat(ui): TERMINAL design tokens — unified palette, tabular numerals, caret/flash/skeleton primitives`

---

### Task 2: 原子组件规范化

**Files:**
- 先 `ls frontend/src/components/ui/` 盘点既有原子件；Modify: `ui/Card.tsx` 及既有 Button/Tag 类
- Create: `ui/Stat.tsx`、`ui/EmptyState.tsx`、`ui/Skeleton.tsx`、`ui/SourceBadge.tsx`

**规范表（后续所有 Task 引用此表，禁止另造）:**

| 组件 | 规格（类名逐字用） |
|---|---|
| Card | `rounded-lg border border-t-border bg-t-card p-3`；标题行 `text-[13px] font-semibold text-t-text mb-2`；浅色加 `shadow-[var(--t-shadow-card)]` |
| Button primary | `h-8 px-3 rounded-md bg-t-accent text-[13px] font-medium text-black/90 hover:bg-t-accent-hi transition-colors`（橙底黑字=终端惯例） |
| Button ghost | `h-8 px-3 rounded-md border border-t-border text-[13px] text-t-text2 hover:border-t-accent/60 hover:text-t-text transition-colors` |
| Tag/chip | `inline-flex items-center h-[22px] px-2 rounded text-2xs font-mono border border-t-border bg-t-elevated text-t-text2`；语义只变文字色不变底 |
| Stat | 标签 `text-2xs uppercase tracking-wider text-t-text3` + 值 `num text-lg text-t-text` + 变化 `num text-xs` 涨 `text-t-up` 前缀▲ / 跌 `text-t-down` 前缀▼（▲▼ 字符，非 emoji） |
| Skeleton | `t-skeleton` + 显式宽高；任何 >300ms 的加载必须骨架屏，禁止裸 spinner 占满卡片 |
| EmptyState | 竖排居中：lucide 图标 20px `text-t-text3` + 一句话 `text-sm text-t-text2` + 一个 ghost Button 主操作；**每个空状态必须带动作**，禁止裸"暂无数据" |
| SourceBadge | `<SourceBadge source="yfinance" asOf="2026-07-03" degraded={false} synthetic={false}/>` → `text-2xs font-mono text-t-text3`；degraded 前缀 ⚠（`text-t-warning`）；synthetic=true 显示 `AI示意` 徽标（`border border-t-warning/50 text-t-warning px-1 rounded`）。**所有图表与数据卡片右上角必挂**（09 的真实性治理靠它落地） |

- [x] Step 1: 按表逐个实现/改造（新建四件按规格即完整需求）。
- [x] Step 2: `grep -rn "rounded-xl" frontend/src/components/ui` → 0。
- [x] Step 3: Commit: `feat(ui): atomic spec — Card/Button/Tag/Stat/Skeleton/EmptyState/SourceBadge`

---

### Task 3: 对话区去廉价化（核心区域）

**Files:**
- Modify: `frontend/src/components/ChatList.tsx`
- Modify: `frontend/src/components/ChatInput.tsx`

**目标形态（ASCII，深色）:**

```
                                          +--------------------------------+
                                          | 分析一下 AAPL 最近的财报        |   <- 用户：右对齐轻色块
                                          +--------------------------------+
  FS| FinSight · 14:32 · [价格] [基本面]                    <- AI：无框文档流，元信息一行
  |
  |  苹果 FY25Q3 营收 940.4 亿美元（+6.1% YoY），超市场预期…
  |
  |  + 营收与净利趋势 --------------- yfinance · 07-03 +   <- 图表卡右上角 SourceBadge
  |  |     ▂▃▅▆█ …                                     |
  |  +---------------------------------------------------+
  |  数据源: FMP ⚠yfinance(降级)   截至: 2026-07-03
     [复制] [重试] [导出]                                    <- hover 才显现
  ^ 左侧 2px 橙色竖线贯穿整条 AI 回答
```

- [x] **Step 1: 用户消息**（锚点 `grep -n "rounded-tr-sm" ChatList.tsx`，基线 275-278）：容器类改 `max-w-[72%] rounded-lg bg-t-elevated border border-t-border/60 px-3.5 py-2.5 text-sm leading-relaxed text-t-text`；删除用户侧头像。

- [x] **Step 2: AI 消息去气泡**：AI 分支删除 `bg-fin-panel border … rounded-*` 容器与两个渐变头像 div（基线 305-308），改为：

```tsx
<div className="group relative pl-4 border-l-2 border-t-accent/70">
  <div className="flex items-center gap-2 mb-1.5 text-2xs font-mono text-t-text3">
    <span className="text-t-accent font-semibold">FS▎</span>
    <span>FinSight</span>
    <span className="num">{formatTime(message.timestamp)}</span>
    {message.agents?.map(a => <Tag key={a}>{AGENT_LABELS[a] ?? a}</Tag>)}
  </div>
  <div className="prose-terminal text-sm leading-[1.7] text-t-text">{/* 现有 markdown 渲染 */}</div>
</div>
```

（`AGENT_LABELS` 中文名表：价格/新闻/基本面/技术面/宏观/风险/深搜——新建常量放 `src/config/agentLabels.ts`。）

- [x] **Step 3: Markdown 排版类 `prose-terminal`**（追加进 index.css）：

```css
.prose-terminal h1, .prose-terminal h2 { font-size: 15px; font-weight: 600; margin: 14px 0 6px; }
.prose-terminal h3 { font-size: 13px; font-weight: 600; color: var(--t-text-2); margin: 12px 0 4px; }
.prose-terminal table { font-size: 12.5px; width: 100%; border-collapse: collapse; }
.prose-terminal th { text-align: left; color: var(--t-text-3); font-weight: 500; border-bottom: 1px solid var(--t-border); padding: 4px 8px; }
.prose-terminal td { border-bottom: 1px solid var(--t-divider); padding: 4px 8px; }
.prose-terminal td:not(:first-child) { font-family: 'JetBrains Mono Variable', monospace; font-variant-numeric: tabular-nums; text-align: right; }
.prose-terminal code { background: var(--t-elevated); border: 1px solid var(--t-border); border-radius: 4px; padding: 0 4px; font-size: 12px; }
.prose-terminal blockquote { border-left: 2px solid var(--t-border); color: var(--t-text-2); padding-left: 10px; margin: 8px 0; }
```

- [x] **Step 4: 加载态**：删除 LoadingDots 三点弹跳（基线 762-768）；流式中最后一个文本节点尾部挂 `t-caret` 类；无文字阶段显示一行 `text-2xs font-mono text-t-text3` 的**真实动作文案**（取 executionStore 最近一条 stage/step 事件，如"正在检索 AAPL 行情…"），不显示任何百分比。

- [x] **Step 5: 操作按钮**：消息底部操作行加 `opacity-0 group-hover:opacity-100 transition-opacity`（触屏 `@media (hover:none)` 下恒显示），按钮用 ghost 规格 + `aria-label`。

- [x] **Step 6: 快捷建议终端化**（ChatInput 底部）：chips 改 `font-mono text-2xs border border-t-border rounded px-2 py-1 text-t-text2 hover:border-t-accent/60 hover:text-t-accent`，文案加前缀 `> `（如 `> 分析 AAPL 财报`），容器补 `flex-wrap`。

- [x] **Step 7: 输入框**：容器 `rounded-lg border border-t-border bg-t-surface focus-within:border-t-accent/70 focus-within:ring-1 focus-within:ring-t-accent/30`；发送按钮 primary 规格；@agent 与 /skill 弹层统一 `bg-t-elevated border border-t-border rounded-md`。

- [x] **Step 8:** 改前/改后截图 + `pnpm test:unit`（类名断言的测试同步改）。
Commit: `feat(chat): document-flow AI replies, terminal caret, real-action loading — kill bubble-template look`

---

### Task 4: 假进度条 → 真实阶段步进器

**Files:**
- Create: `frontend/src/components/execution/StageStepper.tsx`
- Modify: `frontend/src/components/ChatList.tsx`（执行 banner，基线 503-535）

**动机:** 现有 `h-1` 百分比条的数值是硬编码猜测（planner=50、synthesize=88…），一眼假。真实信号是 SSE 的 `pipeline_stage` 事件——直接展示阶段，不编百分比。

**目标形态:**

```
  ● 理解 ── ● 计划 ── ◉ 执行(2/5) ── ○ 综合 ── ○ 撰写      1m24s
  正在运行: 基本面 · 检索 8 季度财报
```

**Interfaces:**

```tsx
export interface StageStepperProps {
  stages: { key: string; label: string; status: 'done' | 'active' | 'pending' | 'error'; detail?: string }[]
  elapsedMs?: number
  currentAction?: string   // 最近一条 step_start 的 "{agent中文名} · {动作}"
}
// detail 例 "2/5" = executing 阶段完成step数/总数，取 executionStore 真实计数
// 视觉: done=实心点 text-t-accent; active=◉ 用 opacity 脉冲(禁 ping); pending=空心 text-t-text3;
// error=text-t-down; 连接线 h-px bg-t-border, done 段 bg-t-accent/60
// 阶段映射(写死): understand→理解, plan→计划, executing→执行, synthesize→综合, render→撰写
```

- [x] Step 1: 实现 StageStepper + vitest 快照（四种 status 渲染断言）。
- [x] Step 2: ChatList 执行 banner 替换：删除百分比条与 `animate-ping` 圆点（基线 511-524），改挂 StageStepper；数据映射复用 executionStore 现有阶段常量（`grep -n "PIPELINE_STAGE" src/store/executionStore.ts`）。
- [x] Step 3: `grep -rn "estimateProgress\|progress_percent" src/components/ChatList.tsx` → 0。
- [x] Step 4: Commit: `feat(execution): honest stage stepper replaces fabricated percentage bar`

---

### Task 5: 执行过程可视化收敛（user/expert/console 三层重整）

**现状:** execution/ 目录 2344 行 17 个组件同屏堆叠，user/expert 界限模糊，agent-log 原始 SSE 面板混在正常 UI——"开发版和用户版显示的东西"混乱的根源。

**目标信息架构（三层，严格分离）:**

```
层1 用户默认(内联聊天): StageStepper + AgentWorkLog 工作日志流 —— 只讲人话
层2 专家抽屉(RightPanel"过程"tab, 手动展开): 瀑布图/统计/决策流 —— 现有 expert 组件收纳
层3 开发者控制台(默认不渲染): agent-log 原始事件 —— localStorage.finsight_dev=1 才有入口
```

**Files:**
- Create: `frontend/src/components/execution/AgentWorkLog.tsx`
- Modify: `RightPanel.tsx`、`execution/ExecutionPanel.tsx`、AgentLogPanel 挂载点（`grep -rn "AgentLogPanel" src --include="*.tsx" | grep -v agent-log/`）

**AgentWorkLog 规格（层1 核心，替代聊天内的 AgentSummaryCards）:**

```
每 agent 一行实时追加，最多显示最近 6 行，完成后折叠为一行摘要 "7 个智能体 · 23 次取数 · 1m24s"
行结构:  [Bot16px] 基本面   检索 8 季度财报…            12.4s ✓
类名: 行 flex items-center gap-2 h-7 text-xs; agent名 w-14 font-medium text-t-text2;
动作 flex-1 truncate text-t-text3; 耗时 num text-2xs text-t-text3
状态: 运行中=Loader2 14px text-t-accent animate-spin(全站唯一允许的spinner);
完成=Check text-t-up; 失败=X text-t-down; 跳过=Minus text-t-text3
数据源: executionStore agentStatuses + step 事件(AgentSummaryCards.tsx:65-70 归一化逻辑搬来复用)
```

- [x] Step 1: 实现 AgentWorkLog（含折叠态；vitest：三种状态行 + 完成折叠断言）。
- [x] Step 2: ChatList 执行 banner 下挂 AgentWorkLog；移除聊天内联的 AgentSummaryCards/ThinkingBubble 重复展示（组件本体保留给层2）。
- [x] Step 3: 层2 收纳：RightPanel execution tab 固定为 ExecutionPanel expert 内容，删除 user/expert 切换 UI（`grep -n "isExpert\|mode ===" execution/ExecutionPanel.tsx`）。
- [x] Step 4: 层3 隔离：AgentLogPanel 渲染入口与按钮包 `localStorage.getItem('finsight_dev') === '1'` 条件；设置「高级」区加开发者模式开关写此 key。
- [x] Step 5: Commit: `feat(execution): three-tier process UX — inline work log / expert drawer / dev-only console`

---

### Task 6: 图表主题统一 + 数据来源标注

**Files:**
- Modify: `useChartTheme` hook（`grep -rn "useChartTheme" src/hooks`）
- Modify: `SmartChart.tsx`、`InlineChart.tsx`、`StockChart.tsx`、`components/dashboard/**` 内直接写 option 的图表

**统一 ECharts 主题（useChartTheme 返回值重写为此规格）:**

```ts
export const terminalChartTheme = {
  textStyle: { fontFamily: "'JetBrains Mono Variable', Menlo, monospace", fontSize: 10.5 },
  grid: { top: 28, right: 12, bottom: 24, left: 48 },
  axisLine: { lineStyle: { color: T('--t-border') } },
  splitLine: { lineStyle: { color: T('--t-chart-grid'), type: 'solid' } },
  axisLabel: { color: T('--t-text-3'), fontSize: 10 },
  tooltip: { backgroundColor: T('--t-elevated'), borderColor: T('--t-border'),
             textStyle: { color: T('--t-text'), fontSize: 11 },
             axisPointer: { type: 'cross', lineStyle: { color: T('--t-text-3'), type: 'dashed' } } },
  colorPalette: ['#FF8A00','#6B9EFF','#2FBF7F','#9775FA','#F5A623','#FF5D5D','#4DD4E8','#C0CA33'],
  candle: { up: T('--t-up'), down: T('--t-down'), border: 'transparent' },
}
// T() = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
// （ECharts 不认 CSS var，必须读算后值；现有 hook 已随主题重算，沿用其机制）
```

- [x] Step 1: useChartTheme 重写为上表；清零图表硬编码色：`grep -rn "#1e2028\|#3b82f6" src/components | grep -i chart` → 0。
- [x] Step 2: 大数据图切 canvas：SmartChart 基线 1649-1655 `renderer: 'svg'` → 点数>200 的 K线/长序列用 `'canvas'`，小型饼/条保持 svg。
- [x] Step 3: SourceBadge 接线：四处图表组件右上角统一挂 `<SourceBadge/>`——ref 模式传真实 source/asOf（chart_ref 响应字段，`grep -n "source\|as_of" SmartChart.tsx` 对齐）；**inline 模式一律 `synthetic={true}`**（数据是 LLM 生成的——与 09 文档 Task A 联动）。
- [x] Step 4: Commit: `feat(charts): unified terminal ECharts theme, canvas for dense series, source badges everywhere`

---

### Task 7: 导航与布局重组

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx`、`frontend/src/components/layout/**`（`grep -rln "WorkspaceShell" frontend/src`）

**目标结构（Sidebar 从上到下）:**

```
  FINSIGHT ▎             <- wordmark: font-mono font-semibold tracking-[0.12em] text-t-accent
  [ ⌘K 搜索/命令… ]       <- 假输入框样式按钮，点击开 CommandPalette（提升既有功能可见性）
  ── 工作区 ──            <- 分组标题: text-2xs uppercase tracking-wider text-t-text3 px-3 pt-4 pb-1
  ● 对话
  ● 看板
  ● 工作台
  ● A股市场
  ── 工具 ──
  ● 筛选器               <- WP6 F0 收编后的一级入口
  ● 回测
  ── 底部固定 ──
  ● 订阅与提醒            <- 09 文档 C-9 的入口修复
  ● 设置
  （rag-inspector / cost-audit 从导航移除 → 设置>高级>诊断工具，见 09 文档 C-7）
```

- [x] Step 1: 按结构重排；条目规格 `h-9 px-3 rounded-md text-[13px] text-t-text2 hover:bg-t-hover`，激活态 `bg-t-hover text-t-text border-l-2 border-t-accent -ml-px`；图标 lucide 16px。
- [x] Step 2: 宽度 200px → 216px（`grep -n "w-\[200px\]" frontend/src/index.css` 基线 107 行）；<768px 折叠为 56px 图标栏（配合 WP6 F5）。
- [x] Step 3: Commit: `feat(nav): grouped sidebar with command palette entry; diagnostics moved out of primary nav`

---

### Task 8: 欢迎页与应用同语言

**Files:**
- Modify: `frontend/src/components/welcome/WelcomePage.tsx`

**原则:** 欢迎页气质是对的（终端感），问题是它私有一套 `--bb-*`。**保留布局与 aurora 氛围，变量并轨：**

- [x] Step 1: `grep -n "\-\-bb-" WelcomePage.tsx` 列全 bb 变量 → 映射改写：`--bb-bg→--t-bg`、`--bb-surface→--t-surface`、`--bb-border→--t-border`、`--bb-text→--t-text`、`--bb-text-mute→--t-text-3`、`--bb-orange→rgb(var(--t-accent))`；aurora 渐变保留但把蓝紫色值换为 `rgb(var(--t-accent) / 0.15)` 与 `var(--t-info)`（10% 透明）双色。
- [x] Step 2: CTA 按钮/输入框换 Task 2 规格；删除 `paletteVars` 私有调色板对象。
- [x] Step 3: 验收：欢迎页 → 进应用无"换产品"感（录屏对比）。Commit: `refactor(welcome): merge bb-palette into TERMINAL tokens — one product, one skin`

---

### Task 9: 涨跌色习惯开关（A股红涨绿跌）

**Files:**
- Modify: `frontend/src/components/SettingsModal.tsx`（外观区）、`frontend/src/store/useStore.ts`（persist `colorConvention: 'intl' | 'cn'`）

- [x] Step 1: 设置外观区加单选「涨跌配色: 国际(绿涨) / A股(红涨)」，写 store 并 `document.documentElement.classList.toggle('cn-colors', v === 'cn')`（应用启动初始化时同步一次）。
- [x] Step 2: 全站涨跌色改经 `text-t-up/text-t-down`：`grep -rn "text-green-\|text-red-\|text-emerald-\|trend-up\|trend-down" frontend/src --include="*.tsx" | grep -v test` 逐个审计；价格、收益、仓位变化与多空趋势改用 token，成功/失败/告警等非涨跌状态色保持固定；ECharts K线经 Task 6 candle token 自动生效。
- [x] Step 3: vitest：切换 convention 后 documentElement class 断言。Commit: `feat(ui): configurable up/down color convention (intl green-up vs CN red-up)`

---

### Task 10: Dashboard 与 Workbench 卡片视觉统一

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx` + `components/dashboard/tabs/*.tsx`、`frontend/src/pages/Workbench.tsx` + `components/workbench/*.tsx`

- [x] Step 1: 全部卡片换 Task 2 Card 规格（`grep -rn "rounded-xl\|shadow-lg\|shadow-md" src/pages src/components/dashboard src/components/workbench` 清零）；数值展示全部换 Stat 组件（自动获得 tabular-nums 与 ▲▼）。
- [x] Step 2: Dashboard 顶栏改"终端行情条"：symbol + 现价（`num text-2xl`）+ 涨跌 Stat + SourceBadge 一行排布，右侧 tab 切换；AI 洞察评分环颜色走 t token，卡片标注「AI 评分 · 置信度 xx%」。
- [x] Step 3: Workbench 卡片同规格；空态全部换 EmptyState（带动作，如晨报空 →「生成今日晨报」按钮）——信息架构重排在 09 文档 C-11，此处只换皮肤。
- [x] Step 4: 每 tab 截图。Commit: `feat(pages): dashboard & workbench on TERMINAL card/stat spec, actionable empty states`

---

### Task 11: 清扫与回归

- [ ] Step 1: 全仓禁用清单清零验证：

```bash
cd frontend
grep -rn "animate-bounce\|animate-ping\|from-blue-500\|from-emerald-500" src --include="*.tsx" | grep -v test   # 期望 0
grep -rn "rounded-xl" src/components/ChatList.tsx src/components/ChatInput.tsx src/components/dashboard src/components/workbench src/components/execution   # 期望 0
```

- [ ] Step 2: 浅色模式全站过一遍（重点查对比度：正文 ≥4.5:1，devtools 抽查 5 处）。
- [ ] Step 3: `pnpm test:unit && pnpm build`；对话/看板/工作台/欢迎四张截图贴 PR。
- [ ] Step 4: Commit: `chore(ui): sweep banned patterns, light-mode contrast pass`

---

## 08 完成门禁

- [ ] 禁用清单 grep 全零；`pnpm test:unit && pnpm build` 全绿
- [ ] 走查清单（逐条截图/录屏）：
  - 欢迎页 → 应用内：同一设计语言，无"换产品"感
  - 对话：AI 回答无气泡无渐变头像；流式尾部是闪烁光标；进度是阶段步进器而非百分比；表格数字等宽右对齐
  - 执行过程：默认只见步进器 + 工作日志；专家内容收在右栏"过程"tab；控制台仅开发者模式可见
  - 所有图表：同一主题、右上角数据来源徽标；inline 图表带「AI示意」标
  - 涨跌色开关即时生效（含 K 线）
  - 空状态都有下一步动作按钮
