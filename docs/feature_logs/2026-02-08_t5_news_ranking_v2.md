# 2026-02-08 - T5-1 Market News Ranking v2 + Workbench Alignment

## Scope
- Phase: T5 (P1 enhancement)
- This round only targets quick-news ranking second optimization and cross-page alignment:
  - dashboard ranking explainability
  - workbench ranked/raw consistency
  - deterministic sorting stability

## What Changed
- Backend (`backend/dashboard/data_service.py`):
  - Introduced mode-aware ranking weights:
    - `market`: time_decay 0.45 / source_reliability 0.25 / impact_score 0.20 / asset_relevance 0.10
    - `impact`: time_decay 0.35 / source_reliability 0.20 / impact_score 0.25 / asset_relevance 0.20
  - Introduced mode-aware half-life:
    - `market=24h`, `impact=36h`
  - Added `asset_relevance` scoring by symbol/alias mention + event keywords.
  - Added `source_penalty` for duplicate-source concentration to improve feed diversity.
  - Upgraded `ranking_meta` to `v2` with `weights`, `half_life_hours`, and notes.
  - Added per-item explainability fields:
    - `ranking_reason`
    - `ranking_factors` (`weights` + weighted contributions)

- Frontend:
  - `frontend/src/types/dashboard.ts`: expanded `NewsItem` and `NewsRankingMeta` contract.
  - `frontend/src/components/dashboard/NewsFeed.tsx`:
    - keeps ranked/raw toggle
    - shows ranking formula/version/notes
    - shows per-item score + ranking reason
  - `frontend/src/components/dashboard/DashboardWidgets.tsx`:
    - passes ranking version/notes into `NewsFeed`
  - `frontend/src/pages/Workbench.tsx`:
    - aligned ranked/raw source usage (`impact` ranked vs `impact_raw` raw)
    - deterministic tie-break in local sort
    - shows ranking meta and ranking reason
  - `frontend/src/components/layout/WorkspaceShell.tsx`:
    - passes `impact`, `impact_raw`, and `ranking_meta` to Workbench

## Tests
- Added `backend/tests/test_dashboard_news_ranking.py`:
  - validates `ranking_meta.version == v2`
  - validates presence of explainability fields
  - validates stable deterministic order

## Validation
- `pytest -q backend/tests/test_dashboard_news_ranking.py backend/tests/test_release_drills.py` -> `6 passed`
- `npm run lint --prefix frontend` -> pass
- `npm run build --prefix frontend` -> pass

## Outcome
- T5-1 completed with ranking quality + explainability uplift and dashboard/workbench behavior alignment.
- Next recommended step: T5-2 report compare/conflict hint surfacing (index tags + workbench badges + report hint strip).

