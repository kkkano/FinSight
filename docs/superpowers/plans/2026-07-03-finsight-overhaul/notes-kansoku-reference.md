# Kansoku（Innei/kansoku）调研笔记 — 为 FinSight 找可借鉴设计

> 调研日期：2026-07-08。方法：shallow clone 全量源码阅读（README + `app/server/src/ai/*` + `app/web/src/charts/*` + `app/shared/types.ts` + realtime 层）。
> 定位：kansoku 是**个人美股交易研究工作台**（交易日志仓库 + Agent Skill 集 + 本地实时图表应用），不是多用户产品。它的图表应用 `app/` 与 FinSight 的"AI 股票分析"高度同题，且它把「AI 盯盘 → 点评 → 升级重估 → 落图 → 事后对账」做成了完整闭环，正好是 FinSight 09（联动）和 10（Agent 原生化）在找的东西。

---

## ① 项目概览（技术栈 / 架构）

### 三层仓库结构

1. **数据源层**：Longbridge 长桥 SDK/CLI（行情、K 线、资金流、新闻、持仓）+ FRED / SEC EDGAR / GDELT / Yahoo Finance 等 Python skill（stdlib-only，统一 `{"ok":true,data,meta}` 输出协议）。
2. **编排工作流层**：Claude Code skill（`stock-deep-dive` / `intraday-signal` / `sepa-strategy` 等），人工会话触发。
3. **落档层**：markdown（journal/stocks）为主记录 + `journal/charts/data/*.json` 图表快照（带 schema_version）+ SQLite `app.db` 运行流水。

### 图表应用 `app/`（本次重点）

- **pnpm workspace 三包**：`shared/`（跨包类型 + 时间工具）、`server/`、`web/`。
- **server**：Fastify 5 + TypeScript，**以 middleware 模式内嵌 Vite dev server**，单进程无打包。数据存储 better-sqlite3 + drizzle（4 张表：`comments` 点评流水、`ai_usage` AI 花费、`chart_meta` 图表索引、`outcomes` 预测结局缓存）。**全部技术指标由服务端 TS 实算**：EMA/MACD/RS/趋势模板/成交分布/14 种 K 线形态/1-2-3 反转/背离背驰/FVG 缺口/盘前盘后时段。
- **web**：React 19 + Vite 8 + **lightweight-charts 4.2**（K 线类图）+ **Recharts 3**（资金流曲线/柱状对比）+ react-markdown。无状态管理库（hooks + WS 订阅）。
- **AI 框架**：`@earendil-works/pi-agent-core` 的 `Agent` 类（轻量 agent loop：systemPrompt + typebox schema 工具 + prompt()），模型经 `provider/id` 环境变量分层配置（`AI_COMMENT_MODEL` / `AI_ANALYST_MODEL` / `AI_DEEPDIVE_MODEL`），缺失即停用对应层、服务照常启动。
- **实时层**：统一 WebSocket `/api/ws`，一个 socket 多频道订阅（quotes/chart/comments/analyses/position/benchmark/board），每频道 emitter 带**最后状态重放 + 指纹去重 + degraded 状态位**，15s ping 保活。
- **架构总纲**（README 原话）：**"server 内置 AI 是廉价高频窄视野的哨兵，CLI + skill 是昂贵低频全视野的参谋"** —— 两条路径产物同格式（intraday 图 + 点评流），但明确不互相替代。

---

## ② AI K 线分析实现细节（数据流 + prompt 构造 + 锚定机制）

### 2.1 两层 AI + 调度器（`server/src/ai/`）

**调度器 `scheduler.ts`**：`setInterval` 60s tick + `ticking` 互斥防重入，按美东时段分流：

- **正常盘（09:30–16:00 ET）**：对每个目标 symbol → 拉数据包 → 纯代码检测触发信号 → 有信号或心跳到点才调点评员。
- **盘前（04:00–09:30）**：5 分钟一轮，**纯机械零 AI 花费**——跳空 ≥2% 写系统提示（≥3% 用 warn 级），附盘前高点，按 `symbol@date` 去重。
- **盘后**：自动生成当日 recap markdown（预测结局、点评统计、警报清单、AI 花费），当天已存在就跳过。

