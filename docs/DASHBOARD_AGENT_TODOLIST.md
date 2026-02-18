# FinSight Dashboard / Workbench 实施清单（Agent-First）

> 更新时间：2026-02-17  
> 执行顺序：`PR-1 -> PR-2 -> PR-3 -> PR-4 -> PR-5(前四稳定后) -> PR-6 -> Dashboard P0 -> P1 -> P2 -> P3`

---

## 0. 进度总览

| 模块 | 状态 | 备注 |
|---|---|---|
| PR-1 安全与稳定 | ✅ 完成 | 已合入工作区 |
| PR-2 调仓数值正确性 | ✅ 完成 | 集中度/前端权重修正 |
| PR-3 调仓输入完整性 | ✅ 完成 | 无关键数据时降级 |
| PR-4 证据链与增强开关 | ✅ 完成 | evidence 与 enhancement 打通 |
| PR-5 前端体验收口 | ✅ 完成 | 历史去重/草稿清空/agent补全 |
| PR-6 回归与门禁 | 🟡 部分完成 | memory gate 完成，postgres gate 受 Docker 阻塞 |
| Dashboard P0 数据可追踪 | 🟡 进行中 | 本次完成 P0-1~P0-5，剩 P0-6 人工验收 |
| Dashboard P1 | ⏳ 待开始 | 评分可解释 |
| Dashboard P2 | ✅ 部分完成 (Phase G2) | EPS revision / 分析师目标价 / 因子暴露 / 期权面 / 事件日历 已由 G2 实现 |
| Dashboard P3 | ⏳ 待开始 | 专业工作流闭环 |
| Phase E RAG 升级 | ✅ 完成 | E1-E6: bge-m3 + chunker + reranker + router + DeepSearch 持久化 |
| Phase F Agentic Dashboard | ✅ 完成 (F1-F3) | Digest Agent 引擎 + InsightCard + 全标签页 AI 洞察 |
| Phase G 可视化升级 | ✅ 完成 (G1-G4) | ECharts 升级 + 新图表 + 智能对话图表 + 工作台优化 |
| Phase H 新闻系统重构 | ✅ 完成 (H1+H2) | H1: 前端三级筛选 + 富卡片; H2: 后端标签注入 + Schema 加固 + 29 个新测试 |

---

## 1. PR 主线清单（已执行）

### PR-1 安全与稳定
- [x] `backend/services/memory.py`：`user_id` 白名单校验，阻断路径遍历
- [x] `backend/graph/store.py`：初始化失败哨兵，阻断重试风暴
- [x] `backend/api/task_router.py`：清理重复 import
- [x] 后端用例通过（路径遍历 + init fail 行为）

### PR-2 调仓数值正确性
- [x] `backend/services/task_generator.py`：集中度按市值（`shares * price`）
- [x] 缺实时价时降级成本价并写入 reason
- [x] `frontend/.../ActionList.tsx`：去除重复 `*100`
- [x] 调仓集中度新增回归用例

### PR-3 调仓输入完整性
- [x] `backend/api/rebalance_router.py` 注入 `live_prices`
- [x] `backend/api/rebalance_router.py` 注入 `sector_map`
- [x] 缺关键输入时降级“仅诊断，不给目标仓位”
- [x] schema 增加 `degraded_mode` / `fallback_reason`

### PR-4 证据链 + 增强开关
- [x] `backend/services/rebalance_engine.py`：填充 `evidence_ids`
- [x] `backend/services/rebalance_engine.py`：填充 `evidence_snapshots`
- [x] `use_llm_enhancement` 全链路接通（request -> router -> engine）
- [x] 增强失败自动回退 deterministic

### PR-5 前端体验收口（在前四稳定后执行）
- [x] `TaskSection.tsx`：刷新后历史去重（含 hydration 防重）
- [x] `TaskSection.tsx`：状态文案中文化
- [x] `ChatInput.tsx`：draft 消费后清空，支持重复命令再次触发
- [x] `AgentControlPanel.tsx`：补全 `risk_agent`

