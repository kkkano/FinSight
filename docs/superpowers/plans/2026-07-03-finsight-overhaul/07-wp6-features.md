# WP6 新功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 8 个功能：Phase Labs 收编（F0）、A股数据源补强（F1）、自选股 watchlist（F2）、报告分享链接（F3）、SSE 断点续传（F4）、移动端/PWA（F5）、组合归因（F6）、报告→回测联动（F7）。通知渠道（Telegram/飞书）**明确不在本期范围**。

**Architecture:** 每个功能独立可发布，F 之间无硬依赖；F2/F6 依赖 WP5 的 user_id（无 WP5 时以 `user_id="public"` 降级运行）；F4 依赖 WP2 的事件通道但不依赖其 flag。功能一律走"后端 API+测试 → 前端入口 → 手工验收"三段。

**Tech Stack:** 新依赖需批准：`akshare`（F1）、`vite-plugin-pwa`（F5）。其余零新依赖。

## Global Constraints

- 每个 F 完成即可独立上线，不允许跨 F 的半成品耦合。
- 新端点一律进 OpenAPI 快照（WP4 Task 4 的测试会强制同步 TS 类型）。
- 新表全部自带 `user_id TEXT NOT NULL DEFAULT 'public'`（复用 WP5 `ensure_column`/建表模板）。

---

### F0: Phase Labs 收编与导航整理

**动机:** "Phase Labs / Phase 2.4 面板"是内部迭代术语，screener/backtest 藏在里面没有正经入口（产品盘点结论）。

**Files:**
- Modify: `frontend/src/App.tsx`（路由）、`frontend/src/components/Sidebar.tsx`、`frontend/src/components/labs/Phase24PanelsPage.tsx`（拆出）
- Create: `frontend/src/pages/ScreenerPage.tsx`、`frontend/src/pages/BacktestPage.tsx`（从 Phase24PanelsPage 中把对应面板组件提升为页面）

**Tasks:**
- [x] T1: 读 `Phase24PanelsPage.tsx`，列出其中的面板组件清单；把 screener 面板、backtest 面板分别包成独立 Page（复用组件本体，不重写）。
- [x] T2: 路由改造：`/screener`、`/backtest` 两条一级路由（EntryGuard 包裹，与 /chat 同级）；`/phase-labs` 保留 302 跳转到 `/screener`（外链兼容一个版本）。Sidebar 增两个入口（图标沿用项目 lucide 图标库习惯：`Filter`、`FlaskConical`）。
- [x] T3: 提醒/订阅入口：Sidebar 或设置里给"邮件订阅管理"一个可发现入口（现状订阅入口过深；复用现有订阅组件，只加导航）。
- [x] 验收：三个新入口可达且功能同旧；`/phase-labs` 跳转正常；`pnpm build` 绿。
- [x] Commit: `feat(nav): promote screener/backtest to first-class pages, retire Phase Labs naming`

---

### F1: A股数据源补强（akshare 接入价格级联）

**动机:** A股级联只有 yfinance 一条腿（`price.py:492-498`），晚间/限流时 A 股基本不可用。

**Files:**
- Modify: `backend/tools/price.py`、`requirements.txt`（`akshare==1.*`，需批准）
- Test: `backend/tests/test_cn_price_sources.py`

**Interfaces:**

```python
def _fetch_with_akshare_spot(ticker: str) -> str | None:
    """ticker 为 Yahoo 格式（600036.SS）。ak.stock_zh_a_spot_em() 全量快照太重，
    用 ak.stock_bid_ask_em(symbol='600036') 或 ak.stock_individual_info_em 轻接口（实现时二选一，
    以"单票、<2s、字段含最新价与涨跌幅"为准）。返回与其他源一致的英文句式：
    'The current price of {ticker} is ${price} (CNY {price}), change {pct}% (source: akshare/eastmoney)'
    ——保持 $ 数字在文本中以兼容 ladder 正则（WP0 T1 已解耦，不强制）。失败返回 None。"""

def _fetch_with_akshare_hist(ticker: str, period: str = "1y") -> dict | None:
    """ak.stock_zh_a_hist(symbol, period='daily', adjust='qfq')，映射到项目历史数据 dict 结构
    （对照 _fetch_with_stooq_history 的返回键：dates/open/high/low/close/volume…以实际为准逐键对齐）。"""
```