**监控目标发现**：`discoverIntradayTargets` = 当天有 intraday 分析图的标的 ∩ **有活跃 lease 的标的**。lease 机制（`leases.ts`）：cockpit 页面 WS 订阅时 `acquireLease(symbol)`，断开后 90s 宽限——**没人看的页面不烧钱**，这是最聪明的成本控制。

**心跳（heartbeat）**：`shouldHeartbeat(lastRunAt, now)` = 距上次点评员运行 ≥5 分钟。无触发信号时心跳兜底，Trigger 为 `{kind:"heartbeat", detail:"定时心跳巡检，无显式触发"}`——保证点评流不会长时间静默，用户能确认"哨兵活着"。

### 2.2 触发信号检测（`triggers.ts`，193 行纯函数，零 AI）

6 种触发，全部是最后两根 5m 收盘价/最新值的确定性判断：

| kind | 逻辑 |
|---|---|
| `macd_cross` | MACD hist 最后两值符号翻转（金叉/死叉） |
| `level_break` | 收盘价上/下穿预测的 entry/stop/target1/target2 |
| `zone_break` | 进入/离开/穿越预测画的支撑阻力区间（进入=entered、离开=exited upward/downward） |
| `day_level_break` | 上/下穿昨日高低/盘前高低/开盘半小时区间（6 个命名价位） |
| `flow_flip` | 累计资金流翻正负，**带峰值比抑制**（\|last\| < 5%·peak 不触发，防零轴附近每 tick 抖动） |
| `volume_spike` | 最新一根量 > 3× 前 20 根均量 |

每个 Trigger 带人话 `detail`（如 `Price broke above target1 187.2 (186.9 -> 187.5)`），多信号并发时 `combineTriggers` 拼接。**这个 detail 直接进 prompt 也直接显示在前端点评的「触发：」字段**——一份文本两用。

### 2.3 数据包构造（`datapack.ts`）——喂给 LLM 的核心

**点评员数据包 `CommentPack`**（并行 7 个请求组装）：

```
{ symbol, as_of,
  quote,                                   // 实时报价（含时段）
  m5: { bars: 尾部48根5mK线, macd: {dif,dea,hist} 同长尾部 },
  flow: 当日资金流曲线,
  prediction: {chartId, direction, anchor, entry, stop, target1, target2, zones},  // 已归档预测摘要
  recent_comments: 最近5条点评,             // 让 AI 知道自己说过什么
  day_levels: { prev_day 高低收, pre_market 高低, opening_range 高低 },
  rel_volume: 相对量能（今日累计÷前5日同时段均值） }
```

**Prompt 构造**：没有花哨模板——**`JSON.stringify({pack, trigger}).slice(0, 24_000)` 直接作为 user message**。系统提示词（中文，9 行）讲清楚 JSON 里有什么、纪律是什么（两句话中文白话、level 三档语义、escalate 只在结论与预测相反或触及止损/目标时 true、必须调 submit_comment 工具）。

**会话复用 + 增量更新**（省 token 的关键设计）：每 symbol 每交易日一个持久 Agent 会话。首次发全量 pack；同日后续触发只发 `buildCommentUpdate` 增量（新增 K 线 + 对应 MACD 尾部 + 最新报价 + 资金流尾 10 行 + opening_range），**prediction/昨日价位/历史点评已在会话上文里不重发**，吃 prompt cache。回收护栏：≥40 次运行或累计发送 ≥120K 字符即弃会话重建；模型没调工具（违约）也立刻弃会话，防污染缓存前缀。

**分析员数据包 `ReassessPack`**：m5/m15/h1 三周期各 60 根 K 线 + 每周期结构摘要（`IntradayTfSummary`：EMA 末值、摆动高低点、最后交叉、背离/背驰候选、MACD 结构信号、K 线形态、123 形态）+ 资金流 + 相对量能 + 日内价位 + **SPY/QQQ 大盘参照** + 新闻前 6 条 + 已归档预测 + 持仓对照。

### 2.4 分析员（`analyst.ts`）——升级重估 + 落图

触发：点评员 `escalate=true`（同 symbol 30 分钟冷却）或手动按钮。10 分钟超时。5 个工具：

- `read_data_pack`（拉 ReassessPack，内存缓存）
- `fetch_kline`（补拉周期，count 上限 500）/ `fetch_news`
- `append_comment`（边看边写观察）
- `submit_prediction`（**终结工具**，必须恰好调一次）