### PR-6 回归与门禁
- [x] rebalance 相关回归测试补齐并通过
- [x] retrieval memory gate 执行通过
- [x] 文档补充本地联调命令与排障说明
- [ ] retrieval postgres gate（受环境 `docker` 缺失阻塞）
- [ ] postgres `gate_summary.json` 归档（同上）

---

## 2. Dashboard P0（必须先做）—— 数据来源可追踪

### P0 子任务
- [x] P0-1 统一 `meta` 契约  
  `provider / source_type / as_of / latency_ms / fallback_used / confidence / currency / calc_window / fallback_reason`
- [x] P0-2 后端透传 `meta`  
  覆盖 `snapshot/charts/news/valuation/financials/technicals/peers`
- [x] P0-3 前端来源入口  
  新增 `DataSourceTrace`（按钮 + 抽屉）
- [x] P0-4 stale 分级可视化  
  `正常 / 偏旧 / 陈旧` 分级，按数据块阈值判定
- [x] P0-5 降级原因显式展示  
  抽屉内展示 `fallback_reason`，不再静默降级
- [ ] P0-6 DoD 人工验收  
  抽查关键卡片数值，确认“来源链 + 时间 + 口径”一致

### P0 DoD
- [ ] 任意关键数值可追溯“从哪来、何时更新、是否降级、为何降级”
- [ ] 至少抽查：`snapshot / market_chart / valuation / financials / technicals / news`
- [ ] 形成验收截图或验收记录

---

## 3. Dashboard P1（高优先）—— 评分可解释

- [ ] P1-1 所有评分补充 `score_breakdown`（因子/权重/贡献）
- [ ] P1-2 增加“本期 vs 上期变化归因”
- [ ] P1-3 风险指标显示窗口和频率（60D/120D/240D，日频/周频）
- [ ] P1-4 前端 `ScoreExplainDrawer` 展示可解释明细
- [ ] P1-5 DoD：点击任意分数可看到构成与变化原因

---

## 4. Dashboard P2（增强全面性）

- [x] P2-1 EPS revision 轨迹 → Phase G2.2 EarningsSurpriseChart 实现
- [x] P2-2 分析师目标价分布（均值+分位+离散）→ Phase G2.3 AnalystTargetCard 实现
- [ ] P2-3 机构持仓变化（13F）与资金流
- [x] P2-4 期权面（IV Rank / Skew / PCR）→ price_agent + get_option_chain_metrics 已接入
- [x] P2-5 事件时间线（财报/FOMC/监管/产品）→ news_agent + get_event_calendar 已接入
- [x] P2-6 因子暴露（Beta/Size/Value/Momentum）→ risk_agent + get_factor_exposure 已接入
- [ ] P2-7 DoD：分析页输出"结论 + 证据 + 结构化上下文"

---

## 5. Dashboard P3（体验收口）

- [ ] P3-1 多标的并排同业对比
- [ ] P3-2 自定义观察板（指标组合可保存）
- [ ] P3-3 情景冲击测试（利率/油价/波动率）
- [ ] P3-4 导出报告自动附“来源附录”
- [ ] P3-5 Workbench Agent Timeline
- [ ] P3-6 Workbench Agent Conflict Matrix
---

## 6. Phase I: Agentic 工作台进化（规划中）

> 目标：让工作台从「黑箱 API 调用器」进化为「可观测、可解释、可操控的 Agent 协作平台」

