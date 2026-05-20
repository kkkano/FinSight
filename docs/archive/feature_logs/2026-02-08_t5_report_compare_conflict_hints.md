# 2026-02-08 - T5-2 Report Compare/Conflict Hints

## Scope
- Phase: T5 (P1 enhancement)
- This round focuses on report-level explainability hints:
  - compare-report hint
  - evidence-conflict hint
  - report-index tag persistence and workbench surface

## Backend Changes
- `backend/graph/report_builder.py`
  - Added `_derive_report_tags_and_hints(...)`.
  - Derives compare signal from:
    - multi-ticker report context
    - `comparison_conclusion`
    - `comparison_metrics`
  - Derives conflict signal from:
    - `agent_status.*.evidence_quality.has_conflicts == true`
  - Emits:
    - `report_hints` (top-level)
    - `meta.report_hints`
    - `tags` (`compare` / `conflict` / `filing`)

## Frontend Changes
- `frontend/src/pages/Workbench.tsx`
  - Uses `ReportIndexItem.tags` to render badges on report cards:
    - 对比
    - 证据冲突
    - Filing
- `frontend/src/components/ReportView.tsx`
  - Renders hint strip under core summary:
    - “对比报告”
    - “存在证据冲突，请重点复核”
    - conflict agent names
- `frontend/src/types/index.ts`
  - Extended `ReportIR` with:
    - `tags?: string[]`
    - `report_hints?: { is_compare, has_conflict, compare_basis, conflict_agents }`

## Tests
- Updated `backend/tests/test_report_builder_synthesis_report.py`
  - Added `test_build_report_payload_adds_compare_and_conflict_hints_and_tags`

## Validation
- `pytest -q backend/tests/test_report_builder_synthesis_report.py backend/tests/test_report_index_api.py` -> `8 passed`
- `npm run lint --prefix frontend` -> pass
- `npm run build --prefix frontend` -> pass

## Outcome
- T5-2 is complete.
- Report library can now quickly identify comparison reports and potential evidence conflicts.
- Report detail view now exposes conflict hints to guide manual review decisions.