**系统提示词是一份完整的"判读纪律 + 结论纪律"**（值得逐条抄）：先定催化日/平静日（有能动价的新闻则技术面情景概率封顶 40）；逆大盘结论必须给理由；无量突破按存疑；direction 三选一；**anchor 必填**；long/short 必须给 entry_plan 且止损必须依托具体结构；**T1 盈亏比不足 1:1 的计划不准提交**；neutral 不给 entry_plan 但必须给箱体 low/high；scenarios 2–4 个概率合计约 100；不给仓位建议（拿不到账户数据）。

**服务端二次校验 `validatePrediction`**：typebox schema 校验 + 业务规则（概率和 100±10、多单止损须低于入场、RR≥1、neutral 箱体必须包住锚点价……），**不合法时把 issues 文本返回给模型让它修正后重调**——工具即校验回路，这是让小模型输出可靠结构化预测的关键。

**落图**：校验通过 → `createChart({type:"intraday", symbol, origin:"analyst", prediction})` 生成新图表文档 → 写一条带 `chartId` 的点评 → 经 WS notice 频道推「分析完成」通知。

### 2.5 锚定机制（分析结果 ↔ 图表时间点/价位的对账闭环）★ 全项目最精华

1. **产生时锚定**：`submit_prediction` 强制 `anchor: {timeframe, time, price}`——"没有锚点的预测事后无法对账"写进 prompt。
2. **渲染时锚定**：前端在对应 timeframe 上画三样——锚点 bar 的**背景高亮**（`AnchorBgPrimitive`）、`🎯 锚 $价格` 虚线价位线、方向 marker（做多▲/做空▼/观望●）。entry/stop/T1/T2 各一条 `createPriceLine`，支撑阻力区间画上下沿线。
3. **状态机推进**：`resolveEntryPlanStatus`（`services/intraday.ts`）每次重算时从锚点时间起扫 K 线，判定计划状态 `waiting/triggered/invalidated/stopped`（未触发入场但价格走破入场-止损中线 = invalidated），**价位线标题实时带后缀**「入场 $187.20（已失效）」且变灰虚线。
4. **事后对账**：`outcomes` 表缓存已了结结局（`hit_target/hit_stop/held_range/broke_range/open`）+ `pct_since_anchor`；历史分析列表每条显示 ✅到目标/⛔到止损/⏳进行中；总览页战绩统计**按方向（long/short/neutral）和来源（analyst vs manual）分桶算命中率**——AI 落的图带 `origin:"analyst"`，人和 AI 的战绩分开对账，"定期看两边命中率对比来校准信任度"。

### 2.6 成本与用量治理

每次 AI 运行经 `attachAiUsageLogger` 记 token/成本进 SQLite（按 layer：commentator/analyst/deepdive 分层），`/api/overview/usage` 可按日查询。加上 lease 门控、30 分钟升级冷却、24K prompt 截断、会话缓存复用、盘前纯机械——一整套"敢让 AI 一天跑几百次"的费控组合拳。

---

## ③ 图表层实现细节

### 3.1 库选型：TradingView Lightweight Charts v4（K 线）+ Recharts（普通图）

K 线主图与 MACD 副图是**两个独立 chart 实例**，用 `syncTimeScales` 双向同步可视区间；主图与副图之间有拖拽分隔条（高度记忆在 localStorage）。成交量在主图内用 `priceScaleId:"vol"` + `scaleMargins:{top:0.75}` 压到底部 25% 区域，与 K 线纵向分区不遮挡。

### 3.2 标注体系（三种画法各司其职）

| 手段 | 用途 | 实现 |
|---|---|---|
| **`createPriceLine`** | 入场/止损/T1/T2/锚点/支撑阻力沿 | 原生价位线，title 带中文与价格（`入场 $187.20（待触发）`），计划失效整体变灰 |
| **`setMarkers` + 自制 tooltip** | K 线形态、MACD 结构信号、预测锚点、买卖点 | `SeriesMarker` 带 `text`（形态名/图标）、`tooltip`（含义+确认价+失效价+历史胜率）、`group`（归属开关组）。lightweight-charts 无原生 marker tooltip，自己实现了 `markerTooltip`（监听 crosshair 命中 marker 显示浮层） |
| **`attachPrimitive` 自定义绘制** | 时段背景（盘前/盘后/夜盘整高色块）、FVG 缺口矩形、锚点 bar 背景高亮、用户手绘 | v4 primitives API，Canvas 自绘。用户手绘（趋势线/水平线/矩形/斐波那契）单独一套 `drawings/` 状态机 + 渲染器，经 `/api/annotations` 持久化 |
| **动态 LineSeries** | 背离/背驰连接线 | 每条背离一条虚线 series（价格图和 MACD 图各一条，交叉印证），tab 切换时整批 remove 重建 |

