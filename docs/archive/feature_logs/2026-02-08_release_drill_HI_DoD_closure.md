# 2026-02-08 - 11.14.13 H/I Release Drill & DoD Closure

## Scope
- Complete requested release-readiness items:
  - pre-release 24h/2h checks
  - gray rollout drill (10% -> 50% -> 100%)
  - rollback threshold hardening + rollback rehearsal
  - multi-endpoint failover rehearsal
  - session isolation + security final validation
  - explainable trace sampling (20 requests)
  - DoD-1~DoD-6 closure

## Delivered

### 1) Runbook hardening
- Updated `docs/11_PRODUCTION_RUNBOOK.md` with:
  - 24h freeze checklist
  - 2h smoke + DB snapshot checklist
  - gray rollout phases and mandatory metrics
  - rollback thresholds (5xx/P95/citation coverage)
  - rollback operation sequence
  - failover drill and security final-check requirements
  - 20-request explainability sampling requirement

### 2) Security and rate-limit final verification
- Added tests:
  - `backend/tests/test_security_gate_auth_rate_limit.py`
- Covers:
  - auth enabled + missing key -> 401
  - auth enabled + empty key config -> 503
  - allowlisted path bypass (`/health`)
  - rate limit 429 + `Retry-After`

### 3) DB migration/rollback and snapshot evidence
- Migration/rollback script checks:
  - `pytest -q backend/tests/test_report_index_migration_scripts.py` -> pass
- Existing-db rollback drill:
  - `python scripts/report_index_migrate.py --db backend/data/report_index_release_drill_existing_*.sqlite`
  - `python scripts/report_index_rollback.py --db backend/data/report_index_release_drill_existing_*.sqlite`
- DB snapshot manifest generated:
  - `docs/release_evidence/2026-02-08_go_live_drill/db_snapshot_manifest.json`

### 4) Gray rollout rehearsal
- Evidence file:
  - `docs/release_evidence/2026-02-08_go_live_drill/gray_rollout_drill.json`
- Includes stage metrics for:
  - 10% (10 requests)
  - 50% (50 requests)
  - 100% (100 requests)
- Gate uses:
  - `5xx <= 2%`
  - `P95 <= 2x baseline`
  - `citation_coverage >= 0.95`

### 5) Multi-endpoint failover rehearsal
- Evidence file:
  - `docs/release_evidence/2026-02-08_go_live_drill/llm_failover_drill.json`
- Result:
  - primary down -> backup selected
  - primary recovers after cooldown

### 6) Explainable trace sampling (20 requests)
- Evidence file:
  - `docs/release_evidence/2026-02-08_go_live_drill/trace_sampling_20.json`
- Coverage:
  - 20/20 requests include explainable thinking events (`stage` + `message`)

### 7) Gate + DoD document closure
- Updated in `docs/06_LANGGRAPH_REFACTOR_GUIDE.md`:
  - Gate A~E -> done
  - 11.14.13.H checklist -> done
  - 11.14.13.I DoD-1~DoD-6 -> done
  - Worklog row appended for this release drill

## Validation
- `pytest -q backend/tests` -> `344 passed, 8 skipped`
- `pytest -q tests/retrieval_eval/test_retrieval_eval_runner.py` -> `6 passed`
- `python tests/retrieval_eval/run_retrieval_eval.py --gate` -> `PASS`
- `npm run build --prefix frontend` -> `success`
- `npm run test:e2e --prefix frontend` -> `13 passed`
- `pytest -q backend/tests/test_security_gate_auth_rate_limit.py backend/tests/test_trace_and_session_security.py backend/tests/test_llm_rotation.py` -> `19 passed`

## Next Layer Start Proposal (P1)
- Start with `11.14.10 首发后优化` in this order:
  1. Market quick-news ranking model (timeline + heat + credibility + asset impact)
  2. Report-library advanced compare/conflict hints
  3. Prompt/Plan A-B experiment harness

