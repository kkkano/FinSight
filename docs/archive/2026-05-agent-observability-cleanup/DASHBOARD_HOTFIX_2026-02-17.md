# Dashboard Hotfix（2026-02-17）

## 问题

研究页 `一键生成报告` 点击后，用户感知为“没反应”。

## 根因

1. `output_mode=investment_report` 在图中默认经过 `confirmation_gate`，会先发 `interrupt` 事件。  
   Dashboard 研究页没有 resume 交互，所以看起来像“没有执行”。
2. 报告索引异步写入（`run_in_executor`），执行完成后立即读取索引可能读空。  
   若只读一次，就会一直显示“尚未生成研究报告”。

## 修复

- `backend/graph/nodes/build_initial_state.py`
  - 对 `source=dashboard*` 且 `output_mode=investment_report` 的请求，默认设置 `require_confirmation=false`，避免中断。
- `frontend/src/hooks/useLatestReport.ts`
  - `refetch()` 改为返回 `Promise<LatestReportData | null>`，支持上层可控轮询。
- `frontend/src/components/dashboard/tabs/ResearchTab.tsx`
  - 增加“执行中 / 同步中 / 失败”可见状态。
  - 执行完成后对报告索引做最多 5 次轮询回读，避免异步落库导致的空结果。
  - 修复按钮文案与查询文案编码异常。
- `frontend/src/store/executionStore.ts`
  - 补充流式终态兜底：流结束但没有 `done/error` 时，标记为错误，避免进度长期停在 80%。
  - `synth/render` 阶段提高进度上限，减少“卡在 80%”错觉。
  - 将执行流 `onRawEvent` 写入全局 Console 事件流（不仅聊天）。
- `frontend/src/components/workbench/TaskSection.tsx`
  - `execute/resume` 链路接入 `onRawEvent`，并补充流终态兜底，保证工作台任务也能进入 Console。

## 回归验证

- `backend/tests/test_build_initial_state_dashboard.py`
  - 验证 Dashboard 投资报告请求会跳过确认门。
- `backend/tests/test_execute_dashboard_report.py`
  - 验证 Dashboard 一键报告流包含 `done` 且不出现 `interrupt`。
- 构建与测试：
  - `pytest -q backend/tests/test_build_initial_state_dashboard.py backend/tests/test_execute_dashboard_report.py backend/tests/test_dashboard_schema.py backend/tests/test_health_and_validation.py`
  - `npm run build --prefix frontend`

## 2026-02-18 补充：仪表盘深度搜索来源隔离与执行面板去重

- 问题：
  - 仪表盘研究区会复用同会话“最新报告”，导致聊天里生成的报告被直接带入 Dashboard。
  - 右侧执行面板在 Dashboard 任务完成后再次渲染整份 `ReportView`，与研究区信息重复。

- 修复：
  - 后端执行链路在 report 中写入 `source_type`（按 `source` 归一：`dashboard/chat/workbench/...`）。
  - `report_index` 入库时持久化 `source_type`，支持后续按来源筛选。
  - 前端 `useLatestReport` 支持 `sourceType` 过滤，Dashboard 各 tab 仅读取 `source_type=dashboard` 的报告。
  - `ResearchTab` 按钮语义调整为“深度搜索并填充”，执行源改为 `dashboard_deep_search`。
  - 右侧 `StreamingResultPanel` 对 Dashboard 任务不再重复渲染整份报告，改为“已同步到仪表盘”提示。

- 验证：
  - `pytest -q backend/tests/test_report_index_api.py backend/tests/test_execute_dashboard_report.py backend/tests/test_build_initial_state_dashboard.py`
  - `npm run build --prefix frontend`
