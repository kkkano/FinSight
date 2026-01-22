# 2026-01-22 Tools/Config/Logging Sync

- Split `backend/tools.py` into `backend/tools/` package (search/news/price/financial/macro/web) with `backend.tools` re-exports.
- Unified LLM config entry: `llm_service` reads `backend/llm_config.py` (user_config.json > .env).
- Migrated core backend `print` calls to `logging` (API/agents/orchestration/services).
- Updated docs 01-05, README, and tests for the new tools package layout.