### 3.3 标注开关按钮组（截图里的 AI 标注开关）

`OverlayGroup = "ai" | "divergence" | "beichi" | "pattern123" | "candle"` + ema/fvg/levels/crosses。每个 marker/connector 带 `group` 字段，前端 `filterByGroup` 统一过滤，开关状态存 localStorage（`useIndicatorToggles`）。**服务端产出时就打好 group 标签，前端只做过滤**——增删标注类型不用改前端开关逻辑。

### 3.4 服务端指标实算（LLM 永远不生成图表数据）

14+ 种 K 线形态检测带**趋势背景过滤 + 实体大小过滤 + 同根只留最强**；每个形态带 `status`（pending/confirmed/invalidated/expired，3 根内未确认即过期）和 `stats`（该形态在本标的历史样本中的胜率 `{sample, wins}`）。MACD 结构信号分类（零上/零下金叉死叉、二次金叉=底部确认、空中加油、零轴缠绕警示）。**所有 K 线/指标/形态数据都来自行情 API + 服务端计算，AI 只产出 prediction（方向/锚点/价位/情景），图表数据与 AI 判断严格分离**。

### 3.5 实时更新不打扰交互

图表数据 60s 重拉重算经 WS 推送，前端 `setData` 原地更新：记录更新前 visible range，右端追加新 bar 时**平移 range 而非 `scrollToRealTime()`**（避免动画抖动）；左端补历史（滚到左缘 10 根内触发 `onNearLeftEdge` 加载更多）时 range 加偏移量，**用户的缩放/平移永不被重置**。

---

## ④ AI 点评面板设计（右侧 AI 点评 tab）

### 4.1 数据结构（`CockpitComment`，SQLite `comments` 表）

```ts
{ ts: string;                       // ISO 时间戳
  symbol: string;
  level: "info" | "warn" | "alert" | "error";   // error=系统故障也进流
  text: string;                     // 中文白话，点评员限两句
  trigger?: string;                 // "kind: detail" 人话触发原因 → 前端「触发：」行
  source: "commentator" | "analyst" | "system";
  escalated?: boolean;              // 本条触发了升级重估 → 前端「已升级重估」标
  chartId?: string; }               // 关联图表 → 前端「查看图表」链接（?analysis=id 深链）
```

### 4.2 交互细节（`AiTab.tsx` + `aiFeed.ts`）

- **倒序时间流**，每条 = 时间（美东钟面）+ level 徽标（warn=accent 色、alert=红、error=实底）+ 正文 + 元信息行（触发原因 / 已升级 / 查看图表 / 来源署名「分析员」「系统」——点评员 info 不署名且淡显）。
- **「无事折叠」**：连续的 `info` 级点评员心跳点评折叠成一行「10:05 – 10:35 无事 ×6（点击展开）」——高频哨兵不淹没重点，这是心跳机制能落地的配套关键。
- **历史日期下拉**：今天没点评自动回退显示最近有点评的一天并提示。
- **「重新分析」按钮**：手动触发分析员（409=已在跑），运行中按钮转 Spinner，**完成信号靠监听点评流里出现新的 analyst/system 条目**（不额外做状态轮询），10 分钟兜底超时。
- **未读徽标**：alert/提醒未读数显示在 tab 标签上；alert 级实时经 WS comments 频道推送；分析完成/深挖成败走 notice 频道 → 前端顶部横幅（截图里的「AI 提醒」横幅）。
- **WS init 重放**：订阅时先发当日全量 `{type:"init", comments}`，随后增量 `{type:"comment"}`，服务端对订阅建立期间的并发点评做 `ts+text` 去重。

### 4.3 顶层看板联动

`/api/overview` 今日看板每行：方向、现价、**离止损/目标百分比**、最新点评、警报计数、预测是否过期（staleness）——点评流的数据同时喂总览，一份流水多处消费。

---

