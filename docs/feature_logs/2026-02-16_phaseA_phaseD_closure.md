# 2026-02-16 Phase A / Phase D 收口说明

## 1. 目标与范围

本次收口覆盖三类改造：

- 图表主题统一第二波：将 dashboard/report 高频图迁移到 `useChartTheme`。
- 右侧告警面板实时化准备：抽离事件接口层，当前仍使用 polling。
- 通用 UI 组件渐进替换：继续替换自定义弹层为统一 `Dialog` primitives。

## 2. 目录树（本次新增/重点变更）

```text
frontend/src/components/
├─ cards/
│  ├─ HoldingsCard.tsx
│  ├─ MarketChartCard.tsx
│  ├─ SectorWeightsCard.tsx
│  └─ SegmentMixCard.tsx
├─ report/
│  └─ ReportSection.tsx
├─ right-panel/
│  ├─ alertFeed.ts                 # 新增：告警事件接口与 polling source
│  ├─ useRightPanelData.ts         # 改造：接入事件流归并逻辑
│  └─ RightPanelChartTab.tsx       # 改造：最大化视图改用 Dialog
└─ CommandPalette.tsx              # 改造：改用 Dialog primitive
```

## 3. 组件抽象变更

### 3.1 `Dialog` 统一化

- `CommandPalette` 从自定义 overlay 迁移到 `ui/Dialog`。
- `RightPanelChartTab` 最大化弹层迁移到 `ui/Dialog`。

收益：

- 统一了 `ESC` / 点击遮罩关闭行为与可访问性语义（`role="dialog"`）。
- 降低重复实现成本，后续 Modal 迁移路径更清晰。

### 3.2 Tooltip/Tabs 接入状态（本阶段验收点）

- 右侧面板 Header 保持 Tooltip primitives 接入。
- Dashboard 主内容保持 Tabs primitives 接入（tablist/tab 语义可识别）。

## 4. 告警数据流改造（为 SSE/WebSocket 预留）

### 4.1 新抽象

新增 `right-panel/alertFeed.ts`：

- `AlertFeedEvent`: `snapshot | upsert | remove | error`
- `AlertFeedSource`: `connect(handler)` + `pull()`
- `reduceAlertFeedEvent(current, event)`：统一事件归并逻辑
- `createPollingAlertFeedSource(...)`：当前轮询实现

### 4.2 运行路径

`useRightPanelData` 当前链路：

1. `fetchAlertSnapshot()` 拉取订阅列表
2. `createPollingAlertFeedSource` 周期拉取
3. 通过 `connect` 推送事件
4. `reduceAlertFeedEvent` 更新 UI 状态

### 4.3 后续实时化迁移点

后续接入 SSE/WebSocket 时，仅需新增 `createSseAlertFeedSource` 或 `createWsAlertFeedSource`，
`useRightPanelData` 与 UI 层可保持不变（替换 source 工厂即可）。

## 5. 图表主题统一（第二波）

### 5.1 已迁移组件

- `HoldingsCard`
- `SectorWeightsCard`
- `SegmentMixCard`
- `MarketChartCard`（补充 alpha 渐变转换）
- `ReportSection`（对 report 图表 option 做主题补丁）

### 5.2 主题策略

- 统一从 `useChartTheme` 读取语义色（文本、边框、tooltip、涨跌色）。
- 尽量避免业务层硬编码颜色，保留少量低频辅助色作为调色板补充。

## 6. 冒烟回归结论（本次）

- 前端构建：`tsc -b` 通过。
- 后端测试：`pytest backend/tests -x -q` 通过（`620 passed, 8 skipped`）。
- UI 冒烟：
  - 主题切换可正常切换 dark/light。
  - 右侧告警面板、Settings/Subscribe 弹层 `dialog` 语义正常。
  - `skip-nav` 可通过键盘 `Tab` 聚焦并跳转目标锚点。
  - Chat 输入框为 `textarea`，可自动增高（已验证主输入与 MiniChat）。

已知环境项：

- 当前本地联调存在跨域/网络错误（`127.0.0.1:4173 -> 127.0.0.1:8000`），
  不影响本次前端结构与交互改造验收结论。