**Tasks:**
- [x] T1: 失败测试（mock akshare 模块——`sys.modules` 注入 fake，断言 A 股级联顺序为 `[_fetch_with_akshare_spot, _fetch_with_yfinance, _fetch_yahoo_api_v8, _search_for_price]`，以及 akshare 成功时返回格式含价格）。akshare 为**惰性导入**（函数体内 import，未安装时函数返回 None 并 debug 日志，不炸整个模块）。
- [x] T2: 实现两个 fetcher；`get_stock_price` 的 `is_china` 分支与 `get_stock_historical_data` 的 A 股路径插入为首选。
- [ ] T3: 联网冒烟脚本（不进 CI）：`python -c "from backend.tools.price import get_stock_price; print(get_stock_price('600036'))"` 交易时段人工跑一次，输出贴 PR。
- [x] Commit: `feat(cn-market): akshare as primary A-share price/history source with lazy import fallback`

---

### F2: 自选股 Watchlist

**动机:** 现有功能是孤岛：快捷建议硬编码、晨报/监控与用户关注的票无关联。watchlist 是把它们串起来的枢纽。

**Files:**
- Create: `backend/services/watchlist_store.py`、`backend/api/watchlist_router.py`、`backend/tests/test_watchlist.py`
- Modify: `backend/api/main.py`（或 app_factory 注册表）+ 前端 `frontend/src/api/domains/market.ts`、`frontend/src/components/Sidebar.tsx`、`frontend/src/components/ChatInput.tsx`（快捷建议动态化）

**API 契约:**

```
GET    /api/watchlist                → {"items": [{"ticker": "AAPL", "note": "", "added_at": "…"}]}
POST   /api/watchlist {ticker,note?} → 201 {"item": {…}}   # ticker 规范化复用 normalize_ticker；重复添加幂等返回 200
DELETE /api/watchlist/{ticker}       → 204
```

**存储:** SQLite 表 `watchlist(user_id TEXT NOT NULL DEFAULT 'public', ticker TEXT NOT NULL, note TEXT DEFAULT '', added_at TEXT NOT NULL, PRIMARY KEY(user_id, ticker))`，store 写法对齐 `portfolio_store` 现有模式。

**Tasks:**
- [x] T1: store + router TDD（增/删/幂等/隔离四用例）→ 注册 router → OpenAPI 快照同步。
- [x] T2: 前端：Sidebar "自选" 区块（列表 + 快速跳 dashboard）；dashboard 股票页加 ☆ 收藏切换；ChatInput 底部快捷建议改为 `watchlist 前 4 只生成`（空则回退现有硬编码 4 条）。
- [x] T3: 联动：晨报生成入参与 monitor 默认标的列表接 watchlist（`grep -rn "morning_brief" backend/services` 找到标的来源处，watchlist 非空则优先）。
- [x] 验收：加两只票 → 快捷建议/晨报/监控默认值全部跟着变；匿名与登录态数据隔离。
- [x] Commit: `feat(watchlist): user watchlist store/api/ui wired into suggestions, morning brief and monitor defaults`

---

### F3: 报告分享链接

**Files:**
- Modify: `backend/services/report_index.py`（加列 `share_token TEXT`、`shared_at TEXT`）、`backend/api/report_router.py`
- Create: `frontend/src/pages/SharedReportPage.tsx`（只读渲染，无需登录）
- Test: `backend/tests/test_report_share.py`

**API 契约:**

```
POST /api/reports/{report_id}/share        → {"share_url": "/share/r/{token}"}   # token=secrets.token_urlsafe(24)；重复调用返回同一 token
DELETE /api/reports/{report_id}/share      → 204（撤销）
GET  /api/reports/shared/{token}           → 报告只读 JSON（脱敏：剥离 trace/cost/内部诊断字段，白名单键输出）
```

`GET /api/reports/shared/*` 加入 `API_PUBLIC_PATHS` 白名单语义（security_gate 白名单机制已支持前缀通配：配置 `API_PUBLIC_PATHS` 默认值追加 `/api/reports/shared/*`）。

**Tasks:**
- [x] T1: TDD：创建分享→匿名可读；撤销→404；脱敏断言（响应 JSON 不含 `trace`/`cost`/`tool_diagnostics` 键）。
- [x] T2: 前端路由 `/share/r/:token`（不进 EntryGuard），复用现有报告渲染组件的只读态；报告页加"分享"按钮（复制链接 + 撤销入口）。
- [x] 验收：无痕窗口打开分享链接可读、撤销后 404；分享页无任何操作按钮。
- [x] Commit: `feat(report): shareable read-only report links with revocation and field whitelisting`

