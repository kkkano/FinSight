# 2026-02-18 Phase I (I1-I4) 实施记录

## 基线校验
- `pytest backend/tests/test_execute_dashboard_report.py -q` ✅
- `pytest backend/tests/test_insights_engine.py -q` ✅
- `pytest backend/tests/test_alert_scheduler.py backend/tests/test_risk_alert_scheduler.py backend/tests/test_subscriptions_api.py -q` ✅
- `npm --prefix frontend run build` ✅

## 本次实现范围
- I1: `run_id` 端到端透传 + Timeline 前端可视化。
- I2: Insight deterministic `score_breakdown`（后端输出 + 前端 Drawer）。
- I3: 冲突矩阵（结构化 `agent_diagnostics` 优先，`conflict_disclosure` 文本兜底）。
- I4: 告警事件流（scheduler 记录事件，`/api/alerts/feed` 提供消费，右侧面板展示事件+订阅）。

## 关键代码变更
- Backend
  - `backend/api/execution_router.py`
  - `backend/services/execution_service.py`
  - `backend/dashboard/insights_engine.py`
  - `backend/dashboard/schemas.py`
  - `backend/graph/report_builder.py`
  - `backend/services/subscription_service.py`
  - `backend/services/alert_scheduler.py`
  - `backend/api/alerts_router.py`
  - `backend/api/main.py`
- Frontend
  - `frontend/src/store/executionStore.ts`
  - `frontend/src/components/execution/AgentTimeline.tsx`
  - `frontend/src/components/execution/timelineUtils.ts`
  - `frontend/src/components/execution/StreamingResultPanel.tsx`
  - `frontend/src/components/dashboard/tabs/research/ScoreExplainDrawer.tsx`
  - `frontend/src/components/dashboard/tabs/research/ConflictMatrix.tsx`
  - `frontend/src/components/dashboard/tabs/research/conflictUtils.ts`
  - `frontend/src/components/dashboard/tabs/research/ConflictPanel.tsx`
  - `frontend/src/components/dashboard/tabs/research/ResearchInsightGrid.tsx`
  - `frontend/src/components/dashboard/tabs/research/ResearchOverviewBar.tsx`
  - `frontend/src/components/dashboard/tabs/ResearchTab.tsx`
  - `frontend/src/components/right-panel/useRightPanelData.ts`
  - `frontend/src/components/right-panel/RightPanelAlertsTab.tsx`
  - `frontend/src/components/RightPanel.tsx`
  - `frontend/src/types/dashboard.ts`
  - `frontend/src/types/index.ts`
  - `frontend/src/types/execution.ts`
  - `frontend/src/api/client.ts`

## 新增测试
- `backend/tests/test_alert_feed_api.py`

## 验证结果
- `pytest backend/tests/test_execute_dashboard_report.py -q` ✅
- `pytest backend/tests/test_insights_engine.py -q` ✅
- `pytest backend/tests/test_alert_scheduler.py backend/tests/test_risk_alert_scheduler.py backend/tests/test_subscriptions_api.py backend/tests/test_alert_feed_api.py -q` ✅
- `npm --prefix frontend run build` ✅
- `npm --prefix frontend run lint` ❌（仓库已有历史 lint 问题，非本次变更引入）
