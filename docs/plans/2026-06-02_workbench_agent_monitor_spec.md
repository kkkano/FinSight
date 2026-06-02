# 工作台重构设计规格：Agent 盯盘中心

> 日期：2026-06-02
> 状态：设计已批准（实施排在产品可信度整改 goal 之后）
> 背景：主人对现状的评价"跟玩具一样，不知道有啥用，点击一下看报告有毛用"

---

## 1. 现状诊断（重构动机）

| 问题 | 证据 |
|------|------|
| 持仓无 UI 录入入口 | 只能通过 Chat 录入 → 持仓永远为空 → 晨报/调仓/任务全是空面板（"玩具感"根源） |
| 与 Chat/Dashboard 高度重复 | 快速分析/持仓追踪/调仓均为复制品，独有功能仅晨报+任务 |
| Agent 联动几乎为零 | 仅"快速分析"调用 7 agent；晨报=纯数据聚合、调仓=纯算法、任务=规则引擎 |
| 看报告无行动转化 | 报告时间线是孤立的阅读器，看完不能执行任何操作 |
| 后端能力闲置 | portfolio/morning_brief/rebalance/task/execution/scheduler 后端都完整，缺的是有意义的组织方式 |

## 2. 产品决策记录（2026-06-02 头脑风暴定稿）

| 决策点 | 结论 |
|--------|------|
| 灵魂定位 | **Agent 主动盯盘中心**——用户不问，agent 也在干活；打开工作台=看 agent 今天帮我发现了什么 |
| 盯盘对象 | 全部四类：自选股 Watchlist + 持仓组合（补录入 UI）+ 用户自定义监控规则 + 宏观事件日历 |
| 扫描机制 | **三层分层盯盘**：L1 规则引擎（零成本常驻）→ L2 agent 自动深析（触发阈值才烧钱）→ L3 用户触发全面体检 |
| 旧功能处置 | **融入盯盘体系**：晨报→每日摄报（发现汇总）；任务→发现卡片的行动按钮；调仓→集中度发现的行动选项；报告时间线→发现历史 |
| 差异化逻辑 | Chat=被动问答，Dashboard=被动查看，**工作台=agent 主动工作**（ChatGPT/Perplexity 给不了的） |

## 3. 信息架构（UI）

```
┌─ 工作台 = Agent 盯盘中心 ──────────────────────────────┐
│ 📰 每日摄报（顶部折叠卡）= 今日发现汇总 ←晨报融入        │
├─────────────────────────────────┬──────────────────────┤
│ 今日发现流（核心区 60%）          │ 监控配置（侧栏）      │
│  发现卡片 = 异常 + agent分析摘要  │  · 盯盘对象管理       │
│            + 行动按钮             │  · 阈值设置          │
│  按时间倒序 / 未读优先            │  · 扫描排班          │
├─────────────────────────────────┴──────────────────────┤
│ 💼 持仓管理（新增）：录入 / 编辑 / 盈亏一览              │
└─────────────────────────────────────────────────────────┘
```

发现卡片结构：
- 触发原因（"TSLA 舆情分数 2 小时内从 +0.2 跌到 -0.4"）
- agent 分析摘要（news_agent 舆情简报的核心观点段）
- 行动按钮（按发现类型动态生成）：[看完整简报] [风险评估] [调仓建议] [全面体检]
- 状态：新 / 已读 / 已行动

## 4. 三层盯盘引擎（后端）

| 层 | 成本 | 触发 | 实现（复用为主） |
|----|------|------|------------------|
| L1 规则引擎 | 零 | 调度器每 15 分钟 | 复用 `task_generator.py`（规则）+ `scheduler_runner.py`（调度，已有 price/news alert scheduler）+ 价格 API + Alpha Vantage 舆情分数 + 财报日历 |
| L2 Agent 深析 | LLM（自动） | L1 触发阈值 | 舆情突变→`news_agent` 简报（sentiment_brief.py 现成）；价格异动→`technical_agent`；财报临近→`deep_search_agent`；集中度→`risk_agent`+`rebalance_engine` |
| L3 全面体检 | LLM（手动） | 用户点击 | `/api/execute` 7 agent 报告（现成） |

L1 默认规则（可配置阈值）：
- 价格异动：±5%（单日）
- 舆情分数突变：变化幅度 > 0.3
- 财报临近：≤ 3 天
- 持仓集中度：单一板块 > 80%
- 宏观事件窗口：CPI/FOMC/非农 ≤ 2 天

成本护栏（继承 P0 的防滥用设计）：
- L2 单日自动 agent 调用上限（默认 20 次，环境变量可配）
- 同一标的同一类型发现 4 小时内不重复触发 L2
- `REPORTS_GENERATION_ENABLED=false` 时 L2/L3 全部暂停

## 5. 数据模型（新建）

```
Finding（发现）—— 工作台的灵魂数据
  id / created_at / target(ticker或板块) / trigger_type / trigger_detail
  agent_analysis(L2 结果，可空) / actions(可执行操作列表) / status(new|viewed|acted)

MonitorTarget（盯盘对象）
  id / type(watchlist|holding|custom_rule|macro) / config(阈值JSON) / enabled

ScanSchedule（扫描排班）
  cron 表达式 / 启用状态（复用 scheduler_runner 机制）
```

存储：SQLite（与现有 portfolio.db 同模式），Finding 保留 30 天。

## 6. 复用 vs 新建清单

**复用（后端能力全部现成）：**
- 规则引擎 ← `task_generator.py`
- 调度器 ← `scheduler_runner.py`（PRICE/NEWS_ALERT_SCHEDULER 已存在）
- 舆情简报 ← `sentiment_brief.py` + `news_agent`
- 报告 ← `execution_router`
- 调仓 ← `rebalance_engine`
- 晨报聚合 ← `morning_brief_router`（改造为发现汇总）
- 持仓 CRUD ← `portfolio_router`（已完整）
- 邮件 ← SMTP 配置（已有）

**新建：**
- Finding / MonitorTarget 数据模型 + 存储 + API
- L1→L2 触发编排逻辑（监控引擎核心）
- 前端：发现流 UI + 监控配置 UI + 持仓录入 UI
- 旧组件改造：MorningBriefCard → DailyDigest；TaskSection 融入发现卡片

**删除：**
- QuickAnalysisBar（与 Chat 重复，分析入口收口到发现卡片的 L3 按钮）
- 独立的 RebalanceEntryCard（融入集中度发现的行动选项）

## 7. 实施分期（排在现有 goal 之后）

| Phase | 内容 | 价值 |
|-------|------|------|
| 1 | 持仓录入 UI + Finding 模型 + 发现流骨架（仅 L1 规则引擎） | 零成本可用，"玩具感"消失 |
| 2 | L2 接入（agent 自动深析）+ 发现卡片行动闭环 | "Agent 主动盯盘"灵魂落地 |
| 3 | 自定义监控规则 + 宏观日历 + 邮件推送 | 完整形态 |

## 8. 不在本次范围

- 实时行情推送（WebSocket 级别的盯盘，成本和架构都不支持）
- 自动交易执行（合规红线，永远只到"建议"）
- 移动端适配（P2 路线图单独处理）