## ⑤ 对 FinSight 的可借鉴清单

> FinSight 前端 ECharts（非 lightweight-charts），后端 FastAPI + LangGraph。以下按「借鉴什么 / 对应模块 / 成本 / 归属工作包」列出，按价值排序。

| # | 借鉴什么 | 对应 FinSight 模块/页面 | 成本 | 工作包 |
|---|---|---|---|---|
| 1 | **预测锚点 + 事后对账闭环**：agent 产出观点时强制 `anchor{time,price}` + entry/stop/target 结构化落库；纯代码判定结局（hit_target/hit_stop/open）缓存进 `outcomes` 类表；**按 agent 来源分桶算命中率**。这正是 10 号文档「agent 没有战绩」诊断的现成答案，且 kansoku 证明判定层零 AI 成本 | 后端 agents 产出 schema + 新 outcomes 表 + Agent 档案页战绩区（10 Part 2） | **L**（但可拆：先只做落锚+结局判定 M，战绩 UI 后补） | **10** |
| 2 | **submit 工具 + 服务端校验回路**：终结工具带 typebox/pydantic 校验，业务规则不过就把 issues 文本返回让模型重试（RR≥1、概率合计 100、止损方向正确）。FinSight 各 agent 的结构化输出可靠性可以照此加固，LangGraph 节点内即可实现 | `backend` 各 agent 的输出解析层（WP2 编排产物之上） | **S–M** | **10**（Part 1 协作协议一并做） |
| 3 | **触发信号库 + 心跳巡检调度器**：6 种纯函数触发（macd_cross/level_break/zone_break/day_level_break/flow_flip 带抖动抑制/volume_spike）+ 5 分钟心跳 + 60s tick 互斥 + 时段分流（盘前纯机械零成本）。`triggers.ts` 193 行可近乎直译成 Python 给 FinSight 监控/晨报系统 | 后端 monitor 模块（09 联动线中的"监控发现"上游） | **M** | **09**（监控联动条目）或 WP6 监控增强 |
| 4 | **点评流数据结构与 UI 范式**：`{ts, level, text, trigger, source, escalated, chartId}` + level 徽标 + 触发原因行 + 署名 + 关联图表深链 + **info 心跳折叠**。直接回答 10 号「监控发现全部匿名」和 09 号「功能之间没联动」：每条发现带 agent 署名 + 可跳转证据图表 | 前端工作台/监控面板新「动态流」组件 + 后端 comments 类表 | **M** | **10**（Part 3 感知层）UI 规范归 **08** |
| 5 | **图表真实性铁律：LLM 永不生成图表数据**。kansoku 全部 K 线/指标服务端实算，AI 只产出 prediction 引用真数据。为 09 Part A（inline 图表禁渲染）提供了参照架构：AI 输出只含 `{direction, anchor, levels, zones}`，前端拿真实 K 线 + 这份轻量标注渲染 | `SmartChart`/`InlineChart` 改造（09 A-1/A-2） | **S**（架构原则，落地即 09 Part A 本身） | **09** |
| 6 | **AI 标注锚定到图表**：ECharts 等价物——价位线=`markLine`（label 带状态后缀「已失效」变灰）、锚点=`markPoint`+`markArea` 背景、支撑阻力区=`markArea`、背离连线=额外 series。加**分组开关按钮组**（数据侧打 group 标签，前端统一过滤，localStorage 记忆） | 前端 K 线图组件（TERMINAL 主题图表层之上） | **M** | **08**（图表主题统一 Task 内或紧后） |
| 7 | **成本治理组合拳**：分层模型env配置（缺失即停用不崩溃）、每次运行记 token/成本流水（按 layer/agent 分组可查）、升级冷却、页面 lease 门控（没人看不跑）、prompt 截断上限 | 后端 LLM 调用层 + 设置/总览页花费卡片 | **M** | **10**（战绩/花费同属 agent 档案）；lease 思路可用于 FinSight 实时功能 |
| 8 | **点评员/分析员两层哨兵模式**：便宜模型高频窄视野扫描 + 贵模型低频全视野重估，escalate 语义明确（仅在与既有观点相反或触及关键价位时升级）。可作为 FinSight「监控 agent → 完整研究管线」的升级链路设计 | LangGraph 编排（WP2 产物之上）+ monitor | **L**（依赖 #1 #3 先行） | **10**（远期）/ WP6 |
| 9 | **实时更新不重置用户视角**：追加数据平移 visible range 而非滚动动画；WS 频道 init 重放 + 指纹去重 + degraded 状态位（连续失败退避并亮黄点） | 前端 WS/轮询数据层 + 图表组件 | **S** | **09**（体验联动）/ **08** |
| 10 | **形态标注带教学 tooltip + 历史胜率**：每个标注 tooltip 给「含义 + 确认/失效条件 + 本标的历史样本胜率」，`AUTO_SIGNAL_META` 集中管理文案。FinSight 的技术面洞察卡可复用此文案结构 | 前端图表 tooltip + 洞察卡 | **S**（文案结构）/ M（含形态检测后端） | **08**（文案与 tooltip 规范） |