### I1: Agent Timeline — 实时执行轨迹（P0）
- [ ] I1-BE.1 `execute_plan_stub.py` — 每个 step 执行时 `emit_event("agent_step", {...})` 推送结构化事件
- [ ] I1-BE.2 `event_bus.py` — 新增 `agent_step` / `tool_call` / `evidence_collected` 事件类型
- [ ] I1-BE.3 `execution_router.py` — SSE 流中新增 `timeline` 事件类型透传
- [ ] I1-FE.1 `AgentTimeline.tsx` — 垂直时间轴面板，实时动画展示各 Agent 的 step
- [ ] I1-FE.2 `TimelineStep.tsx` — 单步卡片：图标 + Agent 名 + 动作描述 + 耗时 + 置信度
- [ ] I1-FE.3 `EvidencePreview.tsx` — 点击 step 展开，预览证据片段
- [ ] I1-FE.4 TaskSection / StreamingResultPanel 集成 Timeline 面板

### I2: Score Explainability — 评分可解释（P1）
- [ ] I2-BE.1 `insights_scorer.py` — 所有 `score_*` 函数返回 `ScoreBreakdown` 结构
- [ ] I2-BE.2 `insights_engine.py` — DigestAgent 输出 `score_breakdown` 字段
- [ ] I2-BE.3 `schemas.py` — `InsightCard` 新增 `score_breakdown` 字段
- [ ] I2-FE.1 `ScoreExplainDrawer.tsx` — 右侧抽屉：因子柱状图 + 变化归因
- [ ] I2-FE.2 `FactorBar.tsx` — 水平柱状图渲染因子权重与贡献
- [ ] I2-FE.3 ResearchInsightGrid 集成 — 点击分数打开抽屉

### I3: Agent Conflict Matrix — 冲突可视化（P1）
- [ ] I3-BE.1 `synthesize.py` — 新增 `_detect_conflicts()` 检测跨 Agent 对立信号
- [ ] I3-BE.2 `report_builder.py` — `ReportIR` 新增 `agent_conflicts` 字段
- [ ] I3-FE.1 `ConflictMatrix.tsx` — 矩阵视图：行=Agent，列=维度，标注分歧点
- [ ] I3-FE.2 `ConflictDetailCard.tsx` — 点击单元格展开对立论证

### I4: Proactive Alerts — 主动预警（P2）
- [ ] I4-BE.1 `alert_scanner.py` — 异步定时扫描 watchlist，检测价格异动/新闻突发/指标突破
- [ ] I4-BE.2 `alert_rules.py` — 规则引擎（PriceSpike/RSIExtreme/EarningsSurprise/NewsImpact）
- [ ] I4-BE.3 `alerts_router.py` — `GET /api/alerts` 返回待读取警报列表
- [ ] I4-FE.1 `AlertBell.tsx` — 顶部铃铛 + 未读计数
- [ ] I4-FE.2 `AlertDrawer.tsx` — 右侧预警列表（按时间/优先级/标的分组）
- [ ] I4-FE.3 `AlertCard.tsx` — 单条预警卡片

### I5: Agent Steering — 用户可操控执行（P2）
- [ ] I5-BE.1 `planner.py` — 支持 `focus_agents` / `skip_agents` 参数
- [ ] I5-BE.2 `confirmation_gate.py` — per-step confirm/skip 细粒度 HITL
- [ ] I5-BE.3 GraphState — 新增 `agent_preferences` 字段
- [ ] I5-FE.1 `AnalysisConfigPanel.tsx` — 执行前配置：选择 Agent、深度、聚焦问题
- [ ] I5-FE.2 `StepApprovalCard.tsx` — 执行中逐步确认/跳过
---

## 6. 执行记录

### 2026-02-17
- [x] PR-1 ~ PR-5 实现与回归完成
- [x] PR-6 memory gate 完成：`tests/retrieval_eval/reports/local-memory/gate_summary.json`
- [x] Dashboard P0-1 ~ P0-5 完成（后端 meta + 前端来源抽屉 + stale/降级展示）
- [ ] Dashboard P0-6 待人工验收
- [ ] PR-6 postgres gate 待环境具备 Docker 后执行

