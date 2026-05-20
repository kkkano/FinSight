# 2026-02-08 T3/T1/T2 Closure Batch 2

## Scope
- T3: Postgres checkpointer cutover drill + rollback evidence workflow
- T1: Trace 3-level visibility (`user/expert/dev`) + fallback path readability
- T2: Retrieval gate artifact hard-binding (`gate_summary.json`) into CI/release evidence

## Code Changes
- Added `backend/services/checkpointer_cutover.py`
- Added `scripts/checkpointer_switch_drill.py`
- Added `backend/tests/test_checkpointer_cutover.py`
- Extended `backend/tests/test_graph_checkpointer.py`
- Extended `backend/orchestration/trace_emitter.py` (`tried_sources` on data_source event)
- Extended `backend/orchestration/orchestrator.py` to emit `tried_sources`
- Added `traceViewMode` store state in `frontend/src/store/useStore.ts`
- Added Trace view mode controls in `frontend/src/components/SettingsModal.tsx`
- Added mode-aware render in `frontend/src/components/ThinkingProcess.tsx`
- Added mode-aware summaries and fallback path display in `frontend/src/components/AgentLogPanel.tsx`
- Added `write_gate_summary` in `tests/retrieval_eval/run_retrieval_eval.py`
- Added retrieval gate summary test in `tests/retrieval_eval/test_retrieval_eval_runner.py`
- Updated `.github/workflows/ci.yml` to verify and archive `gate_summary.json`

## Documentation Sync
- `docs/11_PRODUCTION_RUNBOOK.md`: appended checkpointer cutover drill + retrieval gate evidence binding sections
- `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`: appended 11.16.1 execution status + worklog row

## Validation
- Pending command outputs (will append below).


## Follow-up: Encoding Recovery & Validation Closure (2026-02-08)
### Root Cause Found
- `backend/orchestration/orchestrator.py` and `backend/orchestration/trace_emitter.py` contained malformed encoded characters from prior edits, causing parser failures during backend test collection.

### Fix Applied
- Repaired malformed docstrings/strings and removed non-printable private-use characters.
- Restored `trace_emitter.py` from clean baseline and re-applied required enhancement:
  - `emit_data_source_query(..., tried_sources: Optional[list[str]] = None)`
  - event metadata includes `tried_sources`.
- Kept orchestrator emission side aligned with the same contract.
- Adjusted `frontend/e2e/report-button.spec.ts` to match current product behavior:
  - deep mode triggers report output mode
  - first request includes generated `session_id` (assertion updated)

### Final Validation (all green)
- `pytest -q backend/tests` -> **355 passed, 8 skipped**
- `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py` -> **7 passed**
- `python tests/retrieval_eval/run_retrieval_eval.py --gate --report-prefix ci` -> **PASS** (citation coverage=1.0)
- `npm run lint --prefix frontend` -> **pass**
- `npm run build --prefix frontend` -> **pass**
- `npm run test:e2e --prefix frontend` -> **7 passed**

### Evidence
- Retrieval gate summary: `tests/retrieval_eval/reports/gate_summary.json`