**建议的最小落地顺序**：#5（原则，随 09 Part A）→ #2（S，立即提升输出可靠性）→ #4（点评流骨架）→ #1（锚点+对账，10 号的核心弹药）→ #3/#6 → 其余。

---

## ⑥ 不建议照搬的部分及原因

1. **Longbridge 数据源与美股单一市场假设**：kansoku 的时段分类（ET 硬编码）、盘前盘后逻辑、资金流大中小单口径全部绑长桥美股。FinSight 有自己的数据源体系，只抄触发/锚定的**逻辑**，不抄数据接入。
2. **`pi-agent-core` agent 框架**：小众框架（作者关联生态），FinSight 已有 LangGraph；抄它的**工具契约与校验回路模式**即可，不引依赖。
3. **单用户本地信任模型**：SQLite 单文件、deep-dive agent 直接写仓库 markdown 文件、无鉴权无租户。FinSight 是多用户 Web 产品（WP5 方向），点评/结局/花费需按 user 维度建 PostgreSQL 表，写文件类工具（deep-dive 的 `write_note`）整个模式不适用。
4. **Fastify 内嵌 Vite middleware 单进程模式**：适合本地个人工具，与 FinSight 的 FastAPI + 前后端分离部署（Cloudflare Tunnel）架构冲突，无迁移价值。
5. **换图表库为 lightweight-charts**：诱人但 FinSight 已深投 ECharts，且 08 号文档规划的是 ECharts 主题统一。lightweight-charts 的 primitives/priceLine 能力在 ECharts 里都有等价物（markLine/markPoint/markArea/graphic）。**除非未来专门做专业 K 线工作台页，否则不换库**。
6. **点评员会话复用（prompt cache 优化）第一期不做**：SESSION_MAX_RUNS/字符护栏、违约弃会话等细节复杂度不低，是 kansoku 一天几百次调用逼出来的优化。FinSight 监控频率低得多，先用无状态单次调用，量上来再抄。
7. **macOS 通知等桌面耦合残留**：kansoku 自己也在迁移到 WS notice 频道，FinSight 直接走 Web 内通知即可。
8. **「journal 文件为主记录」的落档哲学**：这是个人交易日志仓库的定位使然；FinSight 的主记录在数据库，不需要 markdown 落档层。

---

## 附：关键源码文件索引（本地 clone：`C:\Users\EDY\AppData\Local\Temp\kansoku`）

| 主题 | 文件 |
|---|---|
| 调度器/心跳/时段分流 | `app/server/src/ai/scheduler.ts` |
| 触发信号检测（可直译） | `app/server/src/ai/triggers.ts` |
| 数据包构造/增量更新/截断 | `app/server/src/ai/datapack.ts` |
| 点评员（会话复用 + submit 工具） | `app/server/src/ai/commentator.ts` |
| 分析员（系统提示词 + validatePrediction + 落图） | `app/server/src/ai/analyst.ts` |
| 页面 lease 门控 | `app/server/src/ai/leases.ts` |
| 类型总纲（CockpitComment/IntradayPrediction/Outcome/Stats） | `app/shared/types.ts` |
| 入场计划状态机 + marker 生成 | `app/server/src/services/intraday.ts` |
| K 线渲染（价位线/marker/primitive/视角保持） | `app/web/src/charts/intraday/useIntradayCharts.ts` |
| AI 点评面板 UI | `app/web/src/pages/cockpit/AiTab.tsx` |
| WS 多频道 + init 重放 | `app/server/src/routes/ws.ts`、`app/server/src/realtime/emitter.ts` |