### 2026-02-17 ~ 2026-02-18 (Phase E/F/G)
- [x] Phase E (E1-E6): RAG 引擎升级 — bge-m3 embedding + chunker + reranker + router + DeepSearch 持久化 + Postgres 升级
- [x] Phase F (F1-F3): Agentic Dashboard — Digest Agent 引擎 + InsightCard 组件 + 全标签页 AI 洞察集成
- [x] Phase G (G1-G4): Dashboard 可视化升级
  - G1: 5 个 CSS 模拟图表 → ECharts 真实图表 (K 线/财务双轴/同行柱状)
  - G2: 后端 data_service 扩展 (earnings_history/analyst_targets/recommendations/indicator_series) + 3 个新前端图表组件
  - G3: LLM 智能图表 — synthesize.py prompt 扩展 + SmartChart 组件 + 双模式 `<chart>`/`<chart_ref>`
  - G4: 工作台可视化 — 持仓分布饼图 + 调仓瀑布图 + 快速分析命令栏
- [x] 全局验证: 742 tests passed / tsc zero errors / README + 文档同步

### 2026-02-18 (Phase H)
- [x] Phase H1 前端新闻重构 (纯前端，零后端改动):
  - H1-FE.1: types/dashboard.ts 扩展 (NewsSubTab/NewsTagGroup/NewsTimeRange 类型 + NEWS_TAG_GROUP_MAP)
  - H1-FE.2: dashboardStore 新增 3 个持久化状态 (newsSubTab/newsTagFilter/newsTimeRange)
  - H1-FE.3: 4 个新组件 (NewsSubTabs/NewsTagChips/NewsTimeRange/NewsCard)
  - H1-FE.4: NewsTab.tsx 全面重写 — 三级筛选 + 富卡片 + 分析影响 + 智能空状态
  - H1-FE.5: utils/news.ts 统一新闻工具函数 (标签计算/影响分级/情绪分类/时间过滤)
  - tsc 零错误验证通过
- [x] Phase H2 后端标签加固:
  - H2.1: news.py — 删除重复 NEWS_TAG_RULES 定义 + _build_news_item() 注入 tags 字段
  - H2.2: schemas.py — NewsItem 新增 tags/ranking_score/impact_score/source_reliability 等 Optional 字段
  - H2.3: data_service.py — _to_news_item() 透传 tags 字段
  - H2.4: test_news_tags.py — 29 个测试全部通过 (规则完整性/标签计算/字典构建/数据透传/Schema 序列化)
  - 全量回归: 776 passed, 15 skipped, tsc zero errors

### 2026-02-18 (TradingKey 重设计 + Bug 修复)
- [x] ResearchTab TradingKey 风格重设计:
  - schemas.py / insights_prompts.py / insights_scorer.py / insights_engine.py: InsightCard 新增 key_metrics
  - ResearchOverviewBar.tsx / ResearchInsightGrid.tsx: 2 个新组件
  - ResearchTab.tsx: 整合 useDashboardInsights + 可折叠报告
- [x] GOOGL vs GOOGLE 三层去重修复:
  - ticker_mapping.py: normalize_ticker() + dedup_tickers()
  - resolve_subject.py: 所有 active_symbol 路径归一化
  - report_builder.py: ticker_label 构建前去重
- [x] ExecutiveSummary Markdown 渲染修复 (ReactMarkdown + remark-gfm)
- [x] CoreFindings 空卡片修复 (extractContentFromContents 提取嵌套 contents[])

### 2026-02-18 (Phase I 规划)
- [x] Phase I: Agentic 工作台进化路线图制定
  - I1: Agent Timeline (P0) — 实时执行轨迹
  - I2: Score Explainability (P1) — 评分可解释
  - I3: Agent Conflict Matrix (P1) — 冲突可视化
  - I4: Proactive Alerts (P2) — 主动预警
  - I5: Agent Steering (P2) — 用户可操控执行