---

### F4: SSE 断点续传（UX-05/UX-09 根治）

**动机:** 断线只能整条重发；`synthetic_done` 把截断伪装成完成。

**Files:**
- Create: `backend/api/stream_replay.py`、`backend/tests/test_stream_replay.py`
- Modify: `backend/api/chat_router.py`（事件写入 replay 缓冲；新增续传端点）、`frontend/src/api/sse.ts`、`frontend/src/hooks/useChatStream.ts`

**后端契约:**

```python
# stream_replay.py
class ReplayBuffer:
    """run_id → deque[(seq:int, event_json:str)]，maxlen=2048；全局 LRU 上限 64 个 run，TTL 15 分钟。"""
    def append(self, run_id: str, event: dict) -> int    # 返回递增 seq
    def replay_from(self, run_id: str, after_seq: int) -> list[tuple[int, str]] | None  # None=run 未知/过期

# chat_router 改造：
# 1) 现有 SSE 生成器发出的每个事件包上 "seq" 字段并写入 ReplayBuffer（run_id 已存在于事件流——grep -n "run_id" backend/api/chat_router.py 确认字段名）。
# 2) 新端点 GET /api/chat/stream/{run_id}?after_seq=N →
#    a. run 仍在进行：先补发 buffer 中 > N 的事件，然后桥接后续实时事件（复用现有 emit 通道的订阅机制）
#    b. run 已结束：补发剩余事件 + done 事件后关闭
#    c. run 未知/过期：410 Gone（前端据此走 recoverReportIfAvailable 兜底）
```

**前端契约:** `sse.ts` 的 `withStreamGuards` 扩展：`onError`/读超时后自动执行至多 2 次指数退避（1s/4s）的 `GET /api/chat/stream/{runId}?after_seq={lastSeq}` 续传；续传也失败才把错误抛给 UI，同时 UI 文案区分"已断线，正在重连…" / "连接中断，内容可能不完整 [重试]"（替换 `synthetic_done` 伪完成——`grep -n "synthetic_done" frontend/src` 改为发出 `connection_lost` 状态）。

**Tasks:**
- [x] T1: ReplayBuffer TDD（append/replay/TTL/LRU 四用例）。
- [x] T2: chat_router 事件包 seq + 写缓冲（对既有前端零破坏：多一个字段）。
- [x] T3: 续传端点 TDD（testclient：先消费一半 → 带 after_seq 续传 → 事件不重不漏）。
- [x] T4: 前端自动重连 + 文案改造；手工验收：开发者工具断网 5s 再恢复 → 回答续上不重发；彻底断网 → 明示"内容可能不完整 + 重试"。
- [x] Commit: `feat(stream): seq-tagged SSE with replay buffer and client auto-resume; honest connection-lost state`

---

### F5: 移动端可用性 + PWA

**Files:**
- Modify: `frontend/vite.config.ts`（vite-plugin-pwa，需批准）、`frontend/index.html`、`frontend/public/`（icons/manifest 由插件生成）
- Modify: `frontend/src/components/WorkspaceShell*.tsx`（`grep -rln "WorkspaceShell" frontend/src`）、`ChatInput.tsx:1072-1104`（快捷建议 `flex-wrap`）

**Tasks:**
- [ ] T1: 响应式审计清单落地（≤768px）：侧栏抽屉化（汉堡开合）、执行指挥台默认收起、dashboard 标签横向可滚动、快捷建议 `flex-wrap`、触控目标 ≥44px 抽查。每项一个小 commit。
- [ ] T2: PWA：manifest（name=FinSight AI、theme_color 取项目主色、display=standalone）+ SW 仅缓存静态资源（`workbox.runtimeCaching` 明确排除 `/api/**`，SSE 不可缓存）。
- [ ] 验收：手机浏览器走一遍聊天+看板核心流程无横向滚动条；Lighthouse PWA 检查通过"可安装"。
- [ ] Commit: `feat(mobile): responsive shell + installable PWA (static assets only, api excluded)`

---

### F6: 组合归因分析

