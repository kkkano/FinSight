# 2026-02-18 Workbench 收口记录（Phase J）

## 范围

- 对齐已上线的 I1-I4 能力，补齐工作台最后一层可感知体验。
- 不新增后端公共 API，不重做已交付能力。

## 本次改动

### 1) Execution 可感知补缝

- `frontend/src/components/RightPanel.tsx`
  - 新增 `hasUnseenExecution` 状态。
  - 当用户锁定非 `execution` 标签页且出现新执行（`0->N`）时，不强切标签，改为提示态。
  - 进入 `execution` 标签页或执行清空时自动清除提示态。

- `frontend/src/components/right-panel/RightPanelHeader.tsx`
  - 新增 `hasUnseenExecution` 入参。
  - execution 标签支持脉冲提示（`animate-ping`）。

### 2) Alerts 空态类型化

- `frontend/src/components/right-panel/types.ts`
  - 新增 `AlertEventState`、`AlertSubscriptionState` 枚举。

- `frontend/src/components/right-panel/useRightPanelData.ts`
  - 输出 `eventState`、`subscriptionState`，统一由 hook 推导空态。
  - 保留原有接口消费链路（`alerts/feed + subscriptions`）。

- `frontend/src/components/right-panel/RightPanelAlertsTab.tsx`
  - 按枚举状态渲染，不再在组件内散落条件判断。

### 3) Timeline 文案映射完善

- `frontend/src/components/execution/timelineUtils.ts`
  - 补全 `step/tool/agent/cache/api/data_source/plan/system/interrupt/error` 事件映射。
  - 统一描述风格：`[主体] [动作] [补充信息]`。
  - 错误事件识别补充 `step_error` 与 `status=error`。

## 验证

- `npx eslint src/components/RightPanel.tsx src/components/right-panel/RightPanelHeader.tsx src/components/right-panel/types.ts src/components/right-panel/useRightPanelData.ts src/components/right-panel/RightPanelAlertsTab.tsx src/components/execution/timelineUtils.ts`（在 `frontend/` 目录）
- `npm --prefix frontend run build`
- `pytest backend/tests/test_execute_dashboard_report.py -q`
- `pytest backend/tests/test_alert_feed_api.py backend/tests/test_subscriptions_api.py -q`

## 备注

- 测试期间会触发 `data/memory/anonymous.json` 更新；本次已按规范回滚运行时数据文件。
- `.omc/` 为本地未跟踪目录，不纳入提交。
