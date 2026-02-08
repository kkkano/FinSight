# 2026-02-07｜超细 TODOLIST 落地（默认 Trace ON）

## 背景

用户要求：

1. Trace/Raw Event 默认开启（先看全量）；
2. 提供“细节到不能再细节”的完整上线 TODOLIST。

## 本次变更

1. 更新 `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`
   - 将 `11.14.2` 的 Raw Trace 默认策略调整为 `默认 ON`；
   - 新增 `11.14.13 超细执行拆解（WBS）`，覆盖：
     - Trace/Raw 开关执行细则；
     - LLM 多 endpoint 多 key 轮换与故障切换；
     - 可解释 Trace 字段与前端渲染；
     - Workbench/快讯/研报库闭环；
     - 研报索引与 citation 回放；
     - 会话隔离与安全脱敏；
     - CI/CD 门禁流水线；
     - 上线/灰度/回滚节奏；
     - DoD 验收标准。
   - 在 `13.Worklog` 增加“11.14 超细拆解（默认 Trace ON）”记录。

2. 文档流程闭环
   - 按团队约束补充本条 devlog，确保“先 TODOLIST -> 执行 -> 证据 -> devlog”一致。

## 验收方式

- 人工核对：
  - `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`（11.14.2 默认 ON + 11.14.13）
  - `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`（13.Worklog 新增记录）
  - `docs/feature_logs/2026-02-07_ultra_granular_todolist_trace_on.md`

## 备注

- 本次仅为“执行计划强化”，不涉及运行时代码变更；
- 下一步可直接按 11.14.13.A（Trace ON + 开关）和 11.14.13.B（LLM 轮换）开始实现。
