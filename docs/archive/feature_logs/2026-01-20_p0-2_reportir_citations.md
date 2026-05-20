# 2026-01-20 P0-2 ReportIR Citation 字段扩展

## 目标
- 为 `ReportIR.citations` 增加 `confidence` 与 `freshness_hours` 字段，确保前后端契约一致。

## 变更范围
- `backend/report/ir.py`：Citation 数据结构扩展默认字段。
- `backend/report/validator.py`：校验与默认值/容错处理。
- `backend/orchestration/supervisor_agent.py`：补齐 citations 生成字段。
- `backend/tests/test_report_validator.py`：新增字段校验测试。
- 文档同步：`docs/01-05`、`readme.md`、`readme_cn.md`。

## 测试
- `pytest backend/tests/test_report_validator.py -q`

## 备注
- 统一以 `confidence ∈ [0,1]`、`freshness_hours ≥ 0` 作为基本契约。
