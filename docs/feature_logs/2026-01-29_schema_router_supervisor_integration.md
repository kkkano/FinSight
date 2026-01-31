# 2026-01-29 Schema Router + Supervisor Integration

## Summary
- Merged updated SchemaToolRouter into AgentProject with confidence + business rules + defaults.
- /chat/supervisor and /chat/supervisor/stream now call SchemaToolRouter and short-circuit clarify when needed.
- Invalid JSON / unknown tool -> clarify (no fallback to old routing).
- limit/timeframe from schema args now flows into news/news_sentiment handlers and tools.
- SlotCompletenessGate now returns structured missing_fields per tool.

## Files Updated
- backend/conversation/schema_router.py
- backend/api/main.py
- backend/handlers/chat_handler.py
- backend/tools/news.py
- docs/01_ARCHITECTURE.md
- docs/02_PHASE0_COMPLETION.md
- docs/03_PHASE1_IMPLEMENTATION.md
- docs/04_PHASE2_DEEP_RESEARCH.md
- docs/05_PHASE3_ACTIVE_SERVICE.md
- docs/05_RAG_ARCHITECTURE.md
- readme.md
- readme_cn.md

## Verification
- python -m py_compile backend/conversation/schema_router.py backend/handlers/chat_handler.py backend/api/main.py backend/tools/news.py

## Notes
- Clarify messages are now consistent across supervisor endpoints.
- get_company_news now respects limit (default 5; capped to 20).