**动机:** `get_factor_exposure`/`run_portfolio_stress_test`/`get_performance_comparison`（`backend/tools/price.py:1818/1915/2013`）原料齐备，没有产品出口。

**Files:**
- Create: `backend/api/attribution_router.py`、`backend/tests/test_attribution.py`
- Create: `frontend/src/components/workbench/AttributionPanel.tsx`
- Modify: workbench 装配（`grep -n "PortfolioPerformance" frontend/src/pages/Workbench.tsx` 附近挂新面板）

**API 契约:**

```
POST /api/portfolio/attribution
body: {"positions": [{"ticker": "AAPL", "weight": 0.4}, …], "lookback_days": 252}
→ {
    "beta": 1.12, "factor_exposure": {…get_factor_exposure 原样…},
    "contribution": [{"ticker": "AAPL", "weight": 0.4, "return_pct": 18.2, "contribution_pct": 7.3}, …],
    "benchmark": {"symbol": "SPY", "return_pct": 11.0},
    "as_of": "2026-07-03"
  }
# contribution 算法：各票 lookback 区间收益率 × 权重；数据取 _download_close_frame（价格工具已有）。
# 无持仓 → 422 带引导文案；单票数据缺失 → 该票 contribution 置 null 并在 "warnings" 数组说明，不整体失败。
```

**Tasks:**
- [ ] T1: 后端 TDD（mock `_download_close_frame` 返回构造 DataFrame：两票已知收益 → 断言 contribution 数学正确、缺数据票进 warnings）。
- [ ] T2: 前端面板：贡献瀑布图（ECharts bar，复用 `useChartTheme`）+ beta/因子卡片；从 PortfolioEditor 现有持仓一键计算。
- [ ] 验收：录入两只票 → 归因面板出图，权重改动结果联动。
- [ ] Commit: `feat(portfolio): attribution endpoint + workbench panel on existing factor/stress tooling`

---

### F7: 报告→回测联动

**动机:** 研究结论到策略验证断链；差异化亮点。

**Files:**
- Create: `backend/api/backtest_prefill.py`（纯函数，挂在 backtest_router）
- Modify: `backend/api/backtest_router.py`、报告前端组件（`grep -rn "ReportSection\|ReportCompare" frontend/src/components/workbench` 的报告操作区）、`frontend/src/pages/BacktestPage.tsx`（F0 产物）

**契约:**

```
POST /api/backtest/prefill-from-report {"report_id": "…"}
→ {"config": {"tickers": [...主标的...], "strategy": "buy_and_hold" | "ma_cross",
              "start": "<报告日期-1y>", "end": "<报告日期>",
              "rationale": "由报告《{title}》生成：主标的 {tickers}，观点 {stance}"}}
# 映射规则（纯规则，不调 LLM）：报告结论 stance 字段（grep -n "stance\|rating\|观点" backend/graph/report_builder.py 确认实际字段）
#   bullish → buy_and_hold；neutral/bearish → ma_cross（保守双均线）；策略枚举取 backend/services/backtest_strategies.py 现有实现集合。
```

**Tasks:**
- [ ] T1: prefill 纯函数 TDD（三种 stance → 三种 config；报告缺 stance → 默认 buy_and_hold + warning）。
- [ ] T2: 报告页操作区加"🧪 回测此观点"按钮 → 跳 `/backtest?prefill={report_id}`，BacktestPage 读参调 prefill 端点填表单。
- [ ] 验收：任一份历史报告一键生成可运行回测并出净值曲线（BacktestEquityChart 复用）。
- [ ] Commit: `feat(backtest): one-click backtest prefilled from research report stance`

---

## WP6 完成门禁

- [ ] 每个 F 独立满足自己的验收行；全量 `pytest` + `pnpm test:unit && pnpm build` 绿
- [ ] OpenAPI 快照与 TS 类型同步（WP4 门禁复跑）
- [ ] 手机 + 桌面各过一遍核心流程录屏留档

---

## 明确不做（本期 YAGNI 清单）

- Telegram / 飞书 / 企业微信通知渠道（主人指示暂缓）
- 消息列表虚拟化之外的前端大改（等 WP1 数据说话）
- SQLite → PostgreSQL 业务数据迁移（写 ADR 后另立项）
- LLM key 服务端加密存储（SEC-04，另立项）
- i18n 框架 / 英文界面（先做 zh 常量表）
