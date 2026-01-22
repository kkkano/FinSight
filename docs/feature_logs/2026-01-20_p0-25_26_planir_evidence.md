# P0-25/P0-26 完成记录：PlanIR + EvidencePolicy

日期：2026-01-20

## 概要
- 落地 PlanIR + Executor：报告路径引入计划模板、执行状态机与 step 级 trace。
- 落地 EvidencePolicy：引用校验 + 覆盖率统计落入 ReportValidator，低覆盖自动提示风险。

## 关键改动
- 新增 `backend/orchestration/plan.py`，提供计划模板与执行器。
- Supervisor 报告路径接入 PlanIR，流式输出带 plan 与 plan_trace。
- ReportValidator 引入 EvidencePolicy，强制引用校验与覆盖率统计。
- 流式报告路径在注入 citations 后重新执行 ReportValidator。

## 影响范围
- `backend/orchestration/supervisor.py`
- `backend/report/validator.py`
- `backend/report/evidence_policy.py`
- `backend/conversation/agent.py`
- `backend/api/main.py`
- `backend/tests/test_report_validator.py`
- `backend/tests/test_plan_executor.py`

## 测试
- 建议运行：`pytest backend/tests/test_report_validator.py -q`
- 建议运行：`pytest backend/tests/test_plan_executor.py -q`
