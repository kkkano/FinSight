# 今夜冲刺工作报告（2026-06-02 深夜 → 2026-06-03 早晨）

> 执行人：浮浮酱（Claude Code 自主通宵执行）
> 授权：主人睡前授权"今晚你全部做完 测完 commit 明天我来检查"
> 范围：死代码清障 + P1 防线 + 工作台重构 Phase 1/2 + P2 产品力
> 约束：只 commit 不 push，不部署，不动 .env

---

## 一、完成任务清单

### 第一批：清障 ✅

| 任务 | Commit | 说明 |
|------|--------|------|
| 删除 SupervisorAgent 死代码 | `ad752c6` | supervisor_agent.py(2329行) + langchain_agent.py(628行) + archive/(33文件) + 3个死测试，共 ~8200 行；真实链路（LangGraph 图）不受影响；sentiment_brief.py 完整保留 |
| 测试环境隔离修复 | `b9aa111` | .env 的 TECHNICAL_AGENT_LLM_SUMMARY_ENABLED=1 导致 deterministic summary 测试失败，加 monkeypatch.delenv 隔离 |

**附带发现**：`backend/orchestration/intent_classifier.py` 在删除 supervisor 后变成孤儿（零生产引用），
列为下一轮死代码清理候选（本轮未删，不在批准范围内）。

### 第二批：P1 防线 ✅（10 项全部处理）

| # | 任务 | Commit | 实现说明 |
|---|------|--------|---------|
| P1-1 | 启动时校验 API key | `4a6afe9` | backend/services/startup_check.py：6 个重要数据源 key 缺失显式 WARNING |
| P1-3 | LLM 不可用立即失败 | `4a6afe9` | 启动验证 LLM endpoint；不可用时 chat 端点 503 快速失败，不再让用户等超时 |
| P1-2 | SSE 流断开检测 | `c14e2ae` | parseSSEStream 30 秒读超时（VITE_SSE_READ_TIMEOUT_MS），心跳帧会重置计时 |
| P1-8 | 429 限流前端提示 | `c14e2ae` | EventTarget 事件总线 + RateLimitToastListener，带 Retry-After 秒数 |
| P1-4 | 执行失败 vs 质量拦截 | `ab8f385` | failure_kind=execution_error/quality_gate 区分；**真实根因比路线图预想更糟**：报告构建崩溃时质量门控不拦截，用户看到"执行完成"+半截内容 |
| P1-5 | 单请求 token 预算 | token budget commit | LLM_REQUEST_TOKEN_BUDGET（默认 30 万），统一 LLM 入口强制检查，超限不重试 |
| P1-6 | 并发限制 | concurrency commit | 全局(10) + 单客户端(2) 双层并发计数，SSE 感知释放（流结束才释放槽位） |
| P1-7 | 报告级缓存 | report cache commit | ticker+12h TTL 内存缓存；命中直接回放（零 LLM 成本），done 事件带 cached=true |
| P1-9 | 数据源失败根因 | 无需新代码 | **核实已基本实现**：report_builder.py:1115 已显示 agent 级"⚠️ 执行失败：具体原因" |
| P1-10 | RAG 降级透明化 | 无需新代码 | **核实已基本实现**：/health + /diagnostics/rag/status 已暴露 backend_actual/fallback_reason |

**P1-9/P1-10 剩余缺口**（记录备查，价值较低未做）：
- P1-9：tool 层降级链路（如 Finnhub 超时→yfinance fallback）不会传播到报告，只有 agent 级失败可见
- P1-10：embedding hash 降级时 /health 的 rag.status 仍为 "ok"（fallback_reason 有值但 status 不变 degraded）

### 第三批：工作台重构 Phase 1 ✅

