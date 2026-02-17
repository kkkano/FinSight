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
| Dashboard P2 | ⏳ 待开始 | 向 TradingKey 全面性靠拢 |
| Dashboard P3 | ⏳ 待开始 | 专业工作流闭环 |

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

- [ ] P2-1 EPS revision 轨迹
- [ ] P2-2 分析师目标价分布（均值+分位+离散）
- [ ] P2-3 机构持仓变化（13F）与资金流
- [ ] P2-4 期权面（IV Rank / Skew / PCR）
- [ ] P2-5 事件时间线（财报/FOMC/监管/产品）
- [ ] P2-6 因子暴露（Beta/Size/Value/Momentum）
- [ ] P2-7 DoD：分析页输出“结论 + 证据 + 结构化上下文”

---

## 5. Dashboard P3（体验收口）

- [ ] P3-1 多标的并排同业对比
- [ ] P3-2 自定义观察板（指标组合可保存）
- [ ] P3-3 情景冲击测试（利率/油价/波动率）
- [ ] P3-4 导出报告自动附“来源附录”
- [ ] P3-5 Workbench Agent Timeline
- [ ] P3-6 Workbench Agent Conflict Matrix

---

## 6. 执行记录

### 2026-02-17
- [x] PR-1 ~ PR-5 实现与回归完成
- [x] PR-6 memory gate 完成：`tests/retrieval_eval/reports/local-memory/gate_summary.json`
- [x] Dashboard P0-1 ~ P0-5 完成（后端 meta + 前端来源抽屉 + stale/降级展示）
- [ ] Dashboard P0-6 待人工验收
- [ ] PR-6 postgres gate 待环境具备 Docker 后执行