| 任务 | 实现内容 | 测试 |
|------|---------|------|
| 后端：L1 监控引擎 | `monitor_store.py`(265行,SQLite data/monitor.db) + `monitor_engine.py`(253行,价格异动±5%/集中度>80%两条规则) + `monitor_router.py`(149行,/api/monitor/*) + main.py 调度注册(15分钟间隔) | 28 passed |
| 前端：发现流+持仓录入 | `FindingsFeed`/`FindingCard`(发现流,60秒轮询) + `PortfolioEditor`/`PositionEditRow`(持仓录入——解决"持仓永远为空"的玩具感根源) + `MonitorConfigPanel`(监控配置) + Workbench.tsx 重布局 | 12 新测试 + 83 全量 + 构建绿 |
| 玩具组件清理 | 删除 QuickAnalysisBar + AnalysisConfigPanel（与 Chat 重复） | - |

**工作台 Phase 1 后的样子**：用户录入持仓 → L1 规则引擎每 15 分钟自动扫描（零 LLM 成本）→
价格异动/集中度风险变成"发现卡片"推给用户 → 点行动按钮跳 Chat 深挖。

### 第三批：工作台重构 Phase 2 ✅

| 任务 | 实现内容 | 测试 |
|------|---------|------|
| L2 agent 自动深析 | `monitor_l2.py`(280行)：price_move→TechnicalAgent / concentration→RiskAgent，agent 实例化遵循 agent_adapter 标准模式，分析结果写入 Finding.agent_analysis | 18 个 L2 测试 |
| 成本护栏 | L2Budget：单日上限(MONITOR_L2_DAILY_LIMIT=20) + MONITOR_L2_ENABLED 开关 + REPORTS_GENERATION_ENABLED 熔断联动 + LLM 不可用优雅跳过 | 含在上面 |
| 前端分析展示 | FindingCard 的 AI 分析区块：agent badge + summary 折叠展开 + 置信度（null→"未评估"，诚实原则）+ 数据源 tag | 8 个新测试 |

**工作台 Phase 1+2 之后的完整链路**：
持仓录入 → L1 规则扫描（15分钟/次，零成本）→ 发现异常 → L2 agent 自动深析（有预算护栏）→
发现卡片带 AI 分析推给用户 → 行动按钮跳 Chat 深挖。
"Agent 主动盯盘"从 spec 变成了现实。

### 第四批：P2 产品力（2026-06-03 早晨主人指令"推进P2"后继续）

| # | 任务 | Commit | 说明 |
|---|------|--------|------|
| P2-2 | 执行追踪默认可见 | `6cc1f1f` | traceViewMode 默认 'expert'——护城河（执行追踪）不再是彩蛋 |
| P2-4 | Dashboard 置信度/数据时点 | `6cc1f1f` | AiInsightCard Footer 显示置信度（颜色编码）+ as_of——后端一直在发，前端之前丢弃 |
| P2-1 | 幻觉洗涤可见化 | `89f84ea` | report.fact_check 暴露 verifier claims + FactCheckCard 组件（零问题也展示"✓通过核查"）；synthesize.py 零改动（数据已在 artifacts，只是从未暴露） |
| P2-3 | 章节数据化（prompt 层） | `11e4f0d` | 催化剂加【已确认/预期/传言】标记/风险加触发阈值（带[阈值待补]防编造兜底）/结论加观察点清单表格；两条 prompt 链路都改 |

**P2 最终验证（2026-06-03 10:20）**：
- 后端全量回归：**1641 passed / 8 skipped / 0 failed / 0 errors**（7 分 05 秒）
- 前端全量：**99 passed（23 文件）** + 构建绿
- P2 净增 10 个测试（fact_check 6 + prompt 结构 5，减去重构整合 1）

**调查发现（修正路线图）**：证据账本已默认展开✅、冲突检测已在报告正文✅——
比路线图预想的好，无需改造。真正的缺口是幻觉洗涤黑盒（P2-1 已修）。

**P2 未做项**（留待后续）：P2-5 英文 claim 中文化（L）/ P2-6 半成品处置（M-L）/
P2-7 成本审计面板（M）/ P2-8 agent 图表（M）/ P2-9 移动端（M-L）/
P2-10 A股体验（L）/ P2-11 价差提示（M）/ P2-12 质量徽章（L）

---

## 二、测试结果汇总

| 测试套件 | 结果 | 说明 |
|---------|------|------|
| 后端全量回归（删除死代码后） | 1511 passed / 8 skipped / 41 errors / 1 failed→fixed | 41 errors 为已知 Windows 文件锁环境问题；1 failed 为测试环境隔离缺陷，已修复 |
| 前端全量（P1-2/P1-8 后） | 68 passed | |
| 前端构建 | ✅ 绿 | tsc -b && vite build |
| P1 各项单元测试 | 全绿 | startup_check 17 / SSE+429 9 / 执行失败区分 11 / token预算 7+26回归 / 并发 16 / 缓存 25 |

> 最终全量回归在所有任务完成后统一执行（见第五节）。

---

## 三、关键发现与决策记录

1. **P1-4 的真实问题比审计结论更严重**：路线图说"执行失败被误报为质量拦截"，
   实际验证发现报告构建崩溃时质量门控根本不拦截（report=None 不触发 block），
   用户看到的是"执行完成"+ 半截内容——失败被完全隐藏。已修复为显式 execution_error 事件。

2. **P1-9/P1-10 大部分已实现**：上轮审计后的修复已覆盖大部分诉求，本轮核实后未重复造轮子。

3. **测试隔离缺陷**：本地 .env 同步线上配置后，4 个"验证默认行为"的测试会受环境变量影响。
   本轮修复了 1 个（TECHNICAL_AGENT_LLM_SUMMARY_ENABLED），后续如有同类失败按同样模式修
   （monkeypatch.delenv 隔离）。

4. **孤儿代码候选**：intent_classifier.py（删除 supervisor 后零引用）、
   forum.py/plan.py/budget.py（只剩测试引用，无生产调用方）——下轮清理候选。

---

## 四、遗留问题与风险

| 项 | 说明 | 建议 |
|----|------|------|
| 41 个 Windows 文件锁 errors | E:\FinSight\tmp\pytest 被管理员权限旧进程锁定 | 环境问题；重启开发机或清理 tmp 目录后消失 |
| pytest 缓存写不了 | .pytest_cache 同样被锁 | 同上 |
| intent_classifier.py 孤儿 | 零生产引用 | 下轮死代码清理 |
| 线上部署时配置同步 | 新增环境变量（见第六节）需要同步到服务器 .env.server | 部署时处理 |

---

## 五、最终验证（2026-06-03 00:40 完成）

- [x] **后端全量回归：1631 passed / 8 skipped / 0 failed / 0 errors**（8 分 31 秒，
  用干净 basetemp 跑，之前的 41 个 Windows 文件锁 errors 全部消除）
- [x] **前端全量测试：91 passed（22 个文件）**
- [x] **前端构建：绿**（tsc -b && vite build，TypeScript 零错误）
- [x] **git log 完整性：11 个功能 commit + 1 个文档 commit，全部 conventional 格式**

**对比基线**（今晚开始前 vs 结束后）：

| 指标 | 开始前 | 结束后 |
|------|--------|--------|
| 后端测试 | 1497 passed + 1 failed + 41 errors | **1631 passed + 0 failed + 0 errors** |
| 前端测试 | 68 passed | **91 passed** |
| 死代码 | ~8,200 行 | **0** |
| 公网防护 | 仅 HTTP 频率限流 | 频率限流 + 并发限制 + token 预算 + 报告缓存 + 启动校验 + fail-fast |
| 工作台 | "玩具"（报告查看器） | **Agent 主动盯盘中心**（L1 规则引擎 + L2 自动深析） |

---

## 六、新增环境变量清单（部署时需关注）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_REQUEST_TOKEN_BUDGET` | 300000 | P1-5 单请求 token 预算（0=不限制） |
| `GENERATION_MAX_CONCURRENT` | 10 | P1-6 生成端点全局并发上限 |
| `GENERATION_MAX_CONCURRENT_PER_CLIENT` | 2 | P1-6 单客户端并发上限 |
| `CONCURRENCY_LIMIT_ENABLED` | true | P1-6 并发限制开关 |
| `REPORT_CACHE_TTL_HOURS` | 12 | P1-7 报告缓存 TTL（0=禁用） |
| `VITE_SSE_READ_TIMEOUT_MS` | 30000 | P1-2 前端 SSE 读超时（构建时注入） |
| `MONITOR_SCAN_ENABLED` | true | 工作台 L1 盯盘扫描开关 |
| `MONITOR_SCAN_INTERVAL_MINUTES` | 15 | L1 扫描间隔 |

---

## 七、Commit 清单（共 11 个，基线 23ef149）

```
635bf2d feat(workbench): L2 agent auto-analysis + cost guardrails (Phase 2)
af2fdf3 feat(workbench): findings feed + portfolio editor + monitor config UI (Phase 1 frontend)
b54b07a feat(workbench): L1 monitor engine + Finding/MonitorTarget store + API (Phase 1 backend)
17be9ac feat(cost): report-level cache with ticker + 12h TTL (P1-7)
f134727 feat(cost): global + per-client concurrency limits on generation endpoints (P1-6)
67bfcb7 feat(cost): per-request LLM token budget cap (P1-5)
ab8f385 feat(execution): distinguish execution failure from quality gate block (P1-4)
c14e2ae feat(frontend): SSE read timeout detection + 429 rate-limit toast (P1-2, P1-8)
4a6afe9 feat(api): startup config self-check + LLM fail-fast (P1-1, P1-3)
b9aa111 fix(tests): isolate TECHNICAL_AGENT_LLM_SUMMARY_ENABLED env in deterministic summary test
ad752c6 refactor: remove SupervisorAgent dead code and legacy archive (~8,200 lines)
```

---

## 八、本地冒烟测试 + 并发测试（2026-06-03 上午，localhost 实测）

> 环境：后端 127.0.0.1:8001 + 前端 localhost:5179（全部功能开启，.env 线上同步配置）

### 冒烟测试（11 项全过）

| # | 测试项 | 结果 | 数据 |
|---|--------|------|------|
| 1 | 启动自检 P1-1/P1-3 | ✅ | LLM endpoint OK + 6/6 数据源 key |
| 2 | /health 健康检查 | ✅ | 全组件 ok，live_tools=active |
| 3 | 持仓 CRUD + 实时价格 | ✅ | NVDA 实时价 $222.82，盈亏 $10,232 |
| 4 | L1 规则扫描（集中度） | ✅ | 9 秒产生发现"NVDA 占比 100%" |
| 5 | L2 RiskAgent 自动深析 | ✅ | 风险评分 49.2/100 (medium) + 置信度 0.75 + 压力测试 -51.9% |
| 6 | 发现流：查询/已读/4h去重/session隔离 | ✅ | 全部符合预期 |
| 7 | Chat 流式舆情简报 | ✅ | 53.9s，完整事件链（plan→3 agents→token→done） |
| 8 | Dashboard insights（P2-4 字段） | ✅ | confidence=0.4 + as_of 时间戳都在 |
| 9 | 报告生成 + fact_check（P2-1） | ✅ | 236s 完成，fact_check 字段完整暴露 |
| 10 | **P1-7 报告缓存命中** | ✅ | **第一次 236s → 第二次 0.1s**（cached=true，零成本） |
| 11 | 浏览器端全流程（录入→扫描→发现卡片+AI分析） | ✅ | 发现卡片完整渲染（标题/摘要/AI分析/置信度/数据源/行动按钮） |

### 并发/防护测试（4 项全过）

| # | 测试项 | 结果 | 数据 |
|---|--------|------|------|
| 1 | P1-6 单客户端并发限制（上限2） | ✅ | 4 并发请求 → 2×200 + 2×429（带 Retry-After: 15 + 中文提示） |
| 2 | 并发槽位释放（SSE 感知） | ✅ | 断开连接后新请求立即可进 |
| 3 | 断开请求自动取消 | ✅ | 后端日志"graph run cancelled"（不白烧 token） |
| 4 | HTTP 频率限流（120/min） | ✅ | 140 个快速请求 → 107 过 + 33 个 429 |

### 发现并修复的 BUG（1 个，commit 7b143ed）

| BUG | 根因 | 修复 |
|-----|------|------|
| 浏览器保存持仓报 422 | 前端把 session_id 放 body，后端 PUT 端点期望 query 参数（浮浮酱给前端 implementer 的契约写错） | client.ts updatePortfolioPosition 改为 query 传参，浏览器复测通过 |

### Agent 联动补全（2026-06-03 上午，主人指令"接上"）

| 联动 | 数据源 | 实测结果 |
|------|--------|---------|
| 舆情突变 → **NewsAgent** | Alpha Vantage（新增结构化工具+1h缓存） | ✅ **真实触发**："NVDA 舆情强正面 +0.36" → NewsAgent 自动产出完整舆情简报（偏多+0.37·高热·5条催化·88%正面占比） |
| 财报临近 → **DeepSearchAgent** | yfinance earnings calendar | ✅ 代码+测试验证（实测需等财报季，当前无 3 天内财报） |
| 宏观事件 → **MacroAgent** | 宏观日历搜索 | ✅ 代码+测试验证（实测需等 CPI/FOMC 临近窗口） |
| 调仓建议按钮闭环 | —— | ✅ 浏览器验证：按钮启用+点击滚动到调仓卡片 |
| 晨报融入发现流 | —— | ✅ 浏览器验证：折叠为发现流顶部摘要 |

**联动后格局**：7 个 agent 中 5 个有专属盯盘规则（Technical/Risk/News/DeepSearch/Macro），
Price/Fundamental 在报告模式和 L3 全面体检中调用。

**测试发现并修复的第 2 个问题（commit 0cc7416）**：Alpha Vantage 免费配额（25次/天+1次/秒）
扛不住 15 分钟扫描频率 → 加 1 小时舆情缓存 + 1.2 秒调用间隔；
限流时诚实跳过不报警（设计如此），配额日均用量从 96×N 降到 ≤24×N。

### 交易时段感知盯盘（2026-06-03 中午，独立 goal：finsight-market-hours-goal）

| 内容 | Commit | 说明 |
|------|--------|------|
| 时段判断 + 盘前价格 + Dispatcher | 后端 commit | market_hours.py（27测试）+ session_price.py（v8 chart includePrePost 盘前价）+ 5分钟心跳节流调度 |
| 盘前/盘后 badge | `faac7d4` | 发现卡片橙色"盘前"/靛蓝"盘后"标注 |

**分时段调度表**：盘前(美东4:00-9:30=北京16:00-21:30) 10min 全规则 / 盘中 15min / 盘后 30min /
闭市·周末·节假日 60min 且跳过价格规则。

**实测**：当前时段正确判断为 closed（美东深夜），调度日志
`dispatch: session=closed interval=60.0min`，价格规则被跳过 ✅

**重要技术发现**：Yahoo v7 quote 端点已 401 失效（preMarketPrice 字段拿不到）；
盘前真实价格唯一途径是 v8 chart `includePrePost=true` 按 currentTradingPeriod 切窗口（已实现）；
拿不到时诚实标注 `price_basis=regular_fallback`，绝不冒充盘前价。

**新增环境变量**：MONITOR_DISPATCH_HEARTBEAT_MINUTES=5 / MONITOR_INTERVAL_PRE_MARKET=10 /
MONITOR_INTERVAL_REGULAR=15 / MONITOR_INTERVAL_AFTER_HOURS=30 / MONITOR_INTERVAL_CLOSED=60 /
NEWS_SENTIMENT_CACHE_TTL_SECONDS=3600（旧的 MONITOR_SCAN_INTERVAL_MINUTES 不再被读取）

### 测试中观察到的已知降级行为（非 bug）

- 本地无 FlagEmbedding 模块 → RAG 自动降级 hash embedding（日志正确记录 fallback_reason，P1-10 行为符合预期）
- Dashboard LLM digest 8 秒超时 → 自动降级规则评分（model_generated=false，符合降级设计）
- done 事件 metrics 中 "token" 关键字被脱敏为 ***（过度保护，不影响功能，可后续优化）

---

**P2 追加 commit（2026-06-03 早晨）：**

```
11e4f0d feat(report): structured constraints for catalysts/risks/conclusion sections (P2-3)
89f84ea feat(report): expose hallucination fact-check results to users (P2-1)
6cc1f1f feat(frontend): expert trace mode by default + dashboard confidence/as_of visibility (P2-2, P2-4)
```

注：本报告自身随 docs commit 提交并随 P2 进展更新。
所有 commit 均未 push，等主人检查后决定。
